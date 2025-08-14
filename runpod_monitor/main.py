#!/usr/bin/env python3
import requests
import json
import argparse
import sys
import yaml
import time
import logging
import os
from pathlib import Path
from dotenv import load_dotenv
try:
    from .data_tracker import DataTracker
except ImportError:
    # Handle running as script directly
    from data_tracker import DataTracker

# Global configuration
config = None
data_tracker = None

# Global timing tracking for server-side polling
last_poll_time = 0
next_poll_time = 0

def load_config(config_path: str = "config.yaml"):
    """Load configuration from YAML file or create from template."""
    global config, data_tracker
    
    # Load .env file if it exists
    load_dotenv()
    
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Config file {config_path} not found.")
        
        # Try to copy from template
        template_path = "config.yaml.template"
        if os.path.exists(template_path):
            print(f"Creating {config_path} from template...")
            try:
                with open(template_path, 'r') as f:
                    config = yaml.safe_load(f)
                
                # Override API key with environment variable if set
                if os.getenv("RUNPOD_API_KEY"):
                    config["api"]["key"] = os.getenv("RUNPOD_API_KEY")
                
                # Save the new config file
                with open(config_path, 'w') as f:
                    yaml.dump(config, f, default_flow_style=False, sort_keys=False)
                print(f"✅ Created {config_path} from template. Please update your API key!")
                
            except Exception as e:
                print(f"Error creating config from template: {e}")
                config = create_default_config()
        else:
            print("No template found. Using hardcoded defaults.")
            config = create_default_config()
    
    # Always override API key with environment variable if set
    if os.getenv("RUNPOD_API_KEY"):
        config["api"]["key"] = os.getenv("RUNPOD_API_KEY")
    
    # Initialize data tracker
    if data_tracker is None and config:
        storage_config = config.get('storage', {})
        data_tracker = DataTracker(
            data_dir=storage_config.get('data_dir', './data'),
            metrics_file=storage_config.get('metrics_file', 'pod_metrics.json')
        )
        print(f"🗄️  Data tracker initialized with storage: {storage_config.get('data_dir', './data')}")
    
    return config

def create_default_config():
    """Create default configuration with monitor-only defaults."""
    return {
        "api": {
            "key": os.getenv("RUNPOD_API_KEY", "YOUR_RUNPOD_API_KEY_HERE"),
            "graphql_url": "https://api.runpod.io/graphql",
            "rest_url": "https://rest.runpod.io/v1"
        },
        "auto_stop": {
            "enabled": False,
            "monitor_only": True,
            "sampling": {
                "frequency": 60,
                "rolling_window": 3600
            },
            "thresholds": {
                "max_cpu_percent": 1,
                "max_gpu_percent": 1,
                "max_memory_percent": 1,
                "duration": 3600,
                "detect_no_change": False
            },
            "exclude_pods": [],
            "include_pods": []
        },
        "storage": {
            "data_dir": "./data",
            "metrics_file": "pod_metrics.json",
            "retention_days": 30
        },
        "logging": {
            "level": "INFO",
            "file": "runpod_monitor.log",
            "max_size_mb": 10,
            "backup_count": 5
        },
        "server": {
            "enabled": False,
            "host": "0.0.0.0",
            "port": 8080,
            "dashboard": True
        }
    }

def get_headers():
    """Get API headers from config."""
    api_key = config["api"]["key"]
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

# GraphQL query
query = """
query GetAllPodsWithMetrics {
  myself {
    pods {
      id
      name
      machine {
        podHostId
      }
      desiredStatus
      lastStatusChange
      imageName
      env
      containerDiskInGb
      volumeInGb
      costPerHr
      runtime {
        uptimeInSeconds
        container {
          cpuPercent
          memoryPercent
        }
        gpus {
          id
          gpuUtilPercent
          memoryUtilPercent
        }
        ports {
          ip
          isIpPublic
          privatePort
          publicPort
          type
        }
      }
    }
  }
}
"""

# Make the request
def fetch_pods():
    try:
        response = requests.post(
            config["api"]["graphql_url"],
            headers=get_headers(),
            json={"query": query}
        )
        
        if response.status_code == 200:
            data = response.json()
            if "errors" in data:
                print("GraphQL Errors:")
                for error in data["errors"]:
                    print(f"  - {error['message']}")
                return None
            
            return data["data"]["myself"]["pods"]
        else:
            print(f"HTTP Error: {response.status_code}")
            print(response.text)
            return None
            
    except Exception as e:
        print(f"Request failed: {e}")
        return None

# Pod management mutations
def stop_pod(pod_id):
    mutation = """
    mutation PodStop($input: PodStopInput!) {
        podStop(input: $input) {
            id
            name
            desiredStatus
            lastStatusChange
        }
    }
    """
    
    variables = {
        "input": {
            "podId": pod_id
        }
    }
    
    return execute_mutation(mutation, variables)

def resume_pod(pod_id):
    """Resume a pod - tries GraphQL first, falls back to REST API"""
    
    mutation = """
    mutation PodResume($input: PodResumeInput!) {
        podResume(input: $input) {
            id
            name
            desiredStatus
            costPerHr
            lastStatusChange
        }
    }
    """
    
    variables = {
        "input": {
            "podId": pod_id
        }
    }
    
    result = execute_mutation(mutation, variables)
    
    if result is None:
        # GraphQL failed, try REST API
        rest_result = start_pod_rest(pod_id)
        return rest_result
    
    return result

# REST API functions
def start_pod_rest(pod_id):
    """Start/resume a pod using REST API"""
    try:
        url = f"{config['api']['rest_url']}/pods/{pod_id}/start"
        
        response = requests.post(url, headers=get_headers())
        
        if response.status_code == 200:
            return {"success": True, "message": "Pod started successfully"}
        elif response.status_code == 400:
            return {"success": False, "message": "Invalid Pod ID"}
        elif response.status_code == 401:
            return {"success": False, "message": "Unauthorized"}
        elif response.status_code == 500:
            # Parse the error message for more user-friendly output
            try:
                error_data = response.json()
                error_msg = error_data.get('error', 'Internal server error')
                if 'not enough free vcpu' in error_msg.lower():
                    return {"success": False, "message": "Cannot start pod: Host machine doesn't have enough free vCPUs"}
                elif 'not enough free memory' in error_msg.lower():
                    return {"success": False, "message": "Cannot start pod: Host machine doesn't have enough free memory"}
                else:
                    return {"success": False, "message": f"Server error: {error_msg}"}
            except:
                return {"success": False, "message": f"HTTP 500: {response.text}"}
        else:
            return {"success": False, "message": f"HTTP {response.status_code}: {response.text}"}
            
    except Exception as e:
        return {"success": False, "message": f"Request failed: {e}"}

def execute_mutation(mutation, variables):
    try:
        response = requests.post(
            config["api"]["graphql_url"],
            headers=get_headers(),
            json={"query": mutation, "variables": variables}
        )
        
        if response.status_code == 200:
            data = response.json()
            if "errors" in data:
                return None
            return data["data"]
        else:
            return None
            
    except Exception as e:
        return None

# Display pod information
def display_pods(pods, show_index=False):
    if not pods:
        print("No pods found or request failed.")
        return
    
    print(f"Found {len(pods)} pods:\n")
    
    for i, pod in enumerate(pods):
        if show_index:
            print(f"[{i+1}] Pod ID: {pod['id']}")
        else:
            print(f"Pod ID: {pod['id']}")
        print(f"Name: {pod['name']}")
        print(f"Status: {pod['desiredStatus']}")
        print(f"Image: {pod['imageName']}")
        print(f"Cost/hr: ${pod['costPerHr']}")
        
        runtime = pod.get('runtime')
        if runtime:
            print(f"Uptime: {runtime['uptimeInSeconds']} seconds")
            
            container = runtime.get('container', {})
            if container:
                print(f"CPU: {container.get('cpuPercent', 'N/A')}%")
                print(f"Memory: {container.get('memoryPercent', 'N/A')}%")
            
            gpus = runtime.get('gpus', [])
            if gpus:
                print("GPUs:")
                for gpu in gpus:
                    print(f"  - GPU {gpu['id']}: {gpu['gpuUtilPercent']}% util, {gpu['memoryUtilPercent']}% memory")
        else:
            print("Runtime info: Not available (pod may be stopped)")
        
        print("-" * 50)

def interactive_mode():
    while True:
        print("\n=== RunPod Management ===")
        print("1. List all pods")
        print("2. Stop a pod")
        print("3. Resume a pod")
        print("4. Exit")
        
        choice = input("\nEnter your choice (1-4): ").strip()
        
        if choice == "1":
            print("\nFetching pods...")
            pods = fetch_pods()
            display_pods(pods, show_index=True)
            
        elif choice == "2":
            print("\nFetching pods for stopping...")
            pods = fetch_pods()
            if not pods:
                continue
                
            display_pods(pods, show_index=True)
            
            try:
                selection = input("\nEnter pod number to stop (or 'c' to cancel): ").strip()
                if selection.lower() == 'c':
                    continue
                    
                pod_index = int(selection) - 1
                if 0 <= pod_index < len(pods):
                    pod = pods[pod_index]
                    print(f"\nStopping pod '{pod['name']}' ({pod['id']})...")
                    
                    result = stop_pod(pod['id'])
                    if result:
                        print(f"✓ Pod stopped successfully. New status: {result.get('podStop', {}).get('desiredStatus', 'Unknown')}")
                    else:
                        print("✗ Failed to stop pod")
                else:
                    print("Invalid selection")
            except ValueError:
                print("Invalid input. Please enter a number.")
                
        elif choice == "3":
            print("\nFetching pods for resuming...")
            pods = fetch_pods()
            if not pods:
                continue
                
            display_pods(pods, show_index=True)
            
            try:
                selection = input("\nEnter pod number to resume (or 'c' to cancel): ").strip()
                if selection.lower() == 'c':
                    continue
                    
                pod_index = int(selection) - 1
                if 0 <= pod_index < len(pods):
                    pod = pods[pod_index]
                    print(f"\nResuming pod '{pod['name']}' ({pod['id']})...")
                    
                    result = resume_pod(pod['id'])
                    if result:
                        if 'success' in result:
                            # REST API response
                            if result['success']:
                                print(f"✓ {result['message']}")
                            else:
                                print(f"✗ {result['message']}")
                        else:
                            # GraphQL response
                            print(f"✓ Pod resumed successfully. New status: {result.get('podResume', {}).get('desiredStatus', 'Unknown')}")
                    else:
                        print("✗ Failed to resume pod")
                else:
                    print("Invalid selection")
            except ValueError:
                print("Invalid input. Please enter a number.")
                
        elif choice == "4":
            print("Goodbye!")
            break
        else:
            print("Invalid choice. Please enter 1-4.")

def monitor_pods():
    """Continuous monitoring mode with auto-stop functionality."""
    sampling_freq = config.get('auto_stop', {}).get('sampling', {}).get('frequency', 60)
    rolling_window = config.get('auto_stop', {}).get('sampling', {}).get('rolling_window', 3600)
    
    print("Starting continuous pod monitoring...")
    print(f"Data sampling: every {sampling_freq} seconds")
    print(f"Rolling window: {rolling_window} seconds ({rolling_window//60} minutes)")
    print(f"Auto-stop enabled: {config['auto_stop']['enabled']}")
    
    if config['auto_stop']['enabled']:
        thresholds = config['auto_stop']['thresholds']
        print(f"Auto-stop thresholds: CPU≤{thresholds['max_cpu_percent']}%, GPU≤{thresholds['max_gpu_percent']}%, Memory≤{thresholds['max_memory_percent']}%")
        print(f"No-change detection window: {thresholds['duration']}s ({thresholds['duration']//60} minutes)")
        if thresholds.get('detect_no_change'):
            print(f"No-change detection: enabled - checking entire rolling window on each data collection")
    
    last_sample_time = 0
    
    try:
        while True:
            current_time = time.time()
            
            # Sample data at the specified frequency
            if current_time - last_sample_time >= sampling_freq:
                # Update global timing variables
                global last_poll_time, next_poll_time
                last_poll_time = current_time
                next_poll_time = current_time + sampling_freq
                
                print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Sampling pod data and checking auto-stop conditions...")
                
                # Fetch current pod data
                pods = fetch_pods()
                if pods:
                    # Auto-cleanup exclusion list: remove pods that no longer exist
                    exclude_list = config.get('auto_stop', {}).get('exclude_pods', [])
                    if exclude_list:
                        current_pod_ids = {pod['id'] for pod in pods}
                        current_pod_names = {pod['name'] for pod in pods}
                        original_exclude_count = len(exclude_list)
                        
                        # Keep only pods that still exist (either by ID or name)
                        cleaned_exclude_list = [
                            pod_ref for pod_ref in exclude_list 
                            if pod_ref in current_pod_ids or pod_ref in current_pod_names
                        ]
                        
                        # Save cleaned exclusion list if it changed
                        if len(cleaned_exclude_list) != original_exclude_count:
                            removed_count = original_exclude_count - len(cleaned_exclude_list)
                            print(f"🧹 Auto-cleanup: Removed {removed_count} non-existent pods from exclusion list")
                            config['auto_stop']['exclude_pods'] = cleaned_exclude_list
                            
                            # Save config to file
                            try:
                                import yaml
                                config_path = './config/runpod_config.yaml'
                                with open(config_path, 'w') as f:
                                    yaml.dump(config, f, default_flow_style=False, sort_keys=False)
                                print(f"💾 Updated exclusion list saved to config")
                            except Exception as e:
                                print(f"⚠️ Failed to save updated exclusion list: {e}")
                    
                    for pod in pods:
                        pod_id = pod['id']
                        pod_name = pod['name']
                        
                        # Only track metrics for non-excluded pods
                        if should_monitor_pod(pod):
                            # Track metrics
                            data_tracker.add_metric(pod_id, pod)
                        else:
                            # Remove any existing data for excluded pods
                            data_tracker.clear_pod_data(pod_id)
                        
                        # Apply smart rolling window: keep minimum 1 hour, or duration * 1.5 if larger
                        duration = config.get('auto_stop', {}).get('thresholds', {}).get('duration', 1800)
                        smart_window = max(3600, int(duration * 1.5))  # min 1 hour, or duration * 1.5
                        data_tracker.apply_rolling_window(pod_id, smart_window)
                        
                        # Show current status
                        status = pod.get('desiredStatus', 'UNKNOWN')
                        runtime = pod.get('runtime')
                        if runtime and status == 'RUNNING':
                            container = runtime.get('container', {})
                            cpu = container.get('cpuPercent', 0)
                            memory = container.get('memoryPercent', 0)
                            
                            gpus = runtime.get('gpus', [])
                            gpu_util = sum(gpu.get('gpuUtilPercent', 0) for gpu in gpus) / len(gpus) if gpus else 0
                            
                            # Get change rate over the rolling window duration
                            change_rate = data_tracker.get_metrics_change_rate(pod_id, config['auto_stop']['thresholds']['duration'])
                            
                            print(f"  📊 {pod_name}: CPU={cpu}%, GPU={gpu_util:.1f}%, Memory={memory}% (Δ={change_rate['total_change']:.1f}% over {config['auto_stop']['thresholds']['duration']//60}min)")
                            
                            # Check auto-stop conditions immediately after data collection
                            auto_stop_config = config.get('auto_stop', {})
                            enabled = auto_stop_config.get('enabled', False)
                            monitor_only = auto_stop_config.get('monitor_only', False)
                            
                            if (enabled or monitor_only) and should_monitor_pod(pod):
                                exclude_list = auto_stop_config.get('exclude_pods', [])
                                if data_tracker.check_auto_stop_conditions(pod_id, auto_stop_config.get('thresholds', {}), exclude_list):
                                    if monitor_only:
                                        print(f"🔍 MONITOR-ONLY: Pod '{pod_name}' ({pod_id}) meets auto-stop conditions (would be stopped)")
                                    elif enabled:
                                        print(f"⚠️  Pod '{pod_name}' ({pod_id}) meets auto-stop conditions. Stopping...")
                                        
                                        result = stop_pod(pod_id)
                                        if result and result.get('podStop'):
                                            print(f"✓ Pod '{pod_name}' stopped successfully")
                                        else:
                                            print(f"✗ Failed to stop pod '{pod_name}'")
                        else:
                            print(f"  ⏸️  {pod_name} ({status})")
                else:
                    print("No pods found or API error")
                
                last_sample_time = current_time
            
            # Cleanup old data periodically
            if current_time % 3600 < sampling_freq:  # Once per hour
                data_tracker.cleanup_old_data(config.get('storage', {}).get('retention_days', 30))
            
            # Sleep for sampling frequency (minimum interval)
            time.sleep(min(sampling_freq, 10))  # Max 10 second sleep to stay responsive
            
    except KeyboardInterrupt:
        print("\n\nMonitoring stopped by user.")
    except Exception as e:
        print(f"\nMonitoring error: {e}")

def should_monitor_pod(pod):
    """Check if a pod should be monitored for auto-stop."""
    pod_name = pod.get('name', '')
    pod_id = pod.get('id', '')
    
    # Check exclude list
    exclude_list = config.get('auto_stop', {}).get('exclude_pods', [])
    if pod_name in exclude_list or pod_id in exclude_list:
        return False
    
    # Check include list (if specified, only monitor these)
    include_list = config.get('auto_stop', {}).get('include_pods', [])
    if include_list and pod_name not in include_list and pod_id not in include_list:
        return False
    
    # Only monitor running pods
    return pod.get('desiredStatus') == 'RUNNING'

def main():
    global data_tracker
    
    parser = argparse.ArgumentParser(description="RunPod Management Tool")
    parser.add_argument("--action", choices=["list", "stop", "resume", "interactive", "monitor"], 
                       help="Action to perform")
    parser.add_argument("--pod-id", help="Pod ID for stop/resume operations")
    parser.add_argument("--pod-name", help="Pod name for stop/resume operations (alternative to pod-id)")
    parser.add_argument("-i", "--interactive", action="store_true", 
                       help="Start in interactive mode")
    parser.add_argument("-m", "--monitor", action="store_true",
                       help="Start continuous monitoring mode")
    parser.add_argument("--config", default="config.yaml",
                       help="Path to configuration file (default: config.yaml)")
    parser.add_argument("--exclude-pods", nargs="*", 
                       help="Pod IDs or names to exclude from auto-stop (space separated)")
    
    args = parser.parse_args()
    
    # Load configuration
    load_config(args.config)
    
    # Override exclude pods from command line if provided
    if args.exclude_pods:
        if 'auto_stop' not in config:
            config['auto_stop'] = {}
        config['auto_stop']['exclude_pods'] = args.exclude_pods
        print(f"Excluding pods from auto-stop: {', '.join(args.exclude_pods)}")
    
    # Initialize data tracker
    storage_config = config.get('storage', {})
    data_tracker = DataTracker(
        data_dir=storage_config.get('data_dir', './data'),
        metrics_file=storage_config.get('metrics_file', 'pod_metrics.json')
    )
    
    # If no arguments provided, default to interactive mode
    if len(sys.argv) == 1:
        interactive_mode()
        return
    
    if args.interactive or args.action == "interactive":
        interactive_mode()
        return
    
    if args.monitor or args.action == "monitor":
        monitor_pods()
        return
    
    if args.action == "list":
        print("Fetching RunPod information...")
        pods = fetch_pods()
        display_pods(pods)
        return
    
    if args.action in ["stop", "resume"]:
        if not args.pod_id and not args.pod_name:
            print("Error: --pod-id or --pod-name required for stop/resume operations")
            return
        
        print("Fetching pods...")
        pods = fetch_pods()
        if not pods:
            return
        
        target_pod = None
        if args.pod_id:
            target_pod = next((pod for pod in pods if pod['id'] == args.pod_id), None)
        elif args.pod_name:
            target_pod = next((pod for pod in pods if pod['name'].lower() == args.pod_name.lower()), None)
        
        if not target_pod:
            print(f"Pod not found: {args.pod_id or args.pod_name}")
            return
        
        print(f"Found pod: {target_pod['name']} ({target_pod['id']})")
        
        if args.action == "stop":
            print("Stopping pod...")
            result = stop_pod(target_pod['id'])
            if result:
                print(f"✓ Pod stopped successfully. New status: {result.get('podStop', {}).get('desiredStatus', 'Unknown')}")
            else:
                print("✗ Failed to stop pod")
                
        elif args.action == "resume":
            print("Resuming pod...")
            result = resume_pod(target_pod['id'])
            if result:
                if 'success' in result:
                    # REST API response
                    if result['success']:
                        print(f"✓ {result['message']}")
                    else:
                        print(f"✗ {result['message']}")
                else:
                    # GraphQL response
                    print(f"✓ Pod resumed successfully. New status: {result.get('podResume', {}).get('desiredStatus', 'Unknown')}")
            else:
                print("✗ Failed to resume pod")

if __name__ == "__main__":
    main()
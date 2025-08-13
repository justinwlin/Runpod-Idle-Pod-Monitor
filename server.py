#!/usr/bin/env python3
"""
RunPod Monitor Server
Simple entry point to start the web interface with integrated monitoring.
"""

import uvicorn
import threading
import time
from runpod_monitor.main import load_config, fetch_pods, data_tracker
from runpod_monitor.web_server import app

def simple_monitoring_loop():
    """Simple monitoring loop that just works."""
    print("🔄 Starting simple monitoring loop...")
    
    # Wait a moment for initialization to complete
    time.sleep(2)
    
    while True:
        try:
            print(f"📊 [{time.strftime('%H:%M:%S')}] Fetching pods from RunPod API...")
            pods = fetch_pods()
            
            if pods:
                print(f"   📦 Found {len(pods)} pods: {[pod['name'] for pod in pods]}")
                
                # Get the SAME data_tracker that the web server uses
                from runpod_monitor.main import data_tracker as main_data_tracker, config
                import runpod_monitor.main as main_module
                
                if main_data_tracker:
                    # Update timing variables for the UI countdown
                    current_time = time.time()
                    main_module.last_poll_time = current_time
                    main_module.next_poll_time = current_time + 60  # Next poll in 60 seconds
                    exclude_pods = config.get('auto_stop', {}).get('exclude_pods', []) if config else []
                    
                    # Auto-cleanup exclusion list: remove pods that no longer exist
                    if exclude_pods:
                        current_pod_ids = {pod['id'] for pod in pods}
                        current_pod_names = {pod['name'] for pod in pods}
                        original_exclude_count = len(exclude_pods)
                        
                        # Keep only pods that still exist (either by ID or name)
                        exclude_pods = [
                            pod_ref for pod_ref in exclude_pods 
                            if pod_ref in current_pod_ids or pod_ref in current_pod_names
                        ]
                        
                        # Save cleaned exclusion list if it changed
                        if len(exclude_pods) != original_exclude_count:
                            removed_count = original_exclude_count - len(exclude_pods)
                            print(f"   🧹 Auto-cleanup: Removed {removed_count} non-existent pods from exclusion list")
                            config['auto_stop']['exclude_pods'] = exclude_pods
                            
                            # Save config to file
                            try:
                                from runpod_monitor.web_server import save_config_to_file
                                config_path = './config/runpod_config.yaml'
                                save_config_to_file(config, config_path)
                                print(f"   💾 Updated exclusion list saved to config")
                            except Exception as e:
                                print(f"   ⚠️ Failed to save updated exclusion list: {e}")
                    
                    monitored_count = 0
                    excluded_count = 0
                    
                    for pod in pods:
                        pod_id = pod['id']
                        pod_name = pod['name']
                        status = pod.get('desiredStatus', 'Unknown')
                        
                        # Check if pod is excluded
                        is_excluded = pod_id in exclude_pods or pod_name in exclude_pods
                        
                        if is_excluded:
                            print(f"   🛡️  EXCLUDED: '{pod_name}' (status: {status}) - skipping data collection")
                            # Clean up any existing data for excluded pods
                            if main_data_tracker and main_data_tracker.has_data(pod_id):
                                main_data_tracker.clear_pod_data(pod_id)
                                print(f"   🧹 Cleaned up existing data for excluded pod: '{pod_name}'")
                            excluded_count += 1
                        else:
                            main_data_tracker.add_metric(pod_id, pod)
                            print(f"   📊 MONITORED: '{pod_name}' (status: {status}) - metrics collected")
                            
                            # Check auto-stop conditions if enabled
                            if config.get('auto_stop', {}).get('enabled', False):
                                thresholds = config.get('auto_stop', {}).get('thresholds', {})
                                monitor_only = config.get('auto_stop', {}).get('monitor_only', False)
                                
                                if main_data_tracker.check_auto_stop_conditions(pod_id, thresholds, exclude_pods):
                                    if monitor_only:
                                        print(f"   🔍 MONITOR-ONLY: Pod '{pod_name}' ({pod_id}) meets auto-stop conditions (would be stopped)")
                                    else:
                                        print(f"   ⚠️  Pod '{pod_name}' ({pod_id}) meets auto-stop conditions. Stopping...")
                                        
                                        from runpod_monitor.main import stop_pod
                                        result = stop_pod(pod_id)
                                        if result and result.get('podStop'):
                                            print(f"   ✅ Pod '{pod_name}' stopped successfully")
                                        else:
                                            print(f"   ❌ Failed to stop pod '{pod_name}'")
                            
                            monitored_count += 1
                    
                    print(f"   ✅ Summary: {monitored_count} pods monitored, {excluded_count} pods excluded")
                    if exclude_pods:
                        print(f"   🛡️  Exclude list: {exclude_pods}")
                    
                    # Verify data was actually stored
                    total_summaries = len(main_data_tracker.get_all_summaries())
                    print(f"   📈 Total tracked pods in data_tracker: {total_summaries}")
                else:
                    print("   ❌ Data tracker not initialized")
            else:
                print("   ⚠️ No pods found - API might be down or no pods exist")
                
        except Exception as e:
            print(f"   ❌ Error in monitoring loop: {e}")
            import traceback
            traceback.print_exc()
        
        print(f"   ⏰ Waiting 60 seconds until next collection...")
        time.sleep(60)

if __name__ == "__main__":
    print("🚀 Starting RunPod Monitor Server...")
    print("📊 Web interface: http://localhost:8080")
    print("🔄 Starting data collection immediately...")
    print("⏹️  Press Ctrl+C to stop")
    
    # Load config and initialize everything
    print("📋 Loading configuration...")
    load_config()
    
    # Import and check data tracker
    from runpod_monitor.main import data_tracker, config
    print(f"🗄️  Data tracker initialized: {data_tracker is not None}")
    print(f"⚙️  Config loaded: {config is not None}")
    if config:
        print(f"🔑 API key configured: {bool(config.get('api', {}).get('key'))}")
    
    # Start simple monitoring in background - no complex config checks, just do it
    monitoring_thread = threading.Thread(target=simple_monitoring_loop, daemon=True)
    monitoring_thread.start()
    print("✅ Background data collection started")
    
    # Start web server
    uvicorn.run(app, host="0.0.0.0", port=8080)
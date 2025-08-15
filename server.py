#!/usr/bin/env python3
"""
RunPod Monitor Server
Simple entry point to start the web interface with integrated monitoring.
"""

import uvicorn
import threading
import time
from datetime import datetime
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
                    
                    # Get current pod IDs for termination detection
                    current_pod_ids = {pod['id'] for pod in pods}
                    current_pod_names = {pod['name'] for pod in pods}
                    
                    # Check for terminated pods (pods we were tracking but are no longer in the API)
                    if main_data_tracker:
                        tracked_pods = set(main_data_tracker.data.keys())
                        terminated_pod_ids = tracked_pods - current_pod_ids
                        
                        for terminated_pod_id in terminated_pod_ids:
                            # Get the last known data for this pod
                            pod_data = main_data_tracker.data.get(terminated_pod_id, [])
                            if pod_data:
                                last_metric = pod_data[-1]
                                pod_name = last_metric.get('name', 'Unknown')
                                
                                # Check if we've already logged termination for this pod
                                already_terminated = any(
                                    metric.get('status') == 'TERMINATED' 
                                    for metric in pod_data
                                )
                                
                                if not already_terminated:
                                    print(f"   🔴 TERMINATED: Pod '{pod_name}' ({terminated_pod_id}) no longer exists - logging termination")
                                    
                                    # Create a termination record
                                    termination_record = last_metric.copy()
                                    termination_record.update({
                                        'timestamp': datetime.now().isoformat(),
                                        'epoch': int(time.time()),
                                        'status': 'TERMINATED',
                                        'cpu_percent': 0,
                                        'gpu_percent': 0,
                                        'memory_percent': 0,
                                        'uptime_seconds': 0
                                    })
                                    
                                    # Add termination record to the pod's data
                                    main_data_tracker.data[terminated_pod_id].append(termination_record)
                                    main_data_tracker.save_data()
                    
                    # Auto-cleanup exclusion list: remove pods that no longer exist
                    if exclude_pods:
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
                            
                            # NOTE: We don't apply rolling window here anymore to preserve historical data
                            # Data retention is handled by the retention policy cleanup instead
                            
                            # Check auto-stop conditions if monitoring is active
                            auto_stop_config = config.get('auto_stop', {})
                            enabled = auto_stop_config.get('enabled', False)
                            monitor_only = auto_stop_config.get('monitor_only', False)
                            
                            # Monitor if either enabled OR monitor_only is true
                            if enabled or monitor_only:
                                thresholds = auto_stop_config.get('thresholds', {})
                                
                                if main_data_tracker.check_auto_stop_conditions(pod_id, thresholds, exclude_pods):
                                    if monitor_only:
                                        print(f"   🔍 MONITOR-ONLY: Pod '{pod_name}' ({pod_id}) meets auto-stop conditions (would be stopped)")
                                    elif enabled:
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
        
        # Cleanup old data periodically (every hour)
        if int(current_time) % 3600 < 60:  # Once per hour (within first minute of each hour)
            storage_config = config.get('storage', {}) if config else {}
            retention_config = storage_config.get('retention_policy', {'value': 0, 'unit': 'forever'})
            if main_data_tracker:
                print(f"   🧹 Performing data retention cleanup...")
                main_data_tracker.cleanup_old_data(retention_config)
                print(f"   ✅ Data retention cleanup completed")
        
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
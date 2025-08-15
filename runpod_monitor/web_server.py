#!/usr/bin/env python3
"""
Web server for RunPod Monitor with HTMX-based GUI
"""

from fastapi import FastAPI, Request, Form, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import time
import yaml
import threading
from datetime import datetime
from typing import List, Dict, Optional

try:
    from .main import fetch_pods, stop_pod, resume_pod, load_config, config, data_tracker, monitor_pods, last_poll_time, next_poll_time
    from .data_tracker import DataTracker
except ImportError:
    from main import fetch_pods, stop_pod, resume_pod, load_config, config, data_tracker, monitor_pods, last_poll_time, next_poll_time
    from data_tracker import DataTracker

# Initialize configuration and data tracker when server starts
import os
# Use current working directory for config path
config_path = 'config.yaml'
print(f"🔍 Web server loading config from: {os.path.abspath(config_path)}")
load_config(config_path)
print(f"📋 Config after loading: auto_stop.enabled = {config.get('auto_stop', {}).get('enabled', 'NOT_SET') if config else 'CONFIG_IS_NONE'}")

def save_config_to_file(config_data, file_path):
    """Save configuration data to YAML file."""
    try:
        with open(file_path, 'w') as f:
            yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False

# Initialize data tracker if not already done
if data_tracker is None:
    try:
        from .main import config as main_config
    except ImportError:
        from main import config as main_config
    
    storage_config = main_config.get('storage', {}) if main_config else {}
    data_tracker = DataTracker(
        data_dir=storage_config.get('data_dir', './data'),
        metrics_file=storage_config.get('metrics_file', 'pod_metrics.json')
    )

app = FastAPI(title="RunPod Monitor", description="Monitor and manage your RunPod instances")

# Setup templates
templates = Jinja2Templates(directory="templates")

# Global variable to track monitoring thread
monitoring_thread = None
monitoring_active = False

def start_monitoring_background():
    """Start monitoring in a background thread if enabled."""
    global monitoring_thread, monitoring_active
    
    if config:
        if monitoring_thread is None or not monitoring_thread.is_alive():
            print("🔄 Starting background data collection...")
            monitoring_active = True
            monitoring_thread = threading.Thread(target=monitor_pods, daemon=True)
            monitoring_thread.start()
            auto_stop_enabled = config.get('auto_stop', {}).get('enabled', False)
            monitor_only = config.get('auto_stop', {}).get('monitor_only', False)
            
            if monitor_only:
                print("✅ Background monitoring started (Monitor-Only mode)")
            elif auto_stop_enabled:
                print("✅ Background monitoring started (Auto-Stop active)")
            else:
                print("✅ Background data collection started (Monitoring disabled)")
        else:
            print("ℹ️  Monitoring already running")
    else:
        print("⏸️  No configuration found")

def stop_monitoring_background():
    """Stop background monitoring."""
    global monitoring_active
    monitoring_active = False
    print("⏹️  Background monitoring stopped")

# Start monitoring when the server starts
@app.on_event("startup")
async def startup_event():
    print("🔄 Server startup: checking monitoring configuration...")
    print(f"   Auto-stop enabled: {config.get('auto_stop', {}).get('enabled', False) if config else False}")
    if config:
        print(f"   Config loaded: {bool(config)}")
        print(f"   Auto-stop section: {config.get('auto_stop', {})}")
    start_monitoring_background()

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page."""
    # Check if API key is configured
    try:
        from .main import config as current_config
    except ImportError:
        from main import config as current_config
    
    api_key_missing = False
    if not current_config or not current_config.get('api', {}).get('key') or current_config.get('api', {}).get('key') in ['YOUR_RUNPOD_API_KEY_HERE', '', None]:
        api_key_missing = True
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "api_key_missing": api_key_missing
    })

@app.get("/pods")
async def get_pods(request: Request):
    """Get all pods with their current status."""
    pods = fetch_pods()
    if not pods:
        return HTMLResponse("<p>No pods found or API error</p>")
    
    # Get exclude list
    try:
        from .main import config as current_config
    except ImportError:
        from main import config as current_config
    
    exclude_pods = current_config.get('auto_stop', {}).get('exclude_pods', []) if current_config else []
    
    # Add historical data and exclude status to each pod
    for pod in pods:
        pod_id = pod['id']
        if data_tracker:
            summary = data_tracker.get_pod_summary(pod_id)
            pod['summary'] = summary
        
        # Add exclude status
        pod['is_excluded'] = pod_id in exclude_pods or pod['name'] in exclude_pods
    
    return templates.TemplateResponse("pods_table.html", {"request": request, "pods": pods})

@app.post("/pods/{pod_id}/stop")
async def stop_pod_endpoint(pod_id: str, request: Request):
    """Stop a specific pod."""
    result = stop_pod(pod_id)
    
    if result and (result.get('podStop') or result.get('success')):
        status = "success"
        message = "Pod stopped successfully"
    else:
        status = "error"
        message = result.get('message', 'Failed to stop pod') if result else 'Failed to stop pod'
    
    return HTMLResponse(f'''
        <div class="alert alert-{status}" role="alert">
            {message}
        </div>
        <div hx-get="/pods" hx-target="#pods-container" hx-trigger="load delay:2s" hx-swap="innerHTML"></div>
    ''')

@app.post("/pods/{pod_id}/resume")
async def resume_pod_endpoint(pod_id: str, request: Request):
    """Resume a specific pod."""
    # Get pod info first to provide better error context
    pods = fetch_pods()
    pod_name = "Unknown Pod"
    is_cpu_pod = False
    
    if pods:
        for pod in pods:
            if pod['id'] == pod_id:
                pod_name = pod['name']
                # Check if it's a CPU pod (no GPUs)
                runtime = pod.get('runtime')
                is_cpu_pod = not runtime or not runtime.get('gpus', [])
                break
    
    result = resume_pod(pod_id)
    
    if result:
        if result.get('success'):
            # REST API response
            if result['success']:
                status = "success"
                message = f"✅ Pod '{pod_name}' resumed successfully"
            else:
                status = "warning"
                error_msg = result.get('message', 'Unknown error')
                
                # Enhanced error handling with specific guidance
                if 'vCPU' in error_msg or 'CPU' in error_msg:
                    message = f"""
                        <strong>⚠️ Resume Failed: '{pod_name}'</strong><br>
                        <small><strong>Issue:</strong> {error_msg}</small><br>
                        <small><strong>💡 Solution:</strong> CPU pods often fail due to no available vCPUs. Please resume manually via 
                        <a href="https://console.runpod.io" target="_blank" class="alert-link">RunPod Console</a> to select different resources.</small>
                    """
                else:
                    message = f"""
                        <strong>❌ Resume Failed: '{pod_name}'</strong><br>
                        <small><strong>Issue:</strong> {error_msg}</small><br>
                        <small><strong>💡 Recommendation:</strong> Try resuming manually via 
                        <a href="https://console.runpod.io" target="_blank" class="alert-link">RunPod Console</a> for better control.</small>
                    """
                    
        elif result.get('podResume'):
            # GraphQL response
            status = "success"
            message = f"✅ Pod '{pod_name}' resumed successfully. Status: {result['podResume'].get('desiredStatus', 'Unknown')}"
        else:
            status = "warning"
            message = f"""
                <strong>❌ Resume Failed: '{pod_name}'</strong><br>
                <small><strong>Issue:</strong> Unknown resume error occurred</small><br>
                <small><strong>💡 Recommendation:</strong> Please resume manually via 
                <a href="https://console.runpod.io" target="_blank" class="alert-link">RunPod Console</a> for better error details.</small>
            """
    else:
        status = "warning"
        pod_type = "CPU pod" if is_cpu_pod else "GPU pod"
        message = f"""
            <strong>❌ Resume Failed: '{pod_name}' ({pod_type})</strong><br>
            <small><strong>Issue:</strong> Resume request failed or timed out</small><br>
            <small><strong>💡 Recommendation:</strong> Please resume manually via 
            <a href="https://console.runpod.io" target="_blank" class="alert-link">RunPod Console</a> for better control.</small>
        """
    
    # Return persistent warning that doesn't auto-dismiss
    return HTMLResponse(f'''
        <div class="alert alert-{status} alert-dismissible" role="alert">
            {message}
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        </div>
        <div hx-get="/pods" hx-target="#pods-container" hx-trigger="load delay:3s" hx-swap="innerHTML"></div>
    ''')

@app.get("/config")
async def get_config(request: Request):
    """Get current configuration."""
    # Reload config from file to ensure we have latest values
    print(f"🔄 Config page: Reloading config from {config_path}")
    load_config(config_path)
    
    try:
        from .main import config as current_config
    except ImportError:
        from main import config as current_config
    
    # Debug config values
    if current_config:
        auto_stop = current_config.get('auto_stop', {})
        enabled = auto_stop.get('enabled')
        monitor_only = auto_stop.get('monitor_only')
        print(f"📋 Config values: enabled={enabled}, monitor_only={monitor_only}")
        print(f"📋 Template will set: enabled checkbox={enabled}, monitor_only checkbox={monitor_only}")
        print(f"📋 Full auto_stop config: {auto_stop}")
    else:
        print("❌ No config loaded!")
    
    # Get current pods to identify orphaned excluded pods
    current_pods = fetch_pods()
    current_pod_ids = {pod['id'] for pod in current_pods} if current_pods else set()
    
    excluded_pods = current_config.get('auto_stop', {}).get('exclude_pods', []) if current_config else []
    orphaned_excluded = [pod_id for pod_id in excluded_pods if pod_id not in current_pod_ids]
    
    # Debug what's actually being passed to template
    template_data = {
        "request": request, 
        "config": current_config,
        "orphaned_excluded_pods": orphaned_excluded
    }
    
    print(f"📋 Passing to template: config.auto_stop.monitor_only = {current_config.get('auto_stop', {}).get('monitor_only') if current_config else 'NO_CONFIG'}")
    print(f"📋 Template data keys: {list(template_data.keys())}")
    
    return templates.TemplateResponse("config.html", template_data)

@app.post("/config/auto-stop")
async def update_auto_stop(
    request: Request,
    enabled: bool = Form(False),
    monitor_only: bool = Form(False),
    max_cpu: int = Form(5),
    max_gpu: int = Form(5),
    max_memory: int = Form(10),
    duration: int = Form(1800),
    detect_no_change: bool = Form(False)
):
    """Update auto-stop configuration including no-change detection and persist to file."""
    try:
        from .main import config as current_config
    except ImportError:
        from main import config as current_config
        
    # Update in-memory configuration (all auto-stop settings)
    current_config['auto_stop']['enabled'] = enabled
    current_config['auto_stop']['monitor_only'] = monitor_only
    current_config['auto_stop']['thresholds']['max_cpu_percent'] = max_cpu
    current_config['auto_stop']['thresholds']['max_gpu_percent'] = max_gpu
    current_config['auto_stop']['thresholds']['max_memory_percent'] = max_memory
    current_config['auto_stop']['thresholds']['duration'] = duration
    current_config['auto_stop']['thresholds']['detect_no_change'] = detect_no_change
    
    # Save to file for persistence
    if save_config_to_file(current_config, config_path):
        status_msg = "✅ Auto-stop configuration updated and saved successfully!"
    else:
        status_msg = "⚠️  Configuration updated in memory but failed to save to file"
    
    # Start or stop monitoring based on enabled OR monitor_only state
    if enabled or monitor_only:
        start_monitoring_background()
        if monitor_only:
            monitoring_status = "🔍 Monitor-only data collection active"
        else:
            monitoring_status = "⚡ Auto-stop data collection active"
    else:
        stop_monitoring_background()
        monitoring_status = "⏸️ Data collection stopped"
    
    # Render the status overview with updated config
    status_overview_html = f'''
        <div class="d-flex justify-content-between align-items-center mb-2">
            <span>Auto-Stop:</span>
            {'<span class="badge bg-success">✅ Enabled</span>' if enabled else '<span class="badge bg-secondary">❌ Disabled</span>'}
        </div>
        
        <div class="d-flex justify-content-between align-items-center mb-2">
            <span>Monitor-Only:</span>
            {'<span class="badge bg-warning">🔍 On</span>' if monitor_only else '<span class="badge bg-secondary">❌ Off</span>'}
        </div>
        
        <div class="d-flex justify-content-between align-items-center">
            <span>No-Change:</span>
            {'<span class="badge bg-success">✅ On</span>' if detect_no_change else '<span class="badge bg-secondary">❌ Off</span>'}
        </div>
    '''
    
    # Return both the success message and updated status overview using hx-swap-oob
    return HTMLResponse(f'''
        <div class="alert alert-success" role="alert">
            {status_msg}<br>
            <small>Auto-stop {'enabled' if enabled else 'disabled'}, persistent duration: {duration}s ({duration//60} minutes)</small><br>
            <small>Monitor-only {'enabled' if monitor_only else 'disabled'}</small><br>
            <small>No-change detection {'enabled' if detect_no_change else 'disabled'}</small><br>
            <small>{monitoring_status}</small>
        </div>
        <div id="status-overview" hx-swap-oob="innerHTML">
            {status_overview_html}
        </div>
    ''')


@app.post("/config/sampling")
async def update_sampling_config(
    request: Request,
    sampling_frequency: int = Form(60),
    rolling_window: int = Form(3600)
):
    """Update sampling configuration separately."""
    try:
        from .main import config as current_config
    except ImportError:
        from main import config as current_config
        
    # Update sampling configuration
    if 'sampling' not in current_config['auto_stop']:
        current_config['auto_stop']['sampling'] = {}
    current_config['auto_stop']['sampling']['frequency'] = sampling_frequency
    current_config['auto_stop']['sampling']['rolling_window'] = rolling_window
    
    # Save to file for persistence
    if save_config_to_file(current_config, config_path):
        status_msg = "✅ Sampling configuration updated successfully!"
    else:
        status_msg = "⚠️ Configuration updated in memory but failed to save to file"
    
    # Render the current settings partial with updated config
    current_settings_html = templates.get_template("current_settings.html").render({"config": current_config})
    
    # Return both the success message and updated current settings using hx-swap-oob
    return HTMLResponse(f'''
        <div class="alert alert-success" role="alert">
            {status_msg}<br>
            <small>Data sampling every {sampling_frequency}s, rolling window {rolling_window}s</small>
        </div>
        <div id="current-settings" hx-swap-oob="innerHTML">
            {current_settings_html}
        </div>
    ''')

@app.get("/metrics")
async def get_metrics(request: Request):
    """Get metrics overview for active pods only."""
    if not data_tracker:
        return HTMLResponse("<p>Data tracker not initialized</p>")
    
    # Get current active pods from RunPod API
    current_pods = fetch_pods()
    active_pod_count = len(current_pods) if current_pods else 0
    
    if current_pods:
        active_pod_ids = {pod['id'] for pod in current_pods}
        active_pod_names = {pod['id']: pod['name'] for pod in current_pods}
        
        print(f"DEBUG: Found {len(current_pods)} active pods from API: {list(active_pod_names.values())}")
        
        # Get all summaries from data tracker
        all_summaries = data_tracker.get_all_summaries()
        print(f"DEBUG: Data tracker has {len(all_summaries)} pod summaries")
        
        # Filter to only include active pods that also have metrics data
        active_summaries = []
        for summary in all_summaries:
            if summary['pod_id'] in active_pod_ids:
                # Update summary with current pod name in case it changed
                summary['name'] = active_pod_names[summary['pod_id']]
                active_summaries.append(summary)
                print(f"DEBUG: Including metrics for active pod: {summary['name']} ({summary['pod_id']})")
        
        # Note: We no longer clean up "inactive" pod data here to preserve terminated pod history
        # Data cleanup is handled by the retention policy instead
        
        summaries = active_summaries
        pods_with_metrics = len(active_summaries)
    else:
        # If we can't fetch pods, show warning but don't clear data
        summaries = []
        pods_with_metrics = 0
        print("Warning: Could not fetch current pods from RunPod API")
    
    # Get config for template
    try:
        from .main import config as current_config
    except ImportError:
        from main import config as current_config
    
    # Get excluded pods information and count running pods
    exclude_list = current_config.get('auto_stop', {}).get('exclude_pods', []) if current_config else []
    excluded_pods_info = []
    running_pods_count = 0
    
    if current_pods:
        for pod in current_pods:
            if pod['id'] in exclude_list or pod['name'] in exclude_list:
                excluded_pods_info.append({
                    'id': pod['id'],
                    'name': pod['name'],
                    'status': pod.get('desiredStatus', 'Unknown')
                })
            
            # Count running pods from API data
            if pod.get('desiredStatus') == 'RUNNING':
                running_pods_count += 1
    
    return templates.TemplateResponse("metrics.html", {
        "request": request, 
        "summaries": summaries,
        "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_active_pods": active_pod_count,
        "running_pods_count": running_pods_count,
        "pods_with_metrics": pods_with_metrics,
        "excluded_pods_count": len(excluded_pods_info),
        "excluded_pods": excluded_pods_info,
        "config": current_config
    })

@app.get("/status")
async def get_status():
    """Get system status for API calls."""
    try:
        from .main import config as current_config
    except ImportError:
        from main import config as current_config
    
    # Get monitoring configuration
    sampling_freq = current_config.get('auto_stop', {}).get('sampling', {}).get('frequency', 60) if current_config else 60
    
    # Calculate actual next poll time from server-side monitoring
    current_time = time.time()
    if next_poll_time > 0:
        next_poll_seconds = max(0, int(next_poll_time - current_time))
    else:
        next_poll_seconds = sampling_freq
    
    return {
        "status": "running",
        "timestamp": datetime.now().isoformat(),
        "auto_stop_enabled": current_config.get('auto_stop', {}).get('enabled', False) if current_config else False,
        "tracked_pods": len(data_tracker.get_all_summaries()) if data_tracker else 0,
        "monitoring": {
            "sampling_frequency": sampling_freq,
            "next_poll_seconds": next_poll_seconds,
            "last_poll_time": last_poll_time,
            "next_poll_time": next_poll_time,
            "is_monitoring_active": monitoring_thread is not None and monitoring_thread.is_alive()
        }
    }

@app.get("/api/monitoring-status")
async def get_monitoring_status():
    """Get real-time monitoring status HTML for live updates."""
    try:
        from .main import config as current_config
    except ImportError:
        from main import config as current_config
    
    # Get current pods and metrics
    current_pods = fetch_pods()
    active_pod_count = len(current_pods) if current_pods else 0
    
    if data_tracker:
        all_summaries = data_tracker.get_all_summaries()
        if current_pods:
            active_pod_ids = {pod['id'] for pod in current_pods}
            pods_with_metrics = len([s for s in all_summaries if s['pod_id'] in active_pod_ids])
        else:
            pods_with_metrics = 0
    else:
        pods_with_metrics = 0
    
    sampling_freq = current_config.get('auto_stop', {}).get('sampling', {}).get('frequency', 30) if current_config else 60
    monitoring_enabled = current_config.get('auto_stop', {}).get('enabled', False) if current_config else False
    
    # Check if monitoring is actually running by looking at the file directly
    monitoring_active = False
    try:
        import json
        with open('./data/pod_metrics.json', 'r') as f:
            data = json.load(f)
            
        # Find the most recent data point
        latest_data_time = 0
        for pod_id, metrics_list in data.items():
            if metrics_list:
                latest_metric = metrics_list[-1]
                metric_time = latest_metric.get('epoch', 0)
                if metric_time > latest_data_time:
                    latest_data_time = metric_time
                    
        # If we have data within the last 2 minutes, monitoring is running
        current_time = time.time()
        if latest_data_time > current_time - 120:
            monitoring_active = True
            
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        monitoring_active = False
    
    # Create status indicators
    status_class = "success" if monitoring_active else "warning"
    status_icon = "🔄" if monitoring_active else "⏸️"
    status_text = "Active" if monitoring_active else "Inactive"
    
    return HTMLResponse(f'''
        <div class="mt-2 d-flex align-items-center justify-content-between" id="monitoring-status" hx-get="/api/monitoring-status" hx-trigger="every 5s" hx-target="this" hx-swap="outerHTML">
            <div class="d-flex align-items-center">
                <span class="badge bg-{status_class} me-2">{status_icon} Monitoring: {status_text}</span>
                <small class="text-muted">
                    Polling every {sampling_freq}s | {active_pod_count} pods | {pods_with_metrics} with data
                </small>
            </div>
            <small class="text-muted">
                Updated: {datetime.now().strftime("%H:%M:%S")}
            </small>
        </div>
    ''')

@app.get("/api/auto-stop-status")
async def get_auto_stop_status():
    """Get auto-stop status for dashboard quick view."""
    try:
        from .main import config as current_config
    except ImportError:
        from main import config as current_config
    
    auto_stop_enabled = current_config.get('auto_stop', {}).get('enabled', False) if current_config else False
    exclude_count = len(current_config.get('auto_stop', {}).get('exclude_pods', [])) if current_config else 0
    
    status_class = "success" if auto_stop_enabled else "secondary"
    status_icon = "🔄" if auto_stop_enabled else "⏸️"
    status_text = "Enabled" if auto_stop_enabled else "Disabled"
    
    return HTMLResponse(f'''
        <div class="d-flex align-items-center justify-content-between">
            <div>
                <span class="badge bg-{status_class}">
                    {status_icon} Auto-Stop: {status_text}
                </span>
                <small class="text-muted ms-2">
                    {exclude_count} excluded pods
                </small>
            </div>
            <button class="btn btn-sm btn-outline-primary" 
                    hx-post="/api/auto-stop-toggle" 
                    hx-target="body" 
                    hx-swap="none"
                    hx-trigger="click"
                    title="Quick toggle auto-stop">
                {"⏸️" if auto_stop_enabled else "▶️"}
            </button>
        </div>
    ''')

@app.post("/api/auto-stop-toggle")
async def toggle_auto_stop():
    """Quick toggle auto-stop on/off."""
    try:
        from .main import config as current_config
    except ImportError:
        from main import config as current_config
    
    # Toggle the enabled state
    current_enabled = current_config.get('auto_stop', {}).get('enabled', False) if current_config else False
    
    if 'auto_stop' not in current_config:
        current_config['auto_stop'] = {}
    
    current_config['auto_stop']['enabled'] = not current_enabled
    new_state = current_config['auto_stop']['enabled']
    
    # Save to file
    if save_config_to_file(current_config, config_path):
        # Show success feedback with auto-refresh of the status
        return HTMLResponse(f'''
            <div class="toast-container position-fixed top-0 end-0 p-3">
                <div class="toast show" role="alert">
                    <div class="toast-header">
                        <strong class="me-auto">✅ Settings Saved</strong>
                        <button type="button" class="btn-close" data-bs-dismiss="toast"></button>
                    </div>
                    <div class="toast-body">
                        Auto-stop is now <strong>{"enabled" if new_state else "disabled"}</strong>
                    </div>
                </div>
            </div>
            <div hx-get="/api/auto-stop-status" hx-target=".auto-stop-status" hx-trigger="load delay:500ms" hx-swap="innerHTML"></div>
        ''')
    else:
        return HTMLResponse(f'''
            <div class="toast-container position-fixed top-0 end-0 p-3">
                <div class="toast show" role="alert">
                    <div class="toast-header">
                        <strong class="me-auto">❌ Error</strong>
                        <button type="button" class="btn-close" data-bs-dismiss="toast"></button>
                    </div>
                    <div class="toast-body">
                        Failed to save configuration
                    </div>
                </div>
            </div>
        ''')

@app.get("/api/next-poll")
async def get_next_poll():
    """Simple endpoint - when is next collection?"""
    current_time = time.time()
    
    # Just check the file directly for recent data
    monitoring_running = False
    latest_data_time = 0
    
    try:
        import json
        with open('./data/pod_metrics.json', 'r') as f:
            data = json.load(f)
            
        # Find the most recent data point across all pods
        for pod_id, metrics_list in data.items():
            if metrics_list:
                latest_metric = metrics_list[-1]
                metric_time = latest_metric.get('epoch', 0)
                if metric_time > latest_data_time:
                    latest_data_time = metric_time
                    
        # If we have data within the last 2 minutes, monitoring is running
        if latest_data_time > current_time - 120:
            monitoring_running = True
            
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        # No file or bad data = not monitoring
        monitoring_running = False
    
    # Calculate next collection time (assuming 60 second intervals)
    if monitoring_running and latest_data_time > 0:
        next_expected = latest_data_time + 60
        if next_expected > current_time:
            seconds_remaining = int(next_expected - current_time)
            next_time_str = datetime.fromtimestamp(next_expected).strftime("%H:%M:%S")
        else:
            seconds_remaining = 0
            next_time_str = "Soon"
    else:
        seconds_remaining = 0
        next_time_str = "Unknown"
    
    return {
        "seconds_remaining": seconds_remaining,
        "next_collection_time": next_time_str,
        "monitoring_running": monitoring_running
    }

@app.get("/api/raw-data")
async def get_raw_data(request: Request, page: int = 1, status_filter: str = None):
    """Get raw data points as HTML table with pagination and optional status filtering."""
    try:
        import json
        with open('./data/pod_metrics.json', 'r') as f:
            data = json.load(f)
        
        # Get current pods from API to determine actual status
        current_pods = fetch_pods()
        current_pod_ids = set()
        current_pod_statuses = {}
        
        if current_pods:
            for pod in current_pods:
                current_pod_ids.add(pod['id'])
                current_pod_statuses[pod['id']] = {
                    'name': pod['name'],
                    'status': pod.get('desiredStatus', 'UNKNOWN'),
                    'cost_per_hr': pod.get('costPerHr', 0)
                }
        
        # Process all historical data and determine real status
        all_raw_data = []
        for pod_id, metrics_list in data.items():
            for metric in metrics_list:
                # Use the STORED status from each individual data point
                stored_status = metric.get('status', 'UNKNOWN')
                stored_name = metric.get('name', 'Unknown')
                stored_cost = metric.get('cost_per_hr', 0)
                
                # Only override if the stored data is incomplete or pod no longer exists
                if stored_status == 'UNKNOWN' or stored_status == '':
                    if pod_id in current_pod_ids:
                        # Use current API data for incomplete records
                        actual_status = current_pod_statuses[pod_id]['status']
                        actual_name = current_pod_statuses[pod_id]['name']
                        actual_cost = current_pod_statuses[pod_id]['cost_per_hr']
                    else:
                        # Pod no longer exists and no stored status
                        actual_status = 'TERMINATED'
                        actual_name = stored_name
                        actual_cost = stored_cost
                else:
                    # Use the stored status - this preserves historical accuracy
                    actual_status = stored_status
                    actual_name = stored_name
                    actual_cost = stored_cost
                
                # Update name/cost if pod still exists (in case name changed)
                if pod_id in current_pod_ids and actual_status != 'TERMINATED':
                    actual_name = current_pod_statuses[pod_id]['name']
                    actual_cost = current_pod_statuses[pod_id]['cost_per_hr']
                
                # Create enhanced metric with actual status
                enhanced_metric = metric.copy()
                enhanced_metric['actual_status'] = actual_status
                enhanced_metric['actual_name'] = actual_name
                enhanced_metric['actual_cost'] = actual_cost
                
                all_raw_data.append(enhanced_metric)
                    
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return HTMLResponse("<p>No metrics data file found</p>")
    
    # Sort by timestamp, newest first
    all_raw_data.sort(key=lambda x: x.get('epoch', 0), reverse=True)
    
    if not all_raw_data:
        return HTMLResponse("<p>No raw data points available yet</p>")
    
    # Apply status filter
    if status_filter:
        if status_filter == 'active':
            all_raw_data = [m for m in all_raw_data if m.get('actual_status') == 'RUNNING']
        elif status_filter == 'exited':
            all_raw_data = [m for m in all_raw_data if m.get('actual_status') in ['STOPPED', 'EXITED']]
        elif status_filter == 'terminated':
            all_raw_data = [m for m in all_raw_data if m.get('actual_status') == 'TERMINATED']
    
    # Pagination settings
    ITEMS_PER_PAGE = 50
    total_items = len(all_raw_data)
    total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    
    # Ensure page is within bounds
    page = max(1, min(page, total_pages if total_pages > 0 else 1))
    
    # Calculate pagination slice
    start_idx = (page - 1) * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    paginated_data = all_raw_data[start_idx:end_idx]
    
    # Count by status for filter buttons
    total_count = len(all_raw_data)
    active_count = len([m for m in all_raw_data if m.get('actual_status') == 'RUNNING'])
    exited_count = len([m for m in all_raw_data if m.get('actual_status') in ['STOPPED', 'EXITED']])
    terminated_count = len([m for m in all_raw_data if m.get('actual_status') == 'TERMINATED'])
    
    # Build simple HTML with status filter buttons and pagination
    html = f'''
    <div class="mb-3">
        <div class="row">
            <div class="col-md-8">
                <div class="btn-group flex-wrap" role="group" aria-label="Status Filter">
                    <button type="button" class="btn btn-sm {'btn-primary' if not status_filter else 'btn-outline-primary'}" 
                            hx-get="/api/raw-data?page={page}" hx-target="#raw-data-table" hx-swap="innerHTML">
                        All ({total_count})
                    </button>
                    <button type="button" class="btn btn-sm {'btn-success' if status_filter == 'active' else 'btn-outline-success'}" 
                            hx-get="/api/raw-data?status_filter=active&page=1" hx-target="#raw-data-table" hx-swap="innerHTML">
                        Active ({active_count})
                    </button>
                    <button type="button" class="btn btn-sm {'btn-warning' if status_filter == 'exited' else 'btn-outline-warning'}" 
                            hx-get="/api/raw-data?status_filter=exited&page=1" hx-target="#raw-data-table" hx-swap="innerHTML">
                        Exited ({exited_count})
                    </button>
                    <button type="button" class="btn btn-sm {'btn-danger' if status_filter == 'terminated' else 'btn-outline-danger'}" 
                            hx-get="/api/raw-data?status_filter=terminated&page=1" hx-target="#raw-data-table" hx-swap="innerHTML">
                        Terminated ({terminated_count})
                    </button>
                </div>
            </div>
            <div class="col-md-4 text-end">
                <small class="text-muted">
                    Showing {start_idx + 1}-{min(end_idx, total_items)} of {total_items} entries
                </small>
            </div>
        </div>
    </div>
    
    <!-- Pagination -->
    <div class="d-flex justify-content-between align-items-center mb-3">
        <div>
            <small class="text-muted">Page {page} of {total_pages}</small>
        </div>
        <div>
            <div class="btn-group" role="group">
    '''
    
    # Previous page button
    if page > 1:
        prev_url = f"/api/raw-data?page={page-1}"
        if status_filter:
            prev_url += f"&status_filter={status_filter}"
        html += f'''
                <button type="button" class="btn btn-sm btn-outline-secondary" 
                        hx-get="{prev_url}" hx-target="#raw-data-table" hx-swap="innerHTML">
                    « Previous
                </button>
        '''
    
    # Next page button
    if page < total_pages:
        next_url = f"/api/raw-data?page={page+1}"
        if status_filter:
            next_url += f"&status_filter={status_filter}"
        html += f'''
                <button type="button" class="btn btn-sm btn-outline-secondary" 
                        hx-get="{next_url}" hx-target="#raw-data-table" hx-swap="innerHTML">
                    Next »
                </button>
        '''
    
    html += '''
            </div>
        </div>
    </div>
    
    <div class="table-responsive">
        <table class="table table-sm table-striped">
            <thead class="table-dark">
                <tr>
                    <th>Timestamp</th>
                    <th>Pod Name</th>
                    <th>Pod ID</th>
                    <th>Status</th>
                    <th>CPU%</th>
                    <th>GPU%</th>
                    <th>Memory%</th>
                    <th>Uptime</th>
                    <th>Cost/Hr</th>
                </tr>
            </thead>
            <tbody>
    '''
    
    # Use paginated data
    for metric in paginated_data:
        timestamp = datetime.fromisoformat(metric.get('timestamp', '')).strftime('%H:%M:%S') if metric.get('timestamp') else 'Unknown'
        uptime_hours = metric.get('uptime_seconds', 0) // 3600
        uptime_mins = (metric.get('uptime_seconds', 0) % 3600) // 60
        
        # Use actual status for display
        actual_status = metric.get('actual_status', 'UNKNOWN')
        actual_name = metric.get('actual_name', metric.get('name', 'Unknown'))
        actual_cost = metric.get('actual_cost', metric.get('cost_per_hr', 0))
        
        # Set badge color based on actual status
        if actual_status == 'RUNNING':
            badge_color = 'success'
        elif actual_status in ['STOPPED', 'EXITED']:
            badge_color = 'warning'
        elif actual_status == 'TERMINATED':
            badge_color = 'danger'
        else:
            badge_color = 'secondary'
        
        html += f'''
                <tr>
                    <td><small>{timestamp}</small></td>
                    <td><small>{actual_name}</small></td>
                    <td><small class="text-muted">{metric.get('pod_id', 'Unknown')[:8]}...</small></td>
                    <td><span class="badge bg-{badge_color}">{actual_status}</span></td>
                    <td>{metric.get('cpu_percent', 0)}%</td>
                    <td>{metric.get('gpu_percent', 0)}%</td>
                    <td>{metric.get('memory_percent', 0)}%</td>
                    <td><small>{uptime_hours}h {uptime_mins}m</small></td>
                    <td><small>${actual_cost}</small></td>
                </tr>
        '''
    
    if not paginated_data:
        html += '''
                <tr>
                    <td colspan="9" class="text-center text-muted">
                        <em>No data points found</em>
                    </td>
                </tr>
        '''
    
    html += '''
            </tbody>
        </table>
    </div>
    '''
    
    return HTMLResponse(html)

@app.get("/api/auto-stop-predictions")
async def get_auto_stop_predictions(request: Request):
    """Get predictions for which pods are close to being auto-stopped."""
    try:
        from .main import config as current_config
    except ImportError:
        from main import config as current_config
    
    if not current_config:
        return HTMLResponse("<p class='text-muted'>No configuration available</p>")
    
    monitor_only = current_config.get('auto_stop', {}).get('monitor_only', False)
    
    # Read data from file
    try:
        import json
        with open('./data/pod_metrics.json', 'r') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return HTMLResponse("<p class='text-muted'>No data available</p>")
    
    # Get thresholds from config
    thresholds = current_config.get('auto_stop', {}).get('thresholds', {})
    max_cpu = thresholds.get('max_cpu_percent', 5)
    max_gpu = thresholds.get('max_gpu_percent', 5)
    max_memory = thresholds.get('max_memory_percent', 20)
    duration = thresholds.get('duration', 1800)  # 30 minutes default
    
    # Calculate data points needed (duration / sampling frequency)
    sampling_freq = current_config.get('auto_stop', {}).get('sampling', {}).get('frequency', 60)
    points_needed = duration // sampling_freq
    
    # Get current pods and exclude list
    current_pods = fetch_pods()
    exclude_list = current_config.get('auto_stop', {}).get('exclude_pods', [])
    pod_names = {pod['id']: pod['name'] for pod in current_pods} if current_pods else {}
    
    predictions = []
    
    for pod_id, metrics_list in data.items():
        if not metrics_list or pod_id in exclude_list:
            continue
            
        pod_name = pod_names.get(pod_id, f"Pod {pod_id[:8]}")
        
        # Only consider RUNNING pods for auto-stop predictions
        latest_status = metrics_list[-1].get('status', 'UNKNOWN')
        if latest_status != 'RUNNING':
            continue
        
        # Only check pods that are currently active (in current_pods list)
        if pod_id not in pod_names:
            continue
        
        # Calculate averages for the time period being analyzed (last duration seconds)
        cutoff_time = time.time() - duration
        recent_metrics = [
            metric for metric in metrics_list
            if metric.get('epoch', 0) >= cutoff_time and metric.get('status') == 'RUNNING'
        ]
        
        avg_cpu = avg_memory = avg_gpu = 0
        if recent_metrics:
            total_cpu = sum(metric.get('cpu_percent', 0) for metric in recent_metrics)
            total_memory = sum(metric.get('memory_percent', 0) for metric in recent_metrics)
            total_gpu = sum(metric.get('gpu_percent', 0) for metric in recent_metrics)
            count = len(recent_metrics)
            
            avg_cpu = round(total_cpu / count, 1)
            avg_memory = round(total_memory / count, 1) 
            avg_gpu = round(total_gpu / count, 1)
        
        # Count consecutive RUNNING points from the most recent that meet auto-stop criteria
        meeting_criteria = 0
        
        # Start from the most recent point and work backwards
        for metric in reversed(metrics_list):
            status = metric.get('status')
            
            # Only count RUNNING points
            if status != 'RUNNING':
                break
                
            cpu = metric.get('cpu_percent', 0)
            gpu = metric.get('gpu_percent', 0)
            memory = metric.get('memory_percent', 0)
            
            # Check if this point meets auto-stop criteria
            if cpu <= max_cpu and gpu <= max_gpu and memory <= max_memory:
                meeting_criteria += 1
                # Stop counting if we've reached the required duration
                if meeting_criteria >= points_needed:
                    break
            else:
                # Reset count if criteria not met (must be consecutive)
                meeting_criteria = 0
        
        if meeting_criteria > 0:
            remaining_points = max(0, points_needed - meeting_criteria)
            predictions.append({
                'pod_id': pod_id,
                'pod_name': pod_name,
                'meeting_criteria': meeting_criteria,
                'remaining_points': remaining_points,
                'total_needed': points_needed,
                'progress_percent': (meeting_criteria / points_needed) * 100,
                'avg_cpu': avg_cpu,
                'avg_memory': avg_memory,
                'avg_gpu': avg_gpu
            })
    
    if not predictions:
        return HTMLResponse("<p class='text-muted'>No pods currently approaching auto-stop thresholds</p>")
    
    # Sort by closest to being stopped
    predictions.sort(key=lambda x: x['remaining_points'])
    
    html = '''
    <div class="table-responsive">
        <table class="table table-sm">
            <thead class="table-dark">
                <tr>
                    <th>Pod Name</th>
                    <th>Pod ID</th>
                    <th>Progress</th>
                    <th>Data Points</th>
                    <th>Avg CPU %</th>
                    <th>Avg Memory %</th>
                    <th>Avg GPU %</th>
                    <th>Status</th>
                    <th>Action</th>
                </tr>
            </thead>
            <tbody>
    '''
    
    for pred in predictions:
        if pred['remaining_points'] == 0:
            status_class = "danger"
            if monitor_only:
                status_text = "🔍 Monitor Alert"
            else:
                status_text = "Ready to Stop"
        elif pred['remaining_points'] <= 3:
            status_class = "warning"
            status_text = f"{pred['remaining_points']} more"
        else:
            status_class = "info"
            status_text = f"{pred['remaining_points']} more"
        
        pod_id_short = pred['pod_id'][:8] + "..." if len(pred['pod_id']) > 8 else pred['pod_id']
        
        html += f'''
            <tr>
                <td><small>{pred['pod_name']}</small></td>
                <td><small><code>{pod_id_short}</code></small></td>
                <td>
                    <div class="progress" style="height: 15px;">
                        <div class="progress-bar bg-{status_class}" style="width: {pred['progress_percent']}%">
                            {pred['progress_percent']:.0f}%
                        </div>
                    </div>
                </td>
                <td><small>{pred['meeting_criteria']}/{pred['total_needed']}</small></td>
                <td><small>{pred['avg_cpu']}%</small></td>
                <td><small>{pred['avg_memory']}%</small></td>
                <td><small>{pred['avg_gpu']}%</small></td>
                <td><span class="badge bg-{status_class}">{status_text}</span></td>
                <td>
                    <button class="btn btn-outline-danger btn-sm" 
                            hx-post="/pods/{pred['pod_id']}/stop"
                            hx-confirm="Stop pod '{pred['pod_name']}'?"
                            hx-target="closest tr"
                            hx-swap="outerHTML">
                        🛑 Stop
                    </button>
                </td>
            </tr>
        '''
    
    html += '''
            </tbody>
        </table>
    </div>
    '''
    
    return HTMLResponse(html)

@app.get("/api/graph-pods")
async def get_graph_pods():
    """Get list of pods that have data for graphing."""
    print("📊 Graph pods API called")
    try:
        import json
        with open('./data/pod_metrics.json', 'r') as f:
            data = json.load(f)
        print(f"📊 Loaded data for {len(data)} pods from file")
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"📊 Error loading data: {e}")
        return JSONResponse([])
    
    # Get current active pods
    current_pods = fetch_pods()
    print(f"📊 Found {len(current_pods) if current_pods else 0} active pods from API")
    
    if not current_pods:
        # If can't fetch from API, return all pods with data
        print("📊 API fetch failed, returning all pods with data")
        pods_with_data = []
        for pod_id, metrics in data.items():
            if metrics:
                # Get pod name from latest metric
                latest_metric = metrics[-1] if metrics else {}
                pod_name = latest_metric.get('name', pod_id[:8] + '...')
                pods_with_data.append({
                    'id': pod_id,
                    'name': pod_name
                })
        print(f"📊 Returning {len(pods_with_data)} pods with data")
        return JSONResponse(pods_with_data)
    
    active_pod_names = {pod['id']: pod['name'] for pod in current_pods}
    
    # Return pods that have data and are currently active
    pods_with_data = []
    for pod_id, metrics in data.items():
        if pod_id in active_pod_names and metrics:
            pods_with_data.append({
                'id': pod_id,
                'name': active_pod_names[pod_id]
            })
    
    print(f"📊 Returning {len(pods_with_data)} active pods with data")
    return JSONResponse(pods_with_data)

@app.get("/api/graph-data/{pod_id}")
async def get_graph_data(pod_id: str, timeRange: int = 3600):
    """Get metrics data for a specific pod for graphing."""
    try:
        import json
        with open('./data/pod_metrics.json', 'r') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return JSONResponse({'error': 'No data available'})
    
    if pod_id not in data:
        return JSONResponse({'error': 'Pod not found'})
    
    # Filter data by time range
    cutoff_time = time.time() - timeRange
    recent_metrics = [
        metric for metric in data[pod_id]
        if metric.get('epoch', 0) >= cutoff_time
    ]
    
    if not recent_metrics:
        return JSONResponse({'error': 'No recent data'})
    
    # Sort by timestamp
    recent_metrics.sort(key=lambda x: x.get('epoch', 0))
    
    # Extract data for chart
    timestamps = []
    cpu_data = []
    memory_data = []
    gpu_data = []
    
    for metric in recent_metrics:
        # Format timestamp
        timestamp = metric.get('timestamp', '')
        if timestamp:
            # Convert to readable format
            from datetime import datetime
            try:
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                timestamps.append(dt.strftime('%H:%M:%S'))
            except:
                timestamps.append(timestamp[-8:])  # Last 8 chars for time
        else:
            timestamps.append('')
        
        cpu_data.append(metric.get('cpu_percent', 0))
        memory_data.append(metric.get('memory_percent', 0))
        gpu_data.append(metric.get('gpu_percent', 0))
    
    # Get pod name
    current_pods = fetch_pods()
    pod_name = pod_id[:8] + "..."
    if current_pods:
        for pod in current_pods:
            if pod['id'] == pod_id:
                pod_name = pod['name']
                break
    
    return JSONResponse({
        'podName': pod_name,
        'timestamps': timestamps,
        'cpu': cpu_data,
        'memory': memory_data,
        'gpu': gpu_data
    })

@app.get("/api/debug/startup")
async def debug_startup():
    """Debug startup state."""
    global monitoring_thread
    return {
        "startup_debug": {
            "config_exists": config is not None,
            "config_auto_stop": config.get('auto_stop', {}) if config else None,
            "monitoring_thread_exists": monitoring_thread is not None,
            "monitoring_thread_alive": monitoring_thread.is_alive() if monitoring_thread else False,
            "data_tracker_exists": data_tracker is not None,
            "server_startup_completed": True
        }
    }

@app.post("/api/monitoring/start")
async def start_monitoring_endpoint():
    """Start monitoring via API endpoint."""
    global monitoring_thread
    
    try:
        start_monitoring_background()
        
        # Check if monitoring actually started
        if monitoring_thread and monitoring_thread.is_alive():
            status = "success"
            message = "✅ Data collection started successfully! Check the metrics page to see data being collected."
        else:
            status = "warning"
            message = "⚠️ Monitoring thread started but may not be active. Check auto-stop settings."
        
    except Exception as e:
        status = "danger"
        message = f"❌ Failed to start monitoring: {str(e)}"
    
    return HTMLResponse(f'''
        <div class="alert alert-{status}" role="alert">
            {message}
        </div>
        <div hx-get="/api/monitoring-status" hx-target="#monitoring-status" hx-trigger="load delay:2s" hx-swap="outerHTML"></div>
    ''')

@app.post("/api/monitoring/stop") 
async def stop_monitoring_endpoint():
    """Stop monitoring via API endpoint."""
    stop_monitoring_background()
    return {"status": "success", "message": "Monitoring stopped"}

@app.post("/pods/{pod_id}/exclude")
async def exclude_pod(pod_id: str, request: Request):
    """Add a pod to the exclude list."""
    try:
        from .main import config as current_config
    except ImportError:
        from main import config as current_config
    
    # Get pod info to show name
    pods = fetch_pods()
    pod_name = "Unknown"
    for pod in pods or []:
        if pod['id'] == pod_id:
            pod_name = pod['name']
            break
    
    # Add to exclude list if not already there
    if 'auto_stop' not in current_config:
        current_config['auto_stop'] = {}
    if 'exclude_pods' not in current_config['auto_stop']:
        current_config['auto_stop']['exclude_pods'] = []
    
    if pod_id not in current_config['auto_stop']['exclude_pods']:
        current_config['auto_stop']['exclude_pods'].append(pod_id)
        
        # Save to file
        if save_config_to_file(current_config, config_path):
            status = "success"
            message = f"✅ '{pod_name}' excluded from auto-stop"
        else:
            status = "warning"
            message = f"⚠️ '{pod_name}' excluded but failed to save to file"
    else:
        status = "info"
        message = f"ℹ️ '{pod_name}' already excluded"
    
    # Return updated message and trigger pod list refresh
    return HTMLResponse(f'''
        <div class="alert alert-{status} alert-dismissible">
            <small>{message}</small>
        </div>
        <div hx-get="/pods" hx-target="#pod-table" hx-trigger="load delay:1s" hx-select="#pod-table" hx-swap="outerHTML"></div>
    ''')

@app.post("/pods/{pod_id}/include")
async def include_pod(pod_id: str, request: Request):
    """Remove a pod from the exclude list."""
    try:
        from .main import config as current_config
    except ImportError:
        from main import config as current_config
    
    # Get pod info to show name - try current pods first, then check exclude list
    pods = fetch_pods()
    pod_name = "Unknown"
    pod_exists = False
    
    # Check if pod exists in current pods
    for pod in pods or []:
        if pod['id'] == pod_id:
            pod_name = pod['name']
            pod_exists = True
            break
    
    # If pod doesn't exist but is in exclude list, allow removal
    if not pod_exists and current_config and current_config.get('auto_stop', {}).get('exclude_pods'):
        excluded_pods = current_config['auto_stop']['exclude_pods']
        if pod_id in excluded_pods:
            pod_name = f"Deleted pod ({pod_id})"
    
    # Remove from exclude list if present
    if (current_config and 
        current_config.get('auto_stop', {}).get('exclude_pods') and 
        pod_id in current_config['auto_stop']['exclude_pods']):
        
        current_config['auto_stop']['exclude_pods'].remove(pod_id)
        
        # Save to file
        if save_config_to_file(current_config, config_path):
            if pod_exists:
                status = "success"
                message = f"✅ '{pod_name}' included in auto-stop monitoring"
            else:
                status = "success"
                message = f"✅ Removed '{pod_name}' from exclude list (pod no longer exists)"
        else:
            status = "warning" 
            message = f"⚠️ '{pod_name}' included but failed to save to file"
    else:
        status = "info"
        message = f"ℹ️ '{pod_name}' already included or not in exclude list"
    
    # Return updated message and trigger pod list refresh
    return HTMLResponse(f'''
        <div class="alert alert-{status} alert-dismissible">
            <small>{message}</small>
        </div>
        <div hx-get="/pods" hx-target="#pod-table" hx-trigger="load delay:1s" hx-select="#pod-table" hx-swap="outerHTML"></div>
    ''')

@app.post("/config/cleanup-excluded")
async def cleanup_excluded_pods(request: Request):
    """Remove all excluded pods that no longer exist."""
    try:
        from .main import config as current_config
    except ImportError:
        from main import config as current_config
    
    # Get current pods to identify orphaned excluded pods
    current_pods = fetch_pods()
    current_pod_ids = {pod['id'] for pod in current_pods} if current_pods else set()
    
    excluded_pods = current_config.get('auto_stop', {}).get('exclude_pods', []) if current_config else []
    orphaned_excluded = [pod_id for pod_id in excluded_pods if pod_id not in current_pod_ids]
    
    if orphaned_excluded:
        # Remove orphaned pods from exclude list
        current_config['auto_stop']['exclude_pods'] = [
            pod_id for pod_id in excluded_pods if pod_id in current_pod_ids
        ]
        
        # Also clean up their data
        for pod_id in orphaned_excluded:
            if data_tracker:
                data_tracker.clear_pod_data(pod_id)
        
        # Save to file
        if save_config_to_file(current_config, config_path):
            status = "success"
            message = f"✅ Cleaned up {len(orphaned_excluded)} deleted excluded pods"
        else:
            status = "warning" 
            message = f"⚠️ Cleaned up pods but failed to save to file"
    else:
        status = "info"
        message = "ℹ️ No orphaned excluded pods found"
    
    return HTMLResponse(f'''
        <div class="alert alert-{status} alert-dismissible">
            <small>{message}</small>
        </div>
    ''')

@app.get("/api/export")
async def export_data_endpoint(
    format: str = Query("csv", description="Export format: csv or json"),
    pod_id: Optional[str] = Query(None, description="Specific pod ID to export"),
    duration: Optional[int] = Query(None, description="Duration in seconds (e.g., 3600 for 1 hour)"),
    start_time: Optional[int] = Query(None, description="Start timestamp (Unix epoch)"),
    end_time: Optional[int] = Query(None, description="End timestamp (Unix epoch)")
):
    """Export pod metrics data in CSV or JSON format."""
    if not data_tracker:
        return JSONResponse({"error": "Data tracker not available"}, status_code=500)
    
    try:
        exported_data = data_tracker.export_data(
            format_type=format,
            pod_id=pod_id,
            start_time=start_time,
            end_time=end_time,
            duration_seconds=duration
        )
        
        # Determine filename and content type
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if format.lower() == "csv":
            filename = f"runpod_metrics_{timestamp}.csv"
            content_type = "text/csv"
        else:
            filename = f"runpod_metrics_{timestamp}.json"
            content_type = "application/json"
        
        # Add pod name to filename if specific pod
        if pod_id:
            try:
                # Try to get pod name from current pods
                current_pods = fetch_pods()
                pod_name = None
                if current_pods:
                    for pod in current_pods:
                        if pod['id'] == pod_id:
                            pod_name = pod['name'].replace(' ', '_').replace('/', '_')
                            break
                
                if pod_name:
                    filename = f"runpod_metrics_{pod_name}_{timestamp}.{format.lower()}"
            except:
                pass  # Keep original filename if error
        
        headers = {
            "Content-Disposition": f"attachment; filename={filename}"
        }
        
        return Response(
            content=exported_data,
            media_type=content_type,
            headers=headers
        )
        
    except Exception as e:
        return JSONResponse({"error": f"Export failed: {str(e)}"}, status_code=500)

@app.post("/config/retention")
async def update_retention_config(
    request: Request,
    retention_value: Optional[int] = Form(None),
    retention_unit: str = Form(...)
):
    """Update data retention policy configuration."""
    # Debug: log received values
    print(f"DEBUG: Received retention_value={retention_value} (type: {type(retention_value)}), retention_unit={retention_unit}")
    
    try:
        from .main import config as current_config
    except ImportError:
        from main import config as current_config
    
    if not current_config:
        return HTMLResponse(
            '<div class="alert alert-danger">No configuration available</div>',
            status_code=500
        )
    
    # Update retention policy
    if 'storage' not in current_config:
        current_config['storage'] = {}
    
    # Ensure we have a valid value
    if retention_value is None or retention_value <= 0:
        retention_value = 1  # Simple fallback
    
    current_config['storage']['retention_policy'] = {
        'value': retention_value,
        'unit': retention_unit
    }
    
    # Save to file
    if save_config_to_file(current_config, config_path):
        status = "success"
        message = f"✅ Data retention updated to {retention_value} {retention_unit}"
    else:
        status = "danger"
        message = "❌ Failed to save retention configuration"
    
    # Prepare the current display text for the updated config
    current_display = f"Current: {retention_value} {retention_unit}"
    
    return HTMLResponse(f'''
        <div class="alert alert-{status} alert-dismissible">
            {message}
        </div>
        <script>
            // Update the current retention display
            document.getElementById('current-retention-display').innerHTML = '{current_display}';
        </script>
    ''')

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
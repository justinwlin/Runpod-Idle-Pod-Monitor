#!/usr/bin/env python3
"""
Web server for RunPod Monitor with HTMX-based GUI
"""

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import time
import yaml
import threading
from datetime import datetime
from typing import List, Dict

try:
    from .main import fetch_pods, stop_pod, resume_pod, load_config, config, data_tracker, monitor_pods
    from .data_tracker import DataTracker
except ImportError:
    from main import fetch_pods, stop_pod, resume_pod, load_config, config, data_tracker, monitor_pods
    from data_tracker import DataTracker

# Initialize configuration and data tracker when server starts
import os
# Use current working directory for config path
config_path = 'config.yaml'
load_config(config_path)

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
    
    if config and config.get('auto_stop', {}).get('enabled', False):
        if monitoring_thread is None or not monitoring_thread.is_alive():
            print("🔄 Starting background monitoring...")
            monitoring_active = True
            monitoring_thread = threading.Thread(target=monitor_pods, daemon=True)
            monitoring_thread.start()
            print("✅ Background monitoring started")
        else:
            print("ℹ️  Monitoring already running")
    else:
        print("⏸️  Monitoring disabled in configuration")

def stop_monitoring_background():
    """Stop background monitoring."""
    global monitoring_active
    monitoring_active = False
    print("⏹️  Background monitoring stopped")

# Start monitoring when the server starts
@app.on_event("startup")
async def startup_event():
    start_monitoring_background()

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page."""
    return templates.TemplateResponse("dashboard.html", {"request": request})

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
    result = resume_pod(pod_id)
    
    if result:
        if result.get('success'):
            # REST API response
            status = "success" if result['success'] else "error"
            message = result['message']
        elif result.get('podResume'):
            # GraphQL response
            status = "success"
            message = f"Pod resumed successfully. New status: {result['podResume'].get('desiredStatus', 'Unknown')}"
        else:
            status = "error"
            message = "Failed to resume pod"
    else:
        status = "error"
        message = "Failed to resume pod"
    
    return HTMLResponse(f'''
        <div class="alert alert-{status}" role="alert">
            {message}
        </div>
        <div hx-get="/pods" hx-target="#pods-container" hx-trigger="load delay:2s" hx-swap="innerHTML"></div>
    ''')

@app.get("/config")
async def get_config(request: Request):
    """Get current configuration."""
    try:
        from .main import config as current_config
    except ImportError:
        from main import config as current_config
    return templates.TemplateResponse("config.html", {"request": request, "config": current_config})

@app.post("/config/auto-stop")
async def update_auto_stop(
    request: Request,
    enabled: bool = Form(False),
    max_cpu: int = Form(5),
    max_gpu: int = Form(5),
    max_memory: int = Form(10),
    duration: int = Form(1800)
):
    """Update basic auto-stop configuration and persist to file."""
    try:
        from .main import config as current_config
    except ImportError:
        from main import config as current_config
        
    # Update in-memory configuration (basic auto-stop only)
    current_config['auto_stop']['enabled'] = enabled
    current_config['auto_stop']['thresholds']['max_cpu_percent'] = max_cpu
    current_config['auto_stop']['thresholds']['max_gpu_percent'] = max_gpu
    current_config['auto_stop']['thresholds']['max_memory_percent'] = max_memory
    current_config['auto_stop']['thresholds']['duration'] = duration
    
    # Save to file for persistence
    if save_config_to_file(current_config, config_path):
        status_msg = "✅ Basic auto-stop configuration updated and saved successfully!"
    else:
        status_msg = "⚠️  Configuration updated in memory but failed to save to file"
    
    # Render the current settings partial with updated config
    current_settings_html = templates.get_template("current_settings.html").render({"config": current_config})
    
    # Return both the success message and updated current settings using hx-swap-oob
    return HTMLResponse(f'''
        <div class="alert alert-success" role="alert">
            {status_msg}<br>
            <small>Auto-stop {'enabled' if enabled else 'disabled'}, persistent duration: {duration}s ({duration//60} minutes)</small>
        </div>
        <div id="current-settings" hx-swap-oob="innerHTML">
            {current_settings_html}
        </div>
    ''')

@app.post("/config/no-change")
async def update_no_change_detection(
    request: Request,
    detect_no_change: bool = Form(False)
):
    """Update no-change detection configuration separately."""
    try:
        from .main import config as current_config
    except ImportError:
        from main import config as current_config
        
    # Update only the no-change detection setting
    current_config['auto_stop']['thresholds']['detect_no_change'] = detect_no_change
    
    # Save to file for persistence
    if save_config_to_file(current_config, config_path):
        status_msg = f"✅ No-Change Detection {'enabled' if detect_no_change else 'disabled'} successfully!"
    else:
        status_msg = "⚠️ Configuration updated in memory but failed to save to file"
    
    # Render the current settings partial with updated config
    current_settings_html = templates.get_template("current_settings.html").render({"config": current_config})
    
    # Return both the success message and updated current settings using hx-swap-oob
    return HTMLResponse(f'''
        <div class="alert alert-success" role="alert">
            {status_msg}<br>
            <small>No-change detection will {'stop pods with completely unchanged metrics' if detect_no_change else 'be ignored'}</small>
        </div>
        <div id="current-settings" hx-swap-oob="innerHTML">
            {current_settings_html}
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
        
        # Clean up data for inactive pods
        inactive_pod_ids = set(summary['pod_id'] for summary in all_summaries) - active_pod_ids
        for inactive_pod_id in inactive_pod_ids:
            print(f"Cleaning up data for inactive pod: {inactive_pod_id}")
            data_tracker.clear_pod_data(inactive_pod_id)
        
        summaries = active_summaries
        pods_with_metrics = len(active_summaries)
    else:
        # If we can't fetch pods, show warning but don't clear data
        summaries = []
        pods_with_metrics = 0
        print("Warning: Could not fetch current pods from RunPod API")
    
    return templates.TemplateResponse("metrics.html", {
        "request": request, 
        "summaries": summaries,
        "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_active_pods": active_pod_count,
        "pods_with_metrics": pods_with_metrics
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
    
    return {
        "status": "running",
        "timestamp": datetime.now().isoformat(),
        "auto_stop_enabled": current_config.get('auto_stop', {}).get('enabled', False) if current_config else False,
        "tracked_pods": len(data_tracker.get_all_summaries()) if data_tracker else 0,
        "monitoring": {
            "sampling_frequency": sampling_freq,
            "next_poll_seconds": sampling_freq,  # This would be calculated from actual monitoring process
            "is_monitoring_active": False  # This should be determined by checking if monitoring process is running
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
    
    # Check if monitoring thread is actually running
    global monitoring_thread
    thread_running = monitoring_thread is not None and monitoring_thread.is_alive()
    monitoring_active = monitoring_enabled and data_tracker is not None and thread_running
    
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
        return {"status": "success", "enabled": new_state}
    else:
        return {"status": "error", "message": "Failed to save configuration"}

@app.post("/api/monitoring/start")
async def start_monitoring_endpoint():
    """Start monitoring via API endpoint."""
    start_monitoring_background()
    return {"status": "success", "message": "Monitoring started"}

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
    
    # Get pod info to show name
    pods = fetch_pods()
    pod_name = "Unknown"
    for pod in pods or []:
        if pod['id'] == pod_id:
            pod_name = pod['name']
            break
    
    # Remove from exclude list if present
    if (current_config and 
        current_config.get('auto_stop', {}).get('exclude_pods') and 
        pod_id in current_config['auto_stop']['exclude_pods']):
        
        current_config['auto_stop']['exclude_pods'].remove(pod_id)
        
        # Save to file
        if save_config_to_file(current_config, config_path):
            status = "success"
            message = f"✅ '{pod_name}' included in auto-stop monitoring"
        else:
            status = "warning" 
            message = f"⚠️ '{pod_name}' included but failed to save to file"
    else:
        status = "info"
        message = f"ℹ️ '{pod_name}' already included"
    
    # Return updated message and trigger pod list refresh
    return HTMLResponse(f'''
        <div class="alert alert-{status} alert-dismissible">
            <small>{message}</small>
        </div>
        <div hx-get="/pods" hx-target="#pod-table" hx-trigger="load delay:1s" hx-select="#pod-table" hx-swap="outerHTML"></div>
    ''')

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
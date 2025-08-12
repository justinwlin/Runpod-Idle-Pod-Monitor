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
    print("🔄 Server startup: checking monitoring configuration...")
    print(f"   Auto-stop enabled: {config.get('auto_stop', {}).get('enabled', False) if config else False}")
    if config:
        print(f"   Config loaded: {bool(config)}")
        print(f"   Auto-stop section: {config.get('auto_stop', {})}")
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
    
    # Get current pods to identify orphaned excluded pods
    current_pods = fetch_pods()
    current_pod_ids = {pod['id'] for pod in current_pods} if current_pods else set()
    
    excluded_pods = current_config.get('auto_stop', {}).get('exclude_pods', []) if current_config else []
    orphaned_excluded = [pod_id for pod_id in excluded_pods if pod_id not in current_pod_ids]
    
    return templates.TemplateResponse("config.html", {
        "request": request, 
        "config": current_config,
        "orphaned_excluded_pods": orphaned_excluded
    })

@app.post("/config/auto-stop")
async def update_auto_stop(
    request: Request,
    enabled: bool = Form(False),
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
    
    # Start or stop monitoring based on enabled state
    if enabled:
        start_monitoring_background()
        monitoring_status = "🔄 Data collection started automatically"
    else:
        stop_monitoring_background()
        monitoring_status = "⏸️ Data collection stopped"
    
    # Render the current settings partial with updated config
    current_settings_html = templates.get_template("current_settings.html").render({"config": current_config})
    
    # Return both the success message and updated current settings using hx-swap-oob
    return HTMLResponse(f'''
        <div class="alert alert-success" role="alert">
            {status_msg}<br>
            <small>Auto-stop {'enabled' if enabled else 'disabled'}, persistent duration: {duration}s ({duration//60} minutes)</small><br>
            <small>No-change detection {'enabled' if detect_no_change else 'disabled'}</small><br>
            <small>{monitoring_status}</small>
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
async def get_raw_data(request: Request, pod_filter: str = None):
    """Get raw data points as HTML table with optional pod filtering."""
    # Read directly from file instead of using data_tracker
    all_raw_data = []
    pod_names = set()
    
    try:
        import json
        with open('./data/pod_metrics.json', 'r') as f:
            data = json.load(f)
            
        for pod_id, metrics_list in data.items():
            for metric in metrics_list[-20:]:  # Last 20 data points per pod for better filtering
                all_raw_data.append(metric)
                if metric.get('name'):
                    pod_names.add(metric.get('name'))
                    
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return HTMLResponse("<p>No metrics data file found</p>")
    
    # Sort by timestamp, newest first
    all_raw_data.sort(key=lambda x: x.get('epoch', 0), reverse=True)
    
    if not all_raw_data:
        return HTMLResponse("<p>No raw data points available yet</p>")
    
    # Filter by pod if requested (pod_filter can be pod_id or pod_name)
    if pod_filter:
        all_raw_data = [metric for metric in all_raw_data 
                       if metric.get('pod_id') == pod_filter or metric.get('name') == pod_filter]
    
    # Get available pods for filter buttons (use current pods to get latest names)
    current_pods = fetch_pods()
    available_pods = []
    if current_pods:
        for pod in current_pods:
            pod_id = pod['id']
            pod_name = pod['name']
            # Only include pods that have data in the file
            try:
                if pod_id in data and data[pod_id]:
                    available_pods.append({'id': pod_id, 'name': pod_name})
            except:
                pass  # Skip if data not available
    
    # Sort by name for better UX
    available_pods.sort(key=lambda x: x['name'])
    
    # Build HTML with filter buttons and table
    html = f'''
    <div class="mb-3">
        <div class="btn-group flex-wrap" role="group">
            <button type="button" class="btn btn-sm {'btn-primary' if not pod_filter else 'btn-outline-primary'}" 
                    hx-get="/api/raw-data" hx-target="#raw-data-table" hx-swap="innerHTML">
                All Pods ({len(all_raw_data) if not pod_filter else len([m for pod_metrics in data.values() for m in pod_metrics[-20:]])})
            </button>
    '''
    
    for pod in available_pods:
        pod_id = pod['id']
        pod_name = pod['name']
        # Count data points for this specific pod ID
        pod_count = len([m for m in all_raw_data if m.get('pod_id') == pod_id]) if not pod_filter else len(data.get(pod_id, [])[-20:])
        is_active = pod_filter == pod_id or pod_filter == pod_name
        html += f'''
            <button type="button" class="btn btn-sm {'btn-primary' if is_active else 'btn-outline-primary'}" 
                    hx-get="/api/raw-data?pod_filter={pod_id}" hx-target="#raw-data-table" hx-swap="innerHTML"
                    title="Pod ID: {pod_id}">
                {pod_name} ({pod_count})
            </button>
        '''
    
    html += '''
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
    
    display_data = all_raw_data[:100] if not pod_filter else all_raw_data[:50]  # Show more when filtering
    
    for metric in display_data:
        timestamp = datetime.fromisoformat(metric.get('timestamp', '')).strftime('%H:%M:%S') if metric.get('timestamp') else 'Unknown'
        uptime_hours = metric.get('uptime_seconds', 0) // 3600
        uptime_mins = (metric.get('uptime_seconds', 0) % 3600) // 60
        
        html += f'''
                <tr>
                    <td><small>{timestamp}</small></td>
                    <td><small>{metric.get('name', 'Unknown')}</small></td>
                    <td><small class="text-muted">{metric.get('pod_id', 'Unknown')[:8]}...</small></td>
                    <td><span class="badge bg-{'success' if metric.get('status') == 'RUNNING' else 'warning'}">{metric.get('status', 'Unknown')}</span></td>
                    <td>{metric.get('cpu_percent', 0)}%</td>
                    <td>{metric.get('gpu_percent', 0)}%</td>
                    <td>{metric.get('memory_percent', 0)}%</td>
                    <td><small>{uptime_hours}h {uptime_mins}m</small></td>
                    <td><small>${metric.get('cost_per_hr', 0)}</small></td>
                </tr>
        '''
    
    if not display_data:
        html += '''
                <tr>
                    <td colspan="9" class="text-center text-muted">
                        <em>No data points found for the selected pod</em>
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
    
    if not current_config or not current_config.get('auto_stop', {}).get('enabled', False):
        return HTMLResponse("<p class='text-muted'>Auto-stop is disabled</p>")
    
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
                'progress_percent': (meeting_criteria / points_needed) * 100
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
                    <th>Progress</th>
                    <th>Data Points</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
    '''
    
    for pred in predictions:
        if pred['remaining_points'] == 0:
            status_class = "danger"
            status_text = "Ready to Stop"
        elif pred['remaining_points'] <= 3:
            status_class = "warning"
            status_text = f"{pred['remaining_points']} more"
        else:
            status_class = "info"
            status_text = f"{pred['remaining_points']} more"
        
        html += f'''
            <tr>
                <td><small>{pred['pod_name']}</small></td>
                <td>
                    <div class="progress" style="height: 15px;">
                        <div class="progress-bar bg-{status_class}" style="width: {pred['progress_percent']}%">
                            {pred['progress_percent']:.0f}%
                        </div>
                    </div>
                </td>
                <td><small>{pred['meeting_criteria']}/{pred['total_needed']}</small></td>
                <td><span class="badge bg-{status_class}">{status_text}</span></td>
            </tr>
        '''
    
    html += '''
            </tbody>
        </table>
    </div>
    '''
    
    return HTMLResponse(html)

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
        <div hx-get="/config" hx-target="body" hx-trigger="load delay:2s" hx-select="body" hx-swap="innerHTML"></div>
    ''')

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
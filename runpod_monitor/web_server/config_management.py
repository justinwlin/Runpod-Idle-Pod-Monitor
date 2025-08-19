"""
Configuration management endpoints for the RunPod Monitor web server.
Handles all configuration-related operations including auto-stop settings,
sampling configuration, and data retention policies.
"""

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import Optional, Dict, Any
import threading

from .helpers import (
    save_config_to_file,
    get_current_config,
    generate_status_overview_html
)

# Create router for configuration endpoints
router = APIRouter(prefix="/config", tags=["configuration"])

# Setup templates
templates = Jinja2Templates(directory="templates")

# Global variables for monitoring thread management
monitoring_thread = None
monitoring_active = False


def start_monitoring_background():
    """
    Start monitoring in a background thread if enabled.
    Checks configuration and starts the monitoring thread if not already running.
    """
    global monitoring_thread, monitoring_active
    
    try:
        from ..main import monitor_pods, config
    except ImportError:
        from runpod_monitor.main import monitor_pods, config
    
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
    """
    Stop background monitoring by setting the active flag to False.
    The monitoring thread will check this flag and stop gracefully.
    """
    global monitoring_active
    monitoring_active = False
    print("⏹️  Background monitoring stopped")


def update_auto_stop_config(enabled: bool, monitor_only: bool, max_cpu: int, max_gpu: int, 
                           max_memory: int, duration: int, detect_no_change: bool) -> Dict[str, Any]:
    """
    Update auto-stop configuration values in memory.
    
    Args:
        enabled: Whether auto-stop is enabled
        monitor_only: Whether to only monitor without stopping
        max_cpu: Maximum CPU percentage threshold
        max_gpu: Maximum GPU percentage threshold
        max_memory: Maximum memory percentage threshold
        duration: Duration in seconds for persistent idle detection
        detect_no_change: Whether to detect pods with no metric changes
        
    Returns:
        Updated configuration dictionary
    """
    current_config = get_current_config()
    
    # Ensure auto_stop section exists
    if 'auto_stop' not in current_config:
        current_config['auto_stop'] = {}
    if 'thresholds' not in current_config['auto_stop']:
        current_config['auto_stop']['thresholds'] = {}
    
    # Update all auto-stop settings
    current_config['auto_stop']['enabled'] = enabled
    current_config['auto_stop']['monitor_only'] = monitor_only
    current_config['auto_stop']['thresholds']['max_cpu_percent'] = max_cpu
    current_config['auto_stop']['thresholds']['max_gpu_percent'] = max_gpu
    current_config['auto_stop']['thresholds']['max_memory_percent'] = max_memory
    current_config['auto_stop']['thresholds']['duration'] = duration
    current_config['auto_stop']['thresholds']['detect_no_change'] = detect_no_change
    
    return current_config


@router.get("")
async def get_config(request: Request):
    """
    Get current configuration page with all settings.
    Reloads configuration from file to ensure latest values are displayed.
    
    Args:
        request: FastAPI request object
        
    Returns:
        HTML response with rendered configuration page
    """
    # Reload config from file to ensure we have latest values
    try:
        from ..main import load_config, fetch_pods
    except ImportError:
        from runpod_monitor.main import load_config, fetch_pods
    
    config_path = 'config.yaml'
    print(f"🔄 Config page: Reloading config from {config_path}")
    load_config(config_path)
    
    current_config = get_current_config()
    
    # Debug config values
    if current_config:
        auto_stop = current_config.get('auto_stop', {})
        enabled = auto_stop.get('enabled')
        monitor_only = auto_stop.get('monitor_only')
        print(f"📋 Config values: enabled={enabled}, monitor_only={monitor_only}")
    else:
        print("❌ No config loaded!")
    
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


@router.post("/auto-stop")
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
    """
    Update auto-stop configuration settings and persist to file.
    Also manages the monitoring thread based on settings.
    
    Args:
        request: FastAPI request object
        enabled: Whether auto-stop is enabled
        monitor_only: Whether to only monitor without stopping
        max_cpu: Maximum CPU percentage threshold
        max_gpu: Maximum GPU percentage threshold
        max_memory: Maximum memory percentage threshold
        duration: Duration in seconds for persistent idle detection
        detect_no_change: Whether to detect pods with no metric changes
        
    Returns:
        HTML response with success message and updated status overview
    """
    # Update configuration
    current_config = update_auto_stop_config(
        enabled, monitor_only, max_cpu, max_gpu, max_memory, duration, detect_no_change
    )
    
    # Save to file for persistence
    config_path = 'config.yaml'
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
    status_overview_html = generate_status_overview_html(enabled, monitor_only, detect_no_change)
    
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
        <div id="settings-card-body" hx-swap-oob="innerHTML">
            <div class="row text-center mb-3">
                <div class="col-4">
                    <div class="fw-bold">{max_cpu}%</div>
                    <small class="text-muted">CPU</small>
                </div>
                <div class="col-4">
                    <div class="fw-bold">{max_gpu}%</div>
                    <small class="text-muted">GPU</small>
                </div>
                <div class="col-4">
                    <div class="fw-bold">{max_memory}%</div>
                    <small class="text-muted">Memory</small>
                </div>
            </div>
            
            <div class="text-center">
                <div class="fw-bold">{duration // 60} minutes</div>
                <small class="text-muted">Duration</small>
            </div>
        </div>
    ''')


@router.post("/sampling")
async def update_sampling_config(
    request: Request,
    sampling_frequency: int = Form(60),
    rolling_window: int = Form(3600)
):
    """
    Update data sampling configuration separately from auto-stop settings.
    
    Args:
        request: FastAPI request object
        sampling_frequency: How often to sample data in seconds
        rolling_window: Time window for rolling metrics in seconds
        
    Returns:
        HTML response with success message and updated current settings
    """
    current_config = get_current_config()
    
    # Update sampling configuration
    if 'auto_stop' not in current_config:
        current_config['auto_stop'] = {}
    if 'sampling' not in current_config['auto_stop']:
        current_config['auto_stop']['sampling'] = {}
    
    current_config['auto_stop']['sampling']['frequency'] = sampling_frequency
    current_config['auto_stop']['sampling']['rolling_window'] = rolling_window
    
    # Save to file for persistence
    config_path = 'config.yaml'
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


@router.post("/retention")
async def update_retention_config(
    request: Request,
    retention_value: Optional[int] = Form(None),
    retention_unit: str = Form(...)
):
    """
    Update data retention policy configuration.
    Controls how long historical metrics data is kept.
    
    Args:
        request: FastAPI request object
        retention_value: Numeric value for retention period
        retention_unit: Unit of time (hours, days, weeks, months)
        
    Returns:
        HTML response with success message and updated display
    """
    print(f"DEBUG: Received retention_value={retention_value} (type: {type(retention_value)}), retention_unit={retention_unit}")
    
    current_config = get_current_config()
    
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
    config_path = 'config.yaml'
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


@router.post("/cleanup-excluded")
async def cleanup_excluded_pods(request: Request):
    """
    Remove all excluded pods that no longer exist from the exclude list.
    Helps maintain a clean configuration by removing orphaned entries.
    
    Args:
        request: FastAPI request object
        
    Returns:
        HTML response with cleanup status message
    """
    try:
        from ..main import fetch_pods, data_tracker
    except ImportError:
        from runpod_monitor.main import fetch_pods, data_tracker
    
    current_config = get_current_config()
    
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
        
        # Also clean up their data if data tracker is available
        for pod_id in orphaned_excluded:
            if data_tracker:
                data_tracker.clear_pod_data(pod_id)
        
        # Save to file
        config_path = 'config.yaml'
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
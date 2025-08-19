"""
Monitoring and status endpoints for the RunPod Monitor web server.
Handles real-time monitoring status, auto-stop status, and system health checks.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse
from datetime import datetime
import time

from .helpers import (
    get_current_config,
    save_config_to_file,
    check_monitoring_active,
    get_monitoring_metrics,
    get_latest_metric_time
)
from .config_management import (
    monitoring_thread,
    start_monitoring_background,
    stop_monitoring_background
)

# Create router for monitoring endpoints
router = APIRouter(prefix="/api", tags=["monitoring"])


@router.get("/status")
async def get_status():
    """
    Get system status for API calls.
    Provides comprehensive status information about the monitoring system.
    
    Returns:
        JSON response with system status including:
        - Overall status
        - Current timestamp
        - Auto-stop enabled state
        - Number of tracked pods
        - Monitoring details (frequency, next poll time, etc.)
    """
    try:
        from ..main import next_poll_time, last_poll_time, data_tracker
    except ImportError:
        from runpod_monitor.main import next_poll_time, last_poll_time, data_tracker
    
    current_config = get_current_config()
    
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


@router.get("/monitoring-status")
async def get_monitoring_status():
    """
    Get real-time monitoring status HTML for live updates.
    Used by the dashboard to show current monitoring state.
    
    Returns:
        HTML response with monitoring status badge and metrics
    """
    try:
        from ..main import fetch_pods, data_tracker
    except ImportError:
        from runpod_monitor.main import fetch_pods, data_tracker
    
    current_config = get_current_config()
    
    # Get metrics summary
    active_pod_count, pods_with_metrics = get_monitoring_metrics()
    
    sampling_freq = current_config.get('auto_stop', {}).get('sampling', {}).get('frequency', 30) if current_config else 60
    monitoring_enabled = current_config.get('auto_stop', {}).get('enabled', False) if current_config else False
    
    # Check if monitoring is actually running
    monitoring_active = check_monitoring_active()
    
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


@router.get("/auto-stop-status")
async def get_auto_stop_status():
    """
    Get auto-stop status for dashboard quick view.
    Shows current auto-stop state and number of excluded pods.
    
    Returns:
        HTML response with auto-stop status badge and quick toggle button
    """
    current_config = get_current_config()
    
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


@router.post("/auto-stop-toggle")
async def toggle_auto_stop():
    """
    Quick toggle for auto-stop functionality on/off.
    Provides a fast way to enable/disable auto-stop without going to config page.
    
    Returns:
        HTML response with toast notification showing new state
    """
    current_config = get_current_config()
    
    # Toggle the enabled state
    current_enabled = current_config.get('auto_stop', {}).get('enabled', False) if current_config else False
    
    if 'auto_stop' not in current_config:
        current_config['auto_stop'] = {}
    
    current_config['auto_stop']['enabled'] = not current_enabled
    new_state = current_config['auto_stop']['enabled']
    
    # Save to file
    config_path = 'config.yaml'
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


@router.get("/next-poll")
async def get_next_poll():
    """
    Simple endpoint to get when the next data collection will occur.
    Used for displaying countdown timers in the UI.
    
    Returns:
        JSON response with:
        - seconds_remaining: Seconds until next collection
        - next_collection_time: Formatted time string
        - monitoring_running: Whether monitoring is active
    """
    current_time = time.time()
    
    # Check monitoring status and get latest data time
    monitoring_running, latest_data_time = get_latest_metric_time()
    
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


@router.post("/monitoring/start")
async def start_monitoring_endpoint():
    """
    Start monitoring via API endpoint.
    Manually starts the monitoring thread if not already running.
    
    Returns:
        HTML response with status message about monitoring start
    """
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


@router.post("/monitoring/stop") 
async def stop_monitoring_endpoint():
    """
    Stop monitoring via API endpoint.
    Stops the background monitoring thread.
    
    Returns:
        JSON response with success status
    """
    stop_monitoring_background()
    return {"status": "success", "message": "Monitoring stopped"}


@router.get("/debug/startup")
async def debug_startup():
    """
    Debug endpoint to check startup state.
    Useful for troubleshooting monitoring initialization issues.
    
    Returns:
        JSON response with detailed startup state information
    """
    try:
        from ..main import config, data_tracker
    except ImportError:
        from runpod_monitor.main import config, data_tracker
    
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
"""
Helper functions for the RunPod Monitor web server.
Contains utility functions for common operations like config management, 
data loading, and HTML generation.
"""

import json
import yaml
import time
from typing import Optional, Dict, Any, Tuple, List
from datetime import datetime
from fastapi.responses import HTMLResponse


def save_config_to_file(config_data: Dict[str, Any], file_path: str) -> bool:
    """
    Save configuration data to a YAML file.
    
    Args:
        config_data: Dictionary containing configuration data
        file_path: Path to the YAML file to save to
        
    Returns:
        bool: True if save was successful, False otherwise
    """
    try:
        with open(file_path, 'w') as f:
            yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False


def get_current_config() -> Dict[str, Any]:
    """
    Get the current configuration from the main module.
    Handles both relative and absolute imports.
    
    Returns:
        Dict containing current configuration
    """
    try:
        from ..main import config as current_config
    except ImportError:
        from runpod_monitor.main import config as current_config
    return current_config


def update_config_value(config_path: List[str], value: Any, current_config: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Update a nested configuration value using a path.
    
    Args:
        config_path: List of keys representing the path to the config value
        value: The new value to set
        current_config: Optional existing config dict, will fetch if not provided
        
    Returns:
        Updated configuration dictionary
    """
    if not current_config:
        current_config = get_current_config()
    
    # Navigate to the nested location
    target = current_config
    for key in config_path[:-1]:
        if key not in target:
            target[key] = {}
        target = target[key]
    
    # Set the value
    target[config_path[-1]] = value
    return current_config


def load_metrics_data() -> Dict[str, Any]:
    """
    Load metrics data from the JSON file.
    
    Returns:
        Dict containing metrics data, empty dict if file not found or invalid
    """
    try:
        with open('./data/pod_metrics.json', 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_monitoring_metrics() -> Tuple[int, int]:
    """
    Get current monitoring metrics including active pod count and pods with data.
    
    Returns:
        Tuple of (active_pod_count, pods_with_metrics)
    """
    try:
        from ..main import fetch_pods, data_tracker
    except ImportError:
        from runpod_monitor.main import fetch_pods, data_tracker
    
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
    
    return active_pod_count, pods_with_metrics


def check_monitoring_active(timeout_seconds: int = 120) -> bool:
    """
    Check if monitoring is actively collecting data by looking at recent metrics.
    
    Args:
        timeout_seconds: Number of seconds to consider data as "recent"
        
    Returns:
        bool: True if monitoring is active, False otherwise
    """
    try:
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
                    
        # If we have data within the timeout period, monitoring is running
        current_time = time.time()
        return latest_data_time > current_time - timeout_seconds
            
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return False


def get_latest_metric_time() -> Tuple[bool, float]:
    """
    Get the latest metric timestamp and check if monitoring is running.
    
    Returns:
        Tuple of (monitoring_running, latest_data_timestamp)
    """
    latest_data_time = 0
    
    try:
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
        current_time = time.time()
        monitoring_running = latest_data_time > current_time - 120
            
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        monitoring_running = False
    
    return monitoring_running, latest_data_time


def create_alert_response(status: str, message: str, refresh_target: Optional[str] = None, 
                         refresh_delay: int = 2) -> HTMLResponse:
    """
    Create a standardized alert response with optional refresh.
    
    Args:
        status: Alert status type (success, error, warning, info)
        message: Message to display in the alert
        refresh_target: Optional URL to refresh after delay
        refresh_delay: Delay in seconds before refresh
        
    Returns:
        HTMLResponse with formatted alert
    """
    refresh_html = ""
    if refresh_target:
        refresh_html = f'<div hx-get="{refresh_target}" hx-target="#pods-container" hx-trigger="load delay:{refresh_delay}s" hx-swap="innerHTML"></div>'
    
    return HTMLResponse(f'''
        <div class="alert alert-{status}" role="alert">
            {message}
        </div>
        {refresh_html}
    ''')


def generate_status_overview_html(enabled: bool, monitor_only: bool, detect_no_change: bool) -> str:
    """
    Generate HTML for the status overview section showing current settings.
    
    Args:
        enabled: Whether auto-stop is enabled
        monitor_only: Whether in monitor-only mode
        detect_no_change: Whether no-change detection is enabled
        
    Returns:
        HTML string for status overview
    """
    return f'''
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


def generate_raw_data_filters_html(page: int, status_filter: str, total_count: int, 
                                  active_count: int, exited_count: int, terminated_count: int,
                                  start_idx: int, end_idx: int, total_items: int) -> str:
    """
    Generate HTML for raw data filter buttons and pagination info.
    
    Args:
        page: Current page number
        status_filter: Current active filter (active, exited, terminated, or None)
        total_count: Total number of data points
        active_count: Number of active pods
        exited_count: Number of exited pods
        terminated_count: Number of terminated pods
        start_idx: Starting index for current page
        end_idx: Ending index for current page
        total_items: Total number of items
        
    Returns:
        HTML string for filter buttons and pagination
    """
    return f'''
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
    '''
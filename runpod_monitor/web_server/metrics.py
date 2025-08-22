"""
Metrics and data visualization endpoints for the RunPod Monitor web server.
Handles metrics display, data export, graphing, predictions, and raw data views.
"""

from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple, Set
import time
import json

from .helpers import (
    get_current_config,
    load_metrics_data,
    generate_raw_data_filters_html
)

# Create router for metrics endpoints
router = APIRouter(tags=["metrics"])

# Setup templates
templates = Jinja2Templates(directory="templates")


def get_pod_statuses() -> Tuple[Set[str], Dict[str, Dict[str, Any]]]:
    """
    Get current pod IDs and their status information from the API.
    
    Returns:
        Tuple containing:
        - Set of current pod IDs
        - Dictionary mapping pod IDs to their status info (name, status, cost)
    """
    try:
        from ..main import fetch_pods
    except ImportError:
        from runpod_monitor.main import fetch_pods
    
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
    
    return current_pod_ids, current_pod_statuses




@router.get("/metrics")
async def get_metrics(request: Request):
    """
    Get metrics overview page for active pods only.
    Shows summary statistics and current state of all monitored pods.
    
    Args:
        request: FastAPI request object
        
    Returns:
        HTML response with rendered metrics page
    """
    try:
        from ..main import fetch_pods, data_tracker
    except ImportError:
        from runpod_monitor.main import fetch_pods, data_tracker
    
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
        
        summaries = active_summaries
        pods_with_metrics = len(active_summaries)
    else:
        # If we can't fetch pods, show warning but don't clear data
        summaries = []
        pods_with_metrics = 0
        print("Warning: Could not fetch current pods from RunPod API")
    
    # Get config for template
    current_config = get_current_config()
    
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


@router.get("/api/raw-data")
async def get_raw_data(
    request: Request, 
    page: int = Query(1, ge=1),
    pod_id: Optional[str] = Query(None),
    resolution: str = Query("1hour", regex="^(raw|30min|1hour)$")
):
    """
    Get metrics table with pod selection and resolution options.
    
    Args:
        request: FastAPI request object
        page: Page number for pagination
        pod_id: Specific pod ID or None for all pods
        resolution: Data resolution - raw, 30min, or 1hour
        
    Returns:
        HTML response with formatted table
    """
    try:
        from runpod_monitor.pod_metrics_manager import PodMetricsManager
        from runpod_monitor.main import fetch_pods
    except ImportError:
        return HTMLResponse("<p>Error loading modules</p>")
    
    manager = PodMetricsManager(base_dir='./data/pods')
    
    # Map resolution to file type
    file_type_map = {
        "raw": "raw",
        "30min": "30min",
        "1hour": "1hour"
    }
    file_type = file_type_map.get(resolution, "1hour")
    
    # Get current pods from API
    current_pods = fetch_pods()
    if not current_pods:
        return HTMLResponse("<p>No pods available</p>")
    
    # Create pod name lookup
    pod_names = {p['id']: p['name'] for p in current_pods}
    pod_statuses = {p['id']: p.get('desiredStatus', 'UNKNOWN') for p in current_pods}
    
    # Collect metrics
    all_metrics = []
    
    if pod_id and pod_id != "all":
        # Single pod selected
        metrics = manager.read_metrics(pod_id, file_type=file_type)
        if metrics:
            pod_name = pod_names.get(pod_id, pod_id[:8])
            pod_status = pod_statuses.get(pod_id, 'TERMINATED')
            
            for metric in metrics:
                metric['pod_name'] = pod_name
                metric['pod_id'] = pod_id
                metric['current_status'] = pod_status
            all_metrics = metrics
    else:
        # Show all pods - merge data from multiple pods
        for pod in current_pods:
            p_id = pod['id']
            p_name = pod['name']
            p_status = pod.get('desiredStatus', 'UNKNOWN')
            
            # Only include RUNNING and recently EXITED pods
            if p_status in ['RUNNING', 'EXITED', 'STOPPED']:
                # Read limited metrics per pod to prevent huge tables
                metrics = manager.read_metrics(p_id, file_type=file_type, limit=50)
                if metrics:
                    for metric in metrics:
                        metric['pod_name'] = p_name
                        metric['pod_id'] = p_id
                        metric['current_status'] = p_status
                    all_metrics.extend(metrics)
    
    # Sort by timestamp/epoch
    if file_type in ["30min", "1hour"]:
        all_metrics.sort(key=lambda x: x.get('window_start_epoch', 0), reverse=True)
    else:
        all_metrics.sort(key=lambda x: x.get('epoch', 0), reverse=True)
    
    if not all_metrics:
        return HTMLResponse("<p>No data available for selected options</p>")
    
    # Pagination
    ITEMS_PER_PAGE = 50
    total_items = len(all_metrics)
    total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    
    page = max(1, min(page, total_pages if total_pages > 0 else 1))
    start_idx = (page - 1) * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    paginated_data = all_metrics[start_idx:end_idx]
    
    # Build HTML
    html = f'''
    <div class="mb-3">
        <div class="row">
            <div class="col-md-4">
                <label class="form-label small">Pod Selection</label>
                <select id="table-pod-selector" class="form-select form-select-sm" 
                        hx-get="/api/raw-data" 
                        hx-target="#raw-data-table" 
                        hx-trigger="change"
                        hx-include="#table-resolution-selector"
                        name="pod_id">
                    <option value="all" {"selected" if not pod_id or pod_id == "all" else ""}>All Pods</option>
    '''
    
    for pod in current_pods:
        selected = "selected" if pod_id == pod['id'] else ""
        html += f'<option value="{pod["id"]}" {selected}>{pod["name"]}</option>'
    
    html += f'''
                </select>
            </div>
            <div class="col-md-4">
                <label class="form-label small">Resolution</label>
                <select id="table-resolution-selector" class="form-select form-select-sm"
                        hx-get="/api/raw-data"
                        hx-target="#raw-data-table"
                        hx-trigger="change"
                        hx-include="#table-pod-selector"
                        name="resolution">
                    <option value="1hour" {"selected" if resolution == "1hour" else ""}>Hourly</option>
                    <option value="30min" {"selected" if resolution == "30min" else ""}>30 Minutes</option>
                    <option value="raw" {"selected" if resolution == "raw" else ""}>Raw (1 min)</option>
                </select>
            </div>
            <div class="col-md-4">
                <small class="text-muted">
                    Showing {start_idx + 1}-{min(end_idx, total_items)} of {total_items} records
                </small>
            </div>
        </div>
    </div>
    
    <div class="d-flex justify-content-between align-items-center mb-3">
        <div>
            <small class="text-muted">Page {page} of {total_pages}</small>
        </div>
        <div class="btn-group" role="group">
    '''
    
    # Previous page button
    if page > 1:
        pod_param = f"&pod_id={pod_id}" if pod_id else ""
        prev_url = f"/api/raw-data?page={page-1}&resolution={resolution}{pod_param}"
        html += f'''
            <button type="button" class="btn btn-sm btn-outline-secondary" 
                    hx-get="{prev_url}" hx-target="#raw-data-table">
                « Previous
            </button>
        '''
    
    # Next page button
    if page < total_pages:
        pod_param = f"&pod_id={pod_id}" if pod_id else ""
        next_url = f"/api/raw-data?page={page+1}&resolution={resolution}{pod_param}"
        html += f'''
            <button type="button" class="btn btn-sm btn-outline-secondary" 
                    hx-get="{next_url}" hx-target="#raw-data-table">
                Next »
            </button>
        '''
    
    html += '''
        </div>
    </div>
    
    <div class="table-responsive">
        <table class="table table-sm table-striped">
            <thead class="table-dark">
                <tr>
    '''
    
    # Table headers based on resolution
    if file_type in ["30min", "1hour"]:
        html += '''
                    <th>Time Window</th>
                    <th>Pod Name</th>
                    <th>Status</th>
                    <th>CPU Avg%</th>
                    <th>GPU Avg%</th>
                    <th>Memory Avg%</th>
                    <th>Data Points</th>
        '''
    else:
        html += '''
                    <th>Timestamp</th>
                    <th>Pod Name</th>
                    <th>Status</th>
                    <th>CPU%</th>
                    <th>GPU%</th>
                    <th>Memory%</th>
                    <th>Uptime</th>
        '''
    
    html += '''
                </tr>
            </thead>
            <tbody>
    '''
    
    # Table rows
    for metric in paginated_data:
        pod_name = metric.get('pod_name', 'Unknown')
        current_status = metric.get('current_status', metric.get('status', 'UNKNOWN'))
        
        # Status badge color
        if current_status == 'RUNNING':
            badge_color = 'success'
        elif current_status in ['STOPPED', 'EXITED']:
            badge_color = 'warning'
        else:
            badge_color = 'secondary'
        
        if file_type in ["30min", "1hour"]:
            # Compacted data display
            window_start = metric.get('window_start', '')
            window_end = metric.get('window_end', '')
            
            # Format time window
            try:
                start_time = datetime.fromisoformat(window_start).strftime('%H:%M')
                end_time = datetime.fromisoformat(window_end).strftime('%H:%M')
                time_display = f"{start_time} - {end_time}"
            except:
                time_display = f"{window_start[:5]} - {window_end[:5]}"
            
            html += f'''
                <tr>
                    <td><small>{time_display}</small></td>
                    <td><small>{pod_name}</small></td>
                    <td><span class="badge bg-{badge_color}">{current_status}</span></td>
                    <td>{metric.get('cpu_avg', 0):.1f}%</td>
                    <td>{metric.get('gpu_avg', 0):.1f}%</td>
                    <td>{metric.get('memory_avg', 0):.1f}%</td>
                    <td><small>{metric.get('metrics_count', 0)}</small></td>
                </tr>
            '''
        else:
            # Raw data display
            timestamp = metric.get('timestamp', '')
            try:
                time_display = datetime.fromisoformat(timestamp).strftime('%H:%M:%S')
            except:
                time_display = timestamp[-8:] if len(timestamp) >= 8 else timestamp
            
            uptime_seconds = metric.get('uptime_seconds', 0)
            uptime_hours = uptime_seconds // 3600
            uptime_mins = (uptime_seconds % 3600) // 60
            
            html += f'''
                <tr>
                    <td><small>{time_display}</small></td>
                    <td><small>{pod_name}</small></td>
                    <td><span class="badge bg-{badge_color}">{current_status}</span></td>
                    <td>{metric.get('cpu_percent', 0)}%</td>
                    <td>{metric.get('gpu_percent', 0)}%</td>
                    <td>{metric.get('memory_percent', 0)}%</td>
                    <td><small>{uptime_hours}h {uptime_mins}m</small></td>
                </tr>
            '''
    
    if not paginated_data:
        html += '''
                <tr>
                    <td colspan="7" class="text-center text-muted">
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


@router.get("/api/auto-stop-predictions")
async def get_auto_stop_predictions(request: Request):
    """
    Get predictions for which pods are close to being auto-stopped.
    Shows progress bars and statistics for pods approaching thresholds.
    
    Args:
        request: FastAPI request object
        
    Returns:
        HTML response with predictions table
    """
    current_config = get_current_config()
    
    if not current_config:
        return HTMLResponse("<p class='text-muted'>No configuration available</p>")
    
    monitor_only = current_config.get('auto_stop', {}).get('monitor_only', False)
    
    # Read counters from file instead of loading all metrics
    import os
    counters_file = './data/auto_stop_counters.json'
    
    if not os.path.exists(counters_file):
        return HTMLResponse("<p class='text-muted'>No auto-stop tracking data available</p>")
    
    try:
        with open(counters_file, 'r') as f:
            counters = json.load(f)
    except Exception as e:
        return HTMLResponse(f"<p class='text-muted'>Error loading counters: {e}</p>")
    
    # Calculate predictions from counters
    thresholds = current_config.get('auto_stop', {}).get('thresholds', {})
    duration = thresholds.get('duration', 1800)
    sampling_freq = current_config.get('auto_stop', {}).get('sampling', {}).get('frequency', 60)
    points_needed = duration // sampling_freq
    
    predictions = []
    for pod_id, counter_data in counters.items():
        consecutive = counter_data.get('consecutive_below_threshold', 0)
        if consecutive > 0:
            remaining_points = max(0, points_needed - consecutive)
            predictions.append({
                'pod_id': pod_id,
                'pod_name': counter_data.get('pod_name', pod_id[:8]),
                'meeting_criteria': consecutive,
                'remaining_points': remaining_points,
                'total_needed': points_needed,
                'progress_percent': (consecutive / points_needed) * 100,
                'avg_cpu': counter_data.get('last_metrics', {}).get('cpu', 0),
                'avg_memory': counter_data.get('last_metrics', {}).get('memory', 0),
                'avg_gpu': counter_data.get('last_metrics', {}).get('gpu', 0)
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
                <td class="align-middle"><small>{pred['pod_name']}</small></td>
                <td class="align-middle"><small><code>{pod_id_short}</code></small></td>
                <td class="align-middle">
                    <div class="progress" style="height: 15px;">
                        <div class="progress-bar bg-{status_class}" style="width: {pred['progress_percent']}%">
                            {pred['progress_percent']:.0f}%
                        </div>
                    </div>
                </td>
                <td class="align-middle"><small>{pred['meeting_criteria']}/{pred['total_needed']}</small></td>
                <td class="align-middle"><small>{pred['avg_cpu']}%</small></td>
                <td class="align-middle"><small>{pred['avg_memory']}%</small></td>
                <td class="align-middle"><small>{pred['avg_gpu']}%</small></td>
                <td class="align-middle"><span class="badge bg-{status_class}">{status_text}</span></td>
                <td class="align-middle">
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


@router.get("/api/graph-pods")
async def get_graph_pods():
    """
    Get list of pods that have data available for graphing.
    Used to populate the pod selector in the metrics charts page.
    
    Returns:
        JSON response with list of pods containing id and name
    """
    print("📊 Graph pods API called")
    
    # Instead of loading all data, just get pod list from PodMetricsManager
    try:
        from ..pod_metrics_manager import PodMetricsManager
    except ImportError:
        from runpod_monitor.pod_metrics_manager import PodMetricsManager
    
    manager = PodMetricsManager(base_dir='./data/pods')
    pod_dirs = manager.get_pod_list()
    
    if not pod_dirs:
        print("📊 No pod directories found")
        return JSONResponse([])
    
    print(f"📊 Found {len(pod_dirs)} pods with data")
    
    # Get current active pods
    try:
        from ..main import fetch_pods
    except ImportError:
        from runpod_monitor.main import fetch_pods
    
    current_pods = fetch_pods()
    print(f"📊 Found {len(current_pods) if current_pods else 0} active pods from API")
    
    if not current_pods:
        # If can't fetch from API, return all pods with data directories
        print("📊 API fetch failed, returning all pods with data")
        pods_with_data = []
        for pod_id in pod_dirs:
            # Try to get name from a recent metric
            recent_metrics = manager.read_metrics(pod_id, file_type="raw", limit=1)
            pod_name = pod_id[:8] + '...'
            if recent_metrics:
                pod_name = recent_metrics[-1].get('name', pod_name)
            pods_with_data.append({
                'id': pod_id,
                'name': pod_name
            })
        print(f"📊 Returning {len(pods_with_data)} pods with data")
        return JSONResponse(pods_with_data)
    
    active_pod_names = {pod['id']: pod['name'] for pod in current_pods}
    
    # Return pods that have data and are currently active
    pods_with_data = []
    for pod_id in pod_dirs:
        if pod_id in active_pod_names:
            pods_with_data.append({
                'id': pod_id,
                'name': active_pod_names[pod_id]
            })
    
    print(f"📊 Returning {len(pods_with_data)} active pods with data")
    return JSONResponse(pods_with_data)


@router.get("/api/graph-data/{pod_id}")
async def get_graph_data(pod_id: str, timeRange: int = 3600, resolution: str = "30min"):
    """
    Get metrics data for a specific pod for graphing.
    Returns time series data for CPU, GPU, and memory usage.
    
    Args:
        pod_id: The ID of the pod to get graph data for
        timeRange: Time range in seconds (default 3600 = 1 hour)
        resolution: Data resolution - "raw", "30min", or "1hour" (default "30min")
        
    Returns:
        JSON response with chart data including timestamps and metrics arrays
    """
    # Use PodMetricsManager for per-pod data
    try:
        from ..pod_metrics_manager import PodMetricsManager
    except ImportError:
        from runpod_monitor.pod_metrics_manager import PodMetricsManager
    
    manager = PodMetricsManager(base_dir='./data/pods')
    
    # Map resolution to file type
    file_type_map = {
        "raw": "raw",
        "30min": "30min", 
        "1hour": "1hour"
    }
    file_type = file_type_map.get(resolution, "30min")
    
    # Calculate cutoff time
    cutoff_time = time.time() - timeRange
    
    # Read metrics based on resolution
    if file_type in ["30min", "1hour"]:
        # Read compacted data
        metrics = manager.read_metrics(
            pod_id, 
            file_type=file_type,
            start_epoch=cutoff_time
        )
        
        # If no compacted data, fall back to raw
        if not metrics:
            metrics = manager.read_metrics(
                pod_id,
                file_type="raw", 
                start_epoch=cutoff_time
            )
            file_type = "raw"  # Mark that we're using raw data
    else:
        # Read raw data
        metrics = manager.read_metrics(
            pod_id,
            file_type="raw",
            start_epoch=cutoff_time
        )
    
    if not metrics:
        return JSONResponse({'error': 'No data available for this pod'})
    
    # Sort by timestamp
    if file_type in ["30min", "1hour"]:
        # Compacted data uses window_start_epoch
        metrics.sort(key=lambda x: x.get('window_start_epoch', 0))
    else:
        # Raw data uses epoch
        metrics.sort(key=lambda x: x.get('epoch', 0))
    
    # Extract data for chart
    timestamps = []
    cpu_data = []
    memory_data = []
    gpu_data = []
    
    for metric in metrics:
        # Format timestamp based on data type
        if file_type in ["30min", "1hour"]:
            # Use window start time for compacted data
            window_start = metric.get('window_start_epoch', 0)
            dt = datetime.fromtimestamp(window_start)
            timestamps.append(dt.strftime('%H:%M'))
            
            # Use average values for compacted data
            cpu_data.append(metric.get('cpu_avg', 0))
            memory_data.append(metric.get('memory_avg', 0))
            gpu_data.append(metric.get('gpu_avg', 0))
        else:
            # Raw data handling
            timestamp = metric.get('timestamp', '')
            if timestamp:
                try:
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    timestamps.append(dt.strftime('%H:%M:%S'))
                except:
                    timestamps.append(timestamp[-8:] if len(timestamp) >= 8 else '')
            else:
                timestamps.append('')
            
            cpu_data.append(metric.get('cpu_percent', 0))
            memory_data.append(metric.get('memory_percent', 0))
            gpu_data.append(metric.get('gpu_percent', 0))
    
    # Get pod name
    pod_name = pod_id[:8] + "..."
    if metrics:
        # Try to get name from the metrics
        pod_name = metrics[-1].get('name', pod_name)
    
    return JSONResponse({
        'podName': pod_name,
        'timestamps': timestamps,
        'cpu': cpu_data,
        'memory': memory_data,
        'gpu': gpu_data,
        'resolution': file_type,
        'dataPoints': len(metrics)
    })


@router.get("/api/export")
async def export_data_endpoint():
    """
    Export all metrics data as a ZIP file of the entire data folder.
    Creates a complete backup of all pod metrics, counters, and statistics.
    
    Returns:
        ZIP file containing the entire data directory
    """
    import zipfile
    import io
    import os
    from pathlib import Path
    
    try:
        # Get the data directory path
        try:
            from ..main import config
        except ImportError:
            from runpod_monitor.main import config
        
        data_dir = config.get('storage', {}).get('data_dir', './data') if config else './data'
        
        if not os.path.exists(data_dir):
            return JSONResponse({"error": "Data directory not found"}, status_code=404)
        
        # Create a ZIP file in memory
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Walk through the data directory and add all files
            for root, dirs, files in os.walk(data_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    # Calculate the archive name (relative path from data_dir)
                    arc_name = os.path.relpath(file_path, os.path.dirname(data_dir))
                    zip_file.write(file_path, arc_name)
        
        # Prepare the ZIP file for download
        zip_buffer.seek(0)
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"runpod_data_backup_{timestamp}.zip"
        
        headers = {
            "Content-Disposition": f"attachment; filename={filename}"
        }
        
        return Response(
            content=zip_buffer.getvalue(),
            media_type="application/zip",
            headers=headers
        )
        
    except Exception as e:
        return JSONResponse({"error": f"Export failed: {str(e)}"}, status_code=500)
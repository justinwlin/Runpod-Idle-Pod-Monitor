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


def calculate_auto_stop_predictions(data: Dict[str, Any], current_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Calculate which pods are close to being auto-stopped based on thresholds.
    
    Args:
        data: Metrics data dictionary
        current_config: Current configuration dictionary
        
    Returns:
        List of prediction dictionaries with pod info and progress towards auto-stop
    """
    try:
        from ..main import fetch_pods
    except ImportError:
        from runpod_monitor.main import fetch_pods
    
    thresholds = current_config.get('auto_stop', {}).get('thresholds', {})
    max_cpu = thresholds.get('max_cpu_percent', 5)
    max_gpu = thresholds.get('max_gpu_percent', 5)
    max_memory = thresholds.get('max_memory_percent', 20)
    duration = thresholds.get('duration', 1800)
    
    sampling_freq = current_config.get('auto_stop', {}).get('sampling', {}).get('frequency', 60)
    points_needed = duration // sampling_freq
    
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
        
        # Only check pods that are currently active
        if pod_id not in pod_names:
            continue
        
        # Calculate averages for the time period
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
        
        # Count consecutive RUNNING points meeting criteria
        meeting_criteria = 0
        
        for metric in reversed(metrics_list):
            status = metric.get('status')
            
            if status != 'RUNNING':
                break
                
            cpu = metric.get('cpu_percent', 0)
            gpu = metric.get('gpu_percent', 0)
            memory = metric.get('memory_percent', 0)
            
            if cpu <= max_cpu and gpu <= max_gpu and memory <= max_memory:
                meeting_criteria += 1
                if meeting_criteria >= points_needed:
                    break
            else:
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
    
    return predictions


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
async def get_raw_data(request: Request, page: int = 1, status_filter: str = None):
    """
    Get raw data points as HTML table with pagination and optional status filtering.
    Shows individual metric data points for debugging and detailed analysis.
    
    Args:
        request: FastAPI request object
        page: Page number for pagination (default 1)
        status_filter: Optional filter for pod status (active, exited, terminated)
        
    Returns:
        HTML response with paginated raw data table
    """
    data = load_metrics_data()
    if not data:
        return HTMLResponse("<p>No metrics data file found</p>")
    
    # Get current pods from API to determine actual status
    current_pod_ids, current_pod_statuses = get_pod_statuses()
    
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
    
    # Build HTML with filter buttons and pagination
    html = generate_raw_data_filters_html(
        page, status_filter, total_count, active_count, exited_count, 
        terminated_count, start_idx, end_idx, total_items
    )
    
    # Pagination controls
    html += f'''
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
    
    # Read data from file
    data = load_metrics_data()
    if not data:
        return HTMLResponse("<p class='text-muted'>No data available</p>")
    
    # Calculate predictions
    predictions = calculate_auto_stop_predictions(data, current_config)
    
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


@router.get("/api/graph-pods")
async def get_graph_pods():
    """
    Get list of pods that have data available for graphing.
    Used to populate the pod selector in the metrics charts page.
    
    Returns:
        JSON response with list of pods containing id and name
    """
    print("📊 Graph pods API called")
    
    data = load_metrics_data()
    if not data:
        print("📊 No metrics data available")
        return JSONResponse([])
    
    print(f"📊 Loaded data for {len(data)} pods from file")
    
    # Get current active pods
    try:
        from ..main import fetch_pods
    except ImportError:
        from runpod_monitor.main import fetch_pods
    
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


@router.get("/api/graph-data/{pod_id}")
async def get_graph_data(pod_id: str, timeRange: int = 3600):
    """
    Get metrics data for a specific pod for graphing.
    Returns time series data for CPU, GPU, and memory usage.
    
    Args:
        pod_id: The ID of the pod to get graph data for
        timeRange: Time range in seconds (default 3600 = 1 hour)
        
    Returns:
        JSON response with chart data including timestamps and metrics arrays
    """
    data = load_metrics_data()
    if not data:
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
    try:
        from ..main import fetch_pods
    except ImportError:
        from runpod_monitor.main import fetch_pods
    
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


@router.get("/api/export")
async def export_data_endpoint(
    format: str = Query("csv", description="Export format: csv or json"),
    pod_id: Optional[str] = Query(None, description="Specific pod ID to export"),
    duration: Optional[int] = Query(None, description="Duration in seconds (e.g., 3600 for 1 hour)"),
    start_time: Optional[int] = Query(None, description="Start timestamp (Unix epoch)"),
    end_time: Optional[int] = Query(None, description="End timestamp (Unix epoch)")
):
    """
    Export pod metrics data in CSV or JSON format.
    Allows filtering by pod, time range, and format.
    
    Args:
        format: Export format (csv or json)
        pod_id: Optional specific pod ID to export
        duration: Optional duration in seconds
        start_time: Optional start timestamp
        end_time: Optional end timestamp
        
    Returns:
        File response with exported data
    """
    try:
        from ..main import data_tracker, fetch_pods
    except ImportError:
        from runpod_monitor.main import data_tracker, fetch_pods
    
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
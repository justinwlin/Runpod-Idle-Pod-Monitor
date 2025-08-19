"""
Pod management endpoints for the RunPod Monitor web server.
Handles pod operations like stopping, resuming, excluding, and including pods.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import Tuple

from .helpers import (
    create_alert_response, 
    save_config_to_file,
    get_current_config
)

# Create router for pod management endpoints
router = APIRouter(prefix="/pods", tags=["pods"])

# Setup templates
templates = Jinja2Templates(directory="templates")


def get_pod_info(pod_id: str) -> Tuple[str, bool]:
    """
    Get pod information including name and whether it's a CPU pod.
    
    Args:
        pod_id: The ID of the pod to get info for
        
    Returns:
        Tuple of (pod_name, is_cpu_pod)
    """
    try:
        from ..main import fetch_pods
    except ImportError:
        from runpod_monitor.main import fetch_pods
    
    pods = fetch_pods()
    pod_name = "Unknown Pod"
    is_cpu_pod = False
    
    if pods:
        for pod in pods:
            if pod['id'] == pod_id:
                pod_name = pod['name']
                runtime = pod.get('runtime')
                is_cpu_pod = not runtime or not runtime.get('gpus', [])
                break
    
    return pod_name, is_cpu_pod


def create_resume_error_message(pod_name: str, error_msg: str = None, is_cpu_pod: bool = False) -> str:
    """
    Create a formatted error message for resume failures with helpful guidance.
    
    Args:
        pod_name: Name of the pod that failed to resume
        error_msg: Optional error message from the API
        is_cpu_pod: Whether this is a CPU pod (affects error messaging)
        
    Returns:
        Formatted HTML error message with recommendations
    """
    if error_msg and ('vCPU' in error_msg or 'CPU' in error_msg):
        return f"""
            <strong>⚠️ Resume Failed: '{pod_name}'</strong><br>
            <small><strong>Issue:</strong> {error_msg}</small><br>
            <small><strong>💡 Solution:</strong> CPU pods often fail due to no available vCPUs. Please resume manually via 
            <a href="https://console.runpod.io" target="_blank" class="alert-link">RunPod Console</a> to select different resources.</small>
        """
    elif error_msg:
        return f"""
            <strong>❌ Resume Failed: '{pod_name}'</strong><br>
            <small><strong>Issue:</strong> {error_msg}</small><br>
            <small><strong>💡 Recommendation:</strong> Try resuming manually via 
            <a href="https://console.runpod.io" target="_blank" class="alert-link">RunPod Console</a> for better control.</small>
        """
    else:
        pod_type = "CPU pod" if is_cpu_pod else "GPU pod"
        return f"""
            <strong>❌ Resume Failed: '{pod_name}' ({pod_type})</strong><br>
            <small><strong>Issue:</strong> Resume request failed or timed out</small><br>
            <small><strong>💡 Recommendation:</strong> Please resume manually via 
            <a href="https://console.runpod.io" target="_blank" class="alert-link">RunPod Console</a> for better control.</small>
        """


@router.get("")
async def get_pods(request: Request):
    """
    Get all pods with their current status and metrics.
    Includes historical data and exclude status for each pod.
    
    Args:
        request: FastAPI request object
        
    Returns:
        HTML response with rendered pods table
    """
    try:
        from ..main import fetch_pods, config, data_tracker
    except ImportError:
        from runpod_monitor.main import fetch_pods, config, data_tracker
    
    pods = fetch_pods()
    if not pods:
        return HTMLResponse("<p>No pods found or API error</p>")
    
    # Get exclude list from configuration
    current_config = config
    exclude_pods = current_config.get('auto_stop', {}).get('exclude_pods', []) if current_config else []
    
    # Add historical data and exclude status to each pod
    for pod in pods:
        pod_id = pod['id']
        if data_tracker:
            summary = data_tracker.get_pod_summary(pod_id)
            pod['summary'] = summary
        
        # Add exclude status - check both ID and name
        pod['is_excluded'] = pod_id in exclude_pods or pod['name'] in exclude_pods
    
    return templates.TemplateResponse("pods_table.html", {"request": request, "pods": pods})


@router.post("/{pod_id}/stop")
async def stop_pod_endpoint(pod_id: str, request: Request):
    """
    Stop a specific pod by ID.
    
    Args:
        pod_id: The ID of the pod to stop
        request: FastAPI request object
        
    Returns:
        HTML response with success/error message and auto-refresh
    """
    try:
        from ..main import stop_pod
    except ImportError:
        from runpod_monitor.main import stop_pod
    
    result = stop_pod(pod_id)
    
    if result and (result.get('podStop') or result.get('success')):
        return create_alert_response("success", "Pod stopped successfully", "/pods", 2)
    else:
        message = result.get('message', 'Failed to stop pod') if result else 'Failed to stop pod'
        return create_alert_response("error", message, "/pods", 2)


@router.post("/{pod_id}/resume")
async def resume_pod_endpoint(pod_id: str, request: Request):
    """
    Resume a stopped pod by ID.
    Provides detailed error messages for common failure scenarios.
    
    Args:
        pod_id: The ID of the pod to resume
        request: FastAPI request object
        
    Returns:
        HTML response with persistent warning/success message
    """
    try:
        from ..main import resume_pod
    except ImportError:
        from runpod_monitor.main import resume_pod
    
    # Get pod information for better error context
    pod_name, is_cpu_pod = get_pod_info(pod_id)
    
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
                message = create_resume_error_message(pod_name, error_msg, is_cpu_pod)
                    
        elif result.get('podResume'):
            # GraphQL response
            status = "success"
            message = f"✅ Pod '{pod_name}' resumed successfully. Status: {result['podResume'].get('desiredStatus', 'Unknown')}"
        else:
            status = "warning"
            message = create_resume_error_message(pod_name, "Unknown resume error occurred", is_cpu_pod)
    else:
        status = "warning"
        message = create_resume_error_message(pod_name, None, is_cpu_pod)
    
    # Return persistent warning that doesn't auto-dismiss
    return HTMLResponse(f'''
        <div class="alert alert-{status} alert-dismissible" role="alert">
            {message}
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        </div>
        <div hx-get="/pods" hx-target="#pods-container" hx-trigger="load delay:3s" hx-swap="innerHTML"></div>
    ''')


@router.post("/{pod_id}/exclude")
async def exclude_pod(pod_id: str, request: Request):
    """
    Add a pod to the exclude list to prevent auto-stop.
    
    Args:
        pod_id: The ID of the pod to exclude
        request: FastAPI request object
        
    Returns:
        HTML response with status message and pod list refresh
    """
    try:
        from ..main import fetch_pods, config as current_config
    except ImportError:
        from runpod_monitor.main import fetch_pods, config as current_config
    
    # Get config path
    import os
    config_path = 'config.yaml'
    
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


@router.post("/{pod_id}/include")
async def include_pod(pod_id: str, request: Request):
    """
    Remove a pod from the exclude list to enable auto-stop monitoring.
    Also handles cleanup of deleted pods from exclude list.
    
    Args:
        pod_id: The ID of the pod to include
        request: FastAPI request object
        
    Returns:
        HTML response with status message and pod list refresh
    """
    try:
        from ..main import fetch_pods, config as current_config
    except ImportError:
        from runpod_monitor.main import fetch_pods, config as current_config
    
    # Get config path
    import os
    config_path = 'config.yaml'
    
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
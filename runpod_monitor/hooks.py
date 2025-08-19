"""
Hook functions for the event-based metric writer.
These can be registered with MetricWriter to extend functionality.
"""

import json
import os
import time
from datetime import datetime
from typing import Dict, Any, Optional


# ============================================================================
# ON-START HOOKS (Run once at initialization)
# ============================================================================

def hello_world_hook() -> None:
    """
    Simple hello world hook for testing on-start functionality.
    """
    print("👋 Hello World from onStart hook!")
    print("   This runs once when MetricWriter starts")


def initialize_directories_hook() -> None:
    """
    Example hook that could create necessary directories.
    """
    import os
    dirs_to_create = ['./data/pods', './data/archives', './data/stats']
    for dir_path in dirs_to_create:
        os.makedirs(dir_path, exist_ok=True)
        print(f"   📁 Ensured directory exists: {dir_path}")


# Global auto-stop tracker instance (initialized by hook)
_auto_stop_tracker = None


def initialize_auto_stop_tracker_hook() -> None:
    """
    Initialize the auto-stop tracker from existing JSONL data.
    This should be called once at startup.
    """
    global _auto_stop_tracker
    from .auto_stop_tracker import AutoStopTracker
    
    # Initialize tracker
    _auto_stop_tracker = AutoStopTracker(data_dir='./data')
    
    # Load thresholds from config (would normally come from main.py)
    # For now, use defaults
    thresholds = {
        'max_cpu_percent': 1,
        'max_gpu_percent': 1,
        'max_memory_percent': 1,
        'duration': 3600,
        'detect_no_change': False
    }
    
    # Initialize from existing JSONL
    _auto_stop_tracker.initialize_from_jsonl('./data/pod_metrics.jsonl', thresholds)
    _auto_stop_tracker.set_thresholds(thresholds)


# ============================================================================
# PRE-WRITE HOOKS (Transform or validate metrics before writing)
# ============================================================================

def validate_metric_hook(metric_point: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate that a metric has all required fields.
    
    Args:
        metric_point: The metric to validate
        
    Returns:
        The metric if valid, raises exception if invalid
    """
    required_fields = ['pod_id', 'timestamp', 'epoch']
    for field in required_fields:
        if field not in metric_point:
            raise ValueError(f"Metric missing required field: {field}")
    return metric_point


def add_metadata_hook(metric_point: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add additional metadata to metrics.
    
    Args:
        metric_point: The metric to enhance
        
    Returns:
        Metric with additional metadata
    """
    metric_point['writer_version'] = '2.0'
    metric_point['write_time'] = time.time()
    return metric_point


def round_numbers_hook(metric_point: Dict[str, Any]) -> Dict[str, Any]:
    """
    Round numeric values to reduce file size.
    
    Args:
        metric_point: The metric to process
        
    Returns:
        Metric with rounded numbers
    """
    numeric_fields = ['cpu_percent', 'memory_percent', 'gpu_percent', 'gpu_memory_percent']
    for field in numeric_fields:
        if field in metric_point and isinstance(metric_point[field], (int, float)):
            metric_point[field] = round(metric_point[field], 2)
    return metric_point


# ============================================================================
# POST-WRITE HOOKS (Additional actions after writing)
# ============================================================================

def update_auto_stop_counter_hook(metric_point: Dict[str, Any], file_path: str) -> None:
    """
    Update auto-stop counter after writing a metric.
    This maintains the fast counter-based tracking system.
    
    Args:
        metric_point: The metric that was just written
        file_path: Path to the JSONL file (not used but required by hook interface)
    """
    global _auto_stop_tracker
    
    if _auto_stop_tracker is None:
        # Tracker not initialized, skip
        return
    
    # Update the counter with the new metric
    _auto_stop_tracker.update_counter(metric_point)
    
    # Check if this pod now meets auto-stop conditions
    pod_id = metric_point.get('pod_id')
    if pod_id:
        should_stop, counter_info = _auto_stop_tracker.check_auto_stop(pod_id)
        if should_stop and counter_info:
            pod_name = counter_info.get('pod_name', pod_id)
            duration = counter_info.get('first_below_epoch')
            if duration:
                time_below = int(time.time() - duration)
                print(f"⚠️  AUTO-STOP: Pod '{pod_name}' has been idle for {time_below}s")


def auto_compact_hook(metric_point: Dict[str, Any], file_path: str) -> None:
    """
    Compact the JSONL file if it exceeds a size threshold.
    Keeps only the most recent data for each pod.
    
    Args:
        metric_point: The metric that was just written
        file_path: Path to the JSONL file
    """
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    
    if os.path.exists(file_path) and os.path.getsize(file_path) > MAX_FILE_SIZE:
        print(f"📦 Auto-compacting {file_path} (size > {MAX_FILE_SIZE/1024/1024}MB)...")
        
        # Read all metrics
        metrics_by_pod = {}
        with open(file_path, 'r') as f:
            for line in f:
                if line.strip():
                    metric = json.loads(line)
                    pod_id = metric.get('pod_id')
                    if pod_id:
                        if pod_id not in metrics_by_pod:
                            metrics_by_pod[pod_id] = []
                        metrics_by_pod[pod_id].append(metric)
        
        # Keep only last 1000 metrics per pod
        MAX_METRICS_PER_POD = 1000
        compacted_count = 0
        
        with open(file_path + '.tmp', 'w') as f:
            for pod_id, metrics in metrics_by_pod.items():
                # Keep only the most recent metrics
                recent_metrics = metrics[-MAX_METRICS_PER_POD:]
                compacted_count += len(metrics) - len(recent_metrics)
                
                for metric in recent_metrics:
                    f.write(json.dumps(metric) + '\n')
        
        # Replace original file
        os.replace(file_path + '.tmp', file_path)
        print(f"✅ Compacted {compacted_count} old metrics")


def separate_by_pod_hook(metric_point: Dict[str, Any], file_path: str) -> None:
    """
    Also write metrics to separate pod-specific files.
    
    Args:
        metric_point: The metric that was just written
        file_path: Path to the main JSONL file
    """
    pod_id = metric_point.get('pod_id')
    if not pod_id:
        return
    
    # Create pod-specific directory
    base_dir = os.path.dirname(file_path)
    pod_dir = os.path.join(base_dir, 'pods', pod_id)
    os.makedirs(pod_dir, exist_ok=True)
    
    # Write to pod-specific file
    pod_file = os.path.join(pod_dir, 'metrics.jsonl')
    with open(pod_file, 'a') as f:
        f.write(json.dumps(metric_point) + '\n')


def daily_rotation_hook(metric_point: Dict[str, Any], file_path: str) -> None:
    """
    Rotate files daily by creating date-stamped files.
    
    Args:
        metric_point: The metric that was just written
        file_path: Path to the main JSONL file
    """
    # Create daily file
    base_dir = os.path.dirname(file_path)
    date_str = datetime.now().strftime('%Y-%m-%d')
    daily_file = os.path.join(base_dir, f'pod_metrics_{date_str}.jsonl')
    
    # Also write to daily file
    with open(daily_file, 'a') as f:
        f.write(json.dumps(metric_point) + '\n')


def alert_threshold_hook(metric_point: Dict[str, Any], file_path: str) -> None:
    """
    Print alerts when metrics exceed thresholds.
    In production, this could send emails, webhooks, etc.
    
    Args:
        metric_point: The metric that was just written
        file_path: Path to the JSONL file
    """
    # Check CPU threshold
    cpu_percent = metric_point.get('cpu_percent', 0)
    if cpu_percent > 90:
        pod_name = metric_point.get('name', metric_point.get('pod_id', 'Unknown'))
        print(f"🚨 ALERT: High CPU ({cpu_percent}%) on pod {pod_name}")
    
    # Check memory threshold
    memory_percent = metric_point.get('memory_percent', 0)
    if memory_percent > 90:
        pod_name = metric_point.get('name', metric_point.get('pod_id', 'Unknown'))
        print(f"🚨 ALERT: High Memory ({memory_percent}%) on pod {pod_name}")


def statistics_hook(metric_point: Dict[str, Any], file_path: str) -> None:
    """
    Maintain running statistics in a separate file.
    
    Args:
        metric_point: The metric that was just written
        file_path: Path to the main JSONL file
    """
    base_dir = os.path.dirname(file_path)
    stats_file = os.path.join(base_dir, 'statistics.json')
    
    # Load existing stats or create new
    stats = {}
    if os.path.exists(stats_file):
        try:
            with open(stats_file, 'r') as f:
                stats = json.load(f)
        except:
            stats = {}
    
    # Update stats for this pod
    pod_id = metric_point.get('pod_id', 'unknown')
    if pod_id not in stats:
        stats[pod_id] = {
            'count': 0,
            'total_cpu': 0,
            'total_memory': 0,
            'total_gpu': 0,
            'max_cpu': 0,
            'max_memory': 0,
            'max_gpu': 0,
            'last_seen': None
        }
    
    pod_stats = stats[pod_id]
    pod_stats['count'] += 1
    pod_stats['total_cpu'] += metric_point.get('cpu_percent', 0)
    pod_stats['total_memory'] += metric_point.get('memory_percent', 0)
    pod_stats['total_gpu'] += metric_point.get('gpu_percent', 0)
    pod_stats['max_cpu'] = max(pod_stats['max_cpu'], metric_point.get('cpu_percent', 0))
    pod_stats['max_memory'] = max(pod_stats['max_memory'], metric_point.get('memory_percent', 0))
    pod_stats['max_gpu'] = max(pod_stats['max_gpu'], metric_point.get('gpu_percent', 0))
    pod_stats['last_seen'] = metric_point.get('timestamp')
    
    # Calculate averages
    if pod_stats['count'] > 0:
        pod_stats['avg_cpu'] = round(pod_stats['total_cpu'] / pod_stats['count'], 2)
        pod_stats['avg_memory'] = round(pod_stats['total_memory'] / pod_stats['count'], 2)
        pod_stats['avg_gpu'] = round(pod_stats['total_gpu'] / pod_stats['count'], 2)
    
    # Save updated stats
    with open(stats_file, 'w') as f:
        json.dump(stats, f, indent=2)


# ============================================================================
# CONDITIONAL HOOKS (Can be used as pre or post hooks with conditions)
# ============================================================================

def debug_hook(metric_point: Dict[str, Any], file_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Debug hook that prints metric details.
    Can be used as either pre or post hook.
    
    Args:
        metric_point: The metric
        file_path: Optional file path (for post-write hook)
        
    Returns:
        The unchanged metric (for pre-write compatibility)
    """
    pod_name = metric_point.get('name', metric_point.get('pod_id', 'Unknown'))
    cpu = metric_point.get('cpu_percent', 0)
    mem = metric_point.get('memory_percent', 0)
    
    if file_path:
        print(f"📝 Wrote metric: {pod_name} - CPU: {cpu}%, MEM: {mem}%")
    else:
        print(f"📊 Processing metric: {pod_name} - CPU: {cpu}%, MEM: {mem}%")
    
    return metric_point


# ============================================================================
# HOOK SETS (Predefined combinations of hooks)
# ============================================================================

def get_default_hooks():
    """Get the default set of hooks for production use."""
    return {
        'pre_write': [validate_metric_hook, round_numbers_hook],
        'post_write': []
    }


def get_debug_hooks():
    """Get hooks useful for debugging."""
    return {
        'pre_write': [validate_metric_hook, debug_hook],
        'post_write': [lambda m, f: debug_hook(m, f)]
    }


def get_production_hooks():
    """Get hooks for production with all features."""
    return {
        'pre_write': [validate_metric_hook, round_numbers_hook],
        'post_write': [auto_compact_hook, alert_threshold_hook, statistics_hook]
    }


def get_archival_hooks():
    """Get hooks for long-term data archival."""
    return {
        'pre_write': [validate_metric_hook, round_numbers_hook, add_metadata_hook],
        'post_write': [separate_by_pod_hook, daily_rotation_hook, auto_compact_hook]
    }
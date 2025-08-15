import json
import os
import time
import csv
import io
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union


class DataTracker:
    """Tracks pod metrics over time and manages historical data."""
    
    def __init__(self, data_dir: str = "./data", metrics_file: str = "pod_metrics.json"):
        self.data_dir = data_dir
        self.metrics_file = os.path.join(data_dir, metrics_file)
        self.data: Dict[str, List[Dict]] = {}
        
        # Ensure data directory exists
        os.makedirs(data_dir, exist_ok=True)
        
        # Load existing data
        self.load_data()
    
    def load_data(self):
        """Load metrics data from file."""
        if os.path.exists(self.metrics_file):
            try:
                with open(self.metrics_file, 'r') as f:
                    self.data = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not load metrics file: {e}")
                self.data = {}
        else:
            self.data = {}
    
    def save_data(self):
        """Save metrics data to file."""
        try:
            with open(self.metrics_file, 'w') as f:
                json.dump(self.data, f, indent=2)
        except IOError as e:
            print(f"Error: Could not save metrics file: {e}")
    
    def add_metric(self, pod_id: str, pod_data: Dict[str, Any]):
        """Add a new metric data point for a pod."""
        timestamp = datetime.now().isoformat()
        
        # Extract relevant metrics
        metric_point = {
            "timestamp": timestamp,
            "epoch": int(time.time()),
            "pod_id": pod_id,
            "name": pod_data.get("name", ""),
            "status": pod_data.get("desiredStatus", "UNKNOWN"),
            "cost_per_hr": pod_data.get("costPerHr", 0),
        }
        
        # Add runtime metrics if available
        runtime = pod_data.get("runtime")
        if runtime:
            metric_point["uptime_seconds"] = runtime.get("uptimeInSeconds", 0)
            
            container = runtime.get("container", {})
            metric_point["cpu_percent"] = container.get("cpuPercent", 0)
            metric_point["memory_percent"] = container.get("memoryPercent", 0)
            
            # GPU metrics
            gpus = runtime.get("gpus", [])
            if gpus:
                # Average GPU utilization across all GPUs
                gpu_utils = [gpu.get("gpuUtilPercent", 0) for gpu in gpus]
                gpu_memory_utils = [gpu.get("memoryUtilPercent", 0) for gpu in gpus]
                
                metric_point["gpu_percent"] = sum(gpu_utils) / len(gpu_utils) if gpu_utils else 0
                metric_point["gpu_memory_percent"] = sum(gpu_memory_utils) / len(gpu_memory_utils) if gpu_memory_utils else 0
                metric_point["gpu_count"] = len(gpus)
            else:
                metric_point["gpu_percent"] = 0
                metric_point["gpu_memory_percent"] = 0
                metric_point["gpu_count"] = 0
        else:
            # Pod is stopped or no runtime data
            metric_point.update({
                "uptime_seconds": 0,
                "cpu_percent": 0,
                "memory_percent": 0,
                "gpu_percent": 0,
                "gpu_memory_percent": 0,
                "gpu_count": 0
            })
        
        # Initialize pod data if not exists
        if pod_id not in self.data:
            self.data[pod_id] = []
        
        # Check for pod restart (uptime decreased)
        current_uptime = metric_point.get("uptime_seconds", 0)
        if self.data[pod_id] and current_uptime > 0:
            last_uptime = self.data[pod_id][-1].get("uptime_seconds", 0)
            if current_uptime < last_uptime - 60:  # Allow 60 second buffer for timing differences
                print(f"Pod restart detected for {pod_id}: uptime {last_uptime}→{current_uptime}. Clearing old data.")
                self.data[pod_id] = []  # Clear all historical data
        
        # Add the metric point
        self.data[pod_id].append(metric_point)
        
        # Save to file
        self.save_data()
    
    def get_recent_metrics(self, pod_id: str, duration_seconds: int) -> List[Dict]:
        """Get recent metrics for a pod within the specified duration."""
        if pod_id not in self.data:
            return []
        
        cutoff_time = time.time() - duration_seconds
        
        return [
            metric for metric in self.data[pod_id]
            if metric.get("epoch", 0) >= cutoff_time
        ]
    
    def check_auto_stop_conditions(self, pod_id: str, thresholds: Dict, excluded_pods: List[str] = None) -> bool:
        """
        Check if a pod meets auto-stop conditions.
        
        Args:
            pod_id: Pod ID to check
            thresholds: Dict with max_cpu_percent, max_gpu_percent, max_memory_percent, duration, detect_no_change
            excluded_pods: List of excluded pod IDs/names to skip (safety check)
            
        Returns:
            True if pod should be stopped, False otherwise
        """
        # Safety check: never auto-stop excluded pods
        if excluded_pods:
            if pod_id in excluded_pods:
                return False
            # Also check if pod name is in excluded list (need recent metric for name)
            recent_metrics = self.get_recent_metrics(pod_id, 300)  # Last 5 minutes
            if recent_metrics:
                pod_name = recent_metrics[-1].get("name", "")
                if pod_name in excluded_pods:
                    return False
        recent_metrics = self.get_recent_metrics(pod_id, thresholds["duration"])
        
        if not recent_metrics:
            return False
        
        # Check if we have enough data points (at least 3 data points over the duration)
        if len(recent_metrics) < 3:
            return False
        
        # Check if all recent metrics are below or equal to thresholds
        threshold_met = True
        no_change_detected = True
        
        first_metric = recent_metrics[0]
        first_cpu = first_metric.get("cpu_percent", 0)
        first_gpu = first_metric.get("gpu_percent", 0)
        first_memory = first_metric.get("memory_percent", 0)
        
        for metric in recent_metrics:
            # Skip if pod is not running
            if metric.get("status") != "RUNNING":
                return False
            
            cpu = metric.get("cpu_percent", 0)
            gpu = metric.get("gpu_percent", 0)
            memory = metric.get("memory_percent", 0)
            
            # Check thresholds (≤ instead of <)
            if (cpu > thresholds["max_cpu_percent"] or 
                gpu > thresholds["max_gpu_percent"] or 
                memory > thresholds["max_memory_percent"]):
                threshold_met = False
            
            # Check for any change in metrics
            if (cpu != first_cpu or gpu != first_gpu or memory != first_memory):
                no_change_detected = False
        
        # If detect_no_change is enabled and no change detected, stop the pod
        if thresholds.get("detect_no_change", False) and no_change_detected:
            print(f"Pod {pod_id}: No change detected in metrics over {thresholds['duration']}s - stopping")
            return True
        
        return threshold_met
    
    def apply_rolling_window(self, pod_id: str, window_seconds: int):
        """Apply rolling window to keep only recent data points in memory."""
        if pod_id not in self.data:
            return
        
        cutoff_time = time.time() - window_seconds
        
        # Keep only recent data points
        self.data[pod_id] = [
            metric for metric in self.data[pod_id]
            if metric.get("epoch", 0) >= cutoff_time
        ]
    
    def get_metrics_change_rate(self, pod_id: str, duration_seconds: int) -> Dict:
        """Calculate the rate of change in metrics over time."""
        recent_metrics = self.get_recent_metrics(pod_id, duration_seconds)
        
        if len(recent_metrics) < 2:
            return {"cpu_change": 0, "gpu_change": 0, "memory_change": 0, "total_change": 0}
        
        first = recent_metrics[0]
        last = recent_metrics[-1]
        
        cpu_change = abs(last.get("cpu_percent", 0) - first.get("cpu_percent", 0))
        gpu_change = abs(last.get("gpu_percent", 0) - first.get("gpu_percent", 0))
        memory_change = abs(last.get("memory_percent", 0) - first.get("memory_percent", 0))
        
        return {
            "cpu_change": cpu_change,
            "gpu_change": gpu_change,
            "memory_change": memory_change,
            "total_change": cpu_change + gpu_change + memory_change
        }
    
    def has_data(self, pod_id: str):
        """Check if a pod has any data stored."""
        return pod_id in self.data and len(self.data[pod_id]) > 0
    
    def clear_pod_data(self, pod_id: str):
        """Clear all historical data for a pod (e.g., when pod is terminated)."""
        if pod_id in self.data:
            del self.data[pod_id]
            self.save_data()
    
    def cleanup_old_data(self, retention_config: Dict):
        """
        Remove data based on retention policy.
        
        Args:
            retention_config: Dict with 'value' and 'unit'
        """
        if not isinstance(retention_config, dict):
            print(f"Warning: Invalid retention config format, skipping cleanup")
            return
            
        if retention_config.get('unit') == 'forever':
            return  # Don't clean up anything (legacy support)
        
        # Handle very long retention (999 years = effectively forever)
        if retention_config.get('unit') == 'years' and retention_config.get('value', 0) >= 999:
            return  # Don't clean up anything
        
        # Convert to seconds
        value = retention_config.get('value', 30)
        unit = retention_config.get('unit', 'days')
        
        seconds_map = {
            'hours': 3600,
            'days': 24 * 3600,
            'weeks': 7 * 24 * 3600,
            'months': 30 * 24 * 3600,
            'years': 365 * 24 * 3600
        }
        
        if unit not in seconds_map:
            print(f"Warning: Unknown retention unit '{unit}', defaulting to days")
            unit = 'days'
        
        cutoff_time = time.time() - (value * seconds_map[unit])
        
        for pod_id in list(self.data.keys()):
            # Filter out old metrics
            self.data[pod_id] = [
                metric for metric in self.data[pod_id]
                if metric.get("epoch", 0) >= cutoff_time
            ]
            
            # Remove pod entry if no metrics remain
            if not self.data[pod_id]:
                del self.data[pod_id]
        
        self.save_data()
    
    def get_pod_summary(self, pod_id: str) -> Optional[Dict]:
        """Get summary statistics for a pod."""
        if pod_id not in self.data or not self.data[pod_id]:
            return None
        
        metrics = self.data[pod_id]
        recent_metric = metrics[-1]  # Most recent
        
        # Calculate averages over last hour
        recent_hour_metrics = self.get_recent_metrics(pod_id, 3600)
        
        if recent_hour_metrics:
            avg_cpu = sum(m.get("cpu_percent", 0) for m in recent_hour_metrics) / len(recent_hour_metrics)
            avg_gpu = sum(m.get("gpu_percent", 0) for m in recent_hour_metrics) / len(recent_hour_metrics)
            avg_memory = sum(m.get("memory_percent", 0) for m in recent_hour_metrics) / len(recent_hour_metrics)
        else:
            avg_cpu = avg_gpu = avg_memory = 0
        
        return {
            "pod_id": pod_id,
            "name": recent_metric.get("name", ""),
            "status": recent_metric.get("status", "UNKNOWN"),
            "total_data_points": len(metrics),
            "first_seen": metrics[0].get("timestamp") if metrics else None,
            "last_seen": recent_metric.get("timestamp"),
            "current_metrics": {
                "cpu_percent": recent_metric.get("cpu_percent", 0),
                "gpu_percent": recent_metric.get("gpu_percent", 0),
                "memory_percent": recent_metric.get("memory_percent", 0),
                "uptime_seconds": recent_metric.get("uptime_seconds", 0),
            },
            "hourly_averages": {
                "cpu_percent": round(avg_cpu, 2),
                "gpu_percent": round(avg_gpu, 2),
                "memory_percent": round(avg_memory, 2),
            }
        }
    
    def get_all_summaries(self) -> List[Dict]:
        """Get summaries for all tracked pods."""
        summaries = []
        for pod_id in self.data:
            summary = self.get_pod_summary(pod_id)
            if summary:
                summaries.append(summary)
        return summaries
    
    def get_filtered_metrics(self, pod_id: Optional[str] = None, 
                           start_time: Optional[int] = None, 
                           end_time: Optional[int] = None,
                           duration_seconds: Optional[int] = None) -> Dict[str, List[Dict]]:
        """
        Get filtered metrics based on time range.
        
        Args:
            pod_id: Specific pod ID to filter (None for all pods)
            start_time: Unix timestamp for start time
            end_time: Unix timestamp for end time
            duration_seconds: Get data for last N seconds (alternative to start/end)
            
        Returns:
            Dict of pod_id -> list of metrics
        """
        if duration_seconds is not None:
            end_time = int(time.time())
            start_time = end_time - duration_seconds
        
        result = {}
        
        # Determine which pods to process
        pod_ids = [pod_id] if pod_id else list(self.data.keys())
        
        for pid in pod_ids:
            if pid not in self.data:
                continue
                
            filtered_metrics = []
            for metric in self.data[pid]:
                metric_time = metric.get("epoch", 0)
                
                # Apply time filters
                if start_time is not None and metric_time < start_time:
                    continue
                if end_time is not None and metric_time > end_time:
                    continue
                    
                filtered_metrics.append(metric)
            
            if filtered_metrics:
                result[pid] = filtered_metrics
        
        return result
    
    def export_data(self, format_type: str = 'csv', 
                   pod_id: Optional[str] = None,
                   start_time: Optional[int] = None,
                   end_time: Optional[int] = None,
                   duration_seconds: Optional[int] = None) -> str:
        """
        Export data in various formats.
        
        Args:
            format_type: 'csv' or 'json'
            pod_id: Specific pod ID (None for all)
            start_time: Unix timestamp start
            end_time: Unix timestamp end
            duration_seconds: Last N seconds of data
            
        Returns:
            Formatted data as string
        """
        filtered_data = self.get_filtered_metrics(
            pod_id=pod_id,
            start_time=start_time,
            end_time=end_time,
            duration_seconds=duration_seconds
        )
        
        if format_type.lower() == 'csv':
            return self._export_csv(filtered_data)
        elif format_type.lower() == 'json':
            return json.dumps(filtered_data, indent=2)
        else:
            raise ValueError(f"Unsupported export format: {format_type}")
    
    def _export_csv(self, data: Dict[str, List[Dict]]) -> str:
        """Convert metrics data to CSV format."""
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        header = [
            'timestamp', 'epoch', 'pod_id', 'name', 'status', 'cost_per_hr',
            'uptime_seconds', 'cpu_percent', 'memory_percent', 'gpu_percent',
            'gpu_memory_percent', 'gpu_count'
        ]
        writer.writerow(header)
        
        # Write data rows
        for pod_id, metrics in data.items():
            for metric in metrics:
                row = [
                    metric.get('timestamp', ''),
                    metric.get('epoch', 0),
                    metric.get('pod_id', pod_id),
                    metric.get('name', ''),
                    metric.get('status', ''),
                    metric.get('cost_per_hr', 0),
                    metric.get('uptime_seconds', 0),
                    metric.get('cpu_percent', 0),
                    metric.get('memory_percent', 0),
                    metric.get('gpu_percent', 0),
                    metric.get('gpu_memory_percent', 0),
                    metric.get('gpu_count', 0)
                ]
                writer.writerow(row)
        
        return output.getvalue()
    
    def get_retention_info(self, retention_config: Dict) -> Dict:
        """Get human-readable retention information."""
        if not isinstance(retention_config, dict):
            # Fallback for invalid config
            return {
                'value': 0,
                'unit': 'forever',
                'display': 'Forever',
                'seconds': 0
            }
            
        value = retention_config.get('value', 0)
        unit = retention_config.get('unit', 'forever')
        
        if unit == 'forever':
            return {
                'value': 999,
                'unit': 'years',
                'display': '999 years',
                'seconds': 999 * 365 * 24 * 3600
            }
        
        # Handle very long retention (999 years = effectively forever)
        if unit == 'years' and value >= 999:
            return {
                'value': 999,
                'unit': 'years',
                'display': '999 years',
                'seconds': 999 * 365 * 24 * 3600
            }
        
        seconds_map = {
            'hours': 3600,
            'days': 24 * 3600,
            'weeks': 7 * 24 * 3600,
            'months': 30 * 24 * 3600,
            'years': 365 * 24 * 3600
        }
        
        seconds = value * seconds_map.get(unit, 24 * 3600)
        
        return {
            'value': value,
            'unit': unit,
            'display': f"{value} {unit}",
            'seconds': seconds
        }
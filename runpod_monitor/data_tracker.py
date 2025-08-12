import json
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any


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
    
    def clear_pod_data(self, pod_id: str):
        """Clear all historical data for a pod (e.g., when pod is terminated)."""
        if pod_id in self.data:
            del self.data[pod_id]
            self.save_data()
    
    def cleanup_old_data(self, retention_days: int):
        """Remove data older than retention_days."""
        cutoff_time = time.time() - (retention_days * 24 * 60 * 60)
        
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
"""
Per-pod metrics storage manager.
Handles reading and writing metrics to individual pod folders for better organization and performance.
"""

import json
import os
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict


class PodMetricsManager:
    """
    Manages per-pod metrics storage with separate files for each pod.
    Future-ready for time-based compaction (30min, 1hr aggregates).
    """
    
    def __init__(self, base_dir: str = "./data/pods"):
        """
        Initialize the pod metrics manager.
        
        Args:
            base_dir: Base directory for pod-specific metric files
        """
        self.base_dir = Path(base_dir)
        self.ensure_base_directory()
    
    def ensure_base_directory(self) -> None:
        """Ensure the base pods directory exists."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
    
    def get_pod_directory(self, pod_id: str) -> Path:
        """
        Get the directory path for a specific pod.
        
        Args:
            pod_id: The pod identifier
            
        Returns:
            Path to the pod's directory
        """
        pod_dir = self.base_dir / pod_id
        pod_dir.mkdir(parents=True, exist_ok=True)
        return pod_dir
    
    def get_metrics_file_path(self, pod_id: str, file_type: str = "raw") -> Path:
        """
        Get the path to a specific metrics file for a pod.
        
        Args:
            pod_id: The pod identifier
            file_type: Type of metrics file (raw, 30min, 1hour, daily)
            
        Returns:
            Path to the metrics file
        """
        pod_dir = self.get_pod_directory(pod_id)
        
        # File naming convention for different aggregation levels
        file_names = {
            "raw": "metrics_raw.jsonl",
            "30min": "metrics_30min.jsonl",
            "1hour": "metrics_1hour.jsonl",
            "daily": "metrics_daily.jsonl"
        }
        
        return pod_dir / file_names.get(file_type, "metrics_raw.jsonl")
    
    def get_pod_list(self) -> List[str]:
        """
        Get list of pod IDs that have data directories.
        
        Returns:
            List of pod IDs
        """
        if not os.path.exists(self.base_dir):
            return []
        
        return [
            pod_id for pod_id in os.listdir(self.base_dir)
            if os.path.isdir(os.path.join(self.base_dir, pod_id))
            and os.path.exists(os.path.join(self.base_dir, pod_id, 'metrics_raw.jsonl'))
        ]
    
    def write_metric(self, pod_id: str, metric: Dict[str, Any], file_type: str = "raw") -> bool:
        """
        Write a metric to the pod-specific file.
        
        Args:
            pod_id: The pod identifier
            metric: The metric dictionary to write
            file_type: Type of metrics file to write to
            
        Returns:
            True if successful, False otherwise
        """
        try:
            file_path = self.get_metrics_file_path(pod_id, file_type)
            
            # Ensure metric has pod_id
            metric['pod_id'] = pod_id
            
            # Append to JSONL file
            with open(file_path, 'a') as f:
                f.write(json.dumps(metric) + '\n')
            
            return True
        except Exception as e:
            print(f"❌ Error writing metric for pod {pod_id}: {e}")
            return False
    
    def read_metrics(self, pod_id: str, file_type: str = "raw", 
                     limit: Optional[int] = None, 
                     start_epoch: Optional[int] = None,
                     end_epoch: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Read metrics from a pod-specific file.
        
        Args:
            pod_id: The pod identifier
            file_type: Type of metrics file to read from
            limit: Maximum number of metrics to return (most recent)
            start_epoch: Filter metrics after this epoch time
            end_epoch: Filter metrics before this epoch time
            
        Returns:
            List of metric dictionaries
        """
        file_path = self.get_metrics_file_path(pod_id, file_type)
        
        if not file_path.exists():
            return []
        
        metrics = []
        try:
            with open(file_path, 'r') as f:
                for line in f:
                    if line.strip():
                        metric = json.loads(line)
                        
                        # Apply time filters based on data type
                        if file_type in ["30min", "1hour", "daily"]:
                            # Compacted data uses window epochs
                            window_start = metric.get('window_start_epoch', 0)
                            window_end = metric.get('window_end_epoch', 0)
                            
                            # Include window if it overlaps with requested time range
                            if start_epoch and window_end < start_epoch:
                                continue
                            if end_epoch and window_start > end_epoch:
                                continue
                        else:
                            # Raw data uses epoch
                            epoch = metric.get('epoch', 0)
                            if start_epoch and epoch < start_epoch:
                                continue
                            if end_epoch and epoch > end_epoch:
                                continue
                        
                        metrics.append(metric)
        except Exception as e:
            print(f"❌ Error reading metrics for pod {pod_id}: {e}")
        
        # Apply limit if specified (return most recent)
        if limit and len(metrics) > limit:
            metrics = metrics[-limit:]
        
        return metrics
    
    def get_latest_metric(self, pod_id: str, file_type: str = "raw") -> Optional[Dict[str, Any]]:
        """
        Get the most recent metric for a pod.
        
        Args:
            pod_id: The pod identifier
            file_type: Type of metrics file to read from
            
        Returns:
            The latest metric or None if no metrics exist
        """
        metrics = self.read_metrics(pod_id, file_type, limit=1)
        return metrics[-1] if metrics else None
    
    def list_pods(self) -> List[str]:
        """
        List all pods that have metrics stored.
        
        Returns:
            List of pod IDs
        """
        if not self.base_dir.exists():
            return []
        
        return [d.name for d in self.base_dir.iterdir() if d.is_dir()]
    
    def get_pod_info(self, pod_id: str) -> Dict[str, Any]:
        """
        Get information about a pod's stored metrics.
        
        Args:
            pod_id: The pod identifier
            
        Returns:
            Dictionary with pod metrics information
        """
        pod_dir = self.get_pod_directory(pod_id)
        
        info = {
            "pod_id": pod_id,
            "directory": str(pod_dir),
            "files": {}
        }
        
        # Check each type of metrics file
        for file_type in ["raw", "30min", "1hour", "daily"]:
            file_path = self.get_metrics_file_path(pod_id, file_type)
            if file_path.exists():
                # Count lines (metrics) and get file size
                line_count = sum(1 for line in open(file_path) if line.strip())
                file_size = file_path.stat().st_size
                
                info["files"][file_type] = {
                    "path": str(file_path),
                    "metrics_count": line_count,
                    "size_bytes": file_size,
                    "size_mb": round(file_size / (1024 * 1024), 2)
                }
        
        # Get latest metric to show pod name and status
        latest = self.get_latest_metric(pod_id)
        if latest:
            info["pod_name"] = latest.get("name", "Unknown")
            info["last_status"] = latest.get("status", "Unknown")
            info["last_seen"] = latest.get("timestamp", "Unknown")
        
        return info
    
    def initialize_from_main_jsonl(self, main_jsonl_path: str) -> Dict[str, int]:
        """
        Initialize per-pod files from the main pod_metrics.jsonl file.
        Used during onStart to populate individual pod files.
        
        Args:
            main_jsonl_path: Path to the main metrics JSONL file
            
        Returns:
            Dictionary with pod_id -> metrics_count
        """
        if not os.path.exists(main_jsonl_path):
            print(f"📭 No main metrics file found at {main_jsonl_path}")
            return {}
        
        print(f"🔄 Initializing per-pod metrics from {main_jsonl_path}...")
        
        pod_counts = {}
        
        try:
            with open(main_jsonl_path, 'r') as f:
                for line in f:
                    if line.strip():
                        metric = json.loads(line)
                        pod_id = metric.get('pod_id')
                        
                        if pod_id:
                            # Write to pod-specific file
                            self.write_metric(pod_id, metric)
                            
                            # Track count
                            pod_counts[pod_id] = pod_counts.get(pod_id, 0) + 1
        
            # Summary
            total_metrics = sum(pod_counts.values())
            print(f"✅ Initialized {len(pod_counts)} pod folders with {total_metrics} total metrics")
            for pod_id, count in pod_counts.items():
                pod_info = self.get_pod_info(pod_id)
                pod_name = pod_info.get("pod_name", pod_id)
                print(f"   📁 {pod_name} ({pod_id}): {count} metrics")
                
        except Exception as e:
            print(f"❌ Error initializing per-pod metrics: {e}")
        
        return pod_counts
    
    def cleanup_terminated_pods(self, active_pod_ids: List[str], archive: bool = False) -> int:
        """
        Clean up or archive metrics for terminated pods.
        
        Args:
            active_pod_ids: List of currently active pod IDs
            archive: If True, move to archive folder instead of deleting
            
        Returns:
            Number of pods cleaned up
        """
        all_pods = set(self.list_pods())
        active_pods = set(active_pod_ids)
        terminated_pods = all_pods - active_pods
        
        cleaned_count = 0
        for pod_id in terminated_pods:
            pod_dir = self.get_pod_directory(pod_id)
            
            if archive:
                # Move to archive folder
                archive_dir = self.base_dir.parent / "archives" / "pods"
                archive_dir.mkdir(parents=True, exist_ok=True)
                
                archive_path = archive_dir / pod_id
                if archive_path.exists():
                    # Add timestamp to avoid overwrite
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    archive_path = archive_dir / f"{pod_id}_{timestamp}"
                
                pod_dir.rename(archive_path)
                print(f"📦 Archived pod metrics: {pod_id}")
            else:
                # Delete the pod directory
                import shutil
                shutil.rmtree(pod_dir)
                print(f"🗑️ Deleted pod metrics: {pod_id}")
            
            cleaned_count += 1
        
        if cleaned_count > 0:
            print(f"🧹 Cleaned up {cleaned_count} terminated pod folders")
        
        return cleaned_count
    
    def _apply_rolling_window(self, pod_id: str, file_type: str, interval_minutes: int) -> None:
        """
        Apply a rolling window to compacted files to keep only 1 week of data.
        
        Args:
            pod_id: The pod identifier
            file_type: The file type (30min or 1hour)
            interval_minutes: Interval in minutes (30 or 60)
        """
        # Calculate max data points for 1 week
        if interval_minutes == 30:
            max_points = 48 * 7  # 336 points (48 per day * 7 days)
        elif interval_minutes == 60:
            max_points = 24 * 7  # 168 points (24 per day * 7 days)
        else:
            return  # Unsupported interval
        
        # Read all compacted data
        compacted_file = self.get_metrics_file_path(pod_id, file_type)
        if not os.path.exists(compacted_file):
            return
        
        # Count lines in file
        with open(compacted_file, 'r') as f:
            lines = f.readlines()
        
        current_points = len(lines)
        
        # If we're over the limit, keep only the most recent points
        if current_points > max_points:
            points_to_remove = current_points - max_points
            
            # Keep only the most recent max_points
            lines_to_keep = lines[points_to_remove:]
            
            # Rewrite the file with only recent data
            with open(compacted_file, 'w') as f:
                f.writelines(lines_to_keep)
            
            print(f"🔄 Rolled {file_type} window for {pod_id}: removed {points_to_remove} old entries, kept {len(lines_to_keep)} recent")
    
    def compact_metrics(self, pod_id: str, interval_minutes: int = 30) -> Tuple[int, int]:
        """
        Compact raw metrics into time-based aggregates.
        
        Args:
            pod_id: The pod identifier
            interval_minutes: Interval for aggregation (30 or 60)
            
        Returns:
            Tuple of (windows_created, metrics_processed)
        """
        # Determine file type based on interval
        if interval_minutes == 30:
            target_file_type = "30min"
        elif interval_minutes == 60:
            target_file_type = "1hour"
        else:
            print(f"⚠️ Unsupported interval: {interval_minutes} minutes")
            return 0, 0
        
        # Read raw metrics
        raw_metrics = self.read_metrics(pod_id, "raw")
        if not raw_metrics:
            return 0, 0
        
        # Read existing compacted data to find last processed time
        existing_compacted = self.read_metrics(pod_id, target_file_type)
        last_processed_epoch = 0
        if existing_compacted:
            last_processed_epoch = existing_compacted[-1].get('window_end_epoch', 0)
        
        # Group metrics by time window
        interval_seconds = interval_minutes * 60
        windows = defaultdict(list)
        metrics_to_process = []
        
        for metric in raw_metrics:
            epoch = metric.get('epoch', 0)
            # Only process metrics newer than last compacted window
            if epoch > last_processed_epoch:
                metrics_to_process.append(metric)
                # Calculate window start (floor to interval)
                window_start = (epoch // interval_seconds) * interval_seconds
                windows[window_start].append(metric)
        
        if not metrics_to_process:
            return 0, 0  # No new metrics to compact
        
        # Create aggregated metrics for each window
        windows_created = 0
        compacted_file = self.get_metrics_file_path(pod_id, target_file_type)
        
        for window_start in sorted(windows.keys()):
            window_metrics = windows[window_start]
            
            # Skip incomplete windows (unless it's been more than 2 intervals)
            current_time = datetime.now().timestamp()
            window_end = window_start + interval_seconds
            if window_end > current_time and (current_time - window_start) < (interval_seconds * 2):
                continue  # Skip this window, it's not complete yet
            
            # Calculate aggregates
            cpu_values = [m.get('cpu_percent', 0) for m in window_metrics if m.get('cpu_percent') is not None]
            memory_values = [m.get('memory_percent', 0) for m in window_metrics if m.get('memory_percent') is not None]
            gpu_values = [m.get('gpu_percent', 0) for m in window_metrics if m.get('gpu_percent') is not None]
            
            # Use the first metric for metadata
            first_metric = window_metrics[0]
            last_metric = window_metrics[-1]
            
            aggregated = {
                'window_start': datetime.fromtimestamp(window_start).isoformat(),
                'window_end': datetime.fromtimestamp(window_end).isoformat(),
                'window_start_epoch': window_start,
                'window_end_epoch': window_end,
                'interval_minutes': interval_minutes,
                'pod_id': pod_id,
                'name': last_metric.get('name', ''),
                'status': last_metric.get('status', 'UNKNOWN'),
                'metrics_count': len(window_metrics),
                
                # CPU stats
                'cpu_avg': round(sum(cpu_values) / len(cpu_values), 2) if cpu_values else 0,
                'cpu_min': round(min(cpu_values), 2) if cpu_values else 0,
                'cpu_max': round(max(cpu_values), 2) if cpu_values else 0,
                
                # Memory stats
                'memory_avg': round(sum(memory_values) / len(memory_values), 2) if memory_values else 0,
                'memory_min': round(min(memory_values), 2) if memory_values else 0,
                'memory_max': round(max(memory_values), 2) if memory_values else 0,
                
                # GPU stats
                'gpu_avg': round(sum(gpu_values) / len(gpu_values), 2) if gpu_values else 0,
                'gpu_min': round(min(gpu_values), 2) if gpu_values else 0,
                'gpu_max': round(max(gpu_values), 2) if gpu_values else 0,
                
                # Additional info
                'cost_per_hr': last_metric.get('cost_per_hr', 0),
                'uptime_start': first_metric.get('uptime_seconds', 0),
                'uptime_end': last_metric.get('uptime_seconds', 0)
            }
            
            # Write aggregated metric
            with open(compacted_file, 'a') as f:
                f.write(json.dumps(aggregated) + '\n')
            
            windows_created += 1
        
        if windows_created > 0:
            print(f"📊 Compacted {len(metrics_to_process)} metrics into {windows_created} {interval_minutes}-minute windows for {pod_id}")
            
            # Apply rolling window to keep only 1 week of data
            self._apply_rolling_window(pod_id, target_file_type, interval_minutes)
        
        return windows_created, len(metrics_to_process)
    
    def auto_compact(self, pod_id: str, raw_metrics_threshold: int = 100) -> None:
        """
        Automatically compact metrics when raw count exceeds threshold.
        
        Args:
            pod_id: The pod identifier
            raw_metrics_threshold: Number of raw metrics to trigger compaction
        """
        # Check raw metrics count
        raw_file = self.get_metrics_file_path(pod_id, "raw")
        if not raw_file.exists():
            return
        
        # Count lines efficiently
        line_count = sum(1 for _ in open(raw_file))
        
        if line_count >= raw_metrics_threshold:
            # Compact to 30-minute intervals
            windows_30, metrics_30 = self.compact_metrics(pod_id, 30)
            
            # Also compact to 1-hour intervals
            windows_60, metrics_60 = self.compact_metrics(pod_id, 60)
            
            # Optional: Clean up old raw metrics if both compactions succeeded
            # This is commented out for safety - uncomment if you want auto-cleanup
            # if windows_30 > 0 and windows_60 > 0:
            #     self.cleanup_old_raw_metrics(pod_id, keep_recent_hours=24)
    
    def cleanup_old_raw_metrics(self, pod_id: str, keep_recent_hours: int = 24) -> int:
        """
        Remove old raw metrics that have been compacted.
        Keep only recent metrics for real-time viewing.
        
        Args:
            pod_id: The pod identifier
            keep_recent_hours: Hours of recent data to keep
            
        Returns:
            Number of metrics removed
        """
        cutoff_epoch = datetime.now().timestamp() - (keep_recent_hours * 3600)
        
        # Read all raw metrics
        raw_metrics = self.read_metrics(pod_id, "raw")
        if not raw_metrics:
            return 0
        
        # Filter to keep only recent
        recent_metrics = [m for m in raw_metrics if m.get('epoch', 0) > cutoff_epoch]
        removed_count = len(raw_metrics) - len(recent_metrics)
        
        if removed_count > 0:
            # Rewrite the file with only recent metrics
            raw_file = self.get_metrics_file_path(pod_id, "raw")
            with open(raw_file, 'w') as f:
                for metric in recent_metrics:
                    f.write(json.dumps(metric) + '\n')
            
            print(f"🧹 Cleaned up {removed_count} old raw metrics for {pod_id}")
        
        return removed_count
    
    def get_storage_stats(self) -> Dict[str, Any]:
        """
        Get storage statistics for all pod metrics.
        
        Returns:
            Dictionary with storage statistics
        """
        stats = {
            "total_pods": 0,
            "total_metrics": 0,
            "total_size_bytes": 0,
            "total_size_mb": 0,
            "pods": {}
        }
        
        for pod_id in self.list_pods():
            pod_info = self.get_pod_info(pod_id)
            stats["total_pods"] += 1
            
            pod_stats = {
                "name": pod_info.get("pod_name", "Unknown"),
                "metrics": 0,
                "size_bytes": 0
            }
            
            for file_type, file_info in pod_info.get("files", {}).items():
                pod_stats["metrics"] += file_info["metrics_count"]
                pod_stats["size_bytes"] += file_info["size_bytes"]
                stats["total_metrics"] += file_info["metrics_count"]
                stats["total_size_bytes"] += file_info["size_bytes"]
            
            pod_stats["size_mb"] = round(pod_stats["size_bytes"] / (1024 * 1024), 2)
            stats["pods"][pod_id] = pod_stats
        
        stats["total_size_mb"] = round(stats["total_size_bytes"] / (1024 * 1024), 2)
        
        return stats
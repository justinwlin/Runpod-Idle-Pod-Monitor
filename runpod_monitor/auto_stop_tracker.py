"""
Fast counter-based auto-stop tracking system.
Maintains counters for each pod to track auto-stop conditions without scanning JSONL.
"""

import json
import os
import time
from typing import Dict, Any, Optional, Tuple
from pathlib import Path


class AutoStopTracker:
    """
    Tracks auto-stop conditions using counters for fast O(1) lookups.
    """
    
    def __init__(self, data_dir: str = "./data", counter_file: str = "auto_stop_counters.json"):
        """
        Initialize the auto-stop tracker.
        
        Args:
            data_dir: Directory to store counter file
            counter_file: Name of the counter file
        """
        self.data_dir = data_dir
        self.counter_file = os.path.join(data_dir, counter_file)
        self.counters: Dict[str, Dict[str, Any]] = {}
        self.thresholds: Dict[str, Any] = {}
        self.excluded_pods: list = []
        
        # Ensure data directory exists
        os.makedirs(data_dir, exist_ok=True)
        
        # Load existing counters if available
        self.load_counters()
    
    def load_counters(self) -> None:
        """Load counters from file if it exists."""
        if os.path.exists(self.counter_file):
            try:
                with open(self.counter_file, 'r') as f:
                    self.counters = json.load(f)
                print(f"📊 Loaded auto-stop counters for {len(self.counters)} pods")
            except Exception as e:
                print(f"⚠️ Could not load counters: {e}")
                self.counters = {}
    
    def save_counters(self) -> None:
        """Save counters to file."""
        try:
            with open(self.counter_file, 'w') as f:
                json.dump(self.counters, f, indent=2)
        except Exception as e:
            print(f"❌ Could not save counters: {e}")
    
    def set_thresholds(self, thresholds: Dict[str, Any], excluded_pods: list = None) -> None:
        """
        Set the auto-stop thresholds.
        
        Args:
            thresholds: Dict with max_cpu_percent, max_gpu_percent, max_memory_percent, duration, detect_no_change
            excluded_pods: List of pod IDs/names to exclude
        """
        self.thresholds = thresholds
        self.excluded_pods = excluded_pods or []
    
    def initialize_from_jsonl(self, jsonl_path: str, thresholds: Dict[str, Any]) -> None:
        """
        Initialize counters from existing JSONL data.
        Called once on startup to sync with existing metrics.
        
        Args:
            jsonl_path: Path to the JSONL metrics file
            thresholds: Auto-stop thresholds to use
        """
        if not os.path.exists(jsonl_path):
            print("📊 No existing metrics to initialize from")
            return
        
        print("🔄 Initializing auto-stop counters from existing metrics...")
        
        # Group metrics by pod
        pod_metrics = {}
        current_time = time.time()
        cutoff_time = current_time - thresholds.get('duration', 3600)
        
        try:
            with open(jsonl_path, 'r') as f:
                for line in f:
                    if line.strip():
                        metric = json.loads(line)
                        pod_id = metric.get('pod_id')
                        epoch = metric.get('epoch', 0)
                        
                        # Only consider recent metrics within the duration window
                        if pod_id and epoch >= cutoff_time:
                            if pod_id not in pod_metrics:
                                pod_metrics[pod_id] = []
                            pod_metrics[pod_id].append(metric)
        except Exception as e:
            print(f"❌ Error reading JSONL: {e}")
            return
        
        # Initialize counters based on recent metrics
        for pod_id, metrics in pod_metrics.items():
            if not metrics:
                continue
            
            # Sort by epoch to get chronological order
            metrics.sort(key=lambda x: x.get('epoch', 0))
            
            # Count consecutive metrics below threshold
            consecutive_count = 0
            first_below_epoch = None
            
            for metric in reversed(metrics):  # Check from most recent backwards
                if self._is_below_threshold(metric, thresholds):
                    consecutive_count += 1
                    if first_below_epoch is None:
                        first_below_epoch = metric.get('epoch')
                else:
                    break  # Stop counting when we hit a metric above threshold
            
            # Get the most recent metric for last values
            last_metric = metrics[-1]
            
            # Initialize counter for this pod
            self.counters[pod_id] = {
                'consecutive_below_threshold': consecutive_count,
                'last_check_epoch': last_metric.get('epoch', current_time),
                'first_below_epoch': first_below_epoch,
                'last_metrics': {
                    'cpu': last_metric.get('cpu_percent', 0),
                    'gpu': last_metric.get('gpu_percent', 0),
                    'memory': last_metric.get('memory_percent', 0)
                },
                'pod_name': last_metric.get('name', ''),
                'status': last_metric.get('status', 'UNKNOWN')
            }
        
        self.save_counters()
        print(f"✅ Initialized counters for {len(self.counters)} pods")
    
    def _is_below_threshold(self, metric: Dict[str, Any], thresholds: Dict[str, Any]) -> bool:
        """
        Check if a metric is below all thresholds.
        
        Args:
            metric: The metric to check
            thresholds: The threshold values
            
        Returns:
            True if metric is below all thresholds
        """
        cpu = metric.get('cpu_percent', 0)
        gpu = metric.get('gpu_percent', 0)
        memory = metric.get('memory_percent', 0)
        
        return (cpu <= thresholds.get('max_cpu_percent', 1) and
                gpu <= thresholds.get('max_gpu_percent', 1) and
                memory <= thresholds.get('max_memory_percent', 1))
    
    def update_counter(self, metric: Dict[str, Any]) -> None:
        """
        Update counter based on a new metric (called from post-write hook).
        
        Args:
            metric: The metric that was just written
        """
        pod_id = metric.get('pod_id')
        if not pod_id:
            return
        
        # Skip excluded pods
        pod_name = metric.get('name', '')
        if pod_id in self.excluded_pods or pod_name in self.excluded_pods:
            # Remove counter for excluded pods
            if pod_id in self.counters:
                del self.counters[pod_id]
            return
        
        current_epoch = metric.get('epoch', time.time())
        status = metric.get('status', 'UNKNOWN')
        
        # Only track RUNNING pods
        if status != 'RUNNING':
            # Reset counter for non-running pods
            if pod_id in self.counters:
                del self.counters[pod_id]
            return
        
        # Check if metric is below threshold
        is_below = self._is_below_threshold(metric, self.thresholds)
        
        if pod_id not in self.counters:
            # Initialize new counter
            self.counters[pod_id] = {
                'consecutive_below_threshold': 1 if is_below else 0,
                'last_check_epoch': current_epoch,
                'first_below_epoch': current_epoch if is_below else None,
                'last_metrics': {
                    'cpu': metric.get('cpu_percent', 0),
                    'gpu': metric.get('gpu_percent', 0),
                    'memory': metric.get('memory_percent', 0)
                },
                'pod_name': pod_name,
                'status': status
            }
        else:
            counter = self.counters[pod_id]
            
            if is_below:
                # Increment counter
                if counter['consecutive_below_threshold'] == 0:
                    # Starting a new below-threshold sequence
                    counter['first_below_epoch'] = current_epoch
                counter['consecutive_below_threshold'] += 1
            else:
                # Reset counter - metric is above threshold
                counter['consecutive_below_threshold'] = 0
                counter['first_below_epoch'] = None
            
            # Update last check info
            counter['last_check_epoch'] = current_epoch
            counter['last_metrics'] = {
                'cpu': metric.get('cpu_percent', 0),
                'gpu': metric.get('gpu_percent', 0),
                'memory': metric.get('memory_percent', 0)
            }
            counter['pod_name'] = pod_name
            counter['status'] = status
        
        # Periodically save counters (every 10 updates)
        if sum(c.get('consecutive_below_threshold', 0) for c in self.counters.values()) % 10 == 0:
            self.save_counters()
    
    def check_auto_stop(self, pod_id: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Fast O(1) check if a pod should be auto-stopped.
        
        Args:
            pod_id: The pod ID to check
            
        Returns:
            Tuple of (should_stop, counter_info)
        """
        if pod_id not in self.counters:
            return False, None
        
        counter = self.counters[pod_id]
        
        # Check if pod has been below threshold for the required duration
        if counter['consecutive_below_threshold'] > 0 and counter['first_below_epoch']:
            duration_below = time.time() - counter['first_below_epoch']
            required_duration = self.thresholds.get('duration', 3600)
            
            # Need at least 3 data points (assuming 60s intervals)
            min_data_points = 3
            if counter['consecutive_below_threshold'] >= min_data_points and duration_below >= required_duration:
                return True, counter
        
        return False, counter
    
    def get_all_auto_stop_candidates(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all pods that currently meet auto-stop conditions.
        
        Returns:
            Dict of pod_id -> counter info for pods that should be stopped
        """
        candidates = {}
        for pod_id in self.counters:
            should_stop, counter = self.check_auto_stop(pod_id)
            if should_stop:
                candidates[pod_id] = counter
        return candidates
    
    def reset_counter(self, pod_id: str) -> None:
        """
        Reset counter for a specific pod (e.g., after stopping it).
        
        Args:
            pod_id: The pod ID to reset
        """
        if pod_id in self.counters:
            del self.counters[pod_id]
            self.save_counters()
    
    def get_counter_info(self, pod_id: str) -> Optional[Dict[str, Any]]:
        """
        Get counter information for a specific pod.
        
        Args:
            pod_id: The pod ID
            
        Returns:
            Counter info or None if not tracked
        """
        return self.counters.get(pod_id)
    
    def cleanup_stale_counters(self, max_age_seconds: int = 7200) -> None:
        """
        Remove counters for pods that haven't been updated recently.
        
        Args:
            max_age_seconds: Maximum age for a counter before removal
        """
        current_time = time.time()
        stale_pods = []
        
        for pod_id, counter in self.counters.items():
            last_check = counter.get('last_check_epoch', 0)
            if current_time - last_check > max_age_seconds:
                stale_pods.append(pod_id)
        
        for pod_id in stale_pods:
            del self.counters[pod_id]
        
        if stale_pods:
            print(f"🧹 Cleaned up {len(stale_pods)} stale auto-stop counters")
            self.save_counters()
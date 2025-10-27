#!/usr/bin/env python3
"""
Test data generator for Runpod Idle Pod Monitor.
Generates realistic pod metrics data in the same format as the actual data tracker.

FEATURES:
- Exact format matching: Generates data in the same JSON structure as DataTracker
- Realistic scenarios: Multiple usage profiles (idle, low, normal, high, spike, steady)
- Pod variety: Different GPU types with accurate cost modeling
- Restart simulation: Can simulate pod restarts with uptime resets
- Configurable size: From small test sets to large datasets for stress testing

USAGE EXAMPLES:
    # Generate default test data (10 pods, 24 hours)
    python3 generate_test_data.py

    # Generate 20 pods with 3 days of history
    python3 generate_test_data.py --pods 20 --days 3

    # Generate large dataset for stress testing (50 pods, 7 days)
    python3 generate_test_data.py --large

    # Custom interval (30 seconds instead of 60)
    python3 generate_test_data.py --interval 30
    
    # Generate without backing up existing data
    python3 generate_test_data.py --no-backup
    
    # Specify custom data directory
    python3 generate_test_data.py --data-dir ./test_data

TEST PROFILES:
- idle: 0-1% usage (auto-stop candidates)
- low: 1-10% usage (low activity)
- normal: 20-60% usage (typical workload)
- high: 70-95% usage (intensive workload)
- spike: Random usage spikes (5-20% normally, 60-90% during spikes)
- steady: Constant values (tests no-change detection)

DATA FORMAT:
The generator creates a JSON file with the following structure:
{
    "pod_id_1": [
        {
            "timestamp": "2024-01-01T12:00:00",
            "epoch": 1704110400,
            "pod_id": "pod_id_1",
            "name": "ml-training-pod-idle-00",
            "status": "RUNNING",
            "cost_per_hr": 0.44,
            "uptime_seconds": 3600,
            "cpu_percent": 0.5,
            "memory_percent": 0.8,
            "gpu_percent": 0.2,
            "gpu_memory_percent": 3.5,
            "gpu_count": 1
        },
        ...
    ],
    "pod_id_2": [...],
    ...
}

NOTES:
- The script automatically backs up existing pod_metrics.json files
- Provides statistics about which pods would be candidates for auto-stopping
- File size and metric counts are displayed after generation
- Supports generating months of data for stress testing data migration
"""

import json
import os
import random
import time
from datetime import datetime, timedelta
from typing import Dict, List


class TestDataGenerator:
    """Generate realistic test data for pod metrics."""
    
    def __init__(self, data_dir: str = "./data", metrics_file: str = "pod_metrics.json"):
        self.data_dir = data_dir
        self.metrics_file = os.path.join(data_dir, metrics_file)
        self.data: Dict[str, List[Dict]] = {}
        
        # Ensure data directory exists
        os.makedirs(data_dir, exist_ok=True)
        
        # Pod name templates
        self.pod_names = [
            "ml-training-pod",
            "inference-server",
            "data-processor",
            "model-finetuning",
            "batch-compute",
            "research-notebook",
            "dev-environment",
            "production-api"
        ]
        
        # GPU configurations
        self.gpu_configs = [
            {"count": 1, "type": "RTX 3090"},
            {"count": 2, "type": "RTX 3090"},
            {"count": 1, "type": "A100 40GB"},
            {"count": 2, "type": "A100 40GB"},
            {"count": 4, "type": "A100 80GB"},
            {"count": 1, "type": "RTX 4090"},
            {"count": 8, "type": "H100"}
        ]
        
        # Cost per hour based on GPU type
        self.cost_map = {
            "RTX 3090": 0.44,
            "RTX 4090": 0.74,
            "A100 40GB": 1.54,
            "A100 80GB": 1.89,
            "H100": 3.99
        }
    
    def generate_pod_id(self) -> str:
        """Generate a realistic pod ID."""
        return ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=10))
    
    def generate_metric_point(self, 
                            pod_id: str, 
                            pod_name: str,
                            timestamp: datetime,
                            uptime_seconds: int,
                            gpu_config: Dict,
                            profile: str = "normal",
                            status: str = "RUNNING") -> Dict:
        """
        Generate a single metric point.
        
        Profiles:
        - idle: Very low usage (0-1%)
        - low: Low usage (1-10%)
        - normal: Normal usage (20-60%)
        - high: High usage (70-90%)
        - spike: Random spikes
        - steady: Constant usage
        """
        
        epoch = int(timestamp.timestamp())
        
        # Base metric structure
        metric = {
            "timestamp": timestamp.isoformat(),
            "epoch": epoch,
            "pod_id": pod_id,
            "name": pod_name,
            "status": status,
            "cost_per_hr": self.cost_map[gpu_config["type"]] * gpu_config["count"],
            "uptime_seconds": uptime_seconds,
            "gpu_count": gpu_config["count"]
        }
        
        # Generate usage based on profile
        if status != "RUNNING":
            # Pod is stopped
            metric.update({
                "cpu_percent": 0,
                "memory_percent": 0,
                "gpu_percent": 0,
                "gpu_memory_percent": 0
            })
        elif profile == "idle":
            # Very low usage - candidate for auto-stop
            metric.update({
                "cpu_percent": random.uniform(0, 1),
                "memory_percent": random.uniform(0, 1),
                "gpu_percent": random.uniform(0, 1),
                "gpu_memory_percent": random.uniform(0, 5)
            })
        elif profile == "low":
            # Low usage
            metric.update({
                "cpu_percent": random.uniform(1, 10),
                "memory_percent": random.uniform(5, 15),
                "gpu_percent": random.uniform(1, 10),
                "gpu_memory_percent": random.uniform(5, 20)
            })
        elif profile == "normal":
            # Normal usage
            base_cpu = random.uniform(20, 60)
            base_gpu = random.uniform(30, 70)
            metric.update({
                "cpu_percent": base_cpu + random.uniform(-5, 5),
                "memory_percent": random.uniform(20, 60),
                "gpu_percent": base_gpu + random.uniform(-5, 5),
                "gpu_memory_percent": random.uniform(40, 80)
            })
        elif profile == "high":
            # High usage
            metric.update({
                "cpu_percent": random.uniform(70, 95),
                "memory_percent": random.uniform(60, 90),
                "gpu_percent": random.uniform(75, 98),
                "gpu_memory_percent": random.uniform(70, 95)
            })
        elif profile == "spike":
            # Random spikes
            if random.random() < 0.2:  # 20% chance of spike
                metric.update({
                    "cpu_percent": random.uniform(60, 90),
                    "memory_percent": random.uniform(50, 80),
                    "gpu_percent": random.uniform(70, 95),
                    "gpu_memory_percent": random.uniform(60, 90)
                })
            else:
                metric.update({
                    "cpu_percent": random.uniform(5, 20),
                    "memory_percent": random.uniform(10, 30),
                    "gpu_percent": random.uniform(5, 25),
                    "gpu_memory_percent": random.uniform(20, 40)
                })
        elif profile == "steady":
            # Constant usage (no change detection test)
            metric.update({
                "cpu_percent": 15.0,
                "memory_percent": 25.0,
                "gpu_percent": 0.0,
                "gpu_memory_percent": 30.0
            })
        else:
            # Default to normal
            metric.update({
                "cpu_percent": random.uniform(10, 50),
                "memory_percent": random.uniform(20, 60),
                "gpu_percent": random.uniform(20, 60),
                "gpu_memory_percent": random.uniform(30, 70)
            })
        
        # Round to 2 decimal places to match real data
        for key in ["cpu_percent", "memory_percent", "gpu_percent", "gpu_memory_percent"]:
            metric[key] = round(metric[key], 2)
        
        return metric
    
    def generate_pod_history(self,
                           pod_id: str,
                           pod_name: str,
                           start_time: datetime,
                           duration_hours: float,
                           interval_seconds: int = 60,
                           profile: str = "normal",
                           gpu_config: Dict = None,
                           include_restart: bool = False) -> List[Dict]:
        """Generate a complete history for a single pod."""
        
        if gpu_config is None:
            gpu_config = random.choice(self.gpu_configs)
        
        history = []
        current_time = start_time
        end_time = start_time + timedelta(hours=duration_hours)
        uptime = 0
        
        # Generate status sequence
        status = "RUNNING"
        
        while current_time < end_time:
            # Simulate restart if requested
            if include_restart and uptime > 7200 and random.random() < 0.01:
                uptime = 0  # Reset uptime on restart
                print(f"Simulating restart for pod {pod_id} at {current_time}")
            
            # Generate metric point
            metric = self.generate_metric_point(
                pod_id=pod_id,
                pod_name=pod_name,
                timestamp=current_time,
                uptime_seconds=uptime,
                gpu_config=gpu_config,
                profile=profile,
                status=status
            )
            
            history.append(metric)
            
            # Advance time
            current_time += timedelta(seconds=interval_seconds)
            uptime += interval_seconds
            
            # Small chance of status change
            if random.random() < 0.001:
                status = "EXITED" if status == "RUNNING" else "RUNNING"
                if status == "EXITED":
                    uptime = 0
        
        return history
    
    def generate_test_data(self,
                         num_pods: int = 5,
                         history_hours: float = 24,
                         interval_seconds: int = 60) -> Dict[str, List[Dict]]:
        """
        Generate complete test dataset.
        
        Args:
            num_pods: Number of pods to generate
            history_hours: Hours of history to generate per pod
            interval_seconds: Interval between metric points (default 60s)
        """
        
        print(f"Generating test data for {num_pods} pods with {history_hours} hours of history...")
        
        # Define test scenarios
        scenarios = [
            {"profile": "idle", "name_suffix": "idle", "duration_ratio": 1.0},
            {"profile": "normal", "name_suffix": "active", "duration_ratio": 1.0},
            {"profile": "high", "name_suffix": "busy", "duration_ratio": 1.0},
            {"profile": "spike", "name_suffix": "variable", "duration_ratio": 1.0},
            {"profile": "steady", "name_suffix": "steady", "duration_ratio": 1.0},
        ]
        
        # Ensure we have at least one of each scenario
        test_data = {}
        current_time = datetime.now()
        
        for i in range(num_pods):
            pod_id = self.generate_pod_id()
            
            # Select scenario
            if i < len(scenarios):
                scenario = scenarios[i]
            else:
                scenario = random.choice(scenarios)
            
            # Generate pod name
            base_name = random.choice(self.pod_names)
            pod_name = f"{base_name}-{scenario['name_suffix']}-{i:02d}"
            
            # Generate history with some randomization in start time
            start_offset = random.uniform(0, history_hours * 0.1)  # Up to 10% variation
            start_time = current_time - timedelta(hours=history_hours - start_offset)
            
            # Generate pod history
            pod_history = self.generate_pod_history(
                pod_id=pod_id,
                pod_name=pod_name,
                start_time=start_time,
                duration_hours=history_hours * scenario['duration_ratio'],
                interval_seconds=interval_seconds,
                profile=scenario['profile'],
                gpu_config=random.choice(self.gpu_configs),
                include_restart=(random.random() < 0.2)  # 20% chance of restart
            )
            
            test_data[pod_id] = pod_history
            print(f"  Generated {len(pod_history)} metrics for pod {pod_name} (profile: {scenario['profile']})")
        
        return test_data
    
    def save_test_data(self, test_data: Dict[str, List[Dict]], backup: bool = True):
        """Save test data to file, optionally backing up existing data."""
        
        # Backup existing file if requested
        if backup and os.path.exists(self.metrics_file):
            backup_file = f"{self.metrics_file}.backup.{int(time.time())}"
            os.rename(self.metrics_file, backup_file)
            print(f"Backed up existing data to: {backup_file}")
        
        # Save new test data
        with open(self.metrics_file, 'w') as f:
            json.dump(test_data, f, indent=2)
        
        # Calculate file size
        file_size = os.path.getsize(self.metrics_file) / (1024 * 1024)  # MB
        total_metrics = sum(len(metrics) for metrics in test_data.values())
        
        print(f"\nTest data saved to: {self.metrics_file}")
        print(f"File size: {file_size:.2f} MB")
        print(f"Total pods: {len(test_data)}")
        print(f"Total metric points: {total_metrics:,}")
    
    def generate_large_dataset(self,
                              num_pods: int = 50,
                              history_days: int = 7,
                              interval_seconds: int = 60):
        """Generate a large dataset for stress testing."""
        
        print(f"\nGenerating LARGE test dataset:")
        print(f"  - Pods: {num_pods}")
        print(f"  - History: {history_days} days")
        print(f"  - Interval: {interval_seconds} seconds")
        print(f"  - Expected data points: ~{num_pods * (history_days * 24 * 3600 / interval_seconds):,.0f}")
        
        test_data = self.generate_test_data(
            num_pods=num_pods,
            history_hours=history_days * 24,
            interval_seconds=interval_seconds
        )
        
        return test_data


def main():
    """Main function with examples of different test data generation scenarios."""
    
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate test data for Runpod Idle Pod Monitor")
    parser.add_argument("--pods", type=int, default=10, help="Number of pods to generate")
    parser.add_argument("--hours", type=float, default=24, help="Hours of history per pod")
    parser.add_argument("--days", type=int, help="Days of history (overrides --hours)")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between metric points")
    parser.add_argument("--large", action="store_true", help="Generate large dataset (50 pods, 7 days)")
    parser.add_argument("--no-backup", action="store_true", help="Don't backup existing data")
    parser.add_argument("--data-dir", default="./data", help="Data directory path")
    
    args = parser.parse_args()
    
    # Initialize generator
    generator = TestDataGenerator(data_dir=args.data_dir)
    
    # Generate data based on arguments
    if args.large:
        test_data = generator.generate_large_dataset()
    else:
        history_hours = args.days * 24 if args.days else args.hours
        test_data = generator.generate_test_data(
            num_pods=args.pods,
            history_hours=history_hours,
            interval_seconds=args.interval
        )
    
    # Save the data
    generator.save_test_data(test_data, backup=not args.no_backup)
    
    # Print some statistics about idle pods
    print("\nIdle detection analysis:")
    for pod_id, metrics in test_data.items():
        if not metrics:
            continue
        
        # Check last hour of metrics
        last_hour_metrics = [m for m in metrics[-60:] if m.get("status") == "RUNNING"]
        if last_hour_metrics:
            avg_cpu = sum(m["cpu_percent"] for m in last_hour_metrics) / len(last_hour_metrics)
            avg_gpu = sum(m["gpu_percent"] for m in last_hour_metrics) / len(last_hour_metrics)
            
            pod_name = metrics[-1]["name"]
            if avg_cpu <= 1 and avg_gpu <= 1:
                print(f"  ⚠️  {pod_name}: IDLE (CPU: {avg_cpu:.1f}%, GPU: {avg_gpu:.1f}%)")
            elif avg_cpu <= 10 and avg_gpu <= 10:
                print(f"  ⚡ {pod_name}: LOW (CPU: {avg_cpu:.1f}%, GPU: {avg_gpu:.1f}%)")


if __name__ == "__main__":
    main()
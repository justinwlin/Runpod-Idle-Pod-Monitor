#!/usr/bin/env python3
"""
Pod Cost Cache - Append-only cache for pod cost data.

Stores {pod_id: {costPerHr, pod_name, first_seen, last_seen}} for all pods ever seen.
Never deletes data - this is our historical cost reference for billing calculations.
"""

import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional


class PodCostCache:
    """
    Append-only cache for pod cost data.

    Data is stored in JSONL format with one entry per pod.
    Updates existing entries when cost or name changes.
    """

    def __init__(self, data_dir: str = "./data"):
        """
        Initialize the cost cache.

        Args:
            data_dir: Directory for storing cache file
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.cache_file = self.data_dir / "pod_cost_cache.jsonl"

        # In-memory cache: {pod_id: cost_data}
        self.cache: Dict[str, Dict[str, Any]] = {}

        # Load existing cache
        self.load_cache()

    def load_cache(self) -> None:
        """Load existing cost cache from file."""
        if not self.cache_file.exists():
            print(f"💰 No existing cost cache found - starting fresh")
            return

        try:
            with open(self.cache_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    entry = json.loads(line)
                    pod_id = entry.get('pod_id')
                    if pod_id:
                        self.cache[pod_id] = entry

            print(f"💰 Loaded cost cache for {len(self.cache)} pods")

        except Exception as e:
            print(f"⚠️ Error loading cost cache: {e}")
            self.cache = {}

    def update_pod_cost(self, pod_id: str, pod_name: str, cost_per_hr: float) -> None:
        """
        Update cost data for a pod.

        If pod is new, creates entry. If exists, updates cost and last_seen.

        Args:
            pod_id: Pod ID
            pod_name: Pod name
            cost_per_hr: Cost per hour
        """
        current_time = int(time.time())

        if pod_id in self.cache:
            # Update existing entry
            entry = self.cache[pod_id]
            entry['pod_name'] = pod_name  # Update name in case it changed
            entry['cost_per_hr'] = cost_per_hr  # Update cost in case it changed
            entry['last_seen_epoch'] = current_time
        else:
            # Create new entry
            self.cache[pod_id] = {
                'pod_id': pod_id,
                'pod_name': pod_name,
                'cost_per_hr': cost_per_hr,
                'first_seen_epoch': current_time,
                'last_seen_epoch': current_time
            }

    def sync_from_graphql_pods(self, pods: List[Dict[str, Any]]) -> None:
        """
        Sync cost cache from GraphQL pod data.

        Args:
            pods: List of pod data from GraphQL API
        """
        updated_count = 0
        new_count = 0

        for pod in pods:
            pod_id = pod.get('id')
            pod_name = pod.get('name', 'Unknown')
            cost_per_hr = pod.get('costPerHr', 0)

            if not pod_id:
                continue

            was_new = pod_id not in self.cache
            self.update_pod_cost(pod_id, pod_name, cost_per_hr)

            if was_new:
                new_count += 1
            else:
                updated_count += 1

        if new_count > 0 or updated_count > 0:
            print(f"💰 Cost cache updated: {new_count} new pods, {updated_count} updated")
            self.save_cache()

    def save_cache(self) -> None:
        """Save entire cache to file (atomic write)."""
        try:
            # Write to temp file
            temp_file = self.cache_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                for entry in self.cache.values():
                    f.write(json.dumps(entry) + '\n')

            # Atomic rename
            temp_file.replace(self.cache_file)

        except Exception as e:
            print(f"⚠️ Error saving cost cache: {e}")

    def get_pod_cost(self, pod_id: str) -> Optional[Dict[str, Any]]:
        """
        Get cost data for a specific pod.

        Args:
            pod_id: Pod ID

        Returns:
            Cost data dictionary or None if not found
        """
        return self.cache.get(pod_id)

    def get_all_cached_costs(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all cached cost data.

        Returns:
            Dictionary mapping pod_id -> cost_data
        """
        return self.cache.copy()

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the cost cache.

        Returns:
            Dictionary with cache statistics
        """
        total_pods = len(self.cache)
        pods_with_cost = sum(1 for entry in self.cache.values() if entry.get('cost_per_hr', 0) > 0)
        pods_without_cost = total_pods - pods_with_cost

        return {
            'total_pods': total_pods,
            'pods_with_cost': pods_with_cost,
            'pods_without_cost': pods_without_cost
        }

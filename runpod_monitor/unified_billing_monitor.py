#!/usr/bin/env python3
"""
Unified Billing Monitor

Orchestrates data enrichment from metrics and API into the Pod registry.

Data flow:
1. Process metrics timeline (our tracking)
2. Fetch current pods from API
3. Update cost cache
4. Enrich Pod objects
5. Save Pod registry to disk
"""

import os
from typing import Dict, Any, List
from pathlib import Path

from .pod import Pod, PodRegistry
from .pod_cost_cache import PodCostCache
from .metrics_timeline_builder import MetricsTimelineBuilder


class UnifiedBillingMonitor:
    """
    Unified billing monitor that enriches pods from metrics and API.

    Maintains a single source of truth (PodRegistry) enriched from:
    - Metrics timeline (our own tracking - ONLY reliable source)
    - GraphQL API (current state)
    - Cost cache (pricing)
    """

    def __init__(self, data_dir: str = "./data", api_key: str = None):
        """
        Initialize unified billing monitor.

        Args:
            data_dir: Directory for data files
            api_key: RunPod API key
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.api_key = api_key or os.getenv('RUNPOD_API_KEY')
        if not self.api_key:
            raise ValueError("RunPod API key required")

        self.graphql_url = "https://api.runpod.io/graphql"

        # Initialize components
        print("\n🚀 Initializing Unified Billing Monitor...")

        self.pod_registry = PodRegistry(cache_file=str(self.data_dir / "pod_registry.jsonl"))
        self.cost_cache = PodCostCache(data_dir=str(self.data_dir))
        self.metrics_builder = MetricsTimelineBuilder(metrics_file=str(self.data_dir / "pod_metrics.jsonl"))

        print("✅ Unified Billing Monitor initialized\n")

    def fetch_current_pods_from_api(self) -> List[Dict[str, Any]]:
        """
        Fetch current pods from GraphQL API.

        Returns:
            List of current pod data
        """
        import requests

        query = """
        query GetAllPodsWithMetrics {
          myself {
            pods {
              id
              name
              costPerHr
              desiredStatus
              createdAt
              runtime {
                uptimeInSeconds
                gpus {
                  gpuUtilPercent
                  memoryUtilPercent
                }
              }
            }
          }
        }
        """

        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

        try:
            response = requests.post(
                self.graphql_url,
                headers=headers,
                json={'query': query},
                timeout=30
            )

            response.raise_for_status()
            data = response.json()

            if 'errors' in data:
                print(f"❌ GraphQL errors: {data['errors']}")
                return []

            pods = data.get('data', {}).get('myself', {}).get('pods', [])
            print(f"📊 Fetched {len(pods)} current pods from GraphQL API")
            return pods

        except Exception as e:
            print(f"⚠️ Error fetching pods from API: {e}")
            return []

    def rebuild_registry(self) -> None:
        """
        Rebuild entire pod registry from all sources.

        This is the main orchestration method.
        """
        print("\n" + "="*60)
        print("🔧 REBUILDING POD REGISTRY FROM ALL SOURCES")
        print("="*60 + "\n")

        # Step 1: Process metrics timeline (OUR tracking - ONLY reliable source!)
        print("📊 Step 1: Processing our own metrics data...")
        metrics_pod_ids = self.metrics_builder.get_all_pod_ids()
        for pod_id in metrics_pod_ids:
            timeline = self.metrics_builder.get_pod_timeline(pod_id)
            if timeline:
                pod = self.pod_registry.get_or_create(pod_id)
                pod.enrich_from_metrics(timeline)

        print(f"   ✅ Processed metrics for {len(metrics_pod_ids)} pods")

        # Step 2: Fetch current pods from API
        print("\n🌐 Step 2: Fetching current pods from API...")
        current_pods = self.fetch_current_pods_from_api()
        for api_data in current_pods:
            pod_id = api_data.get('id')
            pod = self.pod_registry.get_or_create(pod_id)
            pod.enrich_from_api(api_data)

        print(f"   ✅ Enriched {len(current_pods)} current pods from API")

        # Step 3: Update cost cache from current pods
        print("\n💵 Step 3: Updating cost cache...")
        self.cost_cache.sync_from_graphql_pods(current_pods)
        cached_costs = self.cost_cache.get_all_cached_costs()

        for pod_id, cost_data in cached_costs.items():
            pod = self.pod_registry.get_or_create(pod_id)
            pod.enrich_from_cost_cache(cost_data)

        print(f"   ✅ Updated cost cache with {len(cached_costs)} pods")

        # Step 4: Finalize all pods
        print("\n🎯 Step 4: Finalizing pod calculations...")
        for pod in self.pod_registry.get_all():
            pod.finalize()

        print(f"   ✅ Finalized {len(self.pod_registry.pods)} total pods")

        # Step 5: Save registry
        print("\n💾 Step 5: Saving pod registry...")
        self.pod_registry.save_to_cache()

        # Print summary
        summary = self.pod_registry.get_summary()
        print("\n" + "="*60)
        print("📊 REGISTRY SUMMARY")
        print("="*60)
        print(f"   Total pods: {summary['total_pods']}")
        print(f"   Total hours: {summary['total_hours']:,.2f}")
        print(f"   Known cost pods: {summary['known_cost_pods']}")
        print(f"   Known cost hours: {summary['known_cost_hours']:,.2f}")
        print(f"   Known cost total: ${summary['known_cost_total']:,.2f}")
        print(f"   Unknown cost pods: {summary['unknown_cost_pods']}")
        print(f"   Unknown cost hours: {summary['unknown_cost_hours']:,.2f}")
        print("="*60 + "\n")

    def get_billing_report(self) -> Dict[str, Any]:
        """
        Get billing report in the format expected by web API.

        Returns:
            Dict with known_cost_pods, unknown_cost_pods, summary
        """
        known_cost_pods = [pod.to_dict() for pod in self.pod_registry.get_known_cost_pods()]
        unknown_cost_pods = [pod.to_dict() for pod in self.pod_registry.get_unknown_cost_pods()]

        # Sort: RUNNING first, then by terminated_at
        def sort_key(pod_dict):
            is_running = pod_dict['status'] == 'RUNNING'
            terminated = pod_dict.get('terminated_at', 'Still Running')
            if terminated == 'Still Running' or terminated is None or terminated == 'N/A':
                term_date = ''
            else:
                term_date = terminated
            return (not is_running, term_date)

        known_cost_pods.sort(key=sort_key, reverse=False)
        unknown_cost_pods.sort(key=sort_key, reverse=False)

        return {
            'known_cost_pods': known_cost_pods,
            'unknown_cost_pods': unknown_cost_pods,
            'summary': self.pod_registry.get_summary()
        }

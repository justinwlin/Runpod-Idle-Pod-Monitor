#!/usr/bin/env python3
"""
Pod - Unified pod billing and lifecycle representation.

Single source of truth for all pod data, enriched from multiple sources:
- Audit logs (lifecycle events, creator info)
- Billing aggregator (historical cost tracking)
- GraphQL API (current state, createdAt)
- Cost cache (pricing info)
"""

import json
from typing import Dict, Any, Optional, List
from datetime import datetime
from pathlib import Path


class Pod:
    """
    Unified pod representation with data from all sources.

    Data sources (in priority order):
    1. Audit logs - most accurate timeline
    2. Billing aggregator - historical tracking
    3. GraphQL API - current state
    4. Cost cache - pricing
    """

    def __init__(self, pod_id: str):
        """Initialize a pod with just its ID."""
        self.pod_id = pod_id

        # Basic metadata
        self.pod_name: Optional[str] = None
        self.status: Optional[str] = None  # RUNNING, TERMINATED, EXITED
        self.created_at: Optional[str] = None
        self.terminated_at: Optional[str] = None
        self.created_by: Optional[str] = None  # Email from audit logs

        # Cost information
        self.cost_per_hr: Optional[float] = None
        self.cost_known: bool = False

        # Runtime tracking
        self.active_hours: float = 0.0
        self.total_cost: Optional[float] = None
        self.sessions: int = 0

        # Data source tracking
        self.has_metrics_data: bool = False  # Our own monitoring data (BEST!)
        self.has_audit_data: bool = False
        self.has_billing_data: bool = False
        self.has_api_data: bool = False
        self.has_cost_data: bool = False

        # Billing method used
        self.billing_method: Optional[str] = None
        self.billing_note: Optional[str] = None

        # Raw data from sources (for debugging)
        self._audit_timeline: Optional[Dict] = None
        self._billing_aggregate: Optional[Dict] = None
        self._api_data: Optional[Dict] = None

    def enrich_from_metrics(self, timeline: Dict[str, Any]) -> None:
        """
        Enrich pod with our own metrics timeline data.

        Metrics provide:
        - Most accurate runtime (we tracked actual RUNNING → STOPPED transitions)
        - Status changes we observed
        - Actual sessions from our monitoring

        ONLY reports what we actually tracked. If there's a gap between createdAt
        and first_seen, we add a warning note but DON'T estimate the gap.

        Args:
            timeline: Timeline dict from MetricsTimelineBuilder
        """
        self._metrics_timeline = timeline

        # Extract timeline data
        active_hours = timeline.get('total_active_seconds', 0) / 3600.0
        sessions = len(timeline.get('sessions', []))
        first_seen = timeline.get('first_seen')

        # Check if there's a gap between createdAt and first_seen
        gap_warning = ""
        if self.created_at and first_seen and sessions > 0:
            try:
                from datetime import timezone

                # Parse both timestamps and make them timezone-aware if needed
                created_str = self.created_at.replace('Z', '+00:00')
                first_seen_str = first_seen.replace('Z', '+00:00')

                created_dt = datetime.fromisoformat(created_str)
                first_seen_dt = datetime.fromisoformat(first_seen_str)

                # Ensure both are timezone-aware (use UTC if naive)
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=timezone.utc)
                if first_seen_dt.tzinfo is None:
                    first_seen_dt = first_seen_dt.replace(tzinfo=timezone.utc)

                gap_hours = (first_seen_dt - created_dt).total_seconds() / 3600.0
                gap_days = gap_hours / 24.0

                # If gap is >1 day, warn about potential missing runtime
                if gap_days > 1:
                    gap_warning = (
                        f' ⚠️ Note: Pod was created {gap_days:.1f} days ({gap_hours:.1f} hours) '
                        f'before we started tracking. Actual cost may be higher.'
                    )
            except Exception as e:
                print(f"⚠️ Error calculating gap for {self.pod_id}: {e}")

        # Use metrics if we actually tracked sessions
        if sessions > 0 and active_hours > 0:
            self.has_metrics_data = True
            self.active_hours = active_hours
            self.sessions = sessions
            self.billing_method = 'metrics_tracked'
            self.billing_note = (
                f'Tracked {sessions} session(s) totaling {active_hours:.2f} hours. '
                f'We monitored actual RUNNING → STOPPED transitions.{gap_warning}'
            )
        else:
            # We monitored this pod but saw 0 RUNNING sessions
            # Mark has_metrics_data=True so we DON'T trust old billing data
            sample_count = timeline.get('sample_count', 0)
            if sample_count > 0:
                self.has_metrics_data = True
                # Don't set active_hours or billing_method - let it fall through to unknown

        # Always use status from metrics if available
        last_status = timeline.get('last_status')
        if last_status:
            self.status = last_status

        # Check if still running
        timeline_sessions = timeline.get('sessions', [])
        if timeline_sessions and timeline_sessions[-1].get('still_running'):
            self.status = 'RUNNING'
            self.terminated_at = 'Still Running'
        elif last_status in ['EXITED', 'TERMINATED', 'STOPPED']:
            self.status = last_status
            # Use last seen time as termination time
            self.terminated_at = timeline.get('last_seen')

    def enrich_from_api(self, api_data: Dict[str, Any]) -> None:
        """
        Enrich pod with GraphQL API data.

        API provides:
        - Current state
        - Pod name
        - Created time
        - Cost per hour

        Args:
            api_data: Pod data from GraphQL API
        """
        self.has_api_data = True
        self._api_data = api_data

        # Basic info (only if not already set)
        if not self.pod_name:
            self.pod_name = api_data.get('name', self.pod_id)

        if not self.created_at:
            self.created_at = api_data.get('createdAt')

        # IMPORTANT: API status should override if pod is EXITED/TERMINATED
        # (createdAt calculation might have set it to RUNNING incorrectly)
        api_status = api_data.get('desiredStatus', 'UNKNOWN')
        if api_status in ['EXITED', 'TERMINATED', 'STOPPED']:
            self.status = api_status
            # Mark as terminated if not already set
            if not self.terminated_at or self.terminated_at == 'Still Running':
                self.terminated_at = 'Terminated (exact time unknown)'
        elif not self.status:
            self.status = api_status

        # Cost information
        if not self.cost_per_hr:
            self.cost_per_hr = api_data.get('costPerHr', 0)

        # Priority fallback for pods without metrics OR audit data:
        # 1. Try createdAt calculation (simple time math)
        # 2. Only use uptimeInSeconds as LAST resort
        if not self.has_metrics_data and not self.has_audit_data:
            # Try createdAt first
            if self.created_at and not hasattr(self, '_used_created_time'):
                try:
                    import time
                    created_dt = datetime.fromisoformat(self.created_at.replace('Z', '+00:00'))
                    self.active_hours = (time.time() - created_dt.timestamp()) / 3600.0
                    self.sessions = 1
                    self.status = 'RUNNING'
                    self.billing_method = 'created_time'
                    self.billing_note = (
                        f'Estimated by calculating time since pod was created ({self.created_at}): {self.active_hours:.2f} hours × ${self.cost_per_hr:.4f}/hr. '
                        f'⚠️ WARNING: This assumes the pod ran continuously without pausing. '
                        f'If you paused/stopped the pod at any point (paused pods don\'t incur charges), the actual cost will be lower.'
                    )
                    self._used_created_time = True
                except Exception as e:
                    print(f"⚠️ Error calculating hours for {self.pod_id}: {e}")

    def enrich_from_cost_cache(self, cost_data: Dict[str, Any]) -> None:
        """
        Enrich pod with cost cache data.

        Cost cache provides:
        - Cost per hour
        - Pod name

        Args:
            cost_data: Cost cache entry
        """
        self.has_cost_data = True

        # Only set if not already set
        if not self.cost_per_hr:
            self.cost_per_hr = cost_data.get('cost_per_hr', 0)

        if not self.pod_name:
            self.pod_name = cost_data.get('pod_name', self.pod_id)

    def finalize(self) -> None:
        """
        Finalize pod data after all enrichment.

        Calculates derived fields like cost_known and total_cost.

        Priority order for billing calculation:
        1. Our metrics (if we tracked sessions) - ONLY reliable source
        2. createdAt time (estimate for currently RUNNING pods)

        We NO LONGER use audit logs or billing history as they are unreliable.
        """
        # No fallback to billing history - we only trust what we tracked
        # If we don't have metrics, pod will be marked as unknown cost

        # Determine if cost is known
        self.cost_known = (
            self.cost_per_hr is not None and
            self.cost_per_hr > 0 and
            self.active_hours > 0
        )

        # Calculate total cost
        if self.cost_known:
            self.total_cost = self.cost_per_hr * self.active_hours

        # Set defaults for missing fields
        if not self.pod_name:
            self.pod_name = self.pod_id

        if not self.status:
            self.status = 'UNKNOWN'

        if not self.terminated_at and self.status == 'RUNNING':
            self.terminated_at = 'Still Running'

        if not self.created_by:
            self.created_by = 'N/A'

        if not self.billing_method:
            self.billing_method = 'unknown'
            self.billing_note = 'No billing data available'

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert pod to dictionary for JSON/CSV export.

        Returns:
            Dictionary representation
        """
        return {
            'pod_id': self.pod_id,
            'pod_name': self.pod_name,
            'status': self.status,
            'cost_per_hr': self.cost_per_hr,
            'cost_per_hr_display': f"${self.cost_per_hr:.4f}" if self.cost_known else "UNKNOWN",
            'active_hours': self.active_hours,
            'total_cost': self.total_cost,
            'total_cost_display': f"${self.total_cost:.2f}" if self.cost_known else "UNKNOWN",
            'cost_known': self.cost_known,
            'sessions': self.sessions,
            'created_at': self.created_at or 'N/A',
            'created_by': self.created_by,
            'terminated_at': self.terminated_at,
            'billing_method': self.billing_method,
            'billing_note': self.billing_note
        }

    def to_json(self) -> str:
        """Convert pod to JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Pod':
        """
        Create pod from dictionary.

        Args:
            data: Dictionary representation

        Returns:
            Pod instance
        """
        pod = cls(data['pod_id'])
        pod.pod_name = data.get('pod_name')
        pod.status = data.get('status')
        pod.cost_per_hr = data.get('cost_per_hr')
        # Don't load runtime/billing data from cache - these are recalculated during enrichment:
        # - active_hours, sessions, billing_method, billing_note (from enrichment)
        # - total_cost, cost_known (from finalize())
        pod.created_at = data.get('created_at')
        pod.created_by = data.get('created_by')
        pod.terminated_at = data.get('terminated_at')
        return pod

    @classmethod
    def from_json(cls, json_str: str) -> 'Pod':
        """Create pod from JSON string."""
        return cls.from_dict(json.loads(json_str))

    def __repr__(self) -> str:
        """String representation."""
        return f"Pod(id={self.pod_id}, name={self.pod_name}, status={self.status}, cost_known={self.cost_known})"


class PodRegistry:
    """
    Registry of all pods, backed by disk cache.

    Maintains a unified view of all pods from all sources.
    """

    def __init__(self, cache_file: str = "./data/pod_registry.jsonl"):
        """
        Initialize pod registry.

        Args:
            cache_file: Path to cache file
        """
        self.cache_file = Path(cache_file)
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)

        # In-memory registry: {pod_id: Pod}
        self.pods: Dict[str, Pod] = {}

        # Load from cache
        self.load_from_cache()

    def get_or_create(self, pod_id: str) -> Pod:
        """
        Get existing pod or create new one.

        Args:
            pod_id: Pod ID

        Returns:
            Pod instance
        """
        if pod_id not in self.pods:
            self.pods[pod_id] = Pod(pod_id)
        return self.pods[pod_id]

    def get(self, pod_id: str) -> Optional[Pod]:
        """Get pod by ID."""
        return self.pods.get(pod_id)

    def get_all(self) -> List[Pod]:
        """Get all pods."""
        return list(self.pods.values())

    def save_to_cache(self) -> None:
        """Save all pods to cache file."""
        try:
            # Write all pods atomically
            temp_file = self.cache_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                for pod in self.pods.values():
                    f.write(pod.to_json() + '\n')

            # Atomic rename
            temp_file.replace(self.cache_file)
            print(f"💾 Saved {len(self.pods)} pods to cache: {self.cache_file}")

        except Exception as e:
            print(f"⚠️ Error saving pod registry: {e}")

    def load_from_cache(self) -> None:
        """Load pods from cache file."""
        if not self.cache_file.exists():
            print(f"📊 No pod registry cache found - starting fresh")
            return

        try:
            with open(self.cache_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    pod = Pod.from_json(line)
                    self.pods[pod.pod_id] = pod

            print(f"📊 Loaded {len(self.pods)} pods from cache: {self.cache_file}")

        except Exception as e:
            print(f"⚠️ Error loading pod registry: {e}")
            self.pods = {}

    def get_known_cost_pods(self) -> List[Pod]:
        """Get all pods with known costs."""
        return [pod for pod in self.pods.values() if pod.cost_known]

    def get_unknown_cost_pods(self) -> List[Pod]:
        """Get all pods with unknown costs."""
        return [pod for pod in self.pods.values() if not pod.cost_known]

    def get_running_pods(self) -> List[Pod]:
        """Get all running pods."""
        return [pod for pod in self.pods.values() if pod.status == 'RUNNING']

    def get_terminated_pods(self) -> List[Pod]:
        """Get all terminated pods."""
        return [pod for pod in self.pods.values() if pod.status == 'TERMINATED']

    def get_summary(self) -> Dict[str, Any]:
        """
        Get summary statistics.

        Returns:
            Summary dict
        """
        known_cost_pods = self.get_known_cost_pods()
        unknown_cost_pods = self.get_unknown_cost_pods()

        total_hours = sum(pod.active_hours for pod in self.pods.values())
        known_cost_hours = sum(pod.active_hours for pod in known_cost_pods)
        known_cost_total = sum(pod.total_cost for pod in known_cost_pods if pod.total_cost)
        unknown_cost_hours = sum(pod.active_hours for pod in unknown_cost_pods)

        return {
            'total_pods': len(self.pods),
            'total_hours': total_hours,
            'known_cost_pods': len(known_cost_pods),
            'known_cost_hours': known_cost_hours,
            'known_cost_total': known_cost_total,
            'unknown_cost_pods': len(unknown_cost_pods),
            'unknown_cost_hours': unknown_cost_hours
        }

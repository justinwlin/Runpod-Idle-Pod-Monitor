#!/usr/bin/env python3
"""
Metrics Timeline Builder

Builds pod timelines from pod_metrics.jsonl (our own monitoring data).
This is the MOST reliable source since we track actual status transitions.
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime


class MetricsTimelineBuilder:
    """
    Build pod timelines from metrics data.

    Uses pod_metrics.jsonl to detect:
    - When pods were RUNNING vs EXITED/STOPPED
    - Actual runtime periods (start → stop transitions)
    - Status changes over time
    """

    def __init__(self, metrics_file: str = "./data/pod_metrics.jsonl"):
        """
        Initialize metrics timeline builder.

        Args:
            metrics_file: Path to pod metrics JSONL file
        """
        self.metrics_file = Path(metrics_file)

    def get_pod_timeline(self, pod_id: str) -> Optional[Dict[str, Any]]:
        """
        Build timeline for a specific pod from metrics.

        Args:
            pod_id: Pod ID

        Returns:
            Timeline dict with sessions and total runtime, or None if no metrics
        """
        if not self.metrics_file.exists():
            return None

        # Collect all metrics for this pod
        metrics = []
        try:
            with open(self.metrics_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                        if data.get('pod_id') == pod_id:
                            metrics.append(data)
                    except json.JSONDecodeError:
                        continue

        except Exception as e:
            print(f"⚠️ Error reading metrics for {pod_id}: {e}")
            return None

        if not metrics:
            return None

        # Sort by timestamp
        metrics.sort(key=lambda m: m.get('timestamp', ''))

        # Build timeline from status transitions
        timeline = {
            'pod_id': pod_id,
            'first_seen': metrics[0].get('timestamp'),
            'last_seen': metrics[-1].get('timestamp'),
            'last_status': metrics[-1].get('status'),
            'sessions': [],
            'total_active_seconds': 0,
            'sample_count': len(metrics)
        }

        # Track running sessions
        current_session_start = None
        last_status = None

        for metric in metrics:
            status = metric.get('status')
            timestamp = metric.get('timestamp')

            # Detect status transitions
            if status == 'RUNNING':
                if last_status != 'RUNNING':
                    # Transition to RUNNING - start new session
                    current_session_start = timestamp
            else:  # EXITED, STOPPED, TERMINATED, etc.
                if last_status == 'RUNNING' and current_session_start:
                    # Transition from RUNNING to stopped - end session
                    try:
                        start_dt = datetime.fromisoformat(current_session_start.replace('Z', '+00:00'))
                        end_dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        duration_seconds = (end_dt - start_dt).total_seconds()

                        timeline['sessions'].append({
                            'start': current_session_start,
                            'end': timestamp,
                            'duration_seconds': duration_seconds
                        })
                        timeline['total_active_seconds'] += duration_seconds
                    except Exception as e:
                        print(f"⚠️ Error calculating session duration: {e}")

                    current_session_start = None

            last_status = status

        # If still running at end, session extends to last sample
        if current_session_start and last_status == 'RUNNING':
            try:
                start_dt = datetime.fromisoformat(current_session_start.replace('Z', '+00:00'))
                end_dt = datetime.fromisoformat(metrics[-1]['timestamp'].replace('Z', '+00:00'))
                duration_seconds = (end_dt - start_dt).total_seconds()

                timeline['sessions'].append({
                    'start': current_session_start,
                    'end': metrics[-1]['timestamp'],
                    'duration_seconds': duration_seconds,
                    'still_running': True
                })
                timeline['total_active_seconds'] += duration_seconds
            except Exception as e:
                print(f"⚠️ Error calculating final session: {e}")

        return timeline

    def get_all_pod_ids(self) -> List[str]:
        """
        Get list of all pod IDs in metrics file.

        Returns:
            List of unique pod IDs
        """
        if not self.metrics_file.exists():
            return []

        pod_ids = set()
        try:
            with open(self.metrics_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                        pod_id = data.get('pod_id')
                        if pod_id:
                            pod_ids.add(pod_id)
                    except json.JSONDecodeError:
                        continue

        except Exception as e:
            print(f"⚠️ Error reading metrics file: {e}")

        return list(pod_ids)

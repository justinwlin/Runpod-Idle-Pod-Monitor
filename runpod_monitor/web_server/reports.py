#!/usr/bin/env python3
"""
Reports module for billing and cost tracking.
Displays pod billing information from the billing aggregator.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime
import csv
import io
import os

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def get_unified_monitor():
    """
    Get the unified billing monitor instance.

    Returns:
        UnifiedBillingMonitor instance
    """
    try:
        from ..unified_billing_monitor import UnifiedBillingMonitor

        api_key = os.getenv('RUNPOD_API_KEY')
        if not api_key:
            print("⚠️ RUNPOD_API_KEY not set - cannot create unified monitor")
            return None

        return UnifiedBillingMonitor(data_dir="./data", api_key=api_key)
    except Exception as e:
        print(f"⚠️ Error creating unified monitor: {e}")
        import traceback
        traceback.print_exc()
        return None


@router.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request):
    """
    Reports page showing billing information for all pods.

    Args:
        request: FastAPI request object

    Returns:
        HTML response with billing reports
    """
    return templates.TemplateResponse("reports.html", {
        "request": request
    })


@router.get("/api/reports/billing-audit", response_class=JSONResponse)
async def get_audit_billing_data():
    """
    API endpoint to get unified billing data for all pods.

    Returns:
        JSON response with pod billing information from all sources
    """
    unified_monitor = get_unified_monitor()

    if not unified_monitor:
        return JSONResponse({
            "error": "Unified monitor not available",
            "known_cost_pods": [],
            "unknown_cost_pods": [],
            "summary": {
                'total_pods': 0,
                'total_hours': 0,
                'known_cost_total': 0,
                'known_cost_pods': 0,
                'unknown_cost_pods': 0
            }
        })

    try:
        # Rebuild pod registry from all sources (incremental)
        unified_monitor.rebuild_registry()

        # Get billing report (already sorted and structured)
        report = unified_monitor.get_billing_report()

        return JSONResponse(report)

    except Exception as e:
        print(f"⚠️ Error getting audit billing data: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "error": str(e),
            "pods": []
        })


@router.get("/api/reports/download-csv-audit")
async def download_audit_billing_csv():
    """
    Download unified billing data as CSV file.

    Returns:
        CSV file with pod billing information from all sources
    """
    try:
        unified_monitor = get_unified_monitor()

        if not unified_monitor:
            return JSONResponse({
                "error": "Unified monitor not available"
            }, status_code=500)

        # Rebuild registry
        unified_monitor.rebuild_registry()

        # Get billing data
        billing_data = unified_monitor.get_billing_report()

        # Create CSV in memory
        output = io.StringIO()
        writer = csv.writer(output)

        # Write header
        writer.writerow([
            'Pod ID',
            'Pod Name',
            'Status',
            'Cost/Hr',
            'Active Hours',
            'Total Cost',
            'Sessions',
            'Billing Method',
            'Created At',
            'Created By',
            'Terminated At',
            'Billing Note'
        ])

        # Combine known and unknown pods (already sorted)
        all_pods = billing_data['known_cost_pods'] + billing_data['unknown_cost_pods']

        for pod in all_pods:
            writer.writerow([
                pod['pod_id'],
                pod['pod_name'],
                pod['status'],
                pod['cost_per_hr_display'],
                f"{pod['active_hours']:.4f}",
                pod['total_cost_display'],
                pod['sessions'],
                pod['billing_method'],
                pod['created_at'] or 'N/A',
                pod.get('created_by', 'N/A'),
                pod['terminated_at'],
                pod['billing_note']
            ])

        # Prepare CSV for download
        output.seek(0)

        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"runpod_audit_billing_{timestamp}.csv"

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )

    except Exception as e:
        print(f"⚠️ Error generating audit CSV: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "error": str(e)
        }, status_code=500)


@router.get("/api/reports/billing-json-audit")
async def get_audit_billing_json():
    """
    Get raw unified billing data as JSON for external processing.

    Returns:
        JSON with all billing data from all sources
    """
    try:
        unified_monitor = get_unified_monitor()

        if not unified_monitor:
            return JSONResponse({
                "error": "Unified monitor not available"
            }, status_code=500)

        # Rebuild registry
        unified_monitor.rebuild_registry()

        # Get billing data
        billing_data = unified_monitor.get_billing_report()

        # Combine pods for backward compatibility
        all_pods = billing_data['known_cost_pods'] + billing_data['unknown_cost_pods']

        return JSONResponse({
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "pod_count": len(all_pods),
            "summary": billing_data['summary'],
            "pods": all_pods,
            "known_cost_pods": billing_data['known_cost_pods'],
            "unknown_cost_pods": billing_data['unknown_cost_pods']
        })

    except Exception as e:
        print(f"⚠️ Error getting audit billing JSON: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "error": str(e)
        }, status_code=500)

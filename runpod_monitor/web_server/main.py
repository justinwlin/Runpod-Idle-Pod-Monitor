#!/usr/bin/env python3
"""
Main web server module for RunPod Monitor.
Orchestrates all sub-modules and initializes the FastAPI application.
"""

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os

# Import routers from sub-modules
from .pod_management import router as pod_router
from .config_management import router as config_router, start_monitoring_background
from .monitoring import router as monitoring_router
from .metrics import router as metrics_router

# Import shared utilities
from .helpers import get_current_config

# Initialize FastAPI app
app = FastAPI(
    title="RunPod Monitor", 
    description="Monitor and manage your RunPod instances",
    version="2.0.0"
)

# Setup templates
templates = Jinja2Templates(directory="templates")

# Mount static files if directory exists
static_dir = "static"
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Include all routers
app.include_router(pod_router)
app.include_router(config_router)
app.include_router(monitoring_router)
app.include_router(metrics_router)

# Health check endpoint for Docker
@app.get("/status")
async def health_check():
    """Simple health check endpoint for Docker health checks."""
    return JSONResponse({"status": "healthy", "service": "RunPod Monitor"})


# Initialize configuration and data tracker when server starts
def initialize_server():
    """
    Initialize server configuration and data tracker on startup.
    Loads configuration from file and sets up the data tracker.
    """
    try:
        from ..main import load_config, config, data_tracker as main_data_tracker, DataTracker
    except ImportError:
        from runpod_monitor.main import load_config, config, data_tracker as main_data_tracker, DataTracker
    
    # Use current working directory for config path
    config_path = 'config.yaml'
    print(f"🔍 Web server loading config from: {os.path.abspath(config_path)}")
    load_config(config_path)
    print(f"📋 Config after loading: auto_stop.enabled = {config.get('auto_stop', {}).get('enabled', 'NOT_SET') if config else 'CONFIG_IS_NONE'}")
    
    # Initialize data tracker if not already done
    global data_tracker
    data_tracker = main_data_tracker
    
    if data_tracker is None:
        storage_config = config.get('storage', {}) if config else {}
        data_tracker = DataTracker(
            data_dir=storage_config.get('data_dir', './data'),
            metrics_file=storage_config.get('metrics_file', 'pod_metrics.jsonl')
        )
        print("📊 Data tracker initialized")


# Don't initialize on import - let startup event handle it
# initialize_server() - REMOVED to prevent blocking imports


@app.on_event("startup")
async def startup_event():
    """
    Startup event handler for the FastAPI application.
    Starts background monitoring if configured.
    """
    import asyncio
    import threading
    
    print("🔄 Server startup: initializing in background...")
    
    def background_init():
        """Run heavy initialization in background thread."""
        try:
            # Initialize server config and data tracker
            initialize_server()
            
            # Get config and start monitoring
            config = get_current_config()
            if config:
                auto_stop_enabled = config.get('auto_stop', {}).get('enabled', False)
                print(f"   Auto-stop enabled: {auto_stop_enabled}")
                print(f"   Config loaded: {bool(config)}")
                
                # Start monitoring if configured
                start_monitoring_background()
            else:
                print("   No configuration found")
        except Exception as e:
            print(f"❌ Background initialization error: {e}")
    
    # Start initialization in background thread to not block server startup
    init_thread = threading.Thread(target=background_init, daemon=True)
    init_thread.start()
    print("✅ Server started - initialization running in background")


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """
    Main dashboard page endpoint.
    Shows the main interface with pod status and controls.
    
    Args:
        request: FastAPI request object
        
    Returns:
        HTML response with rendered dashboard
    """
    # Check if API key is configured
    current_config = get_current_config()
    
    api_key_missing = False
    if not current_config or not current_config.get('api', {}).get('key') or current_config.get('api', {}).get('key') in ['YOUR_RUNPOD_API_KEY_HERE', '', None]:
        api_key_missing = True
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "api_key_missing": api_key_missing
    })


def run_server(host: str = "0.0.0.0", port: int = 8080):
    """
    Run the web server using uvicorn.
    
    Args:
        host: Host address to bind to (default 0.0.0.0)
        port: Port number to listen on (default 8080)
    """
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
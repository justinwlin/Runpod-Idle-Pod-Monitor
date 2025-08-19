#!/usr/bin/env python3
"""
Web server entry point for RunPod Monitor.
This file now imports from the modularized web_server package.
"""

# Import the app from the new modular structure
from runpod_monitor.web_server import app

# For backwards compatibility, expose the run function
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
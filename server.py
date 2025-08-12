#!/usr/bin/env python3
"""
RunPod Monitor Server
Simple entry point to start the web interface with integrated monitoring.
"""

import uvicorn
from runpod_monitor.web_server import app

if __name__ == "__main__":
    print("🚀 Starting RunPod Monitor Server...")
    print("📊 Web interface: http://localhost:8080")
    print("🔄 Background monitoring: Auto-enabled if configured")
    print("⏹️  Press Ctrl+C to stop")
    
    uvicorn.run(app, host="0.0.0.0", port=8080)
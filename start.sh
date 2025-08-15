#!/bin/bash
set -e

# Ensure workspace directories exist
mkdir -p /workspace/data /workspace/config

# Copy config template to workspace if it doesn't exist
if [ ! -f /workspace/config/config.yaml ]; then
    echo "Creating config.yaml in workspace from template..."
    cp /app/config.yaml.template /workspace/config/config.yaml
fi

# Create symlink to config in workspace
ln -sf /workspace/config/config.yaml /app/config.yaml

# Start RunPod Monitor
echo "Starting RunPod Monitor on port 8080..."
exec python server.py
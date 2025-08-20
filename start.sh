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

# Configure SSH password from environment variable
echo "Setting SSH password..."
echo "root:${SSH_PASSWORD}" | chpasswd
echo "SSH password set to: ${SSH_PASSWORD}"

# Start SSH service
echo "Starting SSH service..."
service ssh start

# Display SSH connection information
echo "=========================================="
echo "🔐 SSH ACCESS ENABLED"
echo "=========================================="
echo "SSH Connection Command:"
echo "  ssh root@<your-host-ip> -p <ssh-port>"
echo ""
echo "For RunPod users:"
echo "  ssh root@\$RUNPOD_PUBLIC_IP -p \$RUNPOD_TCP_PORT_22"
echo ""
echo "Default password: ${SSH_PASSWORD}"
echo "=========================================="

# Start RunPod Monitor
echo "Starting RunPod Monitor on port 8080..."
exec python server.py
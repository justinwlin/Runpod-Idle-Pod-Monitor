#!/bin/bash

# RunPod Self-Monitor Quick Installer
# One-liner installer that sets up tmux and runs the monitor in background

echo "🚀 RunPod Self-Monitor Quick Setup"

# Install tmux if not present
if ! command -v tmux &> /dev/null; then
    echo "📦 Installing tmux..."
    apt-get update && apt-get install -y tmux || yum install -y tmux || apk add --no-cache tmux
fi

# Download the monitor script
echo "📥 Downloading monitor script..."
curl -sSL https://raw.githubusercontent.com/justinwlin/Runpod-Idle-Pod-Monitor/refs/heads/main/self-contained/self_monitor_portable.sh -o /tmp/self_monitor.sh

# Make it executable
chmod +x /tmp/self_monitor.sh

# Create or attach to tmux session
SESSION_NAME="runpod-monitor"

echo ""
echo "🖥️  Starting monitor in tmux session: $SESSION_NAME"
echo ""

# Check if session already exists
if tmux has-session -t $SESSION_NAME 2>/dev/null; then
    echo "⚠️  Session already exists. Attaching..."
    echo ""
    echo "📋 Tmux commands:"
    echo "  • Detach: Press Ctrl+B then D"
    echo "  • Scroll: Press Ctrl+B then ["
    echo "  • Exit scroll: Press Q"
    echo ""
    sleep 2
    tmux attach-session -t $SESSION_NAME
else
    # Create new session and run the script
    echo "📋 Creating new tmux session..."
    echo ""
    echo "========================================="
    echo "📌 IMPORTANT TMUX COMMANDS:"
    echo "========================================="
    echo "  • DETACH (leave running): Ctrl+B then D"
    echo "  • View later: tmux attach -t $SESSION_NAME"
    echo "  • List sessions: tmux ls"
    echo "  • Kill session: tmux kill-session -t $SESSION_NAME"
    echo "========================================="
    echo ""
    echo "Starting monitor in 3 seconds..."
    sleep 3
    
    tmux new-session -d -s $SESSION_NAME "/tmp/self_monitor.sh"
    tmux attach-session -t $SESSION_NAME
fi
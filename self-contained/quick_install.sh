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

# Download help instructions
echo "📖 Downloading help instructions..."
curl -sSL https://raw.githubusercontent.com/justinwlin/Runpod-Idle-Pod-Monitor/refs/heads/main/self-contained/TMUX_HELP.md -o /tmp/TMUX_HELP.md 2>/dev/null || true

# Create or attach to tmux session
SESSION_NAME="monitor"

echo ""
echo "🖥️  Managing tmux session: $SESSION_NAME"
echo ""

# Check if session already exists
if tmux has-session -t $SESSION_NAME 2>/dev/null; then
    echo "⚠️  Session '$SESSION_NAME' already exists!"
    echo ""
    echo "Options:"
    echo "  1) Attach to existing session"
    echo "  2) Kill and restart with fresh session"
    echo "  3) Cancel"
    echo ""
    read -p "Choose (1/2/3): " choice
    
    case $choice in
        1)
            echo "📎 Attaching to existing session..."
            echo ""
            echo "========================================="
            echo "📌 TMUX COMMANDS REMINDER:"
            echo "========================================="
            echo "  • DETACH (leave running): Ctrl+B then D"
            echo "  • SCROLL UP/DOWN: Ctrl+B then ["
            echo "  • EXIT SCROLL MODE: Q"
            echo "  • STOP MONITOR: Ctrl+C"
            echo "========================================="
            echo ""
            sleep 2
            tmux attach-session -t $SESSION_NAME
            ;;
        2)
            echo "🔄 Restarting monitor..."
            tmux kill-session -t $SESSION_NAME 2>/dev/null
            
            # Show help file if it exists
            if [ -f "/tmp/TMUX_HELP.md" ]; then
                echo ""
                cat /tmp/TMUX_HELP.md
                echo ""
                echo "Press Enter to continue..."
                read -r
            else
                echo ""
                echo "========================================="
                echo "📌 IMPORTANT TMUX COMMANDS:"
                echo "========================================="
                echo "  • DETACH (leave running): Ctrl+B then D"
                echo "  • REATTACH LATER: tmux attach -t $SESSION_NAME"
                echo "  • LIST SESSIONS: tmux ls"
                echo "  • KILL SESSION: tmux kill-session -t $SESSION_NAME"
                echo "  • SCROLL UP/DOWN: Ctrl+B then [ (Q to exit)"
                echo "========================================="
                echo ""
                echo "Starting monitor in 3 seconds..."
                sleep 3
            fi
            
            tmux new-session -d -s $SESSION_NAME "/tmp/self_monitor.sh"
            tmux attach-session -t $SESSION_NAME
            ;;
        *)
            echo "❌ Cancelled"
            exit 0
            ;;
    esac
else
    # Create new session and run the script
    echo "📋 Creating new tmux session..."
    
    # Show help file if it exists
    if [ -f "/tmp/TMUX_HELP.md" ]; then
        echo ""
        cat /tmp/TMUX_HELP.md
        echo ""
        echo "Press Enter to continue..."
        read -r
    else
        echo ""
        echo "========================================="
        echo "📌 IMPORTANT TMUX COMMANDS:"
        echo "========================================="
        echo "  • DETACH (leave running): Ctrl+B then D"
        echo "  • REATTACH LATER: tmux attach -t $SESSION_NAME"
        echo "  • LIST SESSIONS: tmux ls"
        echo "  • KILL SESSION: tmux kill-session -t $SESSION_NAME"
        echo "  • SCROLL UP/DOWN: Ctrl+B then [ (Q to exit)"
        echo "========================================="
        echo ""
        echo "Starting monitor in 3 seconds..."
        sleep 3
    fi
    
    tmux new-session -d -s $SESSION_NAME "/tmp/self_monitor.sh"
    tmux attach-session -t $SESSION_NAME
fi
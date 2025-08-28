#!/bin/bash

# RunPod Self-Monitor Script - Portable Version
# Self-contained script with auto-setup capabilities

set -e

# Colors for output (with terminal detection)
if [ -t 1 ] && [ -n "${TERM}" ] && [ "${TERM}" != "dumb" ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    NC='\033[0m' # No Color
else
    # No color support
    RED=''
    GREEN=''
    YELLOW=''
    BLUE=''
    NC=''
fi

printf "${BLUE}🚀 RunPod Self-Monitor Setup (Portable Version)${NC}\n"
echo ""

# Check if running in tmux and show commands
if [ -n "$TMUX" ]; then
    printf "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
    printf "${YELLOW}📌 TMUX SESSION DETECTED - Quick Commands:${NC}\n"
    echo ""
    printf "  ${BLUE}•${NC} DETACH (leave running): ${GREEN}Ctrl+B then D${NC}\n"
    printf "  ${BLUE}•${NC} Scroll up/down: ${GREEN}Ctrl+B then [${NC} (use arrows, ${GREEN}Q${NC} to exit)\n"
    printf "  ${BLUE}•${NC} Stop monitor: ${GREEN}Ctrl+C${NC}\n"
    printf "  ${BLUE}•${NC} Reattach later: ${GREEN}tmux attach -t monitor${NC}\n"
    echo ""
fi

printf "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
printf "${YELLOW}📖 HOW THIS SCRIPT WORKS:${NC}\n"
echo ""
echo "This script monitors your RunPod pod's resource usage and can automatically"
echo "stop it when idle to save money. Here's what it does:"
echo ""
printf "1. ${BLUE}Monitors 3 metrics every minute:${NC}\n"
echo "   • CPU Usage (%)"
echo "   • Memory Usage (%)"
echo "   • GPU Usage (%)"
echo ""
printf "2. ${BLUE}You set thresholds for each metric:${NC}\n"
echo "   For example: CPU < 20%, Memory < 30%, GPU < 15%"
echo "   The pod is considered 'idle' when ALL three metrics are below their thresholds"
echo ""
printf "3. ${BLUE}You set a duration (in minutes):${NC}\n"
echo "   How long the pod must remain idle before taking action"
echo "   For example: 30 minutes of continuous idle time"
echo ""
printf "4. ${BLUE}Two modes available:${NC}\n"
printf "   ${YELLOW}Monitor Mode:${NC} Just tracks and alerts (safe for testing)\n"
printf "   ${RED}Auto-Stop Mode:${NC} Actually stops the pod when idle (saves money!)\n"
echo ""
printf "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
echo ""
echo "Press Enter to continue with setup..."
read -r
echo ""

# Function to check and install dependencies
setup_dependencies() {
    printf "${YELLOW}📦 Checking dependencies...${NC}\n"
    
    # Check for Python3
    if ! command -v python3 &> /dev/null; then
        printf "${YELLOW}Python3 not found. Attempting to install...${NC}\n"
        
        # Try different package managers
        if command -v apt-get &> /dev/null; then
            apt-get update && apt-get install -y python3 python3-minimal
        elif command -v yum &> /dev/null; then
            yum install -y python3
        elif command -v apk &> /dev/null; then
            apk add --no-cache python3
        else
            printf "${RED}❌ Could not install Python3. Please install manually.${NC}\n"
            exit 1
        fi
    fi
    
    # Check for curl
    if ! command -v curl &> /dev/null; then
        printf "${YELLOW}curl not found. Attempting to install...${NC}\n"
        
        if command -v apt-get &> /dev/null; then
            apt-get update && apt-get install -y curl
        elif command -v yum &> /dev/null; then
            yum install -y curl
        elif command -v apk &> /dev/null; then
            apk add --no-cache curl
        else
            # Try wget as fallback
            if command -v wget &> /dev/null; then
                printf "${YELLOW}Using wget instead of curl${NC}\n"
                USE_WGET=1
            else
                printf "${RED}❌ Could not install curl or wget. Please install manually.${NC}\n"
                exit 1
            fi
        fi
    fi
    
    printf "${GREEN}✓ All dependencies satisfied${NC}\n"
}

# Run dependency check
setup_dependencies

# Get the directory where the script is located
# When run from /tmp, we want to use the current working directory instead
if [[ "${BASH_SOURCE[0]}" == "/tmp/"* ]]; then
    # Script is in /tmp, use current working directory
    SCRIPT_DIR="$(pwd)"
    printf "${BLUE}📍 Script running from /tmp, using current directory: $SCRIPT_DIR${NC}\n"
else
    # Script is elsewhere, use its actual directory
    SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
    printf "${BLUE}📍 Script directory: $SCRIPT_DIR${NC}\n"
fi

# Download TMUX help file for reference (save in working directory)
HELP_FILE="${SCRIPT_DIR}/TMUX_HELP.md"
printf "${YELLOW}📖 Downloading tmux help guide...${NC}\n"
echo "  Target location: $HELP_FILE"

# Try to download the help file with better error handling
DOWNLOAD_SUCCESS=0
if command -v curl &> /dev/null; then
    if curl -sSL https://raw.githubusercontent.com/justinwlin/Runpod-Idle-Pod-Monitor/refs/heads/main/self-contained/TMUX_HELP.md -o "$HELP_FILE"; then
        DOWNLOAD_SUCCESS=1
    else
        printf "${YELLOW}  Warning: Could not download from GitHub${NC}\n"
    fi
elif command -v wget &> /dev/null; then
    if wget -q https://raw.githubusercontent.com/justinwlin/Runpod-Idle-Pod-Monitor/refs/heads/main/self-contained/TMUX_HELP.md -O "$HELP_FILE"; then
        DOWNLOAD_SUCCESS=1
    else
        printf "${YELLOW}  Warning: Could not download from GitHub${NC}\n"
    fi
fi

# If download failed, create a basic help file
if [ "$DOWNLOAD_SUCCESS" -eq 0 ] || [ ! -f "$HELP_FILE" ]; then
    printf "${YELLOW}  Creating local help file...${NC}\n"
    cat > "$HELP_FILE" << 'EOF'
=========================================
📌 TMUX SESSION MANAGEMENT GUIDE
=========================================

Your monitor is running in tmux session: 'monitor'

🔑 ESSENTIAL COMMANDS:
----------------------
• DETACH (leave running):     Ctrl+B then D
• REATTACH to session:        tmux attach -t monitor
• LIST all sessions:          tmux ls
• KILL the monitor:           tmux kill-session -t monitor

📜 WHILE IN THE SESSION:
------------------------
• SCROLL UP/DOWN:             Ctrl+B then [
  - Use arrow keys or Page Up/Down to scroll
  - Press Q to exit scroll mode
• STOP the monitor:           Ctrl+C
• DETACH and keep running:    Ctrl+B then D

🔄 IF YOU ACCIDENTALLY EXIT:
-----------------------------
1. Check if still running:    tmux ls
2. Reattach to monitor:       tmux attach -t monitor
3. If session is dead, run the installer again

💡 COMMON SCENARIOS:
--------------------
• Lost SSH connection?        Monitor keeps running!
                             Just reattach: tmux attach -t monitor

• Want to check status?       tmux attach -t monitor
                             Then Ctrl+B, D to detach

• Need to restart fresh?      tmux kill-session -t monitor
                             Then run installer again

📊 VIEW MONITOR STATUS FILES:
------------------------------
• Current metrics:            cat ${SCRIPT_DIR}/monitor_counter.json
• Configuration:              cat ${SCRIPT_DIR}/monitor_config.json

=========================================
EOF
fi

if [ -f "$HELP_FILE" ]; then
    printf "${GREEN}✓ Help guide saved successfully!${NC}\n"
    printf "${GREEN}  📁 Location: $HELP_FILE${NC}\n"
    printf "${GREEN}  📖 View it: cat $HELP_FILE${NC}\n"
    # Show file size to confirm it downloaded
    FILE_SIZE=$(wc -c < "$HELP_FILE")
    printf "${GREEN}  📊 Size: $FILE_SIZE bytes${NC}\n"
else
    printf "${RED}❌ ERROR: Could not save help guide${NC}\n"
    printf "${RED}  Expected location: $HELP_FILE${NC}\n"
fi
echo ""

# Check required environment variables
if [ -z "$RUNPOD_API_KEY" ]; then
    printf "${RED}❌ Error: RUNPOD_API_KEY environment variable not set${NC}\n"
    echo "Please set: export RUNPOD_API_KEY=your_api_key_here"
    exit 1
fi

if [ -z "$RUNPOD_POD_ID" ]; then
    printf "${RED}❌ Error: RUNPOD_POD_ID environment variable not set${NC}\n"
    echo "This script must be run inside a RunPod pod"
    exit 1
fi

# Configuration files (stored in working directory) - SCRIPT_DIR already set above
CONFIG_FILE="${SCRIPT_DIR}/monitor_config.json"
COUNTER_FILE="${SCRIPT_DIR}/monitor_counter.json"

# Helper function for JSON operations using pure bash when possible
json_get() {
    local file=$1
    local key=$2
    grep "\"$key\"" "$file" | sed 's/.*"'"$key"'"\s*:\s*\([^,}]*\).*/\1/' | tr -d '"'
}

# Get configuration from user or use existing
if [ -f "$CONFIG_FILE" ]; then
    printf "${GREEN}✓ Found existing configuration${NC}\n"
    cat "$CONFIG_FILE"
    echo ""
    read -p "Use existing configuration? (y/n): " use_existing
    if [ "$use_existing" != "y" ]; then
        rm -f "$CONFIG_FILE"
    fi
fi

if [ ! -f "$CONFIG_FILE" ]; then
    printf "${YELLOW}📝 Configure monitoring thresholds:${NC}\n"
    echo "Set the maximum usage levels that indicate your pod is idle."
    echo ""
    
    # Get CPU threshold
    printf "${BLUE}CPU Threshold:${NC}\n"
    echo "  Pod is idle when CPU usage is BELOW this percentage"
    echo "  Example: 20 means idle when CPU < 20%"
    read -p "  Enter CPU threshold (%, default 20): " cpu_threshold
    cpu_threshold=${cpu_threshold:-20}
    echo ""
    
    # Get Memory threshold
    printf "${BLUE}Memory Threshold:${NC}\n"
    echo "  Pod is idle when Memory usage is BELOW this percentage"
    echo "  Example: 30 means idle when Memory < 30%"
    read -p "  Enter Memory threshold (%, default 30): " memory_threshold
    memory_threshold=${memory_threshold:-30}
    echo ""
    
    # Get GPU threshold
    printf "${BLUE}GPU Threshold:${NC}\n"
    echo "  Pod is idle when GPU usage is BELOW this percentage"
    echo "  Example: 15 means idle when GPU < 15%"
    read -p "  Enter GPU threshold (%, default 15): " gpu_threshold
    gpu_threshold=${gpu_threshold:-15}
    echo ""
    
    # Get duration (in minutes)
    printf "${BLUE}Idle Duration:${NC}\n"
    echo "  How many minutes must the pod remain idle before action is taken"
    echo "  Example: 30 means wait 30 minutes of continuous idle time"
    read -p "  Enter duration (minutes, default 30): " duration_minutes
    duration_minutes=${duration_minutes:-30}
    echo ""
    
    # Monitor-only mode
    printf "${BLUE}Operating Mode:${NC}\n"
    echo "  Monitor Mode (y): Only track and alert, won't stop the pod (safe for testing)"
    echo "  Auto-Stop Mode (n): Actually stop the pod when idle (saves money)"
    read -p "  Use Monitor-only mode? (y/n, default n): " monitor_only
    monitor_only=${monitor_only:-n}
    echo ""
    
    # Save configuration
    cat > "$CONFIG_FILE" <<EOF
{
    "cpu_threshold": $cpu_threshold,
    "memory_threshold": $memory_threshold,
    "gpu_threshold": $gpu_threshold,
    "duration_minutes": $duration_minutes,
    "monitor_only": $([ "$monitor_only" = "y" ] && echo "true" || echo "false"),
    "pod_id": "$RUNPOD_POD_ID"
}
EOF
    printf "${GREEN}✓ Configuration saved${NC}\n"
fi

# Load configuration
CPU_THRESHOLD=$(json_get "$CONFIG_FILE" "cpu_threshold")
MEMORY_THRESHOLD=$(json_get "$CONFIG_FILE" "memory_threshold")
GPU_THRESHOLD=$(json_get "$CONFIG_FILE" "gpu_threshold")
DURATION_MINUTES=$(json_get "$CONFIG_FILE" "duration_minutes")
MONITOR_ONLY=$(json_get "$CONFIG_FILE" "monitor_only")

echo ""
printf "${BLUE}📊 Starting monitoring with settings:${NC}\n"
echo "  CPU Threshold: ${CPU_THRESHOLD}%"
echo "  Memory Threshold: ${MEMORY_THRESHOLD}%"
echo "  GPU Threshold: ${GPU_THRESHOLD}%"
echo "  Duration: ${DURATION_MINUTES} minutes"
echo "  Monitor-only: ${MONITOR_ONLY}"
echo "  Pod ID: ${RUNPOD_POD_ID}"
echo ""

# Explain the mode
if [ "$MONITOR_ONLY" = "true" ]; then
    printf "${YELLOW}🔍 Running in MONITOR MODE:${NC}\n"
    echo "  • Will track when pod usage falls below thresholds"
    echo "  • Will show alerts when idle threshold is met"
    echo "  • Will NOT actually stop the pod (safe for testing)"
    echo "  • Useful for testing your threshold settings"
else
    printf "${RED}⚠️ Running in AUTO-STOP MODE:${NC}\n"
    echo "  • Will track when pod usage falls below ALL thresholds:"
    echo "    - CPU < ${CPU_THRESHOLD}% AND"
    echo "    - Memory < ${MEMORY_THRESHOLD}% AND"
    echo "    - GPU < ${GPU_THRESHOLD}%"
    echo "  • After ${DURATION_MINUTES} consecutive minutes below thresholds:"
    echo "    - Pod WILL BE STOPPED automatically"
    echo "    - Script will exit after stopping"
    echo "  • Make sure your thresholds are appropriate!"
fi
echo ""

# Initialize counter if doesn't exist
if [ ! -f "$COUNTER_FILE" ]; then
    echo '{"consecutive_below": 0, "last_check": 0}' > "$COUNTER_FILE"
fi

# Function to make API calls
api_call() {
    local query=$1
    if [ "$USE_WGET" = "1" ]; then
        wget -q -O - \
            --header="Content-Type: application/json" \
            --header="Authorization: Bearer $RUNPOD_API_KEY" \
            --post-data="{\"query\": \"$query\"}" \
            https://api.runpod.io/graphql
    else
        curl -s -X POST \
            -H "Content-Type: application/json" \
            -H "Authorization: Bearer $RUNPOD_API_KEY" \
            -d "{\"query\": \"$query\"}" \
            https://api.runpod.io/graphql
    fi
}

# Function to get pod metrics
get_pod_metrics() {
    local query='query { myself { pods { id desiredStatus runtime { uptimeInSeconds container { cpuPercent memoryPercent } gpus { gpuUtilPercent memoryUtilPercent } } } } }'
    
    local response=$(api_call "$query")
    
    # Debug: show response if empty
    if [ -z "$response" ]; then
        echo "Empty response from API" >&2
        return
    fi
    
    # Parse JSON using a simple approach
    # Extract the pod data for our pod ID
    local pod_section=$(echo "$response" | grep -o "\"id\":\"$RUNPOD_POD_ID\"[^}]*")
    
    if [ -z "$pod_section" ]; then
        echo "Pod not found in response" >&2
        return
    fi
    
    # Extract metrics using sed/grep
    local cpu=$(echo "$response" | grep -o '"cpuPercent":[0-9.]*' | head -1 | cut -d':' -f2)
    local memory=$(echo "$response" | grep -o '"memoryPercent":[0-9.]*' | head -1 | cut -d':' -f2)
    local gpu=$(echo "$response" | grep -o '"gpuUtilPercent":[0-9.]*' | head -1 | cut -d':' -f2)
    local status=$(echo "$response" | grep -o '"desiredStatus":"[^"]*"' | head -1 | cut -d'"' -f4)
    
    # Default to 0 if not found
    cpu=${cpu:-0}
    memory=${memory:-0}
    gpu=${gpu:-0}
    status=${status:-UNKNOWN}
    
    # Output as simple format
    echo "$cpu|$memory|$gpu|$status"
}

# Function to compare numbers (integer comparison as fallback)
compare_below() {
    local value=$1
    local threshold=$2
    
    # Convert to integers for comparison
    value_int=${value%.*}
    threshold_int=${threshold%.*}
    
    if [ "$value_int" -lt "$threshold_int" ]; then
        echo "true"
    else
        echo "false"
    fi
}

# Function to stop pod
stop_pod() {
    printf "${YELLOW}🛑 Stopping pod...${NC}\n"
    
    local mutation="mutation { podStop(input: {podId: \\\"$RUNPOD_POD_ID\\\"}) { id desiredStatus } }"
    
    api_call "$mutation"
    
    printf "${GREEN}✓ Stop command sent${NC}\n"
}

# Show final instructions before monitoring starts
printf "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
printf "${GREEN}✅ SETUP COMPLETE! Monitor is now running.${NC}\n"
printf "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
echo ""
printf "${YELLOW}📌 You can safely close this tab/window!${NC}\n"
echo "The monitor will continue running in the background."
echo ""
printf "${BLUE}To check on your monitor later:${NC}\n"
echo "  • Reattach: tmux attach -t monitor"
echo "  • Check status: cat ${SCRIPT_DIR}/monitor_counter.json"
if [ -f "${SCRIPT_DIR}/TMUX_HELP.md" ]; then
    echo "  • View help: cat ${SCRIPT_DIR}/TMUX_HELP.md ✅ (File exists!)"
else
    echo "  • View help: cat ${SCRIPT_DIR}/TMUX_HELP.md ⚠️ (File not found)"
fi
echo ""
printf "${YELLOW}If running in tmux, detach now with: Ctrl+B then D${NC}\n"
echo ""
sleep 3

# Main monitoring loop
printf "${GREEN}🔄 Monitoring started (checking every minute)${NC}\n"
echo "Press Ctrl+C to stop monitoring"
echo ""

# Initialize consecutive counter
CONSECUTIVE=0

while true; do
    # Get current metrics
    METRICS=$(get_pod_metrics)
    
    if [ -z "$METRICS" ]; then
        printf "${RED}⚠️ Could not fetch metrics${NC}\n"
        sleep 60
        continue
    fi
    
    # Parse metrics
    IFS='|' read -r CPU MEMORY GPU STATUS <<< "$METRICS"
    
    # Check if below thresholds
    CPU_BELOW=$(compare_below "$CPU" "$CPU_THRESHOLD")
    MEM_BELOW=$(compare_below "$MEMORY" "$MEMORY_THRESHOLD")
    GPU_BELOW=$(compare_below "$GPU" "$GPU_THRESHOLD")
    
    BELOW_THRESHOLD="false"
    if [ "$CPU_BELOW" = "true" ] && [ "$MEM_BELOW" = "true" ] && [ "$GPU_BELOW" = "true" ]; then
        BELOW_THRESHOLD="true"
        CONSECUTIVE=$((CONSECUTIVE + 1))
    else
        CONSECUTIVE=0
    fi
    
    # Update counter file
    TIMESTAMP=$(date +%s)
    cat > "$COUNTER_FILE" <<EOF
{
    "consecutive_below": $CONSECUTIVE,
    "last_check": $TIMESTAMP,
    "last_cpu": $CPU,
    "last_memory": $MEMORY,
    "last_gpu": $GPU,
    "status": "$STATUS"
}
EOF
    
    # Display status
    TIME=$(date '+%H:%M:%S')
    if [ "$BELOW_THRESHOLD" = "true" ]; then
        printf "[%s] %s📊 Below threshold%s - CPU: %s%% | Mem: %s%% | GPU: %s%% | Counter: %s/%s\n" \
            "$TIME" "$YELLOW" "$NC" "$CPU" "$MEMORY" "$GPU" "$CONSECUTIVE" "$DURATION_MINUTES"
    else
        printf "[%s] %s📊 Active%s - CPU: %s%% | Mem: %s%% | GPU: %s%%\n" \
            "$TIME" "$GREEN" "$NC" "$CPU" "$MEMORY" "$GPU"
    fi
    
    # Check if should stop
    if [ $CONSECUTIVE -ge $DURATION_MINUTES ]; then
        if [ "$MONITOR_ONLY" = "true" ]; then
            printf "${YELLOW}🔍 MONITOR MODE: Pod would be stopped (threshold met for ${DURATION_MINUTES} minutes)${NC}\n"
        else
            printf "${RED}⚠️ Idle threshold met for ${DURATION_MINUTES} minutes!${NC}\n"
            stop_pod
            printf "${GREEN}✅ Pod stop initiated. Exiting monitor.${NC}\n"
            exit 0
        fi
    fi
    
    # Wait 60 seconds
    sleep 60
done
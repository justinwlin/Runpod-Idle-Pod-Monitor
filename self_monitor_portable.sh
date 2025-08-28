#!/bin/bash

# RunPod Self-Monitor Script - Portable Version
# Self-contained script with auto-setup capabilities

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚀 RunPod Self-Monitor Setup (Portable Version)${NC}"
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}📖 HOW THIS SCRIPT WORKS:${NC}"
echo ""
echo "This script monitors your RunPod pod's resource usage and can automatically"
echo "stop it when idle to save money. Here's what it does:"
echo ""
echo "1. ${BLUE}Monitors 3 metrics every minute:${NC}"
echo "   • CPU Usage (%)"
echo "   • Memory Usage (%)"
echo "   • GPU Usage (%)"
echo ""
echo "2. ${BLUE}You set thresholds for each metric:${NC}"
echo "   For example: CPU < 20%, Memory < 30%, GPU < 15%"
echo "   The pod is considered 'idle' when ALL three metrics are below their thresholds"
echo ""
echo "3. ${BLUE}You set a duration (in minutes):${NC}"
echo "   How long the pod must remain idle before taking action"
echo "   For example: 30 minutes of continuous idle time"
echo ""
echo "4. ${BLUE}Two modes available:${NC}"
echo "   ${YELLOW}Monitor Mode:${NC} Just tracks and alerts (safe for testing)"
echo "   ${RED}Auto-Stop Mode:${NC} Actually stops the pod when idle (saves money!)"
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Press Enter to continue with setup..."
read -r
echo ""

# Function to check and install dependencies
setup_dependencies() {
    echo -e "${YELLOW}📦 Checking dependencies...${NC}"
    
    # Check for Python3
    if ! command -v python3 &> /dev/null; then
        echo -e "${YELLOW}Python3 not found. Attempting to install...${NC}"
        
        # Try different package managers
        if command -v apt-get &> /dev/null; then
            apt-get update && apt-get install -y python3 python3-minimal
        elif command -v yum &> /dev/null; then
            yum install -y python3
        elif command -v apk &> /dev/null; then
            apk add --no-cache python3
        else
            echo -e "${RED}❌ Could not install Python3. Please install manually.${NC}"
            exit 1
        fi
    fi
    
    # Check for curl
    if ! command -v curl &> /dev/null; then
        echo -e "${YELLOW}curl not found. Attempting to install...${NC}"
        
        if command -v apt-get &> /dev/null; then
            apt-get update && apt-get install -y curl
        elif command -v yum &> /dev/null; then
            yum install -y curl
        elif command -v apk &> /dev/null; then
            apk add --no-cache curl
        else
            # Try wget as fallback
            if command -v wget &> /dev/null; then
                echo -e "${YELLOW}Using wget instead of curl${NC}"
                USE_WGET=1
            else
                echo -e "${RED}❌ Could not install curl or wget. Please install manually.${NC}"
                exit 1
            fi
        fi
    fi
    
    echo -e "${GREEN}✓ All dependencies satisfied${NC}"
}

# Run dependency check
setup_dependencies

# Check required environment variables
if [ -z "$RUNPOD_API_KEY" ]; then
    echo -e "${RED}❌ Error: RUNPOD_API_KEY environment variable not set${NC}"
    echo "Please set: export RUNPOD_API_KEY=your_api_key_here"
    exit 1
fi

if [ -z "$RUNPOD_POD_ID" ]; then
    echo -e "${RED}❌ Error: RUNPOD_POD_ID environment variable not set${NC}"
    echo "This script must be run inside a RunPod pod"
    exit 1
fi

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Configuration files (stored next to the script)
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
    echo -e "${GREEN}✓ Found existing configuration${NC}"
    cat "$CONFIG_FILE"
    echo ""
    read -p "Use existing configuration? (y/n): " use_existing
    if [ "$use_existing" != "y" ]; then
        rm -f "$CONFIG_FILE"
    fi
fi

if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${YELLOW}📝 Configure monitoring thresholds:${NC}"
    echo "Set the maximum usage levels that indicate your pod is idle."
    echo ""
    
    # Get CPU threshold
    echo -e "${BLUE}CPU Threshold:${NC}"
    echo "  Pod is idle when CPU usage is BELOW this percentage"
    echo "  Example: 20 means idle when CPU < 20%"
    read -p "  Enter CPU threshold (%, default 20): " cpu_threshold
    cpu_threshold=${cpu_threshold:-20}
    echo ""
    
    # Get Memory threshold
    echo -e "${BLUE}Memory Threshold:${NC}"
    echo "  Pod is idle when Memory usage is BELOW this percentage"
    echo "  Example: 30 means idle when Memory < 30%"
    read -p "  Enter Memory threshold (%, default 30): " memory_threshold
    memory_threshold=${memory_threshold:-30}
    echo ""
    
    # Get GPU threshold
    echo -e "${BLUE}GPU Threshold:${NC}"
    echo "  Pod is idle when GPU usage is BELOW this percentage"
    echo "  Example: 15 means idle when GPU < 15%"
    read -p "  Enter GPU threshold (%, default 15): " gpu_threshold
    gpu_threshold=${gpu_threshold:-15}
    echo ""
    
    # Get duration (in minutes)
    echo -e "${BLUE}Idle Duration:${NC}"
    echo "  How many minutes must the pod remain idle before action is taken"
    echo "  Example: 30 means wait 30 minutes of continuous idle time"
    read -p "  Enter duration (minutes, default 30): " duration_minutes
    duration_minutes=${duration_minutes:-30}
    echo ""
    
    # Monitor-only mode
    echo -e "${BLUE}Operating Mode:${NC}"
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
    echo -e "${GREEN}✓ Configuration saved${NC}"
fi

# Load configuration
CPU_THRESHOLD=$(json_get "$CONFIG_FILE" "cpu_threshold")
MEMORY_THRESHOLD=$(json_get "$CONFIG_FILE" "memory_threshold")
GPU_THRESHOLD=$(json_get "$CONFIG_FILE" "gpu_threshold")
DURATION_MINUTES=$(json_get "$CONFIG_FILE" "duration_minutes")
MONITOR_ONLY=$(json_get "$CONFIG_FILE" "monitor_only")

echo ""
echo -e "${BLUE}📊 Starting monitoring with settings:${NC}"
echo "  CPU Threshold: ${CPU_THRESHOLD}%"
echo "  Memory Threshold: ${MEMORY_THRESHOLD}%"
echo "  GPU Threshold: ${GPU_THRESHOLD}%"
echo "  Duration: ${DURATION_MINUTES} minutes"
echo "  Monitor-only: ${MONITOR_ONLY}"
echo "  Pod ID: ${RUNPOD_POD_ID}"
echo ""

# Explain the mode
if [ "$MONITOR_ONLY" = "true" ]; then
    echo -e "${YELLOW}🔍 Running in MONITOR MODE:${NC}"
    echo "  • Will track when pod usage falls below thresholds"
    echo "  • Will show alerts when idle threshold is met"
    echo "  • Will NOT actually stop the pod (safe for testing)"
    echo "  • Useful for testing your threshold settings"
else
    echo -e "${RED}⚠️ Running in AUTO-STOP MODE:${NC}"
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
    echo -e "${YELLOW}🛑 Stopping pod...${NC}"
    
    local mutation="mutation { podStop(input: {podId: \\\"$RUNPOD_POD_ID\\\"}) { id desiredStatus } }"
    
    api_call "$mutation"
    
    echo -e "${GREEN}✓ Stop command sent${NC}"
}

# Main monitoring loop
echo -e "${GREEN}🔄 Monitoring started (checking every minute)${NC}"
echo "Press Ctrl+C to stop monitoring"
echo ""

# Initialize consecutive counter
CONSECUTIVE=0

while true; do
    # Get current metrics
    METRICS=$(get_pod_metrics)
    
    if [ -z "$METRICS" ]; then
        echo -e "${RED}⚠️ Could not fetch metrics${NC}"
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
        echo -e "[$TIME] ${YELLOW}📊 Below threshold${NC} - CPU: ${CPU}% | Mem: ${MEMORY}% | GPU: ${GPU}% | Counter: ${CONSECUTIVE}/${DURATION_MINUTES}"
    else
        echo -e "[$TIME] ${GREEN}📊 Active${NC} - CPU: ${CPU}% | Mem: ${MEMORY}% | GPU: ${GPU}%"
    fi
    
    # Check if should stop
    if [ $CONSECUTIVE -ge $DURATION_MINUTES ]; then
        if [ "$MONITOR_ONLY" = "true" ]; then
            echo -e "${YELLOW}🔍 MONITOR MODE: Pod would be stopped (threshold met for ${DURATION_MINUTES} minutes)${NC}"
        else
            echo -e "${RED}⚠️ Idle threshold met for ${DURATION_MINUTES} minutes!${NC}"
            stop_pod
            echo -e "${GREEN}✅ Pod stop initiated. Exiting monitor.${NC}"
            exit 0
        fi
    fi
    
    # Wait 60 seconds
    sleep 60
done
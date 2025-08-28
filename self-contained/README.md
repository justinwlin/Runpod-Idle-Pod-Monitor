# 🚀 RunPod Self-Monitor - Quick Start

A standalone script to monitor and auto-stop idle RunPod pods to save costs.

## 🎯 One-Liner Installation

Run this single command to set up everything:

```bash
apt-get update && apt-get install -y tmux curl && curl -sSL https://raw.githubusercontent.com/justinwlin/Runpod-Idle-Pod-Monitor/main/self_monitor_portable.sh -o /tmp/monitor.sh && chmod +x /tmp/monitor.sh && tmux new -d -s monitor "/tmp/monitor.sh" && tmux attach -t monitor
```

## 📋 What This Does

1. **Installs tmux** - For background process management
2. **Downloads the monitor script** - Latest version from GitHub
3. **Starts monitoring in tmux** - Runs in background, survives disconnections
4. **Attaches to the session** - Shows you the configuration screen

## 🎮 Tmux Commands

### Essential Commands
- **Detach (leave running)**: `Ctrl+B` then `D`
- **Reattach later**: `tmux attach -t monitor`
- **List sessions**: `tmux ls`
- **Kill monitor**: `tmux kill-session -t monitor`

### While Attached
- **Scroll up/down**: `Ctrl+B` then `[` (then use arrow keys, `Q` to exit)
- **Copy mode**: `Ctrl+B` then `[` (then space to select, Enter to copy)

## 💡 Usage Examples

### First Time Setup
1. Run the one-liner above
2. Configure your thresholds when prompted
3. Choose monitor-only mode (safe) or auto-stop mode
4. Detach with `Ctrl+B` then `D`

### Check Status Later
```bash
# See if monitor is running
tmux ls

# Attach to see current status
tmux attach -t monitor

# Check the logs
cat monitor_counter.json
```

### Stop Monitoring
```bash
# Kill the tmux session
tmux kill-session -t monitor

# Or attach and press Ctrl+C
tmux attach -t monitor
# Then Ctrl+C to stop
```

## ⚙️ Configuration

The script creates two files next to itself:
- `monitor_config.json` - Your threshold settings
- `monitor_counter.json` - Current monitoring state

### Reset Configuration
```bash
rm /tmp/monitor_config.json
tmux new -s monitor "/tmp/monitor.sh"
```

## 🔍 Monitor Modes

### Monitor-Only Mode (Safe Testing)
- Tracks resource usage
- Shows alerts when thresholds are met
- **Does NOT stop pods**
- Perfect for testing your thresholds

### Auto-Stop Mode (Production)
- Actually stops pods when idle
- Saves money automatically
- Use after testing thresholds

## 📊 Understanding Thresholds

The pod is considered "idle" when **ALL** conditions are met:
- CPU < your_threshold%
- Memory < your_threshold%  
- GPU < your_threshold%

For `duration` consecutive minutes.

### Example Settings
- **Development Pod**: CPU=20%, Memory=30%, GPU=15%, Duration=30min
- **Training Pod**: CPU=5%, Memory=10%, GPU=5%, Duration=60min
- **Notebook Pod**: CPU=10%, Memory=20%, GPU=10%, Duration=45min

## 🆘 Troubleshooting

### Can't fetch metrics
- Check `RUNPOD_API_KEY` is set
- Verify `RUNPOD_POD_ID` exists
- Ensure network connectivity

### Tmux session exists
```bash
# Kill old session
tmux kill-session -t monitor
# Start fresh
tmux new -s monitor "/tmp/monitor.sh"
```

### View raw metrics
```bash
# While attached to tmux
# The script shows current metrics every minute
```

## 🔗 Advanced Usage

### Custom Session Name
```bash
SESSION="my-monitor"
tmux new -d -s $SESSION "/tmp/monitor.sh"
tmux attach -t $SESSION
```

### Multiple Monitors
Run different monitors for different purposes:
```bash
# Development monitor (aggressive)
RUNPOD_POD_ID=pod1 tmux new -d -s monitor-dev "/tmp/monitor.sh"

# Production monitor (conservative)  
RUNPOD_POD_ID=pod2 tmux new -d -s monitor-prod "/tmp/monitor.sh"
```

### Remote Monitoring
SSH into your pod and the tmux session persists:
```bash
ssh user@runpod-instance
tmux attach -t monitor  # Resume monitoring view
```

## 📝 Notes

- The monitor checks every 60 seconds
- Config is saved and reused between runs
- Tmux sessions survive SSH disconnections
- Works on most Linux distributions
- Automatically installs dependencies if missing

---

💰 **Start saving money on idle pods today!**
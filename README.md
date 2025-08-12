# 🚀 RunPod Monitor

Monitor and auto-manage your RunPod instances with a simple web interface.

## ⚡ Quick Start

### 1. Clone & Setup
```bash
git clone <repository>
cd RunpodMonitor
echo "RUNPOD_API_KEY=your_api_key_here" > .env
```

### 2. Start Server
```bash
python server.py
```

### 3. Open Browser
```
http://localhost:8080
```

**That's it!** 🎉

## 🐳 Docker (Secure & Easy)

```bash
# Build
docker build -t runpod-monitor .

# Run with API key from environment
docker run -d \
  -p 8080:8080 \
  -e RUNPOD_API_KEY=your_api_key_here \
  -v $(pwd)/data:/app/data \
  runpod-monitor
```

## 📊 Features

- **Real-time monitoring** - See CPU, GPU, memory usage live
- **Auto-stop idle pods** - Save money by stopping unused pods
- **Web dashboard** - Modern interface with live updates  
- **One-click actions** - Start/stop pods instantly
- **Historical metrics** - Track usage over time
- **Smart filtering** - Only shows active pods

## ⚙️ Configuration

The server starts with sensible defaults. To customize:

1. **Edit `config.yaml`** for detailed settings
2. **Use the web interface** - Go to Config page for real-time changes
3. **Environment variables** - Set `RUNPOD_API_KEY` and other options

### Auto-Stop Settings (via Web UI)
- **CPU/GPU/Memory thresholds** - Set limits (e.g., ≤5% usage)
- **Duration** - How long conditions must persist (e.g., 45 minutes)
- **No-change detection** - Stop completely idle pods
- **Exclude pods** - Protect critical workloads

## 🔧 Development

### Manual Installation
```bash
pip install uv
uv pip install .
python server.py
```

### CLI Mode (Optional)
```bash
# Interactive mode
python -m runpod_monitor.main

# Monitoring only (no web UI)
python -m runpod_monitor.main --monitor

# List pods
python -m runpod_monitor.main --action list
```

## 🌟 What You Get

### Web Dashboard
- 📦 **Pod Overview** - Current status of all pods
- 🔄 **Live Updates** - Real-time status every 5 seconds
- 📊 **Metrics History** - Usage graphs and statistics
- ⚙️ **Configuration** - Change settings via web interface
- 🎯 **Actions** - Start/stop pods with one click

### Smart Monitoring
- **Background data collection** - Runs automatically when server starts
- **Active pods only** - Ignores terminated/deleted pods
- **Automatic cleanup** - Removes old data for deleted pods
- **Rolling window** - Manages memory usage efficiently

### Auto-Stop Features
- **Threshold monitoring** - CPU, GPU, memory limits
- **Duration-based** - Must meet conditions for specified time
- **No-change detection** - Stops completely idle workloads
- **Exclude lists** - Protect critical pods
- **Real-time control** - Enable/disable via web interface

## 🚀 Production Tips

1. **Set your API key**: `export RUNPOD_API_KEY=your_key`
2. **Configure auto-stop**: Use the web interface Config page
3. **Monitor safely**: Start with high thresholds, then tune down
4. **Exclude critical pods**: Add important workloads to exclude list
5. **Check logs**: Watch for auto-stop actions

## 📚 API Reference

The server exposes a REST API at `http://localhost:8080`:

- `GET /` - Dashboard page
- `GET /pods` - Live pod list (HTMX)
- `GET /metrics` - Metrics page with live updates
- `GET /config` - Configuration page
- `POST /config/auto-stop` - Update settings
- `GET /api/monitoring-status` - Live monitoring status
- `GET /status` - System status (JSON)

## 🛡️ Security

- **API Keys**: Store in environment variables, never commit to code
- **Exclude Lists**: Protect production workloads from auto-stop
- **Testing**: Verify thresholds on non-critical pods first
- **Monitoring**: Watch logs for unexpected auto-stop actions

---

**Need help?** Check the web interface tooltips or submit an issue!
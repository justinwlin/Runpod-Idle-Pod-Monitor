# 🚀 RunPod Monitor

Monitor and auto-manage your RunPod instances with a simple web interface.

----
Runpod Image:
https://console.runpod.io/deploy?template=xe00ihiurd&ref=p1oqnqy1

**IF YOU DEPLOY THIS ON RUNPOD** MAKE SURE TO EXCLUDE THE POD YOU ARE RUNNING THIS ON FROM THE MONITORING. There is an "Monitoring" Button on the home page for the pod, which when you click it will switch it to the exclude list.
----

## ⚡ Quick Start

### 🏃‍♂️ Running on RunPod (Recommended)
Just click the Runpod image template, and start it on the lowest CPU pod.

**That's it!** 🎉 The `RUNPOD_API_KEY` environment variable is pre-configured.

### 💻 Running Locally

#### 1. Clone & Setup
```bash
git clone <repository>
cd RunpodMonitor
echo "RUNPOD_API_KEY=your_api_key_here" > .env
```

#### 2. Start Server
```bash
python server.py
```

#### 3. Open Browser
```
http://localhost:8080
```

## 📸 Screenshots

### Home Dashboard
![Home Dashboard](./Home.png)
*Main dashboard showing pod status, actions, and real-time monitoring*

### Configuration Page  
![Configuration](./Configuration.png)
*Auto-stop settings, thresholds, and exclusion management*

### Metrics & Data
![Metrics Page](./Metrics.png)
![Metrics Page](./table.png)

*Historical data, usage graphs, and filterable pod metrics*

### Network Storage Pod - Paused State
![Network Storage Paused](./ex_paused_state_with_network_storage.png)
*Example of a network storage pod in paused state - data preserved, can be resumed*

## Exclude Pods
On the home page, you'll see if something is excluded or not. Click the "Monitor" button or the "Exclude" button to switch it to actually shut off or to exclude it from monitoring.

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
## ⚙️ Configuration

The server starts with sensible defaults. To customize:

### Options:
2. **Use the web interface** - Go to Config page for real-time changes. The changes get persisted to the file on the server, so you can turn the server on and off, as long the file is not destroyed.
3. **Environment variables** - `RUNPOD_API_KEY` is auto-configured on RunPod when you start a container is already in the env. But you can also set it manually locally by creating a .env file with the key.

### Recommendations:
Just use the Web UI for configurations since it will autopersist into whatever file, and will create a starting configuration file if it doesn't exist based off the yaml template.

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

### Auto-Stop Modes
- **Active mode** - Automatically stops pods meeting thresholds
- **Monitor-only mode** - Tracks and alerts about at-risk pods without stopping them
- **Smart thresholds** - Duration minimum: 60 seconds (was 5 minutes)
- **Real-time alerts** - Auto-stop predictions show pods at risk with manual stop buttons

### Monitoring Features  
- **Data visualization** - Toggle between table and graph view for raw metrics
- **Time range selection** - View historical data: 1 hour, 4 hours, 24 hours, or 1 week
- **Interactive charts** - CPU, Memory, GPU metrics over time with Chart.js
- **Smart data retention** - Rolling window: max(1 hour, duration × 1.5)
- **Disk-based storage** - Minimal memory usage, all data persisted
- **Network storage support** - Pods with network volumes can be stopped (paused, not deleted)

### Configuration
- **Clean UI** - Streamlined configuration page with collapsible advanced settings
- **Real-time validation** - Live feedback on settings changes
- **Smart defaults** - Intelligent auto-activation based on duration settings

## 🚀 Production Tips

1. **API key**: Auto-configured on RunPod, or set locally with `export RUNPOD_API_KEY=your_key`
2. **Configure monitoring**: Use Config page - choose Active (auto-stop) or Monitor-Only mode
3. **Use graph view**: Switch between table and graph in Metrics page for visual analysis
4. **Set smart durations**: Minimum 60 seconds, rolling window auto-adjusts to max(1 hour, duration × 1.5)
5. **Monitor network storage**: Pods with network volumes are paused when stopped, not deleted - manually terminate via RunPod web interface to delete data

## 📚 API Reference

The server exposes a REST API at `http://localhost:8080`:

### Pages
- `GET /` - Dashboard page
- `GET /pods` - Live pod list (HTMX)
- `GET /metrics` - Metrics page with live updates and filterable data
- `GET /config` - Configuration page

### Pod Actions
- `POST /pods/{pod_id}/stop` - Stop a pod with dynamic button update
- `POST /pods/{pod_id}/resume` - Resume a pod with dynamic button update
- `POST /pods/{pod_id}/exclude` - Add pod to exclude list
- `POST /pods/{pod_id}/include` - Remove pod from exclude list

### Configuration
- `POST /config/auto-stop` - Update basic auto-stop settings
- `POST /config/no-change` - Update no-change detection
- `POST /config/sampling` - Update sampling configuration

### API Endpoints
- `GET /api/monitoring-status` - Live monitoring status (HTML)
- `GET /api/next-poll` - Next collection time and monitoring status (JSON)
- `GET /api/raw-data?pod_filter={name}` - Filterable raw data table (HTML)
- `GET /api/auto-stop-predictions` - Pods at risk of being stopped (HTML)
- `GET /api/graph-pods` - Available pods for graphing (JSON)
- `GET /api/graph-data/{pod_id}?timeRange={seconds}` - Chart data for specific pod (JSON)
- `GET /status` - System status (JSON)

---

**Need help?** Check the web interface tooltips or submit an issue!

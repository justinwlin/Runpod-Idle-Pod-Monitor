# 🚀 RunPod Monitor

Monitor and auto-manage your RunPod instances with a simple web interface.

![RunPod Monitor Demo](ppt/runpod-monitor-demo-small.gif)

## Version
1.0: JSON based file
2.0: Data Migration + Hooks + Data compaction for graphs
2.1: Attempt to fix hanging code on startup server
2.2: Beta Version of Better Memory Management
2.3: Data Clean Up for non-existing pods

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
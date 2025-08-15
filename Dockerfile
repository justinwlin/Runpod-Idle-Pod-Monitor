# RunPod Monitor Dockerfile
FROM python:3.13-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install UV
RUN pip install uv

WORKDIR /app

# Copy everything
COPY . .

# Install dependencies directly from pyproject.toml
RUN uv pip install --system .

# Create workspace directory for persistence (will be mounted as network volume)
RUN mkdir -p /workspace/data /workspace/config

# Create data directory symlink to workspace (for backward compatibility)
RUN ln -sf /workspace/data /app/data

# Remove any config.yaml to force creation from template with env vars
RUN rm -f config.yaml

# Set environment variables for workspace persistence
ENV DATA_DIR=/workspace/data
ENV CONFIG_DIR=/workspace/config

# Expose ports
EXPOSE 8080

# Health check for main app
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8080/status || exit 1

# Make start.sh executable
RUN chmod +x /app/start.sh

# Default command runs both services
CMD ["/app/start.sh"]
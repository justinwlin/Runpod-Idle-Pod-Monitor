# RunPod Monitor Dockerfile
FROM python:3.13-slim

# Install UV
RUN pip install uv

WORKDIR /app

# Copy everything
COPY . .

# Install dependencies directly from pyproject.toml
RUN uv pip install --system .

# Create data directory for metrics storage
RUN mkdir -p /app/data

# Remove any config.yaml to force creation from template with env vars
RUN rm -f config.yaml

# Expose ports
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8080/status || exit 1

# Default command runs the integrated server (web + monitoring)
CMD ["python", "server.py"]
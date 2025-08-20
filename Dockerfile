# RunPod Monitor Dockerfile
FROM python:3.13-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    openssh-server \
    && rm -rf /var/lib/apt/lists/*

# Install UV
RUN pip install uv

# Install UV for root user globally
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# Add UV tools to PATH
ENV PATH="/root/.local/bin:$PATH"

# Configure SSH
RUN mkdir -p /var/run/sshd && \
    sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config && \
    sed -i 's/#PasswordAuthentication no/PasswordAuthentication yes/' /etc/ssh/sshd_config

# Set default SSH password (can be overridden via environment variable)
ENV SSH_PASSWORD=runpod123

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
EXPOSE 8080 22

# Health check for main app
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8080/status || exit 1

# Make start.sh executable
RUN chmod +x /app/start.sh

# Default command runs both services
CMD ["/app/start.sh"]
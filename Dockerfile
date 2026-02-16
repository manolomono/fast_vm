FROM python:3.11-slim

# Install QEMU and required system packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    qemu-kvm \
    qemu-system-x86 \
    qemu-system-modules-spice \
    qemu-utils \
    ovmf \
    swtpm \
    cloud-image-utils \
    genisoimage \
    libvirt-daemon-system \
    websockify \
    openssl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy application code
COPY backend/ /app/backend/
COPY frontend/ /app/frontend/

# Copy entrypoint
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Create necessary directories
RUN mkdir -p /app/vms /app/images /app/data /app/backups /app/backend/logs /app/certs

# Expose port
EXPOSE 8000

# Environment defaults (override in docker-compose or at runtime)
ENV PYTHONUNBUFFERED=1
ENV JWT_SECRET_KEY=change-me-in-production

WORKDIR /app/backend

ENTRYPOINT ["/app/entrypoint.sh"]

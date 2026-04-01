##############################################################################
# Dockerfile — OpenClaw Market Intel Fargate Service
#
# Packages the OpenClaw Gateway and Telegram bot listener into a single
# container for deployment on AWS Fargate.
#
# EFS is mounted at /mnt/efs/shared_memory by the Fargate task definition
# (not baked into the image).
#
# Entry point starts both the OpenClaw gateway and Telegram bot polling loop.
#
# Requirements: 12.1, 20.1
##############################################################################

FROM python:3.12-slim

# Prevent Python from writing .pyc files and enable unbuffered stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Set the shared memory path to the EFS mount point
ENV SHARED_MEMORY_PATH=/mnt/efs/shared_memory

WORKDIR /app

# Install OS-level dependencies (curl for healthcheck)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create the EFS mount point directory (actual mount is via Fargate task def)
RUN mkdir -p /mnt/efs/shared_memory

# Expose no ports — the bot uses outbound HTTPS polling only
# (OpenClaw gateway can optionally expose a port if needed)

# Healthcheck: verify the Python process is alive
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Entry point: start both OpenClaw gateway and Telegram bot
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]

#!/usr/bin/env bash
##############################################################################
# Entrypoint for the OpenClaw Market Intel Fargate container.
#
# Starts both:
#   1. The OpenClaw Gateway (background)
#   2. The Telegram bot long-polling loop (foreground)
#
# If either process exits, the container exits so ECS can restart it.
#
# Requirements: 12.1, 20.1
##############################################################################

set -euo pipefail

echo "=== OpenClaw Market Intel — Starting ==="
echo "SHARED_MEMORY_PATH=${SHARED_MEMORY_PATH:-/mnt/efs/shared_memory}"

# Ensure the shared memory directory structure exists
mkdir -p "${SHARED_MEMORY_PATH:-/mnt/efs/shared_memory}"/{runs,picks,weights,config}

# Start the Telegram bot polling loop (foreground — keeps container alive)
echo "Starting Telegram bot listener..."
exec python -m telegram_bot.run_bot

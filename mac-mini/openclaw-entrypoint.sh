#!/bin/sh
# Pre-install ClawHub skills on startup (idempotent — skills live on the volume)
clawhub install self-improving-agent --workdir /home/node/.openclaw || true
exec "$@"

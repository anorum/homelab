#!/bin/bash
# Push OpenClaw status to Uptime Kuma
# Checks if OpenClaw is accepting TCP connections on 127.0.0.1:18789
# and reports status via Uptime Kuma push monitor

# Direct NodePort access bypasses Authentik SSO proxy
PUSH_URL="http://192.168.1.101:30301/api/push/4iMD5d52iTpkRVB5kuyOCySnURNdbZ7C"

if nc -z -w 2 127.0.0.1 18789 2>/dev/null; then
    curl -sf "${PUSH_URL}?status=up&msg=OK&ping=" > /dev/null
else
    curl -sf "${PUSH_URL}?status=down&msg=OpenClaw+TCP+unreachable&ping=" > /dev/null
fi

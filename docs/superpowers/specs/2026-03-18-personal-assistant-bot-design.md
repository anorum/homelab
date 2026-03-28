# Personal Assistant Bot — Design Spec

**Date**: 2026-03-18
**Status**: Draft

---

## Context

Alex receives more email than he can keep up with daily. Important items get buried, responses are delayed, and there's no unified place to track action items. The goal is a self-hosted personal assistant bot that monitors Gmail, surfaces important emails with AI-drafted responses, and maintains a lightweight todo list — all accessible via Discord on any device. Privacy and local control are priorities; no third-party SaaS beyond what's already in use (Google, Anthropic API).

---

## Architecture

A single Python service (`assistant`) deployed to the homelab k8s cluster as a Deployment. No ingress required — the bot connects outbound to Discord's gateway and Google/Anthropic APIs.

```
Gmail API  ──→  Poller  ──→  PydanticAI Agent  ──→  Discord Bot
                   │               │
                SQLite DB    Claude Haiku/Sonnet
                (todos +         (Anthropic API)
               email state)
```

**Components:**

1. **Discord Bot** (`discord.py` 2.x) — slash commands + guild channel notifications + interactive button UI
2. **Gmail Poller** — asyncio background task, polls every 10 minutes, tracks processed message IDs in SQLite
3. **PydanticAI Agent** — orchestrates triage and draft generation with defined tools (read-only tools only; see Security section)
4. **SQLite DB** — persisted on a 1Gi `local-path` PVC, pinned to swagman-1

---

## Email Flow

### Polling & Triage
- Poll Gmail for unread messages not in SQLite `emails` table every 10 minutes (configurable via ConfigMap)
- For each new email, call **Claude Haiku** with a triage prompt: "Is this email actionable or time-sensitive? Reply yes/no + one-line reason."
- Store result in SQLite regardless of triage outcome (ensures no email is re-processed after pod restart)
- Skip non-actionable emails silently (no Discord noise)

### Discord Notification (actionable emails only)
Bot posts an embed to the configured guild channel with:
- Sender name + address
- Subject
- 2-sentence AI summary
- Suggested action (e.g. "Reply confirming availability")
- Two buttons: **Draft Response** | **Dismiss**
- If triage finds a clear action item, also auto-creates a todo (with `source=email`)

### Draft Loop
1. User clicks **Draft Response** → Agent calls **Claude Sonnet** to generate a reply
2. Bot posts draft in a thread under the notification embed with buttons: **Send** | **Edit** | **Discard**
3. User can type freeform edit instructions (e.g. `edit: shorter, more casual`) → agent regenerates
4. User clicks **Send** → Gmail API `messages.send()` called directly from the button callback, confirmation posted

**Hard rules (non-configurable):**
- The bot will **never send an email without an explicit "Send" button click**
- `send_email` is **never exposed as a PydanticAI tool** — the agent can only generate draft text; the actual send is a Discord button callback that calls the Gmail API directly
- All `discord.py View` button callbacks check `interaction.user.id == owner_user_id` before taking any action; any other user clicking a button is silently ignored
- Draft views have a 24-hour timeout; after expiry buttons are disabled and a note is posted in the thread
- Pending draft state (message ID, email ID, draft text) is persisted in SQLite so it can be referenced after a pod restart, though button views are not reconstructed (user must re-click "Draft Response" on the original notification if pod restarted mid-draft)

### Gmail Auth Failure Handling
- On startup and on each poll cycle, catch `google.auth.exceptions.TransportError` and `google.auth.exceptions.RefreshError`
- On auth failure: post a Discord DM to the owner with `"⚠️ Gmail auth failed — refresh token may need to be rotated. Error: {msg}"`
- Stop polling until the pod is restarted with valid credentials
- **Note**: The Gmail OAuth app must be set to "Published" (not "Testing") to avoid the 7-day refresh token expiry that applies to apps in Testing mode. If using a personal Google account (not Workspace), this requires a simple verification submission.

---

## Todo List

### Storage
SQLite table `todos`:
```sql
CREATE TABLE todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    notes TEXT,
    source TEXT DEFAULT 'manual',  -- 'manual' | 'email'
    email_id TEXT,                 -- FK to emails table if source=email
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);
```

### Discord Commands (guild-scoped, not global — instant registration)
| Command | Description |
|---------|-------------|
| `/todo add <task>` | Add a task manually |
| `/todo list` | Show all open tasks |
| `/todo done <id>` | Mark task complete |
| `/todo note <id> <text>` | Append a note to a task |

### Agent Context
When the agent is in a conversation (editing a draft, answering a question), it receives the current open todo list as system context — enabling responses like "this looks related to your existing todo about X."

### Auto-Extraction
When triage finds a clear action item in an email, the agent auto-creates a todo and mentions it in the Discord notification. Todo creation is a PydanticAI tool (`create_todo`) — safe because it writes to local SQLite only, not to external systems.

---

## k8s Deployment

**Directory**: `assistant/` at repo root (follows existing conventions)

| File | Purpose |
|------|---------|
| `kustomization.yaml` | Sets namespace `assistant`, references all resources |
| `namespace.yaml` | `assistant` namespace |
| `deployment.yaml` | Single-container Deployment, mounts PVC + secret + configmap, node-pinned to swagman-1 |
| `configmap.yaml` | Non-secret configuration (poll interval, channel ID, triage prompt) |
| `pvc.yaml` | 1Gi `local-path` PVC for SQLite |
| `Dockerfile` | Multi-stage build using `uv` for dependencies |
| `assistant-secret-generator.yaml` | KSOPS generator referencing `assistant-secrets.enc.yaml` |
| `assistant-secrets.enc.yaml` | SOPS-encrypted credentials (see Secrets section) |

**ArgoCD**: New entry in `argo-apps/applications.yaml` following existing pattern (`prune: true`, `selfHeal: true`).

**No HTTPRoute** — bot is outbound-only.

### Node Affinity
The `local-path` PVC binds to the node where the pod first schedules. To prevent migration issues in a 2-node cluster, `deployment.yaml` includes:
```yaml
nodeSelector:
  kubernetes.io/hostname: swagman-1
```

### Resource Limits
```yaml
resources:
  requests:
    memory: 128Mi
    cpu: 50m
  limits:
    memory: 256Mi
```

### Health Probe
The Python app exposes a minimal HTTP health endpoint (`aiohttp`, port 8080):
- **Liveness** (`/healthz`): always returns 200 as long as the process is running. Discord temporarily disconnects and reconnects normally — probing that would cause restart loops.
- **Readiness** (`/readyz`): returns 200 only when both the Discord connection and Gmail poller are initialized. Returns 503 during startup.

---

## Container Image

**Image registry**: `ghcr.io/anorum/homelab-assistant` (GitHub Container Registry, same org as the public repo)

**Build**:
- `assistant/Dockerfile` — multi-stage, Python 3.12 slim base, `uv` for dependency install
- `assistant/pyproject.toml` — dependencies declared here

**CI**: GitHub Actions workflow (`.github/workflows/assistant.yml`):
- Triggers on push to `main` when files under `assistant/` change
- Builds and pushes image tagged `ghcr.io/anorum/homelab-assistant:latest` and `:<git-sha>`
- `deployment.yaml` references `ghcr.io/anorum/homelab-assistant:latest` with `imagePullPolicy: Always` (ensures new pushes are picked up without needing a tag change)

**Image visibility**: Set the `homelab-assistant` package to **public** in GitHub → Packages settings so the cluster can pull without an `imagePullSecret`. If kept private, add a `kubernetes.io/dockerconfigjson` secret and `imagePullSecrets` to `deployment.yaml`.

---

## Secrets Required

All stored in `assistant-secrets.enc.yaml`, encrypted with the existing age public key from `.sops.yaml`. The `DISCORD_CHANNEL_ID` and poll interval are **not** secrets and live in `configmap.yaml` instead.

| Secret | Description | Rotation |
|--------|-------------|----------|
| `DISCORD_BOT_TOKEN` | Discord developer portal → Bot token | Infrequent |
| `DISCORD_GUILD_ID` | Discord server ID (for guild-scoped slash command registration) | Stable |
| `DISCORD_OWNER_USER_ID` | Your Discord user ID (for DM alerts + button ownership check) | Stable |
| `GMAIL_CLIENT_ID` | Google Cloud OAuth2 client ID | Infrequent |
| `GMAIL_CLIENT_SECRET` | OAuth2 client secret | Infrequent |
| `GMAIL_REFRESH_TOKEN` | Long-lived refresh token (obtained via one-time auth flow) | If rotated by Google |
| `ANTHROPIC_API_KEY` | Claude API key | As needed |

**Note on rotation**: When the Gmail refresh token needs rotation (e.g. after a Google account security event), re-run the one-time OAuth flow, update the value in `assistant-secrets.enc.yaml` via `sops assistant-secrets.enc.yaml`, and restart the pod. The other credentials in the file remain unchanged.

---

## ConfigMap (non-secret config)

```yaml
GMAIL_POLL_INTERVAL_SECONDS: "600"   # 10 minutes
DISCORD_CHANNEL_ID: "..."            # Channel for email notifications
TRIAGE_PROMPT: |                     # Tunable without re-encrypting
  You are a personal email assistant. Decide if this email requires action
  within 48 hours. Reply with a JSON object: {"actionable": true/false, "reason": "..."}.
  Ignore marketing, newsletters, and automated notifications.
```

---

## One-Time Setup (Outside GitOps)

1. **Discord**: Create application at discord.dev → enable Bot → enable Message Content Intent → copy token → invite bot to server with `bot` + `applications.commands` scopes
2. **Gmail OAuth**: Create Google Cloud project → enable Gmail API → create OAuth2 "Desktop" credentials → run one-time auth flow script (`assistant/scripts/get_gmail_token.py`) to obtain refresh token → set OAuth app to Published
3. **Anthropic**: Get API key from console.anthropic.com
4. Encrypt all credentials: `sops -e assistant-secrets.yaml > assistant-secrets.enc.yaml`

---

## Tech Stack

| Concern | Choice | Reason |
|---------|--------|--------|
| Language | Python 3.12 | User's primary language, PydanticAI familiarity |
| Bot framework | `discord.py` 2.x | Best Discord library, async-native, Views/buttons built-in |
| AI agent | `pydantic-ai` | User uses this at work |
| Gmail | `google-api-python-client` + `google-auth` | Official SDK, handles OAuth2 refresh |
| LLM (triage) | Claude Haiku | Cheap, fast, good enough for yes/no |
| LLM (drafting) | Claude Sonnet | High quality, only called on demand |
| DB | SQLite via `aiosqlite` | Zero-ops, sufficient for personal scale |
| HTTP health | `aiohttp` | Minimal, async, for k8s probes |
| Package manager | `uv` | User preference |

---

## Cost Estimate

| Usage | Model | Est. Cost |
|-------|-------|-----------|
| New emails only (deduplicated before triage) × ~500 tokens | Claude Haiku | ~$2/year at 50 new emails/day |
| 5 draft responses/week × ~1K tokens | Claude Sonnet | ~$0.15/month |
| **Total** | | **< $4/year** |

---

## Security Summary

1. **Send gate**: `send_email` is not a PydanticAI tool. Email sending only happens in a Discord button callback, after `interaction.user.id == owner_user_id` check.
2. **Button ownership**: All interactive button callbacks verify the initiating user. Others are silently rejected.
3. **Button timeout**: 24 hours. Expired views disable buttons and post a notice.
4. **Draft persistence**: Stored in SQLite; pod restart does not lose email state but does lose in-flight button views (user re-initiates draft).
5. **Auth failure alerting**: Gmail auth errors trigger a Discord DM to owner, not a silent failure.
6. **Secrets in public repo**: All credentials are SOPS-encrypted per existing repo convention.

---

## Verification

### Happy Path
1. Deploy to cluster → ArgoCD syncs → pod starts healthy, `/healthz` returns 200
2. Send a test email to Gmail account → within 10 min, Discord notification appears in configured channel
3. Click **Draft Response** → draft appears in a Discord thread
4. Type `edit: make it one sentence` → draft updates
5. Click **Send** → email appears in Gmail Sent folder
6. `/todo add test task` → appears in `/todo list` → `/todo done 1` marks it complete
7. Verify bot auto-created a todo from the test email's action item

### Failure Path
8. **No spurious send**: Close/dismiss the Discord message without clicking Send → confirm Gmail Sent has no new email
9. **Deduplication**: Restart the pod → confirm the test email does not trigger a second Discord notification
10. **Non-actionable silence**: Send a marketing/newsletter email → confirm no Discord notification appears
11. **Button ownership**: Log into a second Discord account, click "Send" on an existing draft → confirm the email is NOT sent and the second account gets no response
12. **Auth failure alert**: Temporarily set an invalid refresh token, restart pod → confirm Discord DM arrives with auth error message

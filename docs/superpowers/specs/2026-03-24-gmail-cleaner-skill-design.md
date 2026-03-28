# Gmail Cleaner Skill Design

## Context

Alex's Gmail has 88K+ messages and accumulates marketing, social notifications, newsletters, and other low-value email. The existing `gmail-cleanup` skill delegates to a Python script (`~/scripts/gmail-cleanup.py`) with hardcoded sender rules. This works but is limited — it can't detect unknown marketing senders, doesn't support time ranges, and has no interactive approval flow.

**Goal:** Replace the existing `gmail-cleanup` skill with a single unified `gmail-cleaner` skill that combines rule-based classification with AI-powered marketing detection. Run weekly with interactive approval before any action.

## Approach

One skill file (`~/.claude/skills/gmail-cleaner.md`) that:
- Uses **Gmail MCP tools** for reading/searching/analyzing emails
- Uses **`gws` CLI** (via Bash) for trashing and label+archive operations
- Replaces both `gmail-cleanup.md` skill and `gmail-cleanup.py` script
- Runs as a conversational flow with explicit user approval before any destructive action

## Skill File

**Path:** `~/.claude/skills/gmail-cleaner.md`

**Frontmatter:**
```yaml
---
name: gmail-cleaner
description: Deep-clean Gmail inbox — trash marketing, archive receipts/finance, keep personal. Use when Alex asks to clean email, purge old messages, clear inbox, trash newsletters, or organize Gmail. Replaces gmail-cleanup. Run weekly or on demand.
---
```

## Execution Flow (7 Steps)

### Step 1 — Ask for Time Range

Ask Alex what time range to clean. Default suggestion: 30 days. Accept natural language ("last 2 weeks", "everything", "90 days"). Convert to Gmail `older_than:` / `newer_than:` / `after:` query syntax. Store for all subsequent searches.

**Time range + age thresholds:** The user's time range sets the outer bound for all searches. Per-category age thresholds (e.g., LinkedIn Jobs >7d, NYT >3d) apply within the user's range. Combine both in queries: e.g., for "last 30 days" + "NYT >3d", use `from:nytimes.com in:inbox newer_than:30d older_than:3d`. If the user's range is narrower than a threshold (e.g., "last 3 days" with Job Alerts >7d), that category yields no results — this is expected.

Also verify gws auth early: run `gws gmail users getProfile --params '{"userId":"me"}' --format json` and check for errors before proceeding.

### Step 2 — Identify Protected Messages

Search for emails that must NEVER be trashed. These form a "protected set" of message IDs.

| Search | Gmail Query | Action |
|--------|-------------|--------|
| Starred | `is:starred in:inbox` | KEEP (never touch) |
| Finance | `in:inbox (from:fidelity.com OR from:capitalone.com OR from:chase.com OR from:firsttechfed.com OR from:bankofamerica.com)` | Label+Archive → **Finance** |
| Government/Tax | `in:inbox (from:irs.gov OR from:oregon.gov OR from:ssa.gov OR from:turbotax.intuit.com OR subject:"arts tax")` | KEEP |
| Orders/Shipping | `in:inbox (subject:order OR subject:shipped OR subject:delivered OR subject:receipt OR subject:confirmation OR subject:invoice) -(from:nytimes.com OR from:linkedin.com OR from:glassdoor.com)` | Label+Archive → **Purchases** |
| Amazon Orders | `from:amazon.com in:inbox (subject:order OR subject:delivered OR subject:shipped OR subject:receipt OR subject:confirm)` | Label+Archive → **Purchases** |
| Airbnb Bookings | `from:airbnb.com in:inbox (subject:reservation OR subject:confirmed OR subject:receipt OR subject:booking OR subject:itinerary OR subject:check-in OR subject:reminder)` | Label+Archive → **Purchases** |
| Strava | `from:strava.com in:inbox` | Label+Archive → **Social** |
| Personal/Direct | `in:inbox -category:promotions -category:social -category:updates -category:forums is:important` | KEEP |

For the Orders/Shipping search, read a sample of messages to confirm they're actual transactional emails (not marketing using transactional-sounding subjects). If a sampled message is clearly marketing, exclude it from the protected set.

Also protect threads where Alex has replied (these indicate personal engagement):
- Search: `in:inbox from:me` to find threads with Alex's participation

All message IDs from these searches go into the protected set.

### Step 3 — Find Trash Candidates (Rule-Based)

Run these searches within the time range:

| Category | Gmail Query | Rule |
|----------|-------------|------|
| Gmail Promotions | `category:promotions in:inbox` | All in range → TRASH |
| LinkedIn Social | `from:linkedin.com in:inbox -subject:job -subject:apply -subject:opportunity -subject:hiring` | All in range → TRASH |
| LinkedIn Job Alerts (old) | `from:linkedin.com in:inbox (subject:job OR subject:apply OR subject:opportunity OR subject:hiring) older_than:7d` | >7 days → TRASH |
| Glassdoor | `from:glassdoor.com in:inbox` | All → TRASH |
| NYT (old) | `from:nytimes.com in:inbox older_than:3d` | >3 days → TRASH |
| Known trash senders (batch 1) | `in:inbox (from:zbiotics.com OR from:rejuvenation.com OR from:ring.com OR from:audible.com OR from:chipotle.com OR from:cbssports.com)` | All → TRASH |
| Known trash senders (batch 2) | `in:inbox (from:audiusa.com OR from:retailmenot.com OR from:tradepending.com OR from:uoregon.edu OR from:databricks.com OR from:hilton.com OR from:aeheatingandcool.com)` | All → TRASH |
| Amazon Marketing | `from:amazon.com in:inbox -subject:order -subject:delivered -subject:shipped -subject:receipt -subject:confirm` | All → TRASH |
| Airbnb Marketing | `from:airbnb.com in:inbox -subject:reservation -subject:confirmed -subject:receipt -subject:booking -subject:itinerary -subject:check-in` | All → TRASH |

**Note:** Known trash sender queries are split to stay within Gmail search length limits.

Paginate fully using `gmail_search_messages` with `maxResults: 500` and `pageToken`. Collect all message IDs.

### Step 4 — AI-Powered Marketing Detection

Catch marketing emails that don't match any known sender rule:

1. Search `in:inbox category:updates` within time range (note: this category contains many legitimate transactional emails — account alerts, 2FA codes, shipping updates. The AI classification step must treat transactional/account-security content as KEEP.)
2. Search `in:inbox "unsubscribe" -category:promotions -category:social` to find bulk emails in primary inbox (most marketing includes "unsubscribe" in the body)
3. For messages NOT already in the protected set or trash set, use `gmail_read_message` on a sample (up to 30 unique senders, one message each for better coverage)
4. Claude classifies each as MARKETING or KEEP based on:
   - **Marketing signals:** unsubscribe links, promotional language ("% off", "limited time", "sale"), bulk sender headers, no personal salutation, HTML-heavy templates
   - **Keep signals:** direct address to "Alex", personal conversational tone, transactional content (account security, 2FA codes), replies to threads Alex participated in
5. **Conservative bias:** When uncertain, classify as KEEP

If a new sender appears 3+ times as marketing, note it for suggesting addition to the known trash list.

### Step 5 — Deduplicate and Present Results

1. Remove any message ID from the trash set that appears in the protected set (protected always wins)
2. Group results by category
3. Present to Alex:

```
## Gmail Clean Plan (last 30 days)

### KEEPING (N messages)
- ⭐ Starred: N
- 👤 Personal/Direct: N
- 🏦 Finance → archived to "Finance": N
- 🏛️ Government/Tax: N
- 📦 Orders/Shipping → archived to "Purchases": N
- 💼 LinkedIn Jobs (recent <7d): N
- 📰 NYT (recent <3d): N

### TRASHING (N messages)
| Category | Count | Sample subjects |
|----------|-------|-----------------|
| Gmail Promotions | N | subject1, subject2, subject3 |
| LinkedIn Social | N | ... |
| LinkedIn Jobs (>7d) | N | ... |
| Glassdoor | N | ... |
| NYT (>3d) | N | ... |
| Known marketing senders | N | domains: x.com, y.com |
| AI-detected marketing | N | subject1 (sender), subject2 (sender) |

### ARCHIVING (N messages)
| Label | Count |
|-------|-------|
| Finance | N |
| Purchases | N |
| Social | N |

**Total to trash: N messages** (recoverable for 30 days)

Proceed? (yes / no / adjust)
```

Wait for explicit approval. If Alex says "adjust", let them exclude categories or specific senders.

### Step 6 — Execute

After approval, execute in this order:

**A. Label+Archive operations first** (non-destructive):

For each label (Finance, Purchases, Social):
1. Fetch all labels: `/Users/alexnorum/.local/bin/gws gmail users labels list --params '{"userId":"me"}' --format json`
2. If label doesn't exist in the list, create it: `/Users/alexnorum/.local/bin/gws gmail users labels create --params '{"userId":"me"}' --json '{"name":"Purchases"}' --format json`
3. Batch modify:
```bash
/Users/alexnorum/.local/bin/gws gmail users messages batchModify \
  --params '{"userId": "me"}' \
  --json '{"ids": ["id1", "id2", ...], "addLabelIds": ["<label_id>"], "removeLabelIds": ["INBOX"]}' \
  --format json
```

**B. Trash operations:**

Batch trash via `gws gmail users messages batchModify`:
```bash
/Users/alexnorum/.local/bin/gws gmail users messages batchModify \
  --params '{"userId": "me"}' \
  --json '{"ids": ["id1", "id2", ...], "addLabelIds": ["TRASH"], "removeLabelIds": ["INBOX"]}' \
  --format json
```

Process in batches of 1000 IDs. Report progress after each batch.

### Step 7 — Report

```
## Clean Complete

Archived:
- Finance: N messages
- Purchases: N messages
- Social: N messages

Trashed: N messages
- [category]: N (✓ N ok, ✗ N failed)
- ...

💡 New marketing senders detected (consider adding to known list):
- sender@example.com (N emails)

Messages recoverable from Trash for 30 days.
```

## Edge Cases

- **Large result sets (>5000 trash candidates):** Warn Alex and suggest narrowing time range or proceeding in phases
- **Gmail search pagination:** Follow `nextPageToken` up to 5000 messages per category
- **Rate limits on gws CLI:** If batch errors occur, retry once. Report persistent failures
- **Sender in both protect and trash rules:** Protected set always wins (e.g., a starred email from a known trash sender stays)
- **Missing labels:** Create labels automatically if they don't exist (Finance, Purchases, Social)

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `~/.claude/skills/gmail-cleaner.md` | **Create** | The new unified skill |
| `~/.claude/skills/gmail-cleanup.md` | **Delete** | Replaced by gmail-cleaner |
| `~/scripts/gmail-cleanup.py` | **Keep for reference** | Don't delete, but no longer invoked by any skill |

## Verification

1. **Dry run test:** Invoke the skill, provide "last 7 days" as time range. Verify it presents a categorized plan without executing anything.
2. **Approval gate:** Confirm the skill waits for explicit "yes" before trashing.
3. **Small batch test:** Approve on a small time range (last 3 days). Verify messages are moved to Trash in Gmail.
4. **Protected set test:** Star a promotional email, run the skill. Verify it appears in KEEP, not TRASH.
5. **Label+archive test:** Verify orders/shipping emails get the "Purchases" label and are removed from inbox.

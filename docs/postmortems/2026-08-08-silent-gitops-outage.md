# Silent GitOps outage — ~117 days

**Date:** 2026-08-08
**Duration:** ~2026-04-13 → 2026-08-08 (~117 days)
**Impact:** No GitOps reconciliation. Config pushed to `main` did not reach the cluster.
**Detected by:** Unrelated investigation into Ollama being unreachable.

## Summary

Both `argocd-repo-server` replicas were stuck in a crash-loop for roughly 117 days. ArgoCD cannot render manifests without the repo-server, so every Application stopped syncing. Nothing alerted anyone, and the ArgoCD UI kept reporting all 16 applications `Healthy` the entire time.

The interesting part is not the crash-loop. It is that four independent safety nets — the health column, the out-of-sync alert, two other alert rules, and the notification channel — all failed in ways that were individually plausible and collectively silent.

## Timeline

| When | What |
|---|---|
| ~2026-04-13 | First `argocd-repo-server` pod enters the `copyutil` crash-loop. Syncing stops. |
| ~2026-05-12 | Second replica recreated; it lands in the same state. |
| 2026-06-25 | Commit `204d775` "alertmanager: disable Discord notifications" pushed. Never applied. |
| 2026-08-08 | Mac Mini IP change makes Ollama unreachable, prompting a cluster health check. Outage found. |
| 2026-08-08 | Pods force-deleted; fresh replicas come up healthy; all 16 apps sync within minutes. |

Only **one** config commit was pushed during the entire window. Low change velocity is why nobody noticed that pushes weren't landing — there was almost nothing to observe not happening.

## Root cause

Both repo-server pods failed on the upstream `copyutil` init container:

```
/bin/ln: Already exists
```

`copyutil` links the ArgoCD binary into a shared `emptyDir`. An `emptyDir` survives *container* restarts within a pod — it is only cleared when the pod itself is replaced. Once something restarted the container in place, the link already existed, `ln` exited non-zero, and the init container could never succeed again. The pod was permanently wedged in a state it could not retry its way out of.

The repo's own KSOPS init container (`install-ksops`, see `argo-cd/ksops-patch.yaml`) had accumulated **673 restarts** against the same volume, which is what drove the container-level restarts in the first place.

**Fix:** delete the pods so the ReplicaSet creates new ones with fresh `emptyDir` volumes. No manifest change was required — the deployment spec was never wrong.

## Why nothing caught it

### 1. Health and sync are independent

ArgoCD reported `HEALTH: Healthy` for all 16 applications throughout. That is technically correct: the workloads *were* running fine. They were simply running whatever had been applied 117 days earlier. Sync status told the real story:

```
NAME          SYNC      HEALTH
adguard       Unknown   Healthy
authentik     Unknown   Healthy
...           Unknown   Healthy      # all 16
```

A green health column is not evidence of a working control loop. It is evidence that whatever is deployed hasn't fallen over.

### 2. The alert that should have caught it was too large to send

`HomelabArgoOutOfSync` exists precisely for this condition and it *was* firing — 64 alert instances, one per out-of-sync resource. Alertmanager grouped them into a single Discord notification, and the message template rendered every alert including its full `description`. The result exceeded Discord's payload limit and failed every single delivery attempt:

```
Notify for alerts failed ... aggrGroup="{}:{alertname=\"HomelabArgoOutOfSync\"...}"
num_alerts=64 err="... unexpected status code 400:
{\"description\": [\"Must be 4096 or fewer in length.\"]}"
```

This is a feedback loop, not a coincidence. **The outage generated exactly the alert volume required to make the notification about the outage undeliverable.** The more broken the cluster got, the more certain it became that nobody would hear about it. The failures repeated every `group_interval` (5m) for as long as the retained logs go back.

### 3. Two alert rules had been firing permanently, training criticals to be ignored

Both compared cumulative or unbounded values with no time window, so once true they were true forever:

- **`HomelabBackupFailed`** — `kube_job_status_failed{namespace="backup"} > 0`. The CronJob's `failedJobsHistoryLimit: 3` retains failed Jobs indefinitely, so three failures from 88–102 days earlier kept a **critical** alert firing continuously. Backups were in fact succeeding; the three most recent runs all completed.
- **`HomelabPodCrashLooping`** — `kube_pod_container_status_restarts_total > 5`. A counter, never a rate. Eight instances were firing against pods whose last restart was in May. Actual restarts cluster-wide in the trailing hour: **zero**.

An alert that fires permanently has stopped being an alert. It is a constant, and constants get filtered out — by tooling and by people.

### 4. The fix for the alerting was itself trapped behind the outage

Commit `204d775` changed the Alertmanager receiver in June. Because repo-server was down it never reached the cluster, so the running config did not match the repo. Any reasoning from the repo about what alerting was doing would have been wrong.

## A trap worth recording

While fixing the Mac Mini IP change, the ollama Application reported `Synced` while the EndpointSlice in the cluster still held the old address.

ArgoCD's default `resource.exclusions` covers `Endpoints` and `EndpointSlice`:

```yaml
- apiGroups: ['', discovery.k8s.io]
  kinds: [Endpoints, EndpointSlice]
```

Excluded resources are not tracked, not diffed, and not applied — but their absence does not make the app `OutOfSync`, because ArgoCD isn't looking at them at all. The manual EndpointSlice in `ollama/service.yaml` had been static since bootstrap.

**For this resource, pushing to git is not enough.** After changing an external service's IP, `kubectl apply -f <service>/service.yaml` by hand. Noted in `CLAUDE.md` next to the pattern itself.

## Resolution

| Problem | Fix |
|---|---|
| repo-server wedged | Pods force-deleted; fresh `emptyDir` volumes. Verified 2/2 Ready, 0 restarts. |
| Undeliverable notifications | Message capped at 8 alerts per group; `description` dropped in favour of `summary`. |
| Delivery disabled | Root route receiver was `"null"`, so nothing was routed anywhere regardless of severity. Now routes to `discord`. |
| `HomelabBackupFailed` | Scoped to Jobs started within 24h. |
| `HomelabPodCrashLooping` | Wrapped in `increase(...[1h])`. |
| Permanently-firing k3s alerts | `kubeEtcd` / `kubeScheduler` / `kubeControllerManager` / `kubeProxy` exporters disabled. k3s embeds these and exposes no metrics endpoints, so the rules could never be anything but firing. Removed at the source rather than muted at the route. |
| Stale failed Jobs | Deleted. |

## Verification

Fixes were verified rather than assumed:

- `promtool check rules` — 20 rules, SUCCESS.
- `amtool check-config` — SUCCESS.
- `amtool config routes test` — criticals and warnings route to `discord`; k3s noise and `Watchdog` route to `null`.
- New `HomelabPodCrashLooping` expression evaluated live: **0** matching series.
- End-to-end delivery test: `alertmanager_notifications_total{integration="slack"}` incremented 22711 → 22712 while `alertmanager_notifications_failed_total` stayed flat at 20495.

Firing alerts went from ~50 to 4, of which two are `Watchdog`/`InfoInhibitor` heartbeats routed to `null` by design. The remaining two are real disk-usage warnings.

## What actually generalises

1. **Monitor the control loop, not just the workloads.** Health and sync are orthogonal signals; a dashboard that shows only health will show green through a total reconciliation outage.
2. **A permanently-firing alert is a broken alert.** Treat "has been firing for weeks" as a defect to fix, not a condition to acknowledge. Both bugs here shared one root cause: comparing a cumulative value without a time window.
3. **The notification path needs its own liveness signal.** Alerting that fails silently is worse than no alerting, because it produces false confidence. This failure mode was self-reinforcing: the worse things got, the less likely the message was to fit.
4. **Low change velocity hides broken automation.** With one commit in four months, there was almost no opportunity to notice pushes weren't landing. Infrequently-exercised automation needs an explicit heartbeat, not incidental verification.
5. **Know what your GitOps tool ignores.** `Synced` means "the resources ArgoCD tracks match" — not "the file was applied."

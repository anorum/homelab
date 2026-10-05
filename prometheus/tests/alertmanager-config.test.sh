#!/usr/bin/env bash
# Checks the Alertmanager config embedded in prometheus/kustomization.yaml.
# Needs amtool (same version as the cluster, see alertmanager_build_info) and yq v4.
#   bash prometheus/tests/alertmanager-config.test.sh
set -uo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cfg="$work/alertmanager.yaml"

yq '.helmCharts[] | select(.name == "kube-prometheus-stack") | .valuesInline.alertmanager.config' \
  "$here/kustomization.yaml" > "$cfg"

pass=0
fail=0
ok()  { echo "PASS  $1"; pass=$((pass + 1)); }
bad() { echo "FAIL  $1"; fail=$((fail + 1)); }

if amtool check-config "$cfg" > "$work/check" 2>&1; then
  ok "amtool check-config"
else
  bad "amtool check-config"; cat "$work/check"
fi

# Discord is for alerts a person should act on. Info-level alerts stay visible
# in Prometheus and Alertmanager but are never delivered.
route() {
  local want="$1"; shift
  local got
  got="$(amtool config routes test --config.file="$cfg" "$@" 2>&1)"
  if [ "$got" = "$want" ]; then ok "route $* -> $want"; else bad "route $* -> got '$got', want '$want'"; fi
}
route null    alertname=CPUThrottlingHigh severity=info namespace=authentik
route null    alertname=KubeNodePressure severity=info
route null    alertname=NodeCPUHighUsage severity=info
route discord alertname=HomelabRootDiskUsageWarning severity=warning
route discord alertname=KubePodCrashLooping severity=critical namespace=blockade
route discord alertname=SomethingWithoutSeverity
route null    alertname=Watchdog severity=none
route null    alertname=KubeMemoryOvercommit severity=warning

# Discord's Slack-compatible endpoint turns the top-level `text` field into the
# message content. Embeds (Slack attachments) are invisible to bots reading the
# channel, so the alert details must also be in message_text.
msg="$(yq '.receivers[] | select(.name == "discord") | .slack_configs[0].message_text // ""' "$cfg")"
if [ -n "$msg" ]; then ok "discord message_text is set"; else bad "discord message_text is set"; fi

if [ -n "$msg" ]; then
  # amtool's built-in sample data: firing alerts with labels and annotations.
  rendered="$(amtool template render --template.glob=/dev/null --template.text="$msg" 2>&1)"
  rc=$?
  if [ $rc -eq 0 ] && [ -n "$(echo "$rendered" | tr -d '[:space:]')" ]; then
    ok "message_text renders non-empty"
  else
    bad "message_text renders non-empty (rc=$rc)"; echo "$rendered"
  fi
  # amtool's sample alerts carry no labels, so check the template itself.
  for field in Labels.alertname Labels.severity Labels.namespace Annotations.summary; do
    case "$msg" in *"$field"*) ok "message_text includes $field" ;; *) bad "message_text includes $field" ;; esac
  done
  # Length: Discord caps content at 2000 chars. amtool's sample data is too thin
  # to test that; a real Alertmanager 0.31.1 run with 12 alerts in one group and
  # 140-char summaries rendered 1697 chars (8 shown + overflow line).
fi

echo
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]

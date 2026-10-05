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

# amtool validates with Alertmanager's own parser, but prometheus-operator
# re-parses this config strictly with its own structs before deploying it, and
# silently keeps the old config if that fails. Operator v0.89.0 (chart 82.x)
# slack_config fields, from pkg/alertmanager/types.go. Update on chart bumps.
op_slack="send_resolved http_config api_url api_url_file app_token app_token_file app_url channel username color title title_link pretext text fields short_fields footer fallback callback_id icon_emoji icon_url image_url thumb_url link_names mrkdwn_in actions timeout"
unknown=""
for k in $(yq '.receivers[].slack_configs[]? | keys | .[]' "$cfg"); do
  case " $op_slack " in *" $k "*) ;; *) unknown="$unknown $k" ;; esac
done
if [ -z "$unknown" ]; then ok "slack_configs fields known to prometheus-operator v0.89"; else bad "slack_configs fields unknown to prometheus-operator v0.89:$unknown"; fi

text="$(yq '.receivers[] | select(.name == "discord") | .slack_configs[0].text // ""' "$cfg")"
for field in Labels.alertname Labels.severity Labels.namespace Annotations.summary; do
  case "$text" in *"$field"*) ok "discord text includes $field" ;; *) bad "discord text includes $field" ;; esac
done


echo
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]

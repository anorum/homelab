#!/bin/bash
# ExecStopPost publishes public status even when the renewal process fails.
set -euo pipefail
umask 077
: "${CERTIFICATE:?}" "${ROOT_CERTIFICATE:?}" "${INTERMEDIATE_CERTIFICATE:?}"
directory=${METRICS_DIRECTORY:-/var/lib/telemetry/metrics}
staging=$(mktemp "$directory/.certificate-XXXXXXXX")
trap 'rm -f -- "$staging"' EXIT
success=0
[[ ${SERVICE_RESULT:-} != success ]] || success=1

expiry() {
    local end
    end=$(openssl x509 -in "$1" -noout -enddate 2>/dev/null) || return 1
    date -u -d "${end#notAfter=}" +%s
}

{
    printf '# HELP telemetry_certificate_expires_at_seconds Certificate expiration as Unix time; zero when unreadable.\n'
    printf '# TYPE telemetry_certificate_expires_at_seconds gauge\n'
    for kind in device intermediate root; do
        case $kind in
            device) certificate=$CERTIFICATE ;;
            intermediate) certificate=$INTERMEDIATE_CERTIFICATE ;;
            root) certificate=$ROOT_CERTIFICATE ;;
        esac
        if ! expires=$(expiry "$certificate"); then
            expires=0
            success=0
        fi
        printf 'telemetry_certificate_expires_at_seconds{certificate="%s"} %s\n' "$kind" "$expires"
    done
    printf '# HELP telemetry_certificate_check_success Whether the last renewal check and status read succeeded.\n'
    printf '# TYPE telemetry_certificate_check_success gauge\n'
    printf 'telemetry_certificate_check_success %s\n' "$success"
    printf '# HELP telemetry_certificate_check_timestamp_seconds Last completed renewal service attempt as Unix time.\n'
    printf '# TYPE telemetry_certificate_check_timestamp_seconds gauge\n'
    printf 'telemetry_certificate_check_timestamp_seconds %s\n' "$(date -u +%s)"
} > "$staging"
chmod 644 "$staging"
mv -f -- "$staging" "$directory/certificate.prom"

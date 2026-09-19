#!/bin/bash
# Same-key renewal only. Run as the owner of the certificate directory.
set -Eeuo pipefail
umask 077

: "${CERTIFICATE:?}" "${PRIVATE_KEY:?}" "${ROOT_CERTIFICATE:?}"
: "${INTERMEDIATE_CERTIFICATE:?}" "${DEVICE_CN:?}" "${CA_URL:?}"
RENEW_BEFORE=${RENEW_BEFORE:-720h}

directory=$(dirname -- "$CERTIFICATE")
exec 9>"$directory/.renew.lock"
flock -n 9
staging=$(mktemp -d "$directory/.renew-XXXXXXXX")
trap 'rm -rf -- "$staging"' EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'printf "certificate renewal failed at line %s\n" "$LINENO" >&2' ERR

key_public=$(openssl pkey -in "$PRIVATE_KEY" -passin pass: -pubout 2>/dev/null)
issuer=$(openssl x509 -in "$INTERMEDIATE_CERTIFICATE" -noout -subject -nameopt RFC2253)

validate() {
    local certificate=$1 subject actual_issuer public usages
    # Read the leaf only and supply the pinned intermediate independently.
    openssl verify -CAfile "$ROOT_CERTIFICATE" -no-CApath \
        -untrusted "$INTERMEDIATE_CERTIFICATE" -purpose sslclient "$certificate"
    subject=$(openssl x509 -in "$certificate" -noout -subject -nameopt RFC2253)
    [[ $subject == "subject=CN=$DEVICE_CN" ]]
    actual_issuer=$(openssl x509 -in "$certificate" -noout -issuer -nameopt RFC2253)
    [[ ${actual_issuer#issuer=} == "${issuer#subject=}" ]]
    public=$(openssl x509 -in "$certificate" -noout -pubkey)
    [[ $public == "$key_public" ]]
    usages=$(openssl x509 -in "$certificate" -noout \
        -ext basicConstraints,keyUsage,extendedKeyUsage)
    # step omits basicConstraints on its default leaf; reject CA=true if present.
    if grep -Fq 'CA:TRUE' <<< "$usages"; then
        return 1
    fi
    grep -Fq 'Digital Signature' <<< "$usages"
    grep -Fq 'TLS Web Client Authentication' <<< "$usages"
}

expiry() {
    local end
    end=$(openssl x509 -in "$1" -noout -enddate)
    date -u -d "${end#notAfter=}" +%s
}

# Fail early for an expired, mismatched, or incorrectly provisioned identity.
validate "$CERTIFICATE"
previous_expiry=$(expiry "$CERTIFICATE")
printf 'certificate_expires_at_seconds=%s\n' "$previous_expiry"
timeout --foreground --kill-after=5s 60s step ca renew "$CERTIFICATE" "$PRIVATE_KEY" \
    --ca-url "$CA_URL" --root "$ROOT_CERTIFICATE" \
    --expires-in "$RENEW_BEFORE" --out "$staging/certificate.crt" --force

# step succeeds without creating output when renewal is not due yet.
if [[ ! -e $staging/certificate.crt ]]; then
    printf 'renewal=not_due\n'
    exit 0
fi
validate "$staging/certificate.crt"
new_expiry=$(expiry "$staging/certificate.crt")
[[ $new_expiry -gt $previous_expiry ]]
chmod 600 "$staging/certificate.crt"
mv -f -- "$staging/certificate.crt" "$CERTIFICATE"
printf 'renewal=published certificate_expires_at_seconds=%s\n' "$new_expiry"

#!/bin/sh
set -eu
CA_CERT=$1
NSS_DIR="${HOME:?HOME must be set}/.pki/nssdb"
mkdir -p "$NSS_DIR"
if [ ! -f "$NSS_DIR/cert9.db" ]; then
    certutil -d "sql:$NSS_DIR" -N --empty-password
fi
certutil -d "sql:$NSS_DIR" -D -n localias-loophole-ca >/dev/null 2>&1 || true
certutil -d "sql:$NSS_DIR" -A -t 'C,,' -n localias-loophole-ca -i "$CA_CERT"
echo "[playwright-loophole] Trusted Root CA from $CA_CERT in $NSS_DIR"

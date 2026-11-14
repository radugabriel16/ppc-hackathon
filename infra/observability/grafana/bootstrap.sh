#!/bin/sh
set -eu
umask 077

# Generated once, kept in the Grafana data volume, and read through __FILE.
# Never print the password or place a default password in Compose/environment.
secret_file="${GF_SECURITY_ADMIN_PASSWORD__FILE:?Secret file path is required}"
if [ ! -e "$secret_file" ]; then
    mkdir -p "$(dirname "$secret_file")"
    head -c 48 /dev/urandom | base64 | tr -d '\n' > "$secret_file.tmp"
    chmod 600 "$secret_file.tmp"
    mv "$secret_file.tmp" "$secret_file"
fi
test -s "$secret_file"
chmod 600 "$secret_file"
exec /run.sh

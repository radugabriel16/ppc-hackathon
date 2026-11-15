#!/bin/sh
set -eu
umask 077

mkdir -p /run/secrets /certs
chmod 755 /run/secrets

secret() {
    name="$1"
    bytes="$2"
    if [ ! -e "/run/secrets/$name" ]; then
        openssl rand -hex "$bytes" > "/run/secrets/$name.tmp"
        mv "/run/secrets/$name.tmp" "/run/secrets/$name"
    fi
    if [ ! -s "/run/secrets/$name" ]; then
        echo "Empty secret: $name" >&2
        exit 1
    fi
    chmod 444 "/run/secrets/$name"
}

secret catalog_db_password 32
secret storage_db_password 32
secret history_db_password 32
secret history_db_reader_password 32
secret history_db_writer_password 32
secret s3_access_key_id 16
secret s3_secret_access_key 32
secret ftp_password 32
secret aes_key 32
secret aes_key_id 16
secret session_secret 32
secret cnp_hmac_key 32
secret simulator_token 32
secret operator_password 16
secret manager_password 16

if [ ! -e /run/secrets/s3.json ]; then
    cat > /run/secrets/s3.json.tmp <<EOF
{"identities":[{"name":"filegrid","credentials":[{"accessKey":"$(cat /run/secrets/s3_access_key_id)","secretKey":"$(cat /run/secrets/s3_secret_access_key)"}],"actions":["Admin","Read","Write","List","Tagging"]}]}
EOF
    mv /run/secrets/s3.json.tmp /run/secrets/s3.json
fi
test -s /run/secrets/s3.json
chmod 444 /run/secrets/s3.json

if [ ! -e /run/secrets/demo-users.txt ]; then
    {
        printf 'operator: %s\n' "$(cat /run/secrets/operator_password)"
        printf 'manager: %s\n' "$(cat /run/secrets/manager_password)"
    } > /run/secrets/demo-users.txt.tmp
    mv /run/secrets/demo-users.txt.tmp /run/secrets/demo-users.txt
fi
chmod 600 /run/secrets/demo-users.txt

if [ ! -e /certs/tls.key ] && [ ! -e /certs/tls.crt ]; then
    openssl req -x509 -nodes -newkey rsa:2048 -sha256 -days 3650 \
        -subj "/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
        -keyout /certs/tls.key.tmp -out /certs/tls.crt.tmp 2>/dev/null
    mv /certs/tls.key.tmp /certs/tls.key
    mv /certs/tls.crt.tmp /certs/tls.crt
fi
openssl x509 -in /certs/tls.crt -noout
openssl pkey -in /certs/tls.key -noout
chmod 600 /certs/tls.key
chmod 644 /certs/tls.crt
echo "Secrets and TLS certificate ready (existing values preserved)."

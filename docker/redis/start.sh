#!/bin/sh
set -eu

: "${REDIS_PASSWORD:?Set REDIS_PASSWORD before starting Redis}"

case "${REDIS_TLS_ENABLED:-false}" in
  false)
    exec redis-server --appendonly yes --requirepass "$REDIS_PASSWORD"
    ;;
  true)
    for file in /tls/fullchain.pem /tls/privkey.pem /tls/ca.crt; do
      if [ ! -s "$file" ]; then
        echo "Redis TLS is enabled but $file is missing or empty" >&2
        exit 1
      fi
    done
    exec redis-server --appendonly yes --requirepass "$REDIS_PASSWORD" \
      --tls-port 6380 \
      --tls-cert-file /tls/fullchain.pem \
      --tls-key-file /tls/privkey.pem \
      --tls-ca-cert-file /tls/ca.crt \
      --tls-auth-clients no
    ;;
  *)
    echo 'REDIS_TLS_ENABLED must be true or false' >&2
    exit 1
    ;;
esac

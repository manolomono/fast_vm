#!/usr/bin/env bash
#
# Fast VM - Docker entrypoint
# Genera certificado autofirmado si no existe y arranca uvicorn con HTTPS.
#
set -e

# Ensure /dev/net/tun exists (required for bridge/macvtap networking)
if [ ! -c /dev/net/tun ]; then
    mkdir -p /dev/net
    mknod /dev/net/tun c 10 200 2>/dev/null || true
    chmod 666 /dev/net/tun 2>/dev/null || true
fi

CERT_DIR="/app/certs"
CERT_FILE="$CERT_DIR/cert.pem"
KEY_FILE="$CERT_DIR/key.pem"

# Hostname para el certificado (por defecto: localhost)
SSL_HOSTNAME="${SSL_HOSTNAME:-localhost}"
# Desactivar SSL si el usuario lo pide explicitamente
SSL_ENABLED="${SSL_ENABLED:-true}"

generate_self_signed_cert() {
    echo "[Fast VM] Generando certificado autofirmado para: $SSL_HOSTNAME"
    mkdir -p "$CERT_DIR"

    # Construir SAN (Subject Alternative Names)
    local san="DNS:localhost,IP:127.0.0.1"
    if [ "$SSL_HOSTNAME" != "localhost" ]; then
        # Detectar si es IP o DNS
        if echo "$SSL_HOSTNAME" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
            san="$san,IP:$SSL_HOSTNAME"
        else
            san="$san,DNS:$SSL_HOSTNAME"
        fi
    fi

    openssl req -x509 -newkey rsa:2048 -nodes \
        -keyout "$KEY_FILE" \
        -out "$CERT_FILE" \
        -days 365 \
        -subj "/CN=$SSL_HOSTNAME/O=Fast VM/C=ES" \
        -addext "subjectAltName=$san" \
        2>/dev/null

    chmod 600 "$KEY_FILE"
    chmod 644 "$CERT_FILE"
    echo "[Fast VM] Certificado generado: $CERT_FILE (valido 365 dias)"
}

# Generar certificado si SSL esta habilitado y no existe
if [ "$SSL_ENABLED" = "true" ]; then
    if [ ! -f "$CERT_FILE" ] || [ ! -f "$KEY_FILE" ]; then
        generate_self_signed_cert
    else
        echo "[Fast VM] Certificado existente encontrado, reutilizando."
    fi
fi

# Construir comando uvicorn
UVICORN_ARGS=(
    "app.main:app"
    "--host" "0.0.0.0"
    "--port" "8000"
)

if [ "$SSL_ENABLED" = "true" ] && [ -f "$CERT_FILE" ] && [ -f "$KEY_FILE" ]; then
    UVICORN_ARGS+=("--ssl-keyfile" "$KEY_FILE" "--ssl-certfile" "$CERT_FILE")
    echo "[Fast VM] Arrancando con HTTPS en https://$SSL_HOSTNAME:8000"
else
    echo "[Fast VM] Arrancando con HTTP en http://0.0.0.0:8000"
fi

exec uvicorn "${UVICORN_ARGS[@]}"

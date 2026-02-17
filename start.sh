#!/bin/bash

# Fast VM - Start Script
# Este script inicia el servidor FastAPI

set -e

echo "================================"
echo "      Fast VM - Iniciando"
echo "================================"
echo ""

# Check if virtual environment exists
if [ ! -d "backend/venv" ]; then
    echo "⚠️  Entorno virtual no encontrado. Creando..."
    cd backend
    python3 -m venv venv
    source venv/bin/activate
    echo "📦 Instalando dependencias..."
    pip install -r requirements.txt
    cd ..
    echo "✅ Entorno configurado"
    echo ""
fi

# Activate virtual environment
echo "🔧 Activando entorno virtual..."
source backend/venv/bin/activate

# Check if QEMU is installed
if ! command -v qemu-system-x86_64 &> /dev/null; then
    echo "⚠️  ADVERTENCIA: qemu-system-x86_64 no encontrado"
    echo "   Instala QEMU para poder crear VMs:"
    echo "   Ubuntu/Debian: sudo apt install qemu-kvm qemu-system-x86 qemu-utils"
    echo "   Fedora/RHEL: sudo dnf install qemu-kvm qemu-img"
    echo ""
fi

# Create necessary directories
mkdir -p vms images

# Find a free port starting from 8000
find_free_port() {
    local port="${1:-8000}"
    local max_port=$((port + 100))
    while [ "$port" -lt "$max_port" ]; do
        if ! ss -tlnH "sport = :$port" 2>/dev/null | grep -q ":$port" && \
           ! ss -tlnH4 2>/dev/null | grep -q ":$port "; then
            # Double-check with a quick connect attempt
            if ! (echo >/dev/tcp/127.0.0.1/$port) 2>/dev/null; then
                echo "$port"
                return 0
            fi
        fi
        port=$((port + 1))
    done
    echo "8000"
    return 1
}

API_PORT=$(find_free_port 8000)

# Start the server
echo "🚀 Iniciando servidor Fast VM..."
echo ""
echo "   URL: http://localhost:${API_PORT}"
echo "   API Docs: http://localhost:${API_PORT}/docs"
if [ "$API_PORT" -ne 8000 ]; then
    echo "   ⚠️  Puerto 8000 ocupado, usando ${API_PORT}"
fi
echo ""
echo "   Presiona Ctrl+C para detener"
echo ""

cd backend
uvicorn app.main:app --host 0.0.0.0 --port "$API_PORT"

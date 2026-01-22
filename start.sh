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

# Start the server
echo "🚀 Iniciando servidor Fast VM..."
echo ""
echo "   URL: http://localhost:8000"
echo "   API Docs: http://localhost:8000/docs"
echo ""
echo "   Presiona Ctrl+C para detener"
echo ""

cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000

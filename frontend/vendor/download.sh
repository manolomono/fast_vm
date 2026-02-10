#!/usr/bin/env bash
# Descarga las dependencias del frontend localmente.
# Ejecutar desde el directorio frontend/vendor/
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "Descargando dependencias del frontend..."

# Alpine.js
if [ ! -s alpine.min.js ]; then
    echo "  -> Alpine.js 3.14..."
    curl -sL -o alpine.min.js "https://cdn.jsdelivr.net/npm/alpinejs@3.14.9/dist/cdn.min.js" \
        || wget -q -O alpine.min.js "https://cdn.jsdelivr.net/npm/alpinejs@3.14.9/dist/cdn.min.js"
fi

# Chart.js
if [ ! -s chart.umd.min.js ]; then
    echo "  -> Chart.js 4..."
    curl -sL -o chart.umd.min.js "https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js" \
        || wget -q -O chart.umd.min.js "https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"
fi

# Tailwind CSS (browser build)
if [ ! -s tailwind.js ]; then
    echo "  -> Tailwind CSS 3.4..."
    curl -sL -o tailwind.js "https://cdn.tailwindcss.com/3.4.17" \
        || wget -q -O tailwind.js "https://cdn.tailwindcss.com/3.4.17"
fi

echo "Dependencias descargadas en $DIR"
ls -lh *.js 2>/dev/null || echo "(sin archivos)"

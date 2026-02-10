#!/usr/bin/env bash
#
# Fast VM - Instalador interactivo para Linux
# Configura dependencias, red y arranca el servicio.
#
set -euo pipefail

# ===================== Colores =====================
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; }

header() {
    echo ""
    echo -e "${BOLD}╔══════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║     ${CYAN}Fast VM${NC}${BOLD} - Instalador Interactivo        ║${NC}"
    echo -e "${BOLD}║     Gestor de VMs QEMU/KVM                  ║${NC}"
    echo -e "${BOLD}╚══════════════════════════════════════════════╝${NC}"
    echo ""
}

# ===================== Deteccion de distro =====================
detect_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        DISTRO_ID="${ID:-unknown}"
        DISTRO_NAME="${PRETTY_NAME:-$ID}"
    elif command -v lsb_release &>/dev/null; then
        DISTRO_ID=$(lsb_release -si | tr '[:upper:]' '[:lower:]')
        DISTRO_NAME=$(lsb_release -sd)
    else
        DISTRO_ID="unknown"
        DISTRO_NAME="Unknown Linux"
    fi

    # Familia de paquetes
    if command -v apt-get &>/dev/null; then
        PKG_MANAGER="apt"
    elif command -v dnf &>/dev/null; then
        PKG_MANAGER="dnf"
    elif command -v yum &>/dev/null; then
        PKG_MANAGER="yum"
    elif command -v pacman &>/dev/null; then
        PKG_MANAGER="pacman"
    elif command -v zypper &>/dev/null; then
        PKG_MANAGER="zypper"
    else
        PKG_MANAGER="unknown"
    fi
}

# ===================== Comprobacion root =====================
check_root() {
    if [ "$EUID" -ne 0 ]; then
        error "Este script necesita permisos de root."
        echo "Ejecuta: sudo $0"
        exit 1
    fi
}

# ===================== Instalar paquetes =====================
install_packages() {
    local packages=("$@")
    info "Instalando: ${packages[*]}"

    case "$PKG_MANAGER" in
        apt)
            apt-get update -qq
            DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${packages[@]}"
            ;;
        dnf)
            dnf install -y -q "${packages[@]}"
            ;;
        yum)
            yum install -y -q "${packages[@]}"
            ;;
        pacman)
            pacman -Sy --noconfirm "${packages[@]}"
            ;;
        zypper)
            zypper install -y "${packages[@]}"
            ;;
        *)
            error "Gestor de paquetes no soportado: $PKG_MANAGER"
            echo "Instala manualmente: ${packages[*]}"
            return 1
            ;;
    esac
}

# ===================== Preguntas interactivas =====================
ask_yes_no() {
    local prompt="$1"
    local default="${2:-y}"
    local answer

    if [ "$default" = "y" ]; then
        prompt="$prompt [S/n]: "
    else
        prompt="$prompt [s/N]: "
    fi

    read -rp "$(echo -e "${BOLD}$prompt${NC}")" answer
    answer="${answer:-$default}"
    [[ "$answer" =~ ^[SsYy]$ ]]
}

ask_choice() {
    local prompt="$1"
    shift
    local options=("$@")
    local i=1

    echo -e "\n${BOLD}$prompt${NC}"
    for opt in "${options[@]}"; do
        echo "  $i) $opt"
        ((i++))
    done

    local choice
    read -rp "$(echo -e "${BOLD}Selecciona [1-${#options[@]}]: ${NC}")" choice
    echo "$choice"
}

# ===================== Paso 1: Dependencias del sistema =====================
step_system_deps() {
    echo ""
    echo -e "${BOLD}=== Paso 1/5: Dependencias del Sistema ===${NC}"
    echo ""

    # Paquetes base segun distro
    local base_pkgs=()
    local qemu_pkgs=()
    local extra_pkgs=()

    case "$PKG_MANAGER" in
        apt)
            base_pkgs=(python3 python3-pip python3-venv git curl wget)
            qemu_pkgs=(qemu-system-x86 qemu-utils ovmf swtpm)
            extra_pkgs=(bridge-utils net-tools genisoimage)
            ;;
        dnf|yum)
            base_pkgs=(python3 python3-pip git curl wget)
            qemu_pkgs=(qemu-kvm qemu-img edk2-ovmf swtpm swtpm-tools)
            extra_pkgs=(bridge-utils net-tools genisoimage)
            ;;
        pacman)
            base_pkgs=(python python-pip git curl wget)
            qemu_pkgs=(qemu-full edk2-ovmf swtpm)
            extra_pkgs=(bridge-utils net-tools cdrtools)
            ;;
        zypper)
            base_pkgs=(python3 python3-pip git curl wget)
            qemu_pkgs=(qemu-kvm qemu-tools ovmf swtpm)
            extra_pkgs=(bridge-utils net-tools genisoimage)
            ;;
    esac

    # Comprobar QEMU
    if command -v qemu-system-x86_64 &>/dev/null; then
        success "QEMU ya instalado: $(qemu-system-x86_64 --version | head -1)"
    else
        warn "QEMU no encontrado."
        if ask_yes_no "Instalar QEMU y dependencias de virtualizacion?"; then
            install_packages "${qemu_pkgs[@]}"
            success "QEMU instalado"
        else
            warn "Saltando instalacion de QEMU. Las VMs no funcionaran."
        fi
    fi

    # Comprobar KVM
    if [ -c /dev/kvm ]; then
        success "KVM disponible (/dev/kvm existe)"
    else
        warn "KVM no disponible. Las VMs funcionaran sin aceleracion hardware (lento)."
        info "Asegurate de que la virtualizacion esta habilitada en la BIOS/UEFI."
    fi

    # Comprobar Python
    if command -v python3 &>/dev/null; then
        success "Python3: $(python3 --version)"
    else
        info "Instalando Python3..."
        install_packages "${base_pkgs[@]}"
    fi

    # Paquetes extra
    if ask_yes_no "Instalar paquetes extra (bridge-utils, genisoimage)?"; then
        install_packages "${extra_pkgs[@]}" 2>/dev/null || warn "Algunos paquetes no se pudieron instalar"
    fi

    # OVMF (UEFI firmware)
    if ls /usr/share/OVMF/OVMF_CODE*.fd &>/dev/null 2>&1 || \
       ls /usr/share/qemu/OVMF_CODE*.fd &>/dev/null 2>&1; then
        success "Firmware UEFI (OVMF) disponible"
    else
        warn "Firmware UEFI no encontrado. Las VMs con UEFI (Windows 11) no funcionaran."
    fi
}

# ===================== Paso 2: Docker =====================
step_docker() {
    echo ""
    echo -e "${BOLD}=== Paso 2/5: Docker (Opcional) ===${NC}"
    echo ""

    if command -v docker &>/dev/null; then
        success "Docker ya instalado: $(docker --version)"
        if command -v docker-compose &>/dev/null || docker compose version &>/dev/null 2>&1; then
            success "Docker Compose disponible"
        fi
    else
        info "Fast VM puede ejecutarse con Docker o directamente."
        if ask_yes_no "Instalar Docker?"; then
            info "Instalando Docker..."
            curl -fsSL https://get.docker.com | sh
            systemctl enable --now docker
            success "Docker instalado y activado"

            # Agregar usuario actual al grupo docker
            local real_user="${SUDO_USER:-$USER}"
            if [ "$real_user" != "root" ]; then
                usermod -aG docker "$real_user"
                info "Usuario '$real_user' agregado al grupo 'docker'"
                warn "Necesitas cerrar e iniciar sesion de nuevo para que surta efecto."
            fi
        else
            info "Saltando Docker. Usaras ejecucion directa."
        fi
    fi
}

# ===================== Paso 3: Configuracion de Red =====================
step_networking() {
    echo ""
    echo -e "${BOLD}=== Paso 3/5: Configuracion de Red ===${NC}"
    echo ""

    info "Interfaces de red detectadas:"
    echo ""
    ip -br link show | grep -v lo | while read -r name state _; do
        if [ "$state" = "UP" ]; then
            echo -e "  ${GREEN}$name${NC} (activa)"
        else
            echo -e "  ${YELLOW}$name${NC} (inactiva)"
        fi
    done
    echo ""

    # Bridges existentes
    local bridges
    bridges=$(ip -br link show type bridge 2>/dev/null | awk '{print $1}' || true)
    if [ -n "$bridges" ]; then
        success "Bridges existentes: $bridges"
    else
        info "No se detectaron bridges de red."
    fi

    echo ""
    echo "Modos de red disponibles en Fast VM:"
    echo "  1) NAT (por defecto, sin configuracion extra)"
    echo "  2) Bridge (la VM obtiene IP de tu red local)"
    echo "  3) Macvtap (conexion directa sin bridge)"
    echo ""

    if ask_yes_no "Configurar un bridge de red ahora?" "n"; then
        configure_bridge
    else
        info "Puedes configurar la red mas tarde desde la interfaz web de Fast VM."
    fi
}

configure_bridge() {
    echo ""
    info "Interfaces fisicas disponibles:"
    local ifaces=()
    while IFS= read -r line; do
        name=$(echo "$line" | awk '{print $1}')
        state=$(echo "$line" | awk '{print $2}')
        [[ "$name" == "lo" ]] && continue
        [[ "$name" == veth* ]] && continue
        [[ "$name" == docker* ]] && continue
        [[ "$name" == br-* ]] && continue
        ifaces+=("$name ($state)")
    done < <(ip -br link show 2>/dev/null)

    if [ ${#ifaces[@]} -eq 0 ]; then
        warn "No se encontraron interfaces fisicas."
        return
    fi

    local i=1
    for iface in "${ifaces[@]}"; do
        echo "  $i) $iface"
        ((i++))
    done

    local choice
    read -rp "$(echo -e "${BOLD}Selecciona la interfaz para el bridge [1-${#ifaces[@]}]: ${NC}")" choice
    choice="${choice:-1}"

    if [[ "$choice" -lt 1 || "$choice" -gt ${#ifaces[@]} ]]; then
        warn "Seleccion invalida. Saltando configuracion del bridge."
        return
    fi

    local selected="${ifaces[$((choice-1))]}"
    local parent_iface
    parent_iface=$(echo "$selected" | awk '{print $1}')

    local bridge_name
    read -rp "$(echo -e "${BOLD}Nombre del bridge [br0]: ${NC}")" bridge_name
    bridge_name="${bridge_name:-br0}"

    info "Creando bridge '$bridge_name' con interfaz '$parent_iface'..."

    # Crear bridge
    ip link add name "$bridge_name" type bridge 2>/dev/null || true
    ip link set "$parent_iface" master "$bridge_name" 2>/dev/null || true
    ip link set "$bridge_name" up

    # Mover IP si la interfaz tenia una
    local ip_addr
    ip_addr=$(ip -4 addr show "$parent_iface" | grep inet | awk '{print $2}' | head -1)
    if [ -n "$ip_addr" ]; then
        warn "Moviendo IP $ip_addr de $parent_iface a $bridge_name"
        warn "ATENCION: Esto puede desconectar temporalmente tu sesion SSH."
        if ask_yes_no "Continuar?"; then
            ip addr del "$ip_addr" dev "$parent_iface" 2>/dev/null || true
            ip addr add "$ip_addr" dev "$bridge_name"
            # Restaurar ruta por defecto via bridge
            local gateway
            gateway=$(ip route | grep default | awk '{print $3}' | head -1)
            if [ -n "$gateway" ]; then
                ip route del default 2>/dev/null || true
                ip route add default via "$gateway" dev "$bridge_name"
            fi
            success "IP movida al bridge"
        else
            info "IP no movida. Configuralo manualmente despues."
        fi
    fi

    # Configurar QEMU bridge helper
    mkdir -p /etc/qemu
    echo "allow $bridge_name" > /etc/qemu/bridge.conf
    success "Bridge '$bridge_name' creado"

    # SetUID para qemu-bridge-helper
    local bridge_helper
    for helper_path in /usr/lib/qemu/qemu-bridge-helper /usr/libexec/qemu-bridge-helper; do
        if [ -f "$helper_path" ]; then
            bridge_helper="$helper_path"
            break
        fi
    done

    if [ -n "${bridge_helper:-}" ]; then
        chmod u+s "$bridge_helper"
        success "Permisos setuid configurados en $bridge_helper"
    else
        warn "qemu-bridge-helper no encontrado. El bridge puede no funcionar sin configuracion adicional."
    fi

    echo ""
    info "Para hacer la configuracion del bridge persistente, anade a /etc/network/interfaces"
    info "o crea un archivo netplan/NetworkManager. Consulta la documentacion de tu distro."
}

# ===================== Paso 4: Instalacion de Fast VM =====================
step_install_fastvm() {
    echo ""
    echo -e "${BOLD}=== Paso 4/5: Instalacion de Fast VM ===${NC}"
    echo ""

    # Determinar directorio de instalacion
    local install_dir
    local default_dir="/opt/fast-vm"
    read -rp "$(echo -e "${BOLD}Directorio de instalacion [$default_dir]: ${NC}")" install_dir
    install_dir="${install_dir:-$default_dir}"

    INSTALL_DIR="$install_dir"

    if [ -d "$install_dir" ] && [ -f "$install_dir/docker-compose.yml" ]; then
        success "Fast VM ya esta instalado en $install_dir"
        if ask_yes_no "Actualizar instalacion existente?"; then
            cd "$install_dir"
            if [ -d .git ]; then
                git pull
                success "Codigo actualizado"
            fi
        fi
    else
        # Copiar archivos del proyecto actual o clonar
        local script_dir
        script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

        if [ -f "$script_dir/docker-compose.yml" ]; then
            info "Copiando archivos desde $script_dir..."
            mkdir -p "$install_dir"
            cp -r "$script_dir"/* "$install_dir"/
            cp -r "$script_dir"/.* "$install_dir"/ 2>/dev/null || true
            success "Archivos copiados a $install_dir"
        else
            error "No se encontraron los archivos del proyecto."
            error "Ejecuta este script desde el directorio raiz del proyecto Fast VM."
            exit 1
        fi
    fi

    # Crear directorios de datos
    mkdir -p "$install_dir"/{vms,images,data,backups}
    success "Directorios de datos creados"

    # Descargar dependencias frontend (Alpine.js, Chart.js, Tailwind)
    info "Descargando dependencias del frontend..."
    if [ -x "$install_dir/frontend/vendor/download.sh" ]; then
        bash "$install_dir/frontend/vendor/download.sh"
        success "Dependencias frontend descargadas"
    else
        warn "Script de descarga no encontrado. Ejecuta: bash frontend/vendor/download.sh"
    fi

    # Generar JWT secret
    local jwt_secret
    jwt_secret=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || openssl rand -hex 32)

    # Crear .env
    if [ ! -f "$install_dir/.env" ]; then
        cat > "$install_dir/.env" <<EOF
JWT_SECRET_KEY=$jwt_secret
FASTVM_PRODUCTION=
CORS_ORIGINS=*
EOF
        success "Archivo .env creado con clave JWT segura"
    else
        info "Archivo .env ya existe, no se modifica"
    fi

    # Instalar dependencias Python si no usa Docker
    if command -v docker &>/dev/null && ask_yes_no "Usar Docker para ejecutar Fast VM? (recomendado)"; then
        USE_DOCKER=true
        info "Se usara Docker"
    else
        USE_DOCKER=false
        info "Instalando dependencias Python..."
        cd "$install_dir/backend"

        if [ -f requirements.txt ]; then
            pip3 install -r requirements.txt 2>/dev/null || pip install -r requirements.txt
            success "Dependencias Python instaladas"
        fi
    fi
}

# ===================== Paso 5: Arranque =====================
step_start_service() {
    echo ""
    echo -e "${BOLD}=== Paso 5/5: Arranque del Servicio ===${NC}"
    echo ""

    cd "$INSTALL_DIR"

    if [ "${USE_DOCKER:-false}" = true ]; then
        info "Construyendo y arrancando con Docker..."
        if docker compose version &>/dev/null 2>&1; then
            docker compose up -d --build
        else
            docker-compose up -d --build
        fi
        success "Fast VM arrancado con Docker"
    else
        # Crear servicio systemd
        if ask_yes_no "Crear servicio systemd para arranque automatico?"; then
            create_systemd_service
        fi

        info "Arrancando Fast VM..."
        cd "$INSTALL_DIR/backend"

        if systemctl is-active --quiet fast-vm 2>/dev/null; then
            systemctl restart fast-vm
            success "Servicio reiniciado"
        else
            # Arrancar en foreground o background
            nohup python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > "$INSTALL_DIR/fast-vm.log" 2>&1 &
            success "Fast VM arrancado (PID: $!)"
        fi
    fi
}

create_systemd_service() {
    local real_user="${SUDO_USER:-$USER}"

    cat > /etc/systemd/system/fast-vm.service <<EOF
[Unit]
Description=Fast VM - QEMU Virtual Machine Manager
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=$real_user
WorkingDirectory=$INSTALL_DIR/backend
ExecStart=/usr/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
Environment=JWT_SECRET_KEY=$(grep JWT_SECRET_KEY "$INSTALL_DIR/.env" 2>/dev/null | cut -d= -f2 || echo "change-me")

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable fast-vm
    success "Servicio systemd 'fast-vm' creado y habilitado"
}

# ===================== Resumen final =====================
show_summary() {
    local ip_addr
    ip_addr=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")

    echo ""
    echo -e "${BOLD}╔══════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║     ${GREEN}Instalacion completada${NC}${BOLD}                    ║${NC}"
    echo -e "${BOLD}╚══════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  ${BOLD}URL:${NC}        http://${ip_addr}:8000"
    echo -e "  ${BOLD}Usuario:${NC}    admin"
    echo -e "  ${BOLD}Password:${NC}   admin"
    echo -e "  ${BOLD}Directorio:${NC} $INSTALL_DIR"
    echo ""
    echo -e "  ${YELLOW}IMPORTANTE:${NC} Cambia la password del admin al primer acceso."
    echo ""

    if [ "${USE_DOCKER:-false}" = true ]; then
        echo -e "  ${BOLD}Comandos utiles:${NC}"
        echo "    docker compose logs -f        Ver logs"
        echo "    docker compose restart         Reiniciar"
        echo "    docker compose down            Detener"
    else
        echo -e "  ${BOLD}Comandos utiles:${NC}"
        echo "    systemctl status fast-vm       Ver estado"
        echo "    systemctl restart fast-vm      Reiniciar"
        echo "    journalctl -u fast-vm -f       Ver logs"
    fi
    echo ""

    # Comprobar si el servicio esta respondiendo
    sleep 2
    if curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/api/health" 2>/dev/null | grep -q "200"; then
        success "Fast VM esta funcionando correctamente"
    else
        warn "El servicio puede tardar unos segundos en arrancar."
        info "Comprueba: curl http://localhost:8000/api/health"
    fi
}

# ===================== Main =====================
main() {
    header
    check_root
    detect_distro
    info "Sistema detectado: $DISTRO_NAME ($PKG_MANAGER)"
    echo ""

    step_system_deps
    step_docker
    step_networking
    step_install_fastvm
    step_start_service
    show_summary
}

main "$@"

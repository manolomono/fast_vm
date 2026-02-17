#!/usr/bin/env bash
#
# Fast VM - Desinstalador interactivo para Linux
# Detiene servicios, elimina datos y limpia configuracion.
#
set -euo pipefail

# ===================== Modo no interactivo =====================
NO_INPUT=false
for arg in "$@"; do
    case "$arg" in
        --no-input) NO_INPUT=true ;;
    esac
done

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
    echo -e "${BOLD}║     ${RED}Fast VM${NC}${BOLD} - Desinstalador                  ║${NC}"
    echo -e "${BOLD}║     Gestor de VMs QEMU/KVM                  ║${NC}"
    echo -e "${BOLD}╚══════════════════════════════════════════════╝${NC}"
    echo ""
}

# ===================== Comprobacion root =====================
check_root() {
    if [ "$EUID" -ne 0 ]; then
        error "Este script necesita permisos de root."
        echo "Ejecuta: sudo $0"
        exit 1
    fi
}

# ===================== Preguntas interactivas =====================
ask_yes_no() {
    local prompt="$1"
    local default="${2:-n}"
    local answer

    if [ "$NO_INPUT" = true ]; then
        [[ "$default" =~ ^[SsYy]$ ]]
        return
    fi

    if [ "$default" = "y" ]; then
        prompt="$prompt [S/n]: "
    else
        prompt="$prompt [s/N]: "
    fi

    read -rp "$(echo -e "${BOLD}$prompt${NC}")" answer
    answer="${answer:-$default}"
    [[ "$answer" =~ ^[SsYy]$ ]]
}

# ===================== Detectar instalacion =====================
detect_install() {
    INSTALL_DIR=""
    INSTALL_MODE=""  # "docker" o "native"

    # Buscar en ubicaciones comunes
    local search_dirs=("/opt/fast-vm" "$(pwd)")

    # Si se pasa como argumento
    if [ -n "${1:-}" ] && [ -d "$1" ]; then
        search_dirs=("$1" "${search_dirs[@]}")
    fi

    for dir in "${search_dirs[@]}"; do
        if [ -f "$dir/docker-compose.yml" ] && [ -d "$dir/backend" ]; then
            INSTALL_DIR="$dir"
            break
        fi
    done

    if [ -z "$INSTALL_DIR" ]; then
        if [ "$NO_INPUT" = true ]; then
            error "No se encontro una instalacion de Fast VM en /opt/fast-vm ni en el directorio actual."
            exit 1
        fi
        warn "No se encontro una instalacion de Fast VM automaticamente."
        local custom_dir
        read -rp "$(echo -e "${BOLD}Introduce el directorio de instalacion: ${NC}")" custom_dir
        if [ -d "$custom_dir" ] && [ -f "$custom_dir/docker-compose.yml" ]; then
            INSTALL_DIR="$custom_dir"
        else
            error "Directorio invalido o no contiene Fast VM."
            exit 1
        fi
    fi

    success "Instalacion encontrada: $INSTALL_DIR"

    # Detectar modo: Docker o nativo
    if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q '^fast-vm$'; then
        INSTALL_MODE="docker"
        info "Modo detectado: Docker"
    elif systemctl list-unit-files fast-vm.service &>/dev/null 2>&1; then
        INSTALL_MODE="native"
        info "Modo detectado: Nativo (systemd)"
    else
        INSTALL_MODE="unknown"
        info "Modo detectado: Manual / desconocido"
    fi
}

# ===================== Paso 1: Parar servicios =====================
step_stop_services() {
    echo ""
    echo -e "${BOLD}=== Paso 1/4: Detener Servicios ===${NC}"
    echo ""

    # Parar procesos QEMU de VMs gestionadas por Fast VM
    local qemu_pids
    qemu_pids=$(pgrep -f "qemu-system.*-name fast_vm" 2>/dev/null || true)
    if [ -n "$qemu_pids" ]; then
        local count
        count=$(echo "$qemu_pids" | wc -l)
        warn "Se encontraron $count VM(s) QEMU en ejecucion gestionadas por Fast VM."
        if ask_yes_no "Detener todas las VMs?"; then
            echo "$qemu_pids" | while read -r pid; do
                kill "$pid" 2>/dev/null || true
            done
            sleep 2
            # SIGKILL si no responden
            echo "$qemu_pids" | while read -r pid; do
                if kill -0 "$pid" 2>/dev/null; then
                    kill -9 "$pid" 2>/dev/null || true
                fi
            done
            success "VMs detenidas"
        else
            warn "Las VMs siguen en ejecucion. Pueden quedar procesos huerfanos."
        fi
    else
        info "No hay VMs en ejecucion."
    fi

    # Docker
    if [ "$INSTALL_MODE" = "docker" ]; then
        info "Deteniendo contenedor Docker..."
        cd "$INSTALL_DIR"
        if docker compose version &>/dev/null 2>&1; then
            docker compose down 2>/dev/null || true
        else
            docker-compose down 2>/dev/null || true
        fi
        success "Contenedor Docker detenido y eliminado"
    fi

    # Systemd
    if systemctl is-active --quiet fast-vm 2>/dev/null; then
        info "Deteniendo servicio systemd..."
        systemctl stop fast-vm
        success "Servicio detenido"
    fi

    # Proceso uvicorn suelto
    local uvicorn_pids
    uvicorn_pids=$(pgrep -f "uvicorn.*app\.main:app" 2>/dev/null || true)
    if [ -n "$uvicorn_pids" ]; then
        info "Deteniendo proceso uvicorn..."
        echo "$uvicorn_pids" | while read -r pid; do
            kill "$pid" 2>/dev/null || true
        done
        success "Proceso uvicorn detenido"
    fi
}

# ===================== Paso 2: Eliminar servicio systemd =====================
step_remove_systemd() {
    echo ""
    echo -e "${BOLD}=== Paso 2/4: Eliminar Servicio Systemd ===${NC}"
    echo ""

    if [ -f /etc/systemd/system/fast-vm.service ]; then
        info "Eliminando servicio systemd 'fast-vm'..."
        systemctl disable fast-vm 2>/dev/null || true
        rm -f /etc/systemd/system/fast-vm.service
        systemctl daemon-reload
        success "Servicio systemd eliminado"
    else
        info "No se encontro servicio systemd de Fast VM."
    fi
}

# ===================== Paso 3: Docker cleanup =====================
step_docker_cleanup() {
    echo ""
    echo -e "${BOLD}=== Paso 3/4: Limpiar Docker ===${NC}"
    echo ""

    if ! command -v docker &>/dev/null; then
        info "Docker no instalado. Saltando."
        return
    fi

    # Eliminar imagen
    local image_ids
    image_ids=$(docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' 2>/dev/null | grep -E 'fast-vm|fast_vm' | awk '{print $2}' || true)

    if [ -n "$image_ids" ]; then
        if ask_yes_no "Eliminar imagenes Docker de Fast VM?"; then
            echo "$image_ids" | while read -r img_id; do
                docker rmi -f "$img_id" 2>/dev/null || true
            done
            success "Imagenes Docker eliminadas"
        else
            info "Imagenes Docker conservadas."
        fi
    else
        info "No se encontraron imagenes Docker de Fast VM."
    fi

    # Volumenes huerfanos
    local orphan_vols
    orphan_vols=$(docker volume ls --filter dangling=true -q 2>/dev/null || true)
    if [ -n "$orphan_vols" ]; then
        info "Se encontraron volumenes Docker huerfanos (no necesariamente de Fast VM)."
        if ask_yes_no "Limpiar volumenes huerfanos?" "n"; then
            docker volume prune -f 2>/dev/null || true
            success "Volumenes huerfanos eliminados"
        fi
    fi
}

# ===================== Paso 4: Eliminar archivos =====================
step_remove_files() {
    echo ""
    echo -e "${BOLD}=== Paso 4/4: Eliminar Archivos ===${NC}"
    echo ""

    # Mostrar resumen de lo que hay
    echo -e "  ${BOLD}Directorio:${NC} $INSTALL_DIR"
    echo ""

    local has_vms=false
    local has_images=false
    local has_backups=false
    local has_data=false

    if [ -d "$INSTALL_DIR/vms" ] && [ "$(ls -A "$INSTALL_DIR/vms" 2>/dev/null)" ]; then
        local vm_count
        vm_count=$(ls -1d "$INSTALL_DIR"/vms/*/ 2>/dev/null | wc -l || echo "0")
        local vms_size
        vms_size=$(du -sh "$INSTALL_DIR/vms" 2>/dev/null | awk '{print $1}' || echo "?")
        echo -e "  ${YELLOW}Discos de VMs:${NC}  $vm_count VM(s), $vms_size"
        has_vms=true
    fi

    if [ -d "$INSTALL_DIR/images" ] && [ "$(ls -A "$INSTALL_DIR/images" 2>/dev/null)" ]; then
        local images_size
        images_size=$(du -sh "$INSTALL_DIR/images" 2>/dev/null | awk '{print $1}' || echo "?")
        echo -e "  ${YELLOW}Imagenes ISO:${NC}   $images_size"
        has_images=true
    fi

    if [ -d "$INSTALL_DIR/backups" ] && [ "$(ls -A "$INSTALL_DIR/backups" 2>/dev/null)" ]; then
        local backups_size
        backups_size=$(du -sh "$INSTALL_DIR/backups" 2>/dev/null | awk '{print $1}' || echo "?")
        echo -e "  ${YELLOW}Backups:${NC}        $backups_size"
        has_backups=true
    fi

    if [ -d "$INSTALL_DIR/data" ] && [ "$(ls -A "$INSTALL_DIR/data" 2>/dev/null)" ]; then
        local data_size
        data_size=$(du -sh "$INSTALL_DIR/data" 2>/dev/null | awk '{print $1}' || echo "?")
        echo -e "  ${YELLOW}Base de datos:${NC} $data_size"
        has_data=true
    fi

    echo ""

    # Preguntar que eliminar
    if [ "$has_vms" = true ]; then
        echo ""
        warn "Los discos de las VMs contienen los sistemas operativos instalados."
        if ask_yes_no "Eliminar discos de VMs? (IRREVERSIBLE)"; then
            rm -rf "$INSTALL_DIR/vms"
            success "Discos de VMs eliminados"
        else
            info "Discos de VMs conservados en: $INSTALL_DIR/vms"
        fi
    fi

    if [ "$has_images" = true ]; then
        if ask_yes_no "Eliminar imagenes ISO descargadas?"; then
            rm -rf "$INSTALL_DIR/images"
            success "Imagenes ISO eliminadas"
        else
            info "Imagenes conservadas en: $INSTALL_DIR/images"
        fi
    fi

    if [ "$has_backups" = true ]; then
        if ask_yes_no "Eliminar backups?"; then
            rm -rf "$INSTALL_DIR/backups"
            success "Backups eliminados"
        else
            info "Backups conservados en: $INSTALL_DIR/backups"
        fi
    fi

    # Eliminar el resto (codigo, config, certs, datos)
    echo ""
    if ask_yes_no "Eliminar codigo, configuracion, certificados SSL y base de datos de Fast VM?" "y"; then
        # Conservar los directorios que el usuario decidio mantener
        local keep_dirs=()
        [ -d "$INSTALL_DIR/vms" ] && keep_dirs+=("$INSTALL_DIR/vms")
        [ -d "$INSTALL_DIR/images" ] && keep_dirs+=("$INSTALL_DIR/images")
        [ -d "$INSTALL_DIR/backups" ] && keep_dirs+=("$INSTALL_DIR/backups")

        if [ ${#keep_dirs[@]} -eq 0 ]; then
            # Nada que conservar, eliminar todo el directorio
            rm -rf "$INSTALL_DIR"
            success "Directorio $INSTALL_DIR eliminado completamente"
        else
            # Eliminar todo excepto los directorios conservados
            find "$INSTALL_DIR" -mindepth 1 -maxdepth 1 \
                ! -name "vms" ! -name "images" ! -name "backups" \
                -exec rm -rf {} + 2>/dev/null || true
            success "Codigo y configuracion eliminados"
            info "Directorios conservados:"
            for d in "${keep_dirs[@]}"; do
                echo "    $d"
            done
        fi
    else
        info "Archivos de Fast VM conservados en: $INSTALL_DIR"
    fi

    # Limpiar config QEMU bridge
    if [ -f /etc/qemu/bridge.conf ]; then
        if grep -q "# Fast VM" /etc/qemu/bridge.conf 2>/dev/null || \
           ask_yes_no "Limpiar /etc/qemu/bridge.conf?" "n"; then
            rm -f /etc/qemu/bridge.conf
            success "/etc/qemu/bridge.conf eliminado"
        fi
    fi
}

# ===================== Resumen final =====================
show_summary() {
    echo ""
    echo -e "${BOLD}╔══════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║     ${GREEN}Desinstalacion completada${NC}${BOLD}                 ║${NC}"
    echo -e "${BOLD}╚══════════════════════════════════════════════╝${NC}"
    echo ""

    info "Fast VM ha sido desinstalado."
    echo ""
    echo -e "  ${BOLD}No se han eliminado:${NC}"
    echo "    - Paquetes del sistema (QEMU, Python, Docker, etc.)"
    echo "    - Configuracion de red (bridges)"
    echo "    - Docker Engine"

    # Avisar de directorios residuales
    if [ -d "${INSTALL_DIR:-/nonexistent}" ]; then
        echo ""
        warn "Directorio residual: $INSTALL_DIR"
        info "Contiene datos que elegiste conservar. Eliminalo manualmente si ya no los necesitas:"
        echo "    sudo rm -rf $INSTALL_DIR"
    fi

    echo ""
    info "Para eliminar tambien QEMU y Docker (si no los usas para otra cosa):"
    echo "    sudo apt remove --purge qemu-system-x86 qemu-utils docker-ce"
    echo ""
}

# ===================== Main =====================
main() {
    header
    check_root

    echo -e "  ${RED}ATENCION:${NC} Este script desinstalara Fast VM."
    echo -e "  Se te preguntara antes de eliminar datos importantes."
    echo ""

    if [ "$NO_INPUT" = true ]; then
        info "Modo no interactivo: usando valores por defecto."
    elif ! ask_yes_no "Continuar con la desinstalacion?"; then
        info "Desinstalacion cancelada."
        exit 0
    fi

    # Filter --no-input from positional args
    local install_arg=""
    for arg in "$@"; do
        [[ "$arg" != "--no-input" ]] && install_arg="$arg" && break
    done
    detect_install "${install_arg:-}"
    step_stop_services
    step_remove_systemd
    step_docker_cleanup
    step_remove_files
    show_summary
}

main "$@"

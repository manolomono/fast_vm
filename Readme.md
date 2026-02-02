# Fast VM

Sistema web para administrar máquinas virtuales con QEMU/KVM.

## Características

- **Interfaz Web Moderna**: UI limpia y responsive para gestionar VMs
- **SPICE Display**: Acceso remoto de alta calidad con soporte para clipboard y resize
- **API REST**: Backend completo con FastAPI
- **Gestión de VMs**: Crear, iniciar, detener, reiniciar y eliminar máquinas virtuales
- **QEMU/KVM**: Virtualización con aceleración por hardware
- **Redes Avanzadas**: NAT, Bridge, MacVTAP e Isolated
- **Volúmenes**: Discos adicionales que se pueden adjuntar/desadjuntar
- **Snapshots**: Crear y restaurar snapshots de VMs
- **UEFI + Secure Boot**: Soporte completo para Windows 11
- **TPM 2.0**: Emulación de TPM con swtpm

## Sistemas Operativos Soportados

| Sistema | Estado | Notas |
|---------|--------|-------|
| Windows 11 | ✅ Funcional | UEFI, Secure Boot, TPM 2.0 |
| Windows 10 | ✅ Funcional | UEFI recomendado |
| Debian/Ubuntu | ✅ Funcional | Con spice-vdagent |
| Fedora/RHEL | ✅ Funcional | Con spice-vdagent |
| Android-x86 | ✅ Funcional | Android 9.0+ |
| Arch Linux | ✅ Funcional | Con spice-vdagent |

## Requisitos

- Python 3.8+
- QEMU/KVM
- swtpm (para TPM 2.0)
- OVMF (para UEFI)
- Permisos de usuario con acceso a KVM

### Instalar dependencias

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install qemu-kvm qemu-system-x86 qemu-utils ovmf swtpm
```

**Fedora/RHEL:**
```bash
sudo dnf install qemu-kvm qemu-img edk2-ovmf swtpm
```

**Arch Linux:**
```bash
sudo pacman -S qemu-base edk2-ovmf swtpm
```

### Configurar Bridge (opcional, para red bridge)

```bash
# Crear bridge
sudo nmcli connection add type bridge con-name br0 ifname br0
sudo nmcli connection add type ethernet slave-type bridge con-name br0-port1 ifname eno1 master br0
sudo nmcli connection up br0

# Permitir QEMU usar el bridge
sudo mkdir -p /etc/qemu
echo "allow br0" | sudo tee /etc/qemu/bridge.conf
sudo chmod u+s /usr/lib/qemu/qemu-bridge-helper
```

## Instalación

1. Clonar el repositorio:
```bash
git clone <repository-url>
cd fast_vm
```

2. Crear entorno virtual e instalar dependencias:
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

3. Verificar permisos KVM:
```bash
sudo usermod -a -G kvm $USER
# Cerrar sesión y volver a entrar
```

## Uso

### Iniciar el servidor

```bash
./start.sh
```

O manualmente:
```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Acceder a la interfaz web

```
http://localhost:8000
```

### Conexión SPICE

**Desde navegador:** Usar la interfaz web integrada

**Con remote-viewer (mejor rendimiento):**
```bash
sudo apt install virt-viewer  # Si no está instalado
remote-viewer spice://localhost:5800
```

### API Endpoints

#### VMs
- `GET /api/vms` - Listar todas las VMs
- `GET /api/vms/{vm_id}` - Obtener información de una VM
- `POST /api/vms` - Crear nueva VM
- `PUT /api/vms/{vm_id}` - Actualizar configuración de VM
- `POST /api/vms/{vm_id}/start` - Iniciar VM
- `POST /api/vms/{vm_id}/stop` - Detener VM
- `POST /api/vms/{vm_id}/restart` - Reiniciar VM
- `DELETE /api/vms/{vm_id}` - Eliminar VM
- `GET /api/vms/{vm_id}/spice` - Obtener conexión SPICE

#### Volúmenes
- `GET /api/volumes` - Listar volúmenes
- `POST /api/volumes` - Crear volumen
- `DELETE /api/volumes/{vol_id}` - Eliminar volumen
- `POST /api/vms/{vm_id}/volumes/{vol_id}/attach` - Adjuntar volumen
- `POST /api/vms/{vm_id}/volumes/{vol_id}/detach` - Desadjuntar volumen

#### Snapshots
- `GET /api/vms/{vm_id}/snapshots` - Listar snapshots
- `POST /api/vms/{vm_id}/snapshots` - Crear snapshot
- `POST /api/vms/{vm_id}/snapshots/{snap_id}/restore` - Restaurar snapshot
- `DELETE /api/vms/{vm_id}/snapshots/{snap_id}` - Eliminar snapshot

#### Sistema
- `GET /api/health` - Health check
- `GET /api/isos` - Listar ISOs disponibles
- `GET /api/bridges` - Listar bridges de red
- `GET /api/interfaces` - Listar interfaces de red

### Ejemplo de creación de VM

```bash
# VM con NAT (simple)
curl -X POST http://localhost:8000/api/vms \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Ubuntu Server",
    "memory": 2048,
    "cpus": 2,
    "disk_size": 20,
    "iso_path": "/path/to/ubuntu.iso"
  }'

# VM con Bridge (acceso directo a la red)
curl -X POST http://localhost:8000/api/vms \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Windows 11",
    "memory": 8192,
    "cpus": 4,
    "disk_size": 60,
    "iso_path": "/path/to/win11.iso",
    "secondary_iso_path": "/path/to/virtio-win.iso",
    "networks": [{"type": "bridge", "bridge_name": "br0"}],
    "boot_order": ["cdrom", "disk"]
  }'
```

## Estructura del Proyecto

```
fast_vm/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py           # FastAPI application
│   │   ├── models.py         # Pydantic models
│   │   ├── vm_manager.py     # QEMU VM manager
│   │   ├── spice_proxy.py    # SPICE WebSocket proxy
│   │   └── vnc_proxy.py      # VNC proxy (legacy)
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── style.css
│   ├── app.js
│   └── spice/                # SPICE HTML5 client
├── vms/                      # VM storage
│   ├── vms.json              # VM configurations
│   ├── volumes.json          # Volume configurations
│   └── volumes/              # Volume files
├── images/                   # ISO images
├── start.sh
└── Readme.md
```

## Configuración de Guest

### Windows

1. Durante la instalación, cargar drivers VirtIO desde el CD secundario
2. Después de instalar, ejecutar `virtio-win-guest-tools.exe` desde el CD
3. Instalar SPICE Guest Tools para clipboard y resize

### Linux (Debian/Ubuntu)

```bash
sudo apt install spice-vdagent xserver-xorg-video-qxl
sudo systemctl enable spice-vdagent
```

### Android-x86

1. En el menú de boot, seleccionar "Installation"
2. Crear partición y formatear como ext4
3. Instalar GRUB
4. Después de instalar, el resize funciona automáticamente

## Tipos de Red

| Tipo | Descripción | Caso de uso |
|------|-------------|-------------|
| NAT | Red privada con acceso a internet | Desarrollo, aislamiento |
| Bridge | Conectado directamente al bridge del host | Servidores, acceso LAN |
| MacVTAP | Conexión directa a interfaz física | Máximo rendimiento |
| Isolated | Sin acceso a red externa | Testing, seguridad |

## Seguridad

**IMPORTANTE**: Este sistema no incluye autenticación. Para producción:

1. Implementar autenticación (JWT, OAuth, etc.)
2. Usar HTTPS con certificados válidos
3. Restringir acceso por firewall
4. Configurar permisos de archivos correctamente
5. No exponer puertos SPICE directamente a internet

## Solución de Problemas

### KVM no disponible

```bash
# Verificar soporte de virtualización
egrep -c '(vmx|svm)' /proc/cpuinfo  # Debe ser > 0

# Cargar módulos
sudo modprobe kvm kvm_intel  # o kvm_amd

# Verificar permisos
ls -la /dev/kvm
sudo usermod -aG kvm $USER
```

### Bridge no funciona

```bash
# Verificar configuración
cat /etc/qemu/bridge.conf  # Debe contener "allow br0"

# Verificar permisos del helper
ls -la /usr/lib/qemu/qemu-bridge-helper  # Debe tener setuid
```

### SPICE no conecta

```bash
# Verificar que la VM está corriendo
ps aux | grep qemu

# Probar conexión directa
remote-viewer spice://localhost:5800
```

### Resize no funciona en Linux

```bash
# Dentro de la VM
sudo apt install spice-vdagent xserver-xorg-video-qxl
sudo systemctl restart spice-vdagent

# Usar remote-viewer, no el cliente web
remote-viewer spice://localhost:5800
```

## Roadmap

### Implementado
- [x] Gestión básica de VMs (crear, iniciar, detener, eliminar)
- [x] Soporte SPICE con cliente web
- [x] Redes: NAT, Bridge, MacVTAP, Isolated
- [x] UEFI + Secure Boot
- [x] TPM 2.0 emulado
- [x] Volúmenes adicionales
- [x] Snapshots
- [x] Soporte Windows 11
- [x] Soporte Linux (Debian, Ubuntu, Fedora, Arch)
- [x] Soporte Android-x86

### En progreso
- [ ] Mejoras en cliente web SPICE (resize automático)

### Planificado
- [ ] **Templates y clonación** - Clonar VMs existentes rápidamente
- [ ] **Métricas en tiempo real** - CPU, RAM, disco, red por VM
- [ ] **Cloud-init** - Provisioning automático de VMs Linux
- [ ] **GPU Passthrough** - Para gaming y ML
- [ ] **Migración en vivo** - Mover VMs entre hosts
- [ ] **Clustering** - Gestionar múltiples hosts
- [ ] **Autenticación** - JWT/OAuth para acceso seguro
- [ ] **ARM emulation** - Raspberry Pi OS, Android ARM
- [ ] **API de backups** - Backups automáticos programados
- [ ] **Importar/Exportar** - OVA, VMDK, VHD
- [ ] **USB Passthrough desde web** - Redirigir dispositivos USB

## Contribuir

1. Fork el proyecto
2. Crea una rama para tu feature (`git checkout -b feature/NuevaFeature`)
3. Commit tus cambios (`git commit -m 'Añadir NuevaFeature'`)
4. Push a la rama (`git push origin feature/NuevaFeature`)
5. Abre un Pull Request

## Licencia

MIT License - ver archivo LICENSE para más detalles.

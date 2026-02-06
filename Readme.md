# Fast VM

Sistema web para administrar maquinas virtuales con QEMU/KVM. Incluye un dashboard moderno con autenticacion, consola SPICE integrada en el navegador y gestion completa de VMs, volumenes y snapshots.

## Capturas

### Dashboard
El dashboard muestra un resumen en tiempo real con tarjetas de estadisticas (Total VMs, Running, Stopped, Volumes) y una cuadricula de VMs con controles rapidos para iniciar, detener, abrir consola, editar y eliminar.

### Consola SPICE
Panel dividido que permite ver la consola de la VM directamente en el navegador con soporte fullscreen, clipboard y redimensionado.

## Caracteristicas

### Dashboard Web
- **UI moderna con dark theme** - Construido con TailwindCSS + Alpine.js
- **Sidebar con navegacion** - Dashboard, Volumes, Users y listado de VMs con indicador de estado
- **Tarjetas de estadisticas** - Total VMs, Running, Stopped, Volumes en tiempo real
- **Metricas del host** - Barras de progreso de CPU, RAM y disco del servidor
- **Metricas por VM** - CPU%, RAM usada e I/O de disco en tiempo real para cada VM running
- **Cuadricula de VMs** - Cards con info de CPU, RAM, disco, metricas live y controles rapidos
- **Auto-refresh** - El dashboard se actualiza automaticamente cada 10 segundos
- **Notificaciones toast** - Feedback visual de exito/error en cada accion
- **Responsive** - Adaptable a diferentes tamanos de pantalla

### Autenticacion y Gestion de Usuarios
- **Login con JWT** - Pagina de login con tokens Bearer
- **Passwords con bcrypt** - Hash seguro de contrasenas
- **Usuario por defecto** - Se crea automaticamente `admin/admin` en el primer inicio
- **Sesion persistente** - Token almacenado en localStorage (24h de duracion)
- **Proteccion de API** - Todos los endpoints requieren autenticacion
- **Cambio de contrasena** - Cada usuario puede cambiar su propia contrasena
- **Panel de administracion** - Los admins pueden crear, listar y eliminar usuarios
- **Roles** - Usuarios admin y usuarios regulares

### Gestion de VMs
- **Crear VMs** - Modal con configuracion de nombre, CPU, RAM, disco, ISOs, redes y mas
- **Editar VMs** - Modificar recursos, ISOs, redes y volumenes (requiere VM detenida)
- **Clonar VMs** - Clon copy-on-write con nuevas MACs, opcion de cambiar CPU/RAM
- **Iniciar/Detener/Reiniciar** - Control completo del ciclo de vida
- **Eliminar VMs** - Con confirmacion y limpieza automatica de recursos
- **Doble ISO** - ISO principal (instalacion) + ISO secundaria (drivers VirtIO, cloud-init)
- **Boot order configurable** - Disco, CDROM, Red

### Cloud-init
- **Generador de ISOs** - Crea ISOs cloud-init desde el dashboard con un formulario visual
- **Configuracion completa** - Hostname, usuario, password, SSH keys, paquetes
- **Red** - DHCP por defecto o IP estatica con gateway y DNS
- **Paquetes automaticos** - Instala spice-vdagent, qemu-guest-agent y lo que necesites
- **Uso sencillo** - Genera la ISO y usala como secondary ISO al crear/editar una VM

### Consola SPICE
- **SPICE HTML5** - Acceso remoto de alta calidad desde el navegador
- **Panel dividido** - Ver el dashboard y la consola simultaneamente
- **Fullscreen** - Modo pantalla completa para la consola
- **Clipboard compartido** - Copiar/pegar entre host y guest (con spice-vdagent)
- **Resize automatico** - La resolucion se adapta al tamano de la ventana
- **Redireccion USB** - Soporte para 2 dispositivos USB redirigidos

### Redes Avanzadas
- **NAT** - Red privada con acceso a internet y port forwarding
- **Bridge** - Conexion directa al bridge del host (acceso LAN)
- **MacVTAP** - Conexion directa a interfaz fisica (maximo rendimiento)
- **Isolated** - Sin acceso a red externa (testing, seguridad)
- **Modelos de NIC** - VirtIO (mejor rendimiento), e1000, RTL8139

### Volumenes
- **Crear volumenes** - qcow2 o raw, de 1GB a 1TB
- **Attach/Detach** - Adjuntar y desadjuntar volumenes desde el modal de edicion
- **Vista dedicada** - Seccion Volumes en el sidebar para gestionar todos los discos

### Snapshots
- **Crear snapshots** - Capturar el estado actual del disco
- **Restaurar** - Volver a un snapshot anterior
- **Eliminar** - Limpiar snapshots antiguos

### Hardware
- **QEMU/KVM** - Virtualizacion con aceleracion por hardware
- **UEFI + Secure Boot** - Soporte completo para Windows 11
- **TPM 2.0** - Emulacion de TPM con swtpm
- **Modelos de CPU** - host, qemu64, max, Skylake-Client, EPYC
- **Display QXL** - Optimizado para SPICE con 64MB de VRAM

## Stack Tecnologico

| Componente | Tecnologia |
|-----------|------------|
| Backend | Python 3.8+ / FastAPI |
| Frontend | TailwindCSS + Alpine.js |
| Autenticacion | JWT (python-jose) + bcrypt |
| Virtualizacion | QEMU/KVM |
| Display remoto | SPICE (spice-html5) |
| WebSocket proxy | websockify |
| Modelos | Pydantic v2 |

## Sistemas Operativos Soportados

| Sistema | Estado | Notas |
|---------|--------|-------|
| Windows 11 | Funcional | UEFI, Secure Boot, TPM 2.0 |
| Windows 10 | Funcional | UEFI recomendado |
| Debian/Ubuntu | Funcional | Con spice-vdagent |
| Fedora/RHEL | Funcional | Con spice-vdagent |
| Android-x86 | Funcional | Android 9.0+ |
| Arch Linux | Funcional | Con spice-vdagent |

## Requisitos

- Python 3.8+
- QEMU/KVM
- swtpm (para TPM 2.0)
- OVMF (para UEFI)
- Permisos de usuario con acceso a KVM

### Instalar dependencias del sistema

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

## Instalacion

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
# Cerrar sesion y volver a entrar
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

**Credenciales por defecto:** `admin` / `admin`

> Cambia la contrasena por defecto en produccion. Tambien configura la variable de entorno `JWT_SECRET_KEY` con una clave segura.

### Conexion SPICE

**Desde el dashboard:** Click en "Console" en cualquier VM running. Se abre un panel SPICE integrado en la misma pagina.

**Con remote-viewer (mejor rendimiento):**
```bash
sudo apt install virt-viewer  # Si no esta instalado
remote-viewer spice://localhost:5800
```

## API Endpoints

Todos los endpoints (excepto login) requieren header `Authorization: Bearer <token>`.

### Autenticacion
- `POST /api/auth/login` - Obtener token JWT
- `POST /api/auth/logout` - Cerrar sesion
- `GET /api/auth/me` - Info del usuario autenticado
- `POST /api/auth/change-password` - Cambiar contrasena propia
- `GET /api/auth/users` - Listar usuarios (solo admin)
- `POST /api/auth/users` - Crear usuario (solo admin)
- `DELETE /api/auth/users/{username}` - Eliminar usuario (solo admin)

### VMs
- `GET /api/vms` - Listar todas las VMs
- `GET /api/vms/{vm_id}` - Obtener info de una VM
- `POST /api/vms` - Crear nueva VM
- `PUT /api/vms/{vm_id}` - Actualizar configuracion de VM
- `POST /api/vms/{vm_id}/start` - Iniciar VM
- `POST /api/vms/{vm_id}/stop` - Detener VM
- `POST /api/vms/{vm_id}/clone` - Clonar una VM (debe estar detenida)

### Cloud-init
- `POST /api/cloudinit` - Crear ISO cloud-init para provisioning automatico
- `POST /api/vms/{vm_id}/restart` - Reiniciar VM
- `DELETE /api/vms/{vm_id}` - Eliminar VM
- `GET /api/vms/{vm_id}/logs` - Ver logs de QEMU y serial

### SPICE
- `GET /api/vms/{vm_id}/spice` - Obtener conexion SPICE (inicia proxy WebSocket)
- `POST /api/vms/{vm_id}/spice/disconnect` - Desconectar proxy SPICE

### VNC (legacy)
- `GET /api/vms/{vm_id}/vnc` - Obtener conexion VNC
- `POST /api/vms/{vm_id}/vnc/disconnect` - Desconectar proxy VNC

### Volumenes
- `GET /api/volumes` - Listar volumenes
- `GET /api/volumes/{vol_id}` - Obtener volumen
- `POST /api/volumes` - Crear volumen
- `DELETE /api/volumes/{vol_id}` - Eliminar volumen
- `POST /api/vms/{vm_id}/volumes/{vol_id}` - Adjuntar volumen a VM
- `DELETE /api/vms/{vm_id}/volumes/{vol_id}` - Desadjuntar volumen

### Snapshots
- `GET /api/vms/{vm_id}/snapshots` - Listar snapshots
- `POST /api/vms/{vm_id}/snapshots` - Crear snapshot
- `POST /api/vms/{vm_id}/snapshots/{snap_id}/restore` - Restaurar snapshot
- `DELETE /api/vms/{vm_id}/snapshots/{snap_id}` - Eliminar snapshot

### Metricas
- `GET /api/vms/{vm_id}/metrics` - Metricas en tiempo real de una VM (CPU%, RAM, I/O)
- `GET /api/system/metrics` - Metricas del host (CPU, RAM, disco)

### Sistema
- `GET /api/health` - Health check
- `GET /api/isos` - Listar ISOs disponibles
- `GET /api/bridges` - Listar bridges de red
- `GET /api/interfaces` - Listar interfaces de red
- `GET /api/system/user` - Usuario del sistema
- `GET /api/spice-tools` - Estado de spice-guest-tools

### Ejemplo de creacion de VM

```bash
# Obtener token
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin"}' | jq -r '.access_token')

# VM con NAT (simple)
curl -X POST http://localhost:8000/api/vms \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
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
  -H "Authorization: Bearer $TOKEN" \
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
│   │   ├── main.py           # FastAPI app + rutas
│   │   ├── auth.py           # Autenticacion JWT + bcrypt
│   │   ├── models.py         # Modelos Pydantic (VM, Volume, Snapshot, Auth)
│   │   ├── vm_manager.py     # Gestor de VMs con QEMU
│   │   ├── spice_proxy.py    # Proxy WebSocket para SPICE
│   │   └── vnc_proxy.py      # Proxy VNC (legacy)
│   ├── requirements.txt
│   └── users.json            # Base de datos de usuarios
├── frontend/
│   ├── index.html            # Dashboard principal (TailwindCSS + Alpine.js)
│   ├── login.html            # Pagina de login
│   ├── style.css
│   ├── app.js                # Logica del dashboard (Alpine.js)
│   ├── spice/                # Cliente SPICE HTML5
│   └── vnc/                  # Cliente noVNC (legacy)
├── vms/                      # Almacenamiento de VMs
│   ├── vms.json              # Configuraciones de VMs
│   ├── volumes.json          # Configuraciones de volumenes
│   └── volumes/              # Archivos de volumenes
├── images/                   # Imagenes ISO
├── start.sh
├── config.example.json
├── LICENSE
└── Readme.md
```

## Configuracion de Guest

### Windows

1. Durante la instalacion, cargar drivers VirtIO desde el CD secundario
2. Despues de instalar, ejecutar `virtio-win-guest-tools.exe` desde el CD
3. Instalar SPICE Guest Tools para clipboard y resize

### Linux (Debian/Ubuntu)

```bash
sudo apt install spice-vdagent xserver-xorg-video-qxl
sudo systemctl enable spice-vdagent
```

### Android-x86

1. En el menu de boot, seleccionar "Installation"
2. Crear particion y formatear como ext4
3. Instalar GRUB
4. Despues de instalar, el resize funciona automaticamente

## Tipos de Red

| Tipo | Descripcion | Caso de uso |
|------|-------------|-------------|
| NAT | Red privada con acceso a internet y port forwarding | Desarrollo, aislamiento |
| Bridge | Conectado directamente al bridge del host | Servidores, acceso LAN |
| MacVTAP | Conexion directa a interfaz fisica | Maximo rendimiento |
| Isolated | Sin acceso a red externa | Testing, seguridad |

## Seguridad

El sistema incluye autenticacion JWT. Para un entorno de produccion:

1. Cambiar la contrasena del usuario `admin` por defecto
2. Configurar `JWT_SECRET_KEY` como variable de entorno con una clave segura
3. Usar HTTPS con certificados validos (reverse proxy con nginx/caddy)
4. Restringir acceso por firewall
5. Configurar permisos de archivos correctamente
6. No exponer puertos SPICE directamente a internet

## Solucion de Problemas

### KVM no disponible

```bash
# Verificar soporte de virtualizacion
egrep -c '(vmx|svm)' /proc/cpuinfo  # Debe ser > 0

# Cargar modulos
sudo modprobe kvm kvm_intel  # o kvm_amd

# Verificar permisos
ls -la /dev/kvm
sudo usermod -aG kvm $USER
```

### Bridge no funciona

```bash
# Verificar configuracion
cat /etc/qemu/bridge.conf  # Debe contener "allow br0"

# Verificar permisos del helper
ls -la /usr/lib/qemu/qemu-bridge-helper  # Debe tener setuid
```

### SPICE no conecta

```bash
# Verificar que la VM esta corriendo
ps aux | grep qemu

# Probar conexion directa
remote-viewer spice://localhost:5800
```

### Resize no funciona en Linux

```bash
# Dentro de la VM
sudo apt install spice-vdagent xserver-xorg-video-qxl
sudo systemctl restart spice-vdagent
```

## Roadmap

### Implementado
- [x] Dashboard web con TailwindCSS + Alpine.js
- [x] Autenticacion JWT con bcrypt
- [x] Gestion de usuarios (crear, listar, eliminar) con panel admin
- [x] Cambio de contrasena desde la UI
- [x] Metricas en tiempo real del host (CPU, RAM, disco)
- [x] Metricas en tiempo real por VM (CPU%, RAM, I/O)
- [x] Gestion de VMs (crear, editar, iniciar, detener, eliminar)
- [x] Clonacion de VMs (copy-on-write, nuevas MACs)
- [x] Cloud-init (generador de ISOs desde el dashboard)
- [x] Consola SPICE integrada en el navegador
- [x] Redes: NAT con port forwarding, Bridge, MacVTAP, Isolated
- [x] UEFI + Secure Boot
- [x] TPM 2.0 emulado
- [x] Volumenes (crear, attach/detach, eliminar)
- [x] Snapshots (crear, restaurar, eliminar)
- [x] Soporte Windows 11, Linux y Android-x86
- [x] Doble ISO (instalacion + drivers)
- [x] Auto-refresh del dashboard
- [x] Logs de VM (QEMU + serial)

### Planificado
- [ ] **GPU Passthrough** - Para gaming y ML
- [ ] **Migracion en vivo** - Mover VMs entre hosts
- [ ] **Clustering** - Gestionar multiples hosts
- [ ] **Roles granulares** - Permisos por recurso y por usuario
- [ ] **ARM emulation** - Raspberry Pi OS, Android ARM
- [ ] **API de backups** - Backups automaticos programados
- [ ] **Importar/Exportar** - OVA, VMDK, VHD
- [ ] **USB Passthrough desde web** - Redirigir dispositivos USB
- [ ] **Metricas historicas** - Graficos con Chart.js y almacenamiento en SQLite

## Contribuir

1. Fork el proyecto
2. Crea una rama para tu feature (`git checkout -b feature/NuevaFeature`)
3. Commit tus cambios (`git commit -m 'Anadir NuevaFeature'`)
4. Push a la rama (`git push origin feature/NuevaFeature`)
5. Abre un Pull Request

## Licencia

MIT License - ver archivo LICENSE para mas detalles.

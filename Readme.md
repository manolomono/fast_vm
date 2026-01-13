# Fast VM

Sistema web simple para administrar máquinas virtuales con QEMU.

## Características

- **Interfaz Web Moderna**: UI limpia y responsive para gestionar VMs
- **API REST**: Backend completo con FastAPI
- **Gestión de VMs**: Crear, iniciar, detener y eliminar máquinas virtuales
- **QEMU/KVM**: Virtualización potente y eficiente
- **Monitoreo**: Ver estado, recursos y conectividad VNC de cada VM

## Requisitos

- Python 3.8+
- QEMU/KVM instalado
- Permisos de root o usuario con acceso a KVM

### Instalar QEMU (si no está instalado)

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install qemu-kvm qemu-system-x86 qemu-utils
```

**Fedora/RHEL:**
```bash
sudo dnf install qemu-kvm qemu-img
```

**Arch Linux:**
```bash
sudo pacman -S qemu-base
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
source venv/bin/activate  # En Windows: venv\Scripts\activate
pip install -r requirements.txt
```

3. Verificar permisos KVM (opcional, para mejor rendimiento):
```bash
# Agregar usuario al grupo kvm
sudo usermod -a -G kvm $USER
# Cerrar sesión y volver a entrar para aplicar cambios
```

## Uso

### Iniciar el servidor

```bash
cd backend
source venv/bin/activate
python -m app.main
```

O usando uvicorn directamente:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Acceder a la interfaz web

Abre tu navegador y ve a:
```
http://localhost:8000
```

### API Endpoints

- `GET /api/health` - Health check
- `GET /api/vms` - Listar todas las VMs
- `GET /api/vms/{vm_id}` - Obtener información de una VM
- `POST /api/vms` - Crear nueva VM
- `POST /api/vms/{vm_id}/start` - Iniciar VM
- `POST /api/vms/{vm_id}/stop` - Detener VM
- `DELETE /api/vms/{vm_id}` - Eliminar VM

### Ejemplo de creación de VM con curl

```bash
curl -X POST http://localhost:8000/api/vms \
  -H "Content-Type: application/json" \
  -d '{
    "name": "mi-vm-ubuntu",
    "memory": 2048,
    "cpus": 2,
    "disk_size": 20,
    "iso_path": "/ruta/a/ubuntu.iso"
  }'
```

## Estructura del Proyecto

```
fast_vm/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py          # FastAPI application
│   │   ├── models.py        # Pydantic models
│   │   └── vm_manager.py    # QEMU VM manager
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
├── vms/                      # Almacenamiento de VMs
├── images/                   # Imágenes ISO
└── Readme.md
```

## Configuración

### Cambiar directorios de VMs e imágenes

Edita `backend/app/vm_manager.py` y modifica la ruta en `VMManager.__init__()`:

```python
def __init__(self, vms_dir: str = "/tu/ruta/personalizada"):
```

### Acceso VNC

Cada VM tiene asignado un puerto VNC único (desde 5900). Para conectarte:

```bash
# Usando vncviewer
vncviewer localhost:5900

# O usando otro puerto
vncviewer localhost:5901
```

También puedes usar clientes VNC gráficos como:
- TigerVNC
- RealVNC
- Remmina

## Seguridad

**IMPORTANTE**: Este es un sistema básico sin autenticación. Para uso en producción:

1. Agrega autenticación (JWT, OAuth, etc.)
2. Implementa HTTPS
3. Restringe acceso a la red
4. Configura firewall para puertos VNC
5. Valida permisos de archivos y rutas ISO

## Desarrollo

### Ejecutar en modo desarrollo

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Ejecutar tests (próximamente)

```bash
pytest
```

## Solución de Problemas

### Error: "KVM not available"

Si ves este error, QEMU funcionará en modo emulación (más lento):
- Verifica que tu CPU soporte virtualización (Intel VT-x o AMD-V)
- Habilita virtualización en la BIOS
- Instala módulos del kernel: `sudo modprobe kvm kvm_intel` o `kvm_amd`

### Error: "Permission denied" al crear VM

- Verifica permisos en el directorio `vms/`
- Asegúrate de tener acceso al grupo `kvm`

### VM no inicia

- Verifica que QEMU esté instalado: `which qemu-system-x86_64`
- Revisa logs del sistema: `journalctl -xe`
- Verifica que la ruta ISO sea correcta y accesible

## Contribuir

1. Fork el proyecto
2. Crea una rama para tu feature (`git checkout -b feature/AmazingFeature`)
3. Commit tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abre un Pull Request

## Licencia

MIT License - ver archivo LICENSE para más detalles

## Autor

Fast VM Team

## Roadmap

- [ ] Autenticación y autorización
- [ ] Soporte para redes personalizadas
- [ ] Snapshots de VMs
- [ ] Clonación de VMs
- [ ] Integración con noVNC para consola web
- [ ] Métricas de rendimiento en tiempo real
- [ ] Importar/exportar VMs
- [ ] Soporte para múltiples hipervisores

# Guía de Migración: PowerShell → Python 3 (Multiplataforma)

Este documento detalla la refactorización y migración estructural del proyecto CX-Radar de scripts en PowerShell (`.ps1`) a Python 3 (`.py`) compatible con Windows, Linux y macOS.

## Razón de la Migración

1. **Aislamiento Criptográfico y Compatibilidad Heredada**: En sistemas como Windows Server 2012 R2, el script de PowerShell fallaba debido a incompatibilidades de TLS 1.2 y la falta de soporte para APIs modernas de .NET Framework.
2. **Portabilidad Multiplataforma**: Al migrar a Python 3, la sonda se vuelve universal y ejecutable nativamente en entornos Linux y macOS.
3. **Cero Dependencias Externas**: La nueva implementación utiliza exclusivamente la biblioteca estándar de Python (stdlib), evitando `pip install` u otros gestores de paquetes.

---

## Equivalencia de Archivos

Los scripts originales se han guardado en `scripts/legacy-powershell/` para contingencias y referencia histórica. La correspondencia es la siguiente:

| Script Original (PowerShell) | Nuevo Script (Python 3) | Propósito |
| :--- | :--- | :--- |
| `scripts/setup-portable.ps1` | `scripts/setup_portable.py` | Descarga herramientas portables (`node`, `yt-dlp`, `fast-cli`) |
| `scripts/set-influx-token.ps1` | `scripts/set_influx_token.py` | Almacenamiento seguro del token de InfluxDB |
| `scripts/validate-qoe-probe.ps1` | `scripts/validate_qoe_probe.py` | Validaciones de entorno, configuración y herramientas |
| `scripts/qoe-probe.ps1` | `scripts/qoe_probe.py` | Sonda de monitoreo principal (HTTP y speedtest) |
| `scripts/run-qoe-certification.ps1` | `scripts/run_qoe_certification.py` | Pruebas de QA de humo y resiliencia |
| `scripts/register-qoe-task.ps1` | `scripts/register_qoe_task.py` | Registro periódico en el planificador del OS |

Además, se ha creado el directorio `orchestration/` con plantillas de orquestación nativas:
- `orchestration/crontab-example.txt`
- `orchestration/cx-radar-qoe-probe.service` (Systemd Service)
- `orchestration/cx-radar-qoe-probe.timer` (Systemd Timer)
- `orchestration/com.cx-radar.qoe-probe.plist` (macOS LaunchAgent)

---

## Equivalencia de Comandos

A continuación se muestra el mapeo de ejecución de los comandos principales:

### 1. Inicialización de herramientas
*   **PowerShell**:
    ```powershell
    & .\scripts\setup-portable.ps1
    ```
*   **Python**:
    ```bash
    python scripts/setup_portable.py
    ```

### 2. Guardado de credenciales
*   **PowerShell**:
    ```powershell
    & .\scripts\set-influx-token.ps1
    ```
*   **Python** (usa archivo local `.env` o variables de entorno):
    ```bash
    python scripts/set_influx_token.py --method file
    ```

### 3. Validación de entorno
*   **PowerShell**:
    ```powershell
    & .\scripts\validate-qoe-probe.ps1
    ```
*   **Python**:
    ```bash
    python scripts/validate_qoe_probe.py
    ```

### 4. Ejecución de la sonda (Prueba)
*   **PowerShell**:
    ```powershell
    & .\scripts\qoe-probe.ps1 -SkipInfluxWrite
    ```
*   **Python**:
    ```bash
    python scripts/qoe_probe.py --skip-influx-write
    ```

### 5. Ejecución completa
*   **PowerShell**:
    ```powershell
    & .\scripts\qoe-probe.ps1
    ```
*   **Python**:
    ```bash
    python scripts/qoe_probe.py
    ```

### 6. Registro de Tarea Programada
*   **PowerShell**:
    ```powershell
    & .\scripts\register-qoe-task.ps1
    ```
*   **Python**:
    ```bash
    python scripts/register_qoe_task.py
    ```

### 7. Ejecución de QA y Certificación
*   **PowerShell**:
    ```powershell
    & .\scripts\run-qoe-certification.ps1 -RunResilienceChecks
    ```
*   **Python**:
    ```bash
    python scripts/run_qoe_certification.py --run-resilience-checks
    ```

---

## Decisiones de Arquitectura Clave

1. **Depreciación de DPAPI**: DPAPI es exclusivo de Windows. Se ha depreciado por completo. La sonda Python ahora lee de variables de entorno de proceso o un archivo `.env` en la raíz con permisos restrictivos gestionado por `set_influx_token.py`.
2. **Tag `probeType`**: Modificado en la consulta del panel de Grafana y en `config/probe-catalog.json` a `"python"` para acomodar la nueva telemetría.
3. **Mapeo Híbrido HTTP**: Si `curl` está presente en la ruta del sistema o en `bin/`, se ejecuta y se parsean sus métricas mediante `--write-out`. Si no está, la sonda realiza una conexión socket pura + wrapper TLS para medir DNS, TCP, y TLS, completando la descarga mediante `urllib.request`.
4. **Jitter de Inicio y Retardo de Objetivos**: Soportados nativamente con sleeps aleatorios (`random.randint`) y retardos parametrizados para mitigar picos de tráfico en las plataformas de destino.

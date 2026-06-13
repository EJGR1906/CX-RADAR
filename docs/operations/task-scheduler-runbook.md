# Runbook del Programador de Tareas

> [!NOTE]
> **Nota de Migración:** Los scripts de PowerShell detallados aquí se consideran legados. El proyecto ha migrado a Python 3. Consulta la [Guía de Migración](file:///c:/Users/Eduar/Documents/CX-RADAR/docs/MIGRATION.md) para conocer las nuevas instrucciones multiplataforma.

## Propósito

Este runbook describe cómo validar y registrar la sonda Windows 11 para que se ejecute cada 5 minutos en segundo plano.

## Prerrequisitos

1. `curl.exe` disponible en `PATH`.
2. PowerShell capaz de ejecutar scripts locales con una política de ejecución en el ámbito del proceso como `RemoteSigned`.
3. `config/probe-catalog.json` actualizado con valores reales de InfluxDB.
4. Token de InfluxDB almacenado con `scripts\set-influx-token.ps1`, o disponible temporalmente mediante la variable de entorno configurada.

## Provisionar el Token

Ruta preferida:

```powershell
& .\scripts\set-influx-token.ps1
```

Si estás migrando desde una variable de entorno de usuario y no necesitas la ruta de reversión:

```powershell
& .\scripts\set-influx-token.ps1 -ClearUserEnvironmentVariable
```

## Validar Antes de Programar

Ejecuta esto desde PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\validate-qoe-probe.ps1 | Format-List
```

El resultado esperado hoy es:

1. `ProbeScriptSyntax = OK`
2. `ConfigFile = OK`
3. `CurlAvailable = True`
4. `InfluxTokenAvailable = True` una vez que el token esté configurado
5. `InfluxTokenSource = CredentialFile` después de la migración DPAPI

## Ejecución en Seco Sin Escritura en InfluxDB

Usa esto para probar el flujo de medición HTTP sin enviar métricas:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\qoe-probe.ps1 -SkipInfluxWrite
```

Los logs se escriben en `logs\qoe-probe-YYYY-MM-DD.log`.

## Instalación y Registro Unificado (Recomendado)

La forma más rápida y recomendada para provisionar el token, configurar el catálogo, descargar herramientas y registrar las tareas programadas en un servidor de producción es ejecutar:

```bash
python scripts/install.py
```

O en modo desatendido de una sola línea:

```bash
python scripts/install.py --probe-id "servidor-prod" --site "centro-datos" --environment "production" --isp "fiber" --influx-token "TOKEN" --influx-url "URL" --influx-org "ORG" --influx-bucket "BUCKET"
```

*(En Windows, si deseas que las tareas se ejecuten bajo la sesión interactiva del usuario actual en lugar de ejecutarse en segundo plano (S4U), agrega la bandera `--run-as-current-user` al instalador).*

---

## Registro Manual Alternativo de Tareas (Detallado)

Si necesitas registrar o reconfigurar las tareas programadas individualmente sin alterar el resto de la configuración:

### 1. Registrar la Tarea Programada de la Sonda (Python 3)

Para programar la ejecución recurrente de la sonda (por defecto cada 10 minutos):

```bash
python scripts/register_qoe_task.py
```

En equipos de escritorio de Windows o servidores personales donde prefieras ejecutarlo bajo la sesión interactiva del usuario actual, usa:

```bash
python scripts/register_qoe_task.py --run-as-current-user
```

*(En Linux se utilizará Systemd/Cron, y en macOS LaunchAgents).*

### 2. Registrar la Tarea de Actualización Automática (Python 3)

Para programar la tarea diaria de actualización automática a las 8:00 AM (la cual verifica hashes SHA-256 contra GitHub para actualizar sólo cuando existan cambios):

```bash
python scripts/update_qoe_probe.py --register
```

Si ejecutas sobre Windows Server 2012 R2 o sistemas con certificados obsoletos y necesitas omitir la verificación SSL, o si quieres usar inicio de sesión interactivo, utiliza:

```bash
python scripts/update_qoe_probe.py --register --run-as-current-user --no-verify-ssl
```

---

## Comprobaciones Posteriores al Registro

1. Abre el Programador de tareas y confirma que las tareas `CX-Radar-QoE-Probe` y `CX-Radar-QoE-Updater` existen.
2. Ejecuta las tareas manualmente una vez para validar que inicien.
3. Confirma que el archivo de log se actualiza en `logs/`.
4. Confirma que las métricas llegan a InfluxDB una vez ejecutada la sonda principal.

## Recuperación

Si alguna tarea existe pero no se ejecuta correctamente:

1. Ejecuta `python scripts/validate_qoe_probe.py` de nuevo.
2. Revisa el archivo de log diario en `logs/`.
3. Confirma que las credenciales del token estén presentes en tu archivo `.env` local.
4. Vuelve a registrar las tareas ejecutando de nuevo los scripts de registro con la configuración adecuada.

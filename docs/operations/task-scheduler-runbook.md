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

## Registrar la Tarea Programada

Usa el script auxiliar:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\register-qoe-task.ps1
```

Por defecto, el nombre de la tarea es `CX-Radar-QoE-Probe` y el intervalo es de 5 minutos.

Si firmas los scripts, prefiere:

```powershell
& .\scripts\register-qoe-task.ps1 -ExecutionPolicy AllSigned
```

Usa `Bypass` solo como una excepción explícita:

```powershell
& .\scripts\register-qoe-task.ps1 -ExecutionPolicy Bypass
```

## Comprobaciones Posteriores al Registro

1. Abre el Programador de tareas y confirma que la tarea existe.
2. Ejecuta la tarea manualmente una vez.
3. Confirma que el archivo de log se actualiza.
4. Confirma que las métricas llegan a InfluxDB una vez configurado el token.
5. Confirma que los argumentos de acción muestran `RemoteSigned` o `AllSigned`, no `Bypass`, a menos que hayas aprobado explícitamente la excepción.

## Recuperación

Si la tarea existe pero no se ejecuta correctamente:

1. Ejecuta `scripts\validate-qoe-probe.ps1` de nuevo.
2. Revisa el archivo de log diario en `logs\`.
3. Confirma que el usuario configurado puede descifrar el archivo de credenciales DPAPI o aún tiene la variable de entorno temporal.
4. Registra nuevamente la tarea con la política de ejecución prevista volviendo a ejecutar `register-qoe-task.ps1`.

# Notas de Endurecimiento

> [!NOTE]
> **Nota de Migración:** Los scripts de PowerShell detallados aquí se consideran legados. El proyecto ha migrado a Python 3. Consulta la [Guía de Migración](../MIGRATION.md) para conocer las nuevas instrucciones multiplataforma y de almacenamiento de secretos mediante archivos `.env`.

## Estado actual (Python 3)

Las secciones de más abajo describen la versión PowerShell y se conservan como referencia. Lo vigente:

### Credenciales

- Viven en `.env` en la raíz (fuera de git): `INFLUXDB_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. El instalador y `set_influx_token.py` dejan el archivo legible solo por el usuario actual (`chmod 600` o `icacls`). Si se edita a mano, repetir la restricción.
- El instalador pasa el token de InfluxDB por variable de entorno al paso que lo guarda: no queda en la línea de comandos ni en pantalla.
- **Un token por sonda, solo de escritura** al bucket. Hoy todas las sondas pueden compartir un mismo token: una sonda comprometida podría escribir datos falsos de las demás. Crear en InfluxDB Cloud un token *Write* por sonda permite revocar una sin tocar el resto.
- **El bot de Telegram** es el mismo en todas las sondas: quien tenga el token puede enviar mensajes al chat y leer lo que se le escriba al bot. No usar ese bot para nada más y regenerar el token en @BotFather si una sonda se pierde.
- `GRAFANA_TOKEN` (rol Editor o Admin) solo hace falta para `setup_grafana_alert.py`: usarlo desde un equipo de administración, no dejarlo en las sondas.

### Actualizaciones y descargas

- `update_qoe_probe.py` descarga `scripts/release-manifest.json` y los scripts que cambiaron. Cada archivo debe coincidir con su SHA-256, compilar y poder importarse junto a los demás; se instalan todos o ninguno, con respaldo en `scripts/.update-backup/` y restauración si falla un reemplazo.
- TLS se verifica siempre en el actualizador. `--no-verify-ssl` y `verifyTls: false` no lo desactivan.
- Límite: el manifiesto viene del mismo repositorio. Protege la integridad de la descarga, no contra alguien con permiso de escritura en la rama. Proteger `main` (revisión obligatoria) o actualizar desde un tag con `--ref`.
- Quien publica cambios en `scripts/` regenera el manifiesto con `python scripts/update_qoe_probe.py --write-manifest`; el CI falla si quedó desactualizado.
- `setup_portable.py` compara Node.js con `SHASUMS256.txt` de nodejs.org y `yt-dlp` con `SHA2-256SUMS` de su publicación. Si no coincide borra la descarga y aborta. `fast-cli` se instala con versión fija por npm.

### Reporte de ONUs

`onu_report.py` rechaza archivos `.xlsx` con contenido interno de más de 300 MB o con DOCTYPE en su XML.

## Manejo de secretos

La sonda ahora admite dos fuentes de token, en este orden:

1. Un archivo de credenciales protegido por DPAPI en el ámbito de usuario referenciado por `influx.credentialFilePath`
2. La variable de entorno de usuario o de proceso nombrada por `influx.tokenEnvVar`

No almacenes el token directamente en:

1. `qoe-probe.ps1`
2. `probe-catalog.json`
3. Argumentos de tareas
4. Archivos de log en texto plano

Ruta recomendada para producción:

1. Almacena el token con `scripts\set-influx-token.ps1` para que el valor se cifre con el contexto de usuario de Windows actual mediante DPAPI.
2. Mantén el archivo secreto fuera del repositorio, bajo `%LOCALAPPDATA%\CX-Radar\secrets\`.
3. Elimina la variable de entorno de usuario después de la migración a menos que se requiera una ruta de reversión temporal.

Ejemplo:

```powershell
& .\scripts\set-influx-token.ps1
& .\scripts\set-influx-token.ps1 -ClearUserEnvironmentVariable
```

Credential Manager sigue siendo una opción válida para el futuro, pero requeriría un módulo adicional o un wrapper de API nativo dedicado. El repositorio actual predetermina DPAPI porque es nativo de Windows y funciona sin añadir dependencias nuevas.

## Política de ejecución de PowerShell

Usa la opción más estricta posible en este orden:

1. `AllSigned` si estás preparado para firmar la sonda y los scripts auxiliares.
2. `RemoteSigned` para scripts locales no firmados en este equipo supervisado.
3. `Bypass` solo como un fallback explícito por tarea si un control local bloquea las opciones más seguras y la excepción está documentada.

El helper de tarea programada ahora predetermina `-ExecutionPolicy RemoteSigned`, que está en el ámbito del proceso para esa invocación de tarea y evita debilitar todo el host.

## Principio de menor privilegio

La tarea se registra con un nivel de ejecución limitado. Evita el contexto de administrador a menos que una dependencia futura lo requiera y el requisito esté documentado explícitamente.

La tarea programada ya no usa `RunOnlyIfNetworkAvailable`: el monitor tiene que correr justo cuando el equipo se queda sin red, para registrar la falla y diagnosticarla como local. Cada corrida tiene tiempo máximo (`ExecutionTimeLimit`: 2 min el monitor, 20 min la sonda).

## Seguridad de tasa y reputación

Cinco solicitudes GET cada 5 minutos desde un host siguen siendo de bajo volumen, pero el tiempo predecible y la falta de separación hacen que el tráfico sintético sea más fácil de identificar.

La configuración actual agrega dos guardarraíles por defecto:

1. `startJitterSecondsMax = 15` añade una pequeña demora aleatoria al inicio de cada ejecución.
2. `targetDelayMilliseconds = 750` separa las solicitudes para que el host no dispare todos los targets de forma consecutiva.

Guardarraíles operativos:

1. Mantén una solicitud por target por ciclo.
2. Evita programaciones de menos de un minuto para endpoints de streaming público.
3. Mantén el user agent estable y veraz.
4. Escalona múltiples sondas en lugar de lanzarlas en el mismo segundo del reloj.
5. Trata HTTP `403`, `429` o reinicios TLS repetidos como una señal para reducir la frecuencia y revisar la cadencia.

## Registro de logs

Los logs registran intencionalmente resultados y tiempos, pero nunca deben registrar tokens, encabezados de autorización ni trazas HTTP detalladas con secretos.

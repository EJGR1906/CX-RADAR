# Notas de Endurecimiento

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

La tarea programada también usa `RunOnlyIfNetworkAvailable` para que la sonda no siga generando fallas locales mientras la estación de trabajo está desconectada.

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

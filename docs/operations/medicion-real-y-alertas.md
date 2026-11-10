# Medición real, monitor cada minuto y reporte de ONUs

Guía para poner en marcha los cambios de la versión 0.3.0 de la sonda en el
servidor del hub (UCS C220, conectado como cliente: ONU, router y servidor).

## Qué cambió y por qué

| Problema | Causa | Cambio |
|---|---|---|
| Velocidades que no cuadran | Se descargaba una cantidad fija (32 MB en 8 conexiones) y se dividía entre el tiempo total. Con 600 Mbps eso dura menos de 1 s y casi todo es arranque lento de TCP. Con el mismo archivo de Microsoft: 240-375 Mbps con el método anterior, 1262 Mbps con el nuevo. | Motor por tiempo (`scripts/qoe_throughput.py`): 8 conexiones durante 8 s, se descartan los 2 primeros segundos. |
| Disney+ irreal | El archivo configurado es una imagen de 684 KB; cada conexión la bajaba una sola vez. | El motor la vuelve a pedir durante todo el tiempo de la prueba. |
| Mediciones vacías en Netflix | `fast-cli` abre Chrome sin interfaz y fast.com lo detecta como bot. | Método `fast-api`: el mismo procedimiento de la página (API pública, descargas y subidas contra la OCA) sin navegador. Registra en el log qué OCAs asignó Netflix. |
| Latencia 0 ms con 100 % de pérdida | Los CDN filtran el ping (ICMP). | Si no hay respuesta de ping, se mide el tiempo de conexión TCP. |
| La subida "de Microsoft" era de Cloudflare | Todas las subidas iban a `speed.cloudflare.com`. | Se mide una vez por corrida y el campo `upload_tool` dice a qué servidor fue. |
| Sin referencia dentro de Inter | Todo se medía contra servicios externos. | Método `ookla-http` contra los Ookla de Inter (Barquisimeto 38816 y Caracas 37714). |

Las páginas que ya se medían (Microsoft, YouTube, Netflix, Disney+, Amazon) se
mantienen; ahora se miden igual que un speedtest real.

Ajustes después de la primera corrida en HUB_BTO (10-nov):

- Las conexiones se reutilizan entre pedidos (keep-alive), como en un
  navegador. Con archivos pequeños, abrir una conexión por pedido hacía que
  casi todo el tiempo se fuera en conectar: Disney+ daba 55 Mbps en el hub.
- Disney+ mide contra los videos de su CDN de video (`media.dssott.com`,
  `downloadUrls`). No hay archivos públicos grandes de Disney+; con
  conexiones reutilizadas el tamaño deja de importar.
- Netflix mide solo contra las OCAs cuyo nombre contiene `ocaHostFilter`
  (`telemic`, la caché de Inter). fast.com también asigna OCAs de Bogotá y
  Miami, pero Netflix reproduce desde la caché del ISP. Si ninguna coincide,
  se mide contra todas y el log lo advierte. `source_host` y el log muestran
  qué OCAs se usaron.

Consumo de datos: cada prueba de velocidad dura unos 14 s (8 de bajada y 6 de
subida). Con 7 objetivos y un plan de 600 Mbps son del orden de 4 GB por
corrida. Cada 10 minutos serían unos 600 GB por día, así que se recomienda
ejecutar la sonda completa cada 30 minutos y dejar la detección rápida al
monitor de cada minuto. Las duraciones se ajustan en `probeRun`
(`downloadDurationSeconds`, `uploadDurationSeconds`, `warmupSeconds`), y
`"throughputEngine": "fixed-bytes"` vuelve al método anterior.

## Pasos en el servidor del hub

Todos desde la raíz del repositorio.

1. Dejar de editar `config/probe-catalog.json` en el servidor. Ese archivo
   llega con cada `git pull`; si el servidor lo modifica, el pull deja marcas
   de conflicto dentro y la sonda deja de leerlo (pasó en HUB_BTO). Los datos
   propios del servidor van en `config/probe-catalog.local.json`, que está
   fuera de git y se aplica encima del catálogo (ver
   `config/probe-catalog.local.example.json` y `scripts/qoe_config.py`):

   ```bash
   git checkout -- config/probe-catalog.json
   git pull origin main
   cp config/probe-catalog.local.example.json config/probe-catalog.local.json
   ```

   Después se ajustan los valores de `probe-catalog.local.json` (identidad,
   router, tipo de conexión). Solo se escriben las claves que cambian; una
   lista como `targets` reemplaza la del repo completa.

2. Validar y correr en seco:

   ```bash
   python scripts/validate_qoe_probe.py
   python scripts/qoe_probe.py --skip-influx-write
   ```

   En el log debe aparecer `fast-api OCAs asignadas: ...`. Si los nombres de
   las OCAs indican Venezuela o Inter, Netflix está sirviendo desde la caché
   interna. Los objetivos `Inter-Ookla-*` deben dar velocidad; si dan
   `connect_error`, el puerto 8080 no es accesible desde el hub.

3. Pasar la sonda completa a cada 30 minutos:

   ```bash
   python scripts/register_qoe_task.py --interval-minutes 30
   ```

4. Telegram:
   1. En Telegram, abrir @BotFather, enviar `/newbot` y seguir los pasos. Entrega un token.
   2. Agregar al `.env` de la raíz: `TELEGRAM_BOT_TOKEN=<token>`.
   3. Escribirle cualquier mensaje al bot nuevo y correr
      `python scripts/qoe_telegram.py --find-chat-id`.
   4. Agregar al `.env`: `TELEGRAM_CHAT_ID=<id>` y probar con
      `python scripts/qoe_telegram.py --test`.

5. Monitor cada minuto:

   ```bash
   python scripts/qoe_heartbeat.py --skip-telegram
   python scripts/register_qoe_task.py --script heartbeat --task-name CX-Radar-Heartbeat --interval-minutes 1
   ```

### Si Telegram da error de certificado

`qoe_telegram.py --test` explica la causa. En Windows Server 2012 R2 el
almacén de Windows puede no tener la raíz de GoDaddy que firma
`api.telegram.org` (Windows solo descarga raíces cuando las pide un
navegador, y Python no lo hace). Comprobar el emisor y, si es GoDaddy,
instalar la raíz verificando su huella SHA1
`47:BE:AB:C9:22:EA:E8:0E:78:78:34:62:A7:9F:45:C2:54:FD:E6:8B`:

```bash
openssl s_client -connect api.telegram.org:443 -servername api.telegram.org </dev/null 2>/dev/null | openssl x509 -noout -issuer
curl -sSo gdroot-g2.crt https://certs.godaddy.com/repository/gdroot-g2.crt
openssl x509 -in gdroot-g2.crt -noout -subject -fingerprint -sha1
certutil -addstore Root gdroot-g2.crt
```

Nunca desactivar la verificación de certificados: el token del bot quedaría
expuesto a quien intercepte la conexión.

### Disney+ en 0 % con `SSLCertVerificationError`

Mismo problema con otra raíz: los videos de Disney+ (`*.media.dssott.com`)
están firmados por Sectigo y su cadena termina en **Sectigo Public Server
Authentication Root R46** (2021). Si esa raíz no está en el almacén de Windows,
la sonda marca Disney+ como caído con `download_error` y el detalle
`SSLCertVerificationError`, aunque en el navegador los videos abran. Se ve en la
columna Detalle de "Estado de Endpoints" del tablero por sonda.

Instalar la raíz en la sonda (PowerShell como administrador) y comprobar antes
que la huella SHA1 sea `AD:98:F9:F3:E4:7D:75:3B:65:D4:82:B3:A4:52:17:BB:6E:F5:E4:38`
(la misma de la lista de Mozilla):

```powershell
Invoke-WebRequest -Uri http://crt.sectigo.com/SectigoPublicServerAuthenticationRootR46.crt -OutFile r46.crt
certutil -dump r46.crt | findstr /i "sha1"
certutil -addstore Root r46.crt
python -c "import urllib.request as u; u.urlopen('https://vod-bgc-na-east-1.media.dssott.com/ps01/disney/bgui/2025/11/19/1763572017-national-geographic.mp4').read(1024); print('OK')"
```

Si la última línea imprime `OK`, la siguiente corrida de la sonda mide Disney+.

## Monitor cada minuto (`qoe_heartbeat.py`)

Hace conexiones cortas (sin pruebas de velocidad) al router local, a los Ookla
de Inter, a Cloudflare, Google y fast.com, y resuelve DNS. Clasifica:

| Estado | Significado |
|---|---|
| `ok` | Todo responde dentro de los umbrales. |
| `degradado` | Responde, pero con latencia o pérdida altas, o algún destino no responde. |
| `caida_transito` | La red de Inter responde pero internet no: salida o tránsito. |
| `caida_acceso` | No responde nada: PON, OLT, agregación o BNG. |
| `caida_router_local` | No responde el router de la sonda: falla del punto de medición. |

Avisa por Telegram con 2 corridas malas seguidas (2 minutos), avisa si empeora
y avisa la recuperación con la duración. Si la caída impide enviar el aviso de
falla, no lo manda atrasado: al volver la conexión envía un solo mensaje
RECUPERADO con el diagnóstico (acceso, tránsito o router local), la hora de
inicio y la duración. Las
métricas que no se pudieron escribir se reenvían, así que Grafana muestra la
ventana completa.

Umbrales en la sección `heartbeat` del catálogo: `maxLatencyMs` (40 ms para
Inter, 150 ms para externos), `maxLossPercentage`, `failThreshold` y
`recoverThreshold`.

### Aviso inmediato durante la caída (Grafana Cloud)

Sin internet la sonda no puede llegar a Telegram, así que el aviso en el momento
lo da Grafana Cloud. La regla `CX-Radar: sonda sin reportar` revisa cada minuto
hace cuánto llegó el último `qoe_heartbeat_status` de cada sonda. Si pasan más
de 3 minutos, avisa por el mismo bot de Telegram (una alerta por sonda) y, cuando
la sonda vuelve a reportar, manda el aviso de resuelto.

Mensajes de una caída de acceso:

1. Grafana, unos 3 a 4 minutos después del corte: `SIN CONEXIÓN: no reporta hace N min`.
2. Grafana, al volver: `La sonda volvió a reportar`.
3. La sonda, al volver: `RECUPERADO` con el diagnóstico, la hora de inicio y la duración.

Grafana no distingue entre una sonda sin internet y un equipo apagado o
suspendido: avisa en los dos casos. Una sonda que no reporta en 7 días sale de
la consulta y su alerta se cierra sola.

Crear o actualizar la regla (idempotente):

```bash
python scripts/setup_grafana_alert.py --grafana-url https://<stack>.grafana.net --dry-run
python scripts/setup_grafana_alert.py --grafana-url https://<stack>.grafana.net
```

Necesita `GRAFANA_TOKEN` (service account con rol Editor o Admin) y las mismas
`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` de la sonda, en el entorno o en `.env`.
Crea el contact point `CX-Radar Telegram`, la carpeta `CX-Radar`, la regla y una
ruta `app=cx-radar` en la política de notificaciones, sin tocar las demás rutas.
Opciones: `--minutes` (umbral) y `--datasource-uid` (si hay más de un datasource
InfluxDB con Flux).

## Reporte diario de ONUs (`onu_report.py`)

Procesa el Excel de las 5 a. m. de la página de herramientas FTTH (una ciudad
o varias):

```bash
python scripts/onu_report.py ruta/informe_conectividad_ciudad.xlsx
python scripts/onu_report.py carpeta_con_los_xlsx/
```

Compara con el reporte anterior y marca por PON:
- 6 o más ONUs que estaban encendidas y hoy no, o el 30 % del PON con al
  menos 4 (corte de fibra, splitter o energía);
- una caída de 2 dB o más en la Rx media que ve el OLT;
- PONs con la mitad o más de sus ONUs apagadas.

Envía el resumen por Telegram, deja el detalle por PON en
`logs/onu-reports/<fecha>-pon.csv` y escribe un resumen por OLT en InfluxDB
(`onu_olt_health`). No se escribe por PON porque las 42 ciudades suman unas
40.000 series y la capa gratuita de InfluxDB Cloud admite unas 10.000.

Solo se leen columnas técnicas. El nombre, el número de abonado y la
dirección nunca se leen ni se guardan. Aun así, el Excel descargado contiene
esos datos: no se debe subir al repositorio ni compartir.

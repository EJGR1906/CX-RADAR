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

Consumo de datos: cada prueba de velocidad dura unos 14 s (8 de bajada y 6 de
subida). Con 7 objetivos y un plan de 600 Mbps son del orden de 4 GB por
corrida. Cada 10 minutos serían unos 600 GB por día, así que se recomienda
ejecutar la sonda completa cada 30 minutos y dejar la detección rápida al
monitor de cada minuto. Las duraciones se ajustan en `probeRun`
(`downloadDurationSeconds`, `uploadDurationSeconds`, `warmupSeconds`), y
`"throughputEngine": "fixed-bytes"` vuelve al método anterior.

## Pasos en el servidor del hub

Todos desde la raíz del repositorio.

1. Actualizar el código y revisar el catálogo. El actualizador no toca
   `config/probe-catalog.json`, así que hay que copiar a mano desde el
   repositorio: el objetivo Netflix con `fast-api`, los dos objetivos
   `Inter-Ookla-*`, las claves nuevas de `probeRun` y las secciones
   `heartbeat` y `onuReport`.

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
y avisa la recuperación con la duración. Si la caída impide enviar el mensaje,
lo guarda y lo envía al volver la conexión, con la hora real de la falla. Las
métricas que no se pudieron escribir se reenvían, así que Grafana muestra la
ventana completa.

Umbrales en la sección `heartbeat` del catálogo: `maxLatencyMs` (40 ms para
Inter, 150 ms para externos), `maxLossPercentage`, `failThreshold` y
`recoverThreshold`.

Mientras el acceso está caído la sonda no puede avisar en el momento. Para
recibir la alerta durante la caída hace falta una alerta "sin datos" en
Grafana Cloud sobre `qoe_heartbeat_status`: si no llegan datos en 3 minutos,
notificar al mismo bot de Telegram (contact point de tipo Telegram con el
mismo token y chat id).

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

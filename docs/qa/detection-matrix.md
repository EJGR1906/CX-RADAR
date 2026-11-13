# Matriz de detección

Qué fallas detecta el monitor de cada minuto (`scripts/qoe_heartbeat.py`), en
cuánto tiempo avisa y qué prueba automática lo demuestra. Las pruebas están en
`tests/test_fault_injection.py`: simulan la falla y corren el monitor completo
(muestreo, diagnóstico, InfluxDB, estado y Telegram). Si una fila no tiene
prueba, el producto no lo afirma.

```bash
python -m unittest discover -s tests
```

El CI (`.github/workflows/tests.yml`) las corre en Windows, Linux y macOS con
Python 3.8 y 3.13 en cada cambio.

## Fallas de la conexión

| Falla | Diagnóstico | Aviso | Prueba |
|---|---|---|---|
| Corte total del acceso | `caida_acceso` | 2 min. Sin conexión no sale por Telegram: avisa Grafana Cloud (3–4 min) y la sonda resume al volver | `test_total_outage_is_access_down_alerted_on_second_minute` |
| Corte que empieza a mitad de la corrida | `caida_acceso` en esa misma corrida | 2 min | `test_outage_starting_mid_window_is_already_a_cut` |
| Sale a la red del proveedor pero no a internet | `caida_transito` | 2 min | `test_transit_outage_isp_answers_internet_does_not` |
| DNS caído (hay conexión por IP) | `falla_dns`, indica si los DNS públicos responden | 2 min | `test_dns_outage_is_diagnosed_as_dns_not_as_degraded`, `test_dns_outage_without_cached_ips_is_still_dns` |
| Cable o Wi-Fi desconectado en la sonda | `sin_red_local` (no culpa al proveedor) | 2 min, al volver | `test_unplugged_cable_is_local_not_the_isp` |
| Router de la sonda apagado | `caida_router_local` | 2 min, al volver | `test_router_down_is_local_router` |
| Portal cautivo o proxy que responde por internet | `internet_interceptado` | 2 min | `test_captive_portal_is_not_reported_as_ok` |
| Microcorte de 20 s | `microcortes`, con los segundos sin respuesta | Se registra. Avisa si se repite 5 min seguidos | `test_twenty_second_microcut_is_seen_and_measured`, `test_repeated_microcuts_alert` |
| Latencia alta sostenida | `degradado` | 5 min | `test_high_latency_alerts_only_when_sustained_five_minutes` |
| Latencia alta de 1–2 min | `degradado` | No avisa | `test_short_latency_blip_does_not_alert` |
| Pérdida de 10 % | Se mide (`loss_pct`), estado `ok` | No avisa | `test_ten_percent_loss_is_measured_but_not_an_alarm` |
| Pérdida de 30 % en un destino | `degradado` | 5 min | `test_thirty_percent_loss_on_one_target_is_degraded` |
| Conexión intermitente (3 cortes en 10 min) | Un solo incidente | 1 FALLA y 1 RECUPERADO con el número de cortes | `test_flapping_is_one_incident_with_cut_count` |
| Degradación que termina en corte | `degradado` y luego la caída | EMPEORA inmediato | `test_degraded_then_outage_escalates` |

## Servicios externos

| Falla | Diagnóstico | Aviso | Prueba |
|---|---|---|---|
| Outlook no responde (error 5xx, conexión cortada, timeout) | Servicio `caido`, red `ok` | 3 min, "la falla es del servicio, no de la conexión" | `test_outlook_outage_is_reported_as_external_service` |
| Falla una parte de las pruebas de un servicio | `parcial` | 3 min | `test_partial_outlook_failure_says_partial` |
| Servicio "caído" porque la red de la sonda está caída | No se evalúa | No avisa del servicio | `test_services_are_not_blamed_while_the_network_is_down` |

## Fallas de la propia sonda

| Falla | Comportamiento | Prueba |
|---|---|---|
| Archivo de estado dañado | Se descarta y el monitor sigue | `test_corrupt_state_file_does_not_kill_the_monitor` |
| Error interno del monitor | Queda en el log y avisa por Telegram una vez cada 6 h | `test_internal_error_is_logged_and_notified_once`, `test_main_survives_an_exception_inside_run` |
| InfluxDB sin respuesta durante la caída | Las métricas se guardan y se reenvían completas | `test_outage_metrics_are_resent_when_influx_returns` |
| InfluxDB rechaza una línea guardada | Se aparta y lo nuevo sigue entrando | `test_rejected_buffer_is_set_aside_and_new_data_flows` |
| Telegram sin respuesta al recuperar | El RECUPERADO queda pendiente y sale después | `test_recovery_waits_for_telegram_and_is_sent_late` |
| Dos corridas a la vez | La segunda se omite; un bloqueo viejo se ignora | `test_only_one_run_at_a_time_and_stale_lock_is_taken` |

## Caso real

`test_november_12_produces_one_alert_per_real_outage` repite los 1425 estados
del log del 12/11/2026 (`tests/fixtures/heartbeat-2026-11-12-statuses.txt`):
la lógica anterior envió 13 avisos de FALLA; la actual envía 4, uno por cada
corte real (12:32, 12:58, 13:33 y 15:55).

## Lo que no se detecta

- Cortes de menos de 10 s (dos rondas de 5 s).
- Fallas de Outlook por cuenta o buzón: el portal carga pero el correo no sale.
- Diferencia entre una sonda sin internet y un equipo apagado o suspendido, vista desde Grafana.
- Velocidad baja: la mide la sonda completa cada 30 min y todavía no tiene alerta.
- En Windows falta confirmar en una sonda real que las latencias dejan de ser múltiplos de 15,6 ms y que la tarea corre con el cable desconectado.

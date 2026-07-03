# Guía de Despliegue de Sonda Híbrida (Python + Telegraf)

Esta guía explica cómo implementar y configurar el esquema híbrido en sucursales u oficinas remotas críticas con conexiones inestables.

---

## Arquitectura de Operación

En este modelo, el sistema se divide en dos componentes locales en cada host de sonda:
1. **Sonda de Python (`qoe_probe.py`):** Ejecuta las pruebas sintéticas activas definidas en `config/probe-catalog.json`, realiza cálculos de QoE y velocidades, y escribe los resultados resultantes en formato Line Protocol a la salida estándar (`stdout`). Los logs de diagnóstico van a `stderr` y al archivo de log diario local.
2. **Telegraf (Agente de Transporte):** Ejecuta la sonda a intervalos fijos, captura los datos de `stdout`, administra un búfer local en memoria/disco en caso de desconexión y se encarga de subir las métricas a InfluxDB Cloud cuando hay enlace disponible.

---

## 1. Despliegue en Windows (Windows 11 / Windows Server)

### Paso A: Preparar el Entorno
1. Instale **Python 3.8+** en el host. Asegúrese de marcar la opción "Add Python to PATH" durante la instalación.
2. Descargue y descomprima **Telegraf** para Windows (ej. `C:\Program Files\Telegraf`).
3. Descargue o clone el repositorio de **CX-Radar** en una ruta del disco (ej. `C:\CX-Radar`).

### Paso B: Configurar el Servicio de Telegraf
1. Edite el archivo de configuración `telegraf.conf` (copie el contenido de `config/telegraf-qoe.conf` de este repositorio) y colóquelo en `C:\Program Files\Telegraf\telegraf.conf`.
2. Configure la sección `[[inputs.exec]]` con el comando correspondiente para Windows:
   ```toml
   [[inputs.exec]]
     commands = ['python "C:\\CX-Radar\\scripts\\qoe_probe.py" --skip-influx-write --config-path "C:\\CX-Radar\\config\\probe-catalog.json"']
     timeout = "4m30s"
     data_format = "influx"
   ```
3. Configure la sección de salida `[[outputs.influxdb_v2]]` con los datos de su cuenta InfluxDB Cloud.
4. Establezca el token de InfluxDB como una variable de entorno del sistema (`INFLUX_TOKEN`). Esto es preferible a guardarlo en texto plano en el archivo de configuración.

### Paso C: Registrar Telegraf como Servicio de Windows
Abra una consola de PowerShell como Administrador y ejecute:
```powershell
# Registrar Telegraf como servicio de Windows
& "C:\Program Files\Telegraf\telegraf.exe" --service install --config "C:\Program Files\Telegraf\telegraf.conf"

# Establecer la variable de entorno INFLUX_TOKEN para el servicio de Windows
[System.Environment]::SetEnvironmentVariable('INFLUX_TOKEN', 'TU_TOKEN_DE_INFLUXDB', 'Machine')

# Iniciar el servicio
Start-Service telegraf
```

---

## 2. Despliegue en Linux (Ubuntu / RHEL)

### Paso A: Instalar Dependencias y Agente
1. Instale Python 3:
   ```bash
   sudo apt-get update && sudo apt-get install -y python3
   ```
2. Instale Telegraf desde el repositorio oficial de InfluxData:
   ```bash
   # Agregar llave y repositorio de InfluxData
   curl -s https://repos.influxdata.com/influxdata-archive_compat.key | sudo apt-key add -
   echo "deb https://repos.influxdata.com/debian stable main" | sudo tee /etc/apt/sources.list.d/influxdata.list
   
   # Instalar agente
   sudo apt-get update && sudo apt-get install -y telegraf
   ```
3. Coloque el código de **CX-Radar** en una ruta (ej. `/opt/cx-radar`).

### Paso B: Configurar Telegraf
1. Reemplace el archivo `/etc/telegraf/telegraf.conf` con el contenido del archivo `config/telegraf-qoe.conf`.
2. Modifique la sección `[[inputs.exec]]` para Linux:
   ```toml
   [[inputs.exec]]
     commands = ["python3 /opt/cx-radar/scripts/qoe_probe.py --skip-influx-write --config-path /opt/cx-radar/config/probe-catalog.json"]
     timeout = "4m30s"
     data_format = "influx"
   ```
3. Para configurar el token de forma segura en systemd, edite el servicio para inyectar la variable de entorno:
   ```bash
   sudo systemctl edit telegraf
   ```
   Añada el siguiente bloque en el editor:
   ```ini
   [Service]
   Environment="INFLUX_TOKEN=TU_TOKEN_DE_INFLUXDB"
   ```
4. Recargue el demonio de systemd e inicie el servicio:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart telegraf
   sudo systemctl enable telegraf
   ```

---

## 3. Ajustes de Resiliencia en Producción

En el archivo `telegraf.conf` de producción, preste especial atención a las siguientes directivas bajo la sección `[agent]`:

* **`metric_buffer_limit = 10000`**: Define cuántas métricas guarda Telegraf en memoria si InfluxDB Cloud no está disponible. Como una corrida típica de la sonda genera entre 5 y 20 métricas (según el número de targets), un buffer de `10000` permitirá guardar el equivalente a cientos de corridas (varios días de inactividad de enlace) antes de empezar a descartar métricas viejas.
* **`timeout = "4m30s"`**: Si su catálogo de pruebas en `probe-catalog.json` tiene muchos targets de Speedtest (los cuales pueden tardar hasta 1-2 minutos por target en conexiones saturadas), asegúrese de que el timeout de `inputs.exec` sea mayor a la duración máxima estimada de la sonda. De lo contrario, Telegraf terminará el proceso de forma abrupta antes de que éste imprima las métricas a stdout.

---

## 4. Diagnóstico de Problemas

1. **Ver los logs de diagnóstico de la sonda Python:**
   * La sonda sigue escribiendo logs detallados en la carpeta `logs/qoe-probe-YYYY-MM-DD.log` relativa al catálogo. Revise este archivo si sospecha que algún target está fallando o dando timeouts internos.
2. **Ver los logs de error de Telegraf:**
   * **Linux:** `journalctl -u telegraf -n 50 --no-pager`
   * **Windows:** Revise el Visor de Eventos (Event Viewer) de Windows bajo *Application logs* buscando la fuente `Telegraf`.
3. **Probar la ejecución manual de Telegraf:**
   Para validar que Telegraf ejecuta correctamente el script de Python y parsea las métricas sin subirlas (modo dry-run), ejecute:
   ```bash
   telegraf --config config/telegraf-qoe.conf --test
   ```
   Debería ver las métricas formateadas en la consola.

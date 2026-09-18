# Guía de Instalación, Configuración y Uso

Este documento proporciona las instrucciones operativas para instalar, desplegar y operar la solución CX-Radar en servidores corporativos, manteniendo un procedimiento sencillo e intuitivo.

---

## 1. Requisitos Previos

Antes de iniciar la instalación en un servidor, verifique que se cumplan las siguientes condiciones:

- **Sistema Operativo**: Compatible con Windows (10, 11, Server 2012 R2 en adelante), Linux o macOS.
- **Python 3**: Debe estar instalado Python versión 3.8 o superior (con la opción de agregar Python a la variable de entorno PATH activada).
- **Conectividad a Internet**: Requerida para realizar las mediciones y transmitir métricas a la nube.
- **Credenciales de InfluxDB Cloud**: Token de acceso con permisos de escritura, dirección URL de la organización y nombre del bucket configurado.

---

## 2. Método Recomendado: Instalador Unificado Automatizado

La forma más rápida y segura de desplegar la sonda es mediante el instalador automatizado (`scripts/install.py`). Este componente guía al usuario en el proceso, descarga las herramientas necesarias, almacena las credenciales de forma segura y registra las tareas programadas en el sistema operativo.

### Opción A: Instalación Interactiva (Recomendada)

1. Descargue o clone el repositorio en la carpeta de su preferencia dentro del servidor.
2. Abre una consola de comandos o terminal en dicha carpeta.
3. Ejecute el siguiente comando:
   ```bash
   python scripts/install.py
   ```
4. El asistente interactivo solicitará los siguientes datos (mostrando valores predeterminados entre corchetes):
   - **Identificador de la Sonda (`probeId`)**: Nombre único del equipo (ejemplo: `Sonda-Sede-Central`).
   - **Ubicación o Sede (`site`)**: Nombre de la oficina o servidor (ejemplo: `Oficina-Lima`).
   - **Entorno (`environment`)**: Clasificación del entorno (ejemplo: `production`).
   - **Proveedor de Internet (`isp`)**: Nombre del proveedor del enlace (ejemplo: `Fibra-Empresarial`).
   - **Token de InfluxDB (`influxToken`)**: Clave de autenticación para la base de datos en la nube.
   - **URL de InfluxDB**: Dirección del servicio InfluxDB Cloud.
   - **Organización y Bucket**: Nombres asignados en su cuenta de InfluxDB.
   - **Intervalo de Ejecución**: Frecuencia deseada para las pruebas (predeterminado: 10 minutos).

Al finalizar, el instalador dejará la sonda operando de forma automática.

### Opción B: Instalación Desatendida (Ideal para Despliegue Masivo)

Si requiere desplegar la sonda en múltiples servidores mediante scripts automáticos, puede enviar los parámetros directamente en una sola línea de comandos:

```bash
python scripts/install.py \
  --probe-id "Sonda-Sede-Central" \
  --site "Oficina-Lima" \
  --environment "production" \
  --isp "Fibra-Empresarial" \
  --influx-token "SU_TOKEN_DE_INFLUXDB" \
  --influx-url "https://us-east-1-1.aws.cloud2.influxdata.com" \
  --influx-org "su-organizacion" \
  --influx-bucket "qoe_metrics" \
  --interval-minutes 10
```

---

## 3. Método Manual Paso a Paso (Alternativo)

Si desea realizar la configuración paso a paso o requiere auditar cada etapa del proceso:

### Paso 1: Descargar Herramientas Portables
Ejecute el script de preparación para descargar las dependencias portables de Node.js, `fast-cli` y `yt-dlp` en el directorio local `bin/`:
```bash
python scripts/setup_portable.py
```

### Paso 2: Editar el Archivo de Configuración
Abra el archivo `config/probe-catalog.json` con un editor de texto y configure los parámetros de la sonda y los servicios web a evaluar.

### Paso 3: Guardar el Token de Forma Segura
Almacene la clave de InfluxDB en un archivo local cifrado y restringido (`.env`):
```bash
python scripts/set_influx_token.py --method file
```

### Paso 4: Validar el Entorno
Verifique que la configuración, herramientas y tokens se hayan registrado correctamente:
```bash
python scripts/validate_qoe_probe.py
```

### Paso 5: Prueba de Ejecución en Seco
Compruebe que la sonda realiza las mediciones sin escribir en la base de datos remota:
```bash
python scripts/qoe_probe.py --skip-influx-write
```

### Paso 6: Programación Automática de la Tarea
Registre la sonda en el planificador de tareas nativo del sistema operativo para que se ejecute en segundo plano cada 10 minutos:
```bash
python scripts/register_qoe_task.py
```

### Paso 7: Programación de Actualizaciones Automáticas
Active la tarea diaria de actualización (configurada por defecto a las 08:00 AM):
```bash
python scripts/update_qoe_probe.py --register
```

---

## 4. Visualización de Resultados

Una vez que la sonda se encuentra operando, los resultados pueden consultarse a través de tres medios:

1. **Registros Locales**: En la carpeta `logs/` del servidor se genera un archivo de texto diario (`qoe-probe-YYYY-MM-DD.log`) con el detalle cronológico de cada prueba.
2. **Plataforma InfluxDB Cloud**: Acceso a la base de datos en la nube para consultas personalizadas sobre las series temporales.
3. **Paneles en Grafana Cloud**: Visualización ejecutiva interactiva utilizando los tableros incluidos en la carpeta `grafana/dashboards/`:
   - **Tablero Global Nacional**: Vista consolidada del estado de todas las sedes y servicios a nivel nacional.
   - **Tablero Detallado por Sonda**: Vista técnica específica para analizar el comportamiento individual de un servidor determinado.

---

## 5. Preguntas Frecuentes de Operación

- **¿La sonda modifica configuraciones del servidor?** No. Opera de forma completamente aislada utilizando herramientas portables en su propia carpeta.
- **¿Qué sucede si se interrumpe la conexión a internet?** La sonda registra el evento de desconexión localmente y reintentará la medición en el siguiente ciclo programado sin bloquear el sistema.
- **¿Cómo se actualiza la solución?** El script de actualización diaria descarga de forma transparente las mejoras publicadas en el repositorio central previa validación de firmas digitales.

# Sistema de Monitoreo Ambiental Inteligente (DHT22 + ESP8266)

Sistema de monitoreo ambiental orientado a objetos, pensado para apoyar el secado y
almacenamiento poscosecha de café y granos en Chachapoyas (Amazonas, Perú). Lee un sensor
DHT22 (real o simulado), calcula un nivel de riesgo, guarda el historial en JSON y entrena un
modelo de Machine Learning que predice la siguiente lectura.

Proyecto final del curso **POO Avanzado** — Universidad Nacional Toribio Rodríguez de Mendoza
de Amazonas (UNTRM).

## Requisitos

- **Python 3.10+** (probado en 3.13).
- Dependencias de Python (ver [`requirements.txt`](requirements.txt)):
  - `pandas`, `matplotlib`, `scikit-learn`, `pyserial`
- Para usar el sensor **real** (opcional; sin esto el sistema funciona igual en modo simulado):
  - Un DHT22 cableado a un ESP8266 (NodeMCU/Wemos), conectado a la PC por cable USB.
  - [Arduino IDE](https://www.arduino.cc/en/software) con soporte para placas ESP8266 y la
    librería **"DHT sensor library"** de Adafruit instalada.

## Instalación

```bash
pip install -r requirements.txt
```

## Preparar el sensor real (opcional)

Si vas a usar el DHT22 físico en vez del modo simulado:

1. Cablea el DHT22 al ESP8266: DATA → pin **D2** (GPIO4), VCC → **3V3**, GND → **GND**.
2. Abre [`esp8266_dht22.ino`](esp8266_dht22.ino) en el Arduino IDE y súbelo al ESP8266
   (selecciona la placa y el puerto correctos en Herramientas).
3. Deja el ESP8266 conectado por USB a la PC. **No hace falta WiFi**: se descartó a propósito
   porque el radio del ESP8266 interfiere con la lectura del DHT22. El ESP8266 solo necesita
   quedar conectado por cable.
4. Cierra el Monitor Serie del Arduino IDE antes de correr `proyecto2.0.py` — si lo dejas
   abierto, se queda dueño del puerto y Python no podrá conectarse (`PermissionError`).

## Uso

```bash
python proyecto2.0.py
```

Aparece un menú con 9 opciones:

| Opción | Qué hace |
|---|---|
| 1 | Conectar un sensor **simulado** (genera lecturas aleatorias realistas; no necesita hardware). |
| 2 | Conectar el sensor **real** (lista los puertos COM disponibles y pide cuál usar). |
| 3 | Ver los sensores conectados. |
| 4 | Leer todos los sensores conectados una vez y guardar la lectura en `historial_dht22.json`. |
| 5 | Medir un sensor de forma continua en segundo plano (cada 3s) — presiona ENTER para pausar. |
| 6 | Comparar dos mediciones guardadas de un sensor (cuál tuvo más riesgo, y su promedio). |
| 7 | Entrenar el modelo de predicción con el historial acumulado (mínimo 12 lecturas). |
| 8 | Predecir la siguiente lectura a partir de una temperatura/humedad actuales. |
| 9 | Salir. |

**Flujo típico:**

1. Opción 1 (simulado) u opción 2 (real) para conectar un sensor.
2. Opción 4 u opción 5 varias veces hasta acumular al menos 12 lecturas.
3. Opción 7 para entrenar el modelo.
4. Opción 8 para pedirle una predicción.

## Archivos que genera el sistema

- `historial_dht22.json` — historial de todas las lecturas tomadas (persistencia).
- `grafico_prediccion.jpg` — gráfico de temperatura/humedad real vs. predicha (se regenera cada
  vez que entrenas el modelo, opción 7).
- `reporte_prediccion.txt` — interpretación en texto del modelo entrenado (R², confiabilidad).

## Estructura del proyecto

```
proyecto2.0.py       → programa principal (Python)
esp8266_dht22.ino    → firmware del ESP8266 (Arduino/C++), solo necesario si usas el sensor real
requirements.txt     → dependencias de Python
```

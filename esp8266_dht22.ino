// Firmware del ESP8266: lee el DHT22 y manda cada lectura por el cable USB.
// El script de Python (proyecto2.0.py) NO usa WiFi: lee este puerto Serial con
// pyserial y busca el patrón "Humedad del aire: X%  |  Temperatura: Y°C" en
// cada línea. Se eligió este modo porque el WiFi del ESP8266 interfiere con la
// temporización que necesita el DHT22 para leerse bien (probado en la práctica).

#include "DHT.h"

// Definimos el pin digital donde está conectado el sensor de datos
// En las placas NodeMCU/Wemos, el pin D2 corresponde al GPIO4
#define DHTPIN 4

// Especificamos el tipo de sensor que estamos usando
#define DHTTYPE DHT22   // DHT 22 (AM2302, AM2321)

// Inicializamos el objeto del sensor
DHT dht(DHTPIN, DHTTYPE);

void setup() {
  // Iniciamos la comunicación serial a 115200 baudios (frecuencia típica del ESP8266)
  Serial.begin(115200);
  Serial.println(F("\nIniciando lectura del sensor DHT22..."));

  // Arrancamos el sensor
  dht.begin();
}

void loop() {
  // El DHT22 requiere al menos 2 segundos entre cada lectura para ser preciso
  delay(2000);

  // Leemos la humedad relativa (%)
  float h = dht.readHumidity();

  // Leemos la temperatura en grados Celsius (°C)
  float t = dht.readTemperature();

  // Comprobamos si la lectura falló (NaN = Not a Number) para evitar errores
  if (isnan(h) || isnan(t)) {
    Serial.println(F("¡Error: No se pudo leer el sensor DHT22! Revisa las conexiones."));
    return;
  }

  // Mostramos los resultados en el Monitor Serie
  Serial.print(F("Humedad del aire: "));
  Serial.print(h);
  Serial.print(F("%  |  "));
  Serial.print(F("Temperatura: "));
  Serial.print(t);
  Serial.println(F("°C"));
}

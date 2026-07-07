from abc import ABC, abstractmethod
import random
import os
import json
import threading
import re
import time
import pandas as pd
import serial
import matplotlib.pyplot as plt
from datetime import datetime
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import train_test_split

# ==========================================
# 1. METACLASE
# ==========================================
class RegistroSensoresMeta(type(ABC)):
    clases_sensores = []
    def __new__(mcs, name, bases, dct):
        cls = super().__new__(mcs, name, bases, dct)
        if name not in ["Sensor"]:
            mcs.clases_sensores.append(name)
        return cls

# ==========================================
# 2. DECORADORES
# ==========================================
def avisar_medicion(funcion):
    def proceso(self, *args, **kwargs):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {self.__class__.__name__} ({self.id}) consultando al DHT22...")
        return funcion(self, *args, **kwargs)
    return proceso

def cachear_medicion(funcion):
    # El DHT22 real necesita al menos 2 segundos entre lecturas o devuelve datos corruptos.
    # Este decorador simula esa restricción reutilizando la última lectura si no ha pasado el tiempo mínimo.
    def envoltura(self, *args, **kwargs):
        ahora = datetime.now()
        ultima = getattr(self, '_hora_ultima_lectura', None)
        if ultima is not None and (ahora - ultima).total_seconds() < 2:
            print("   ⏳ Lectura en caché (todavía no pasan 2s desde la última consulta al DHT22).")
            return self._cache_lectura
        resultado = funcion(self, *args, **kwargs)
        self._hora_ultima_lectura = ahora
        self._cache_lectura = resultado
        return resultado
    return envoltura

# ==========================================
# 3. PATRÓN OBSERVER: PERSISTENCIA EN JSON
# ==========================================
class Observador(ABC):
    @abstractmethod
    def actualizar(self, datos):
        pass

class GestorDatosJSON(Observador):
    def __init__(self, archivo="historial_dht22.json"):
        self.archivo = archivo
        if not os.path.exists(self.archivo):
            with open(self.archivo, 'w', encoding='utf-8') as f:
                json.dump([], f)

    def actualizar(self, datos):
        with open(self.archivo, 'r', encoding='utf-8') as f:
            historial = json.load(f)

        historial.append({
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "id_sensor": datos['id'],
            "temperatura": round(datos['temperatura'], 2),
            "humedad": round(datos['humedad'], 2)
        })

        with open(self.archivo, 'w', encoding='utf-8') as f:
            json.dump(historial, f, indent=2, ensure_ascii=False)

    def cantidad_registros(self):
        with open(self.archivo, 'r', encoding='utf-8') as f:
            return len(json.load(f))

# ==========================================
# 4. DESCRIPTOR: VALIDACIÓN DE RANGO FÍSICO
# ==========================================
class ValidarRango:
    def __init__(self, minimo, maximo, nombre_atributo):
        self.minimo = minimo
        self.maximo = maximo
        self.nombre_interno = f'_{nombre_atributo}'

    def __get__(self, instancia, propietario):
        if instancia is None:
            return self
        return getattr(instancia, self.nombre_interno, 0.0)

    def __set__(self, instancia, valor):
        if not(self.minimo <= valor <= self.maximo):
            raise ValueError(f'Peligro de hardware: el valor {valor} no es posible para el sensor.')
        setattr(instancia, self.nombre_interno, valor)

# ==========================================
# 5. CLASE BASE Y JERARQUÍA (todo gira en torno al DHT22)
# ==========================================
class Sensor(ABC, metaclass=RegistroSensoresMeta):
    # Límites físicos reales del DHT22 según su hoja de datos
    temperatura = ValidarRango(-40, 85, "temperatura")
    humedad = ValidarRango(0, 100, "humedad")

    def __init__(self, id, ubicacion):
        self.id = id
        self._ubicacion = ubicacion
        self.observadores = []
        self.historial_mediciones = []  # guarda cada Medicion tomada en la sesión

    @property
    def ubicacion(self):
        return self._ubicacion

    @ubicacion.setter
    def ubicacion(self, nueva):
        if not isinstance(nueva, str): raise ValueError("Ubicación inválida.")
        self._ubicacion = nueva

    def agregar_observador(self, observador):
        self.observadores.append(observador)

    def notificar_observadores(self):
        datos = {"id": self.id, "temperatura": self.temperatura, "humedad": self.humedad}
        for obs in self.observadores:
            obs.actualizar(datos)

    @abstractmethod
    def medir(self):
        pass

    def __repr__(self):
        return f'{self.__class__.__name__}(ID: {self.id}, Ubicación: {self.ubicacion})'

class Medicion:
    """Una lectura puntual del DHT22 (temperatura + humedad) en un momento dado.
    Como solo hay un sensor físico, lo que tiene sentido comparar/combinar no son
    dos sensores, sino dos lecturas suyas tomadas en momentos distintos."""
    def __init__(self, temperatura, humedad, momento=None):
        self.temperatura = temperatura
        self.humedad = humedad
        self.momento = momento or datetime.now()

    @property
    def nivel_riesgo(self):
        # Índice simple (0 a 1) de qué tan lejos están la temperatura y la humedad
        # de un rango cómodo/seguro en esa lectura puntual.
        riesgo_temp = max(0.0, (self.temperatura - 30) / 20)
        riesgo_hum = max(0.0, (self.humedad - 70) / 30)
        return min(1.0, (riesgo_temp + riesgo_hum) / 2)

    def __repr__(self):
        return f'Medicion({self.momento.strftime("%H:%M:%S")} - Temp: {self.temperatura:.1f}°C, Humedad: {self.humedad:.1f}%)'

    def __add__(self, otra):
        # Promedia dos lecturas (ej: para suavizar ruido entre dos mediciones cercanas)
        if not isinstance(otra, Medicion):
            return NotImplemented
        return Medicion((self.temperatura + otra.temperatura) / 2, (self.humedad + otra.humedad) / 2)

    def __lt__(self, otra):
        # Compara qué lectura fue más riesgosa (ej: la de la mañana vs la de la tarde)
        if not isinstance(otra, Medicion):
            return NotImplemented
        return self.nivel_riesgo < otra.nivel_riesgo

# -- Clase intermedia: todo lo común de un DHT22 (caché, notificación) --
class SensorDHT22(Sensor):
    def _leer_valores_crudos(self):
        # Cada modo de operación (real o simulado) decide cómo obtener el dato crudo.
        raise NotImplementedError

    # cachear_medicion va aquí (y no en _leer_valores_crudos) porque medir() es el
    # único método que NO sobrescriben las subclases: si el caché se pusiera en
    # _leer_valores_crudos, cada subclase lo taparía al redefinirlo y nunca se aplicaría.
    @avisar_medicion
    @cachear_medicion
    def medir(self):
        self.temperatura, self.humedad = self._leer_valores_crudos()
        medicion = Medicion(self.temperatura, self.humedad)
        self.historial_mediciones.append(medicion)
        print(f'   DHT22 -> Temp: {self.temperatura:.1f}°C | Humedad: {self.humedad:.1f}%')
        self.notificar_observadores()
        return medicion

# -- Polimorfismo: dos formas de obtener el dato crudo del mismo DHT22 --
class SensorDHT22Simulado(SensorDHT22):
    """Para desarrollar y probar el sistema sin tener la placa conectada."""
    def _leer_valores_crudos(self):
        return random.uniform(15, 38), random.uniform(30, 95)

class SensorDHT22Real(SensorDHT22):
    """El DHT22 real está cableado a un ESP8266 conectado a la PC por cable USB.
    El ESP8266 corre su propio firmware (ver esp8266_dht22.ino) que imprime cada
    lectura por Serial como "Humedad del aire: 61.30%  |  Temperatura: 24.70°C".
    Python solo lee ese puerto y extrae los dos números con una expresión regular.
    (Se descartó leerlo por WiFi: el radio del ESP8266 interfiere con la
    temporización que necesita el DHT22 y las lecturas fallaban siempre)."""

    PATRON_LECTURA = re.compile(r'Humedad del aire:\s*([\d.]+)%.*Temperatura:\s*([\d.]+)')

    def __init__(self, id, ubicacion, puerto, baudios=115200):
        super().__init__(id, ubicacion)
        self.conexion = serial.Serial(puerto, baudios, timeout=5)
        time.sleep(2)  # el ESP8266 se reinicia al abrirse el puerto serie; hay que esperar a que arranque

    def _leer_valores_crudos(self):
        # Se leen varias líneas porque el ESP8266 también manda mensajes que no son
        # lecturas (el aviso de inicio, o "¡Error: No se pudo leer el sensor!").
        for _ in range(5):
            linea = self.conexion.readline().decode('utf-8', errors='ignore').strip()
            if not linea:
                continue
            coincidencia = self.PATRON_LECTURA.search(linea)
            if coincidencia:
                humedad, temperatura = float(coincidencia.group(1)), float(coincidencia.group(2))
                return temperatura, humedad

        raise RuntimeError("El ESP8266 no envió una lectura válida por el puerto serie (revisa el cable y el puerto).")

# ==========================================
# 6. MACHINE LEARNING: PREDICCIÓN DE TEMPERATURA Y HUMEDAD
# ==========================================
# El modelo aprende del historial real guardado en el JSON: a partir de la lectura
# actual del DHT22, predice cuál será la siguiente lectura de temperatura y humedad.
class MotorPredictivo:
    MINIMO_LECTURAS = 12

    def __init__(self, archivo_datos="historial_dht22.json"):
        self.archivo_datos = archivo_datos
        self.modelo = LinearRegression()
        self.entrenado = False
        self.r2 = 0.0

    def entrenar_modelo(self):
        try:
            with open(self.archivo_datos, 'r', encoding='utf-8') as f:
                historial = json.load(f)
        except FileNotFoundError:
            print("⚠️ Todavía no hay datos guardados. Lee el sensor primero.")
            return

        if len(historial) < self.MINIMO_LECTURAS:
            print(f"⚠️ Se necesitan al menos {self.MINIMO_LECTURAS} lecturas para entrenar (hay {len(historial)}).")
            return

        df = pd.DataFrame(historial)
        X = df[['temperatura', 'humedad']].iloc[:-1].values  # lectura actual
        y = df[['temperatura', 'humedad']].iloc[1:].values   # lectura siguiente

        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
        self.modelo.fit(X_train, y_train)
        score = self.modelo.score(X_test, y_test)
        self.entrenado = True
        self.r2 = score

        predicciones = self.modelo.predict(X_test)
        self._generar_grafico(y_test, predicciones)
        self._generar_reporte(score)

        print(f"📊 Modelo entrenado con éxito (R²: {score:.3f}).")
        print("🖼️ Se generaron 'grafico_prediccion.jpg' y 'reporte_prediccion.txt'.")

    def _generar_grafico(self, y_real, y_pred):
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))

        ax1.plot(y_real[:, 0], 'o-', color='green', label='Temperatura real')
        ax1.plot(y_pred[:, 0], 'x--', color='orange', label='Temperatura predicha')
        ax1.set_title('Predicción de Temperatura')
        ax1.set_xlabel('Muestra de prueba')
        ax1.set_ylabel('°C')
        ax1.legend()

        ax2.plot(y_real[:, 1], 'o-', color='blue', label='Humedad real')
        ax2.plot(y_pred[:, 1], 'x--', color='red', label='Humedad predicha')
        ax2.set_title('Predicción de Humedad')
        ax2.set_xlabel('Muestra de prueba')
        ax2.set_ylabel('%')
        ax2.legend()

        plt.tight_layout()
        plt.savefig('grafico_prediccion.jpg', format='jpg', dpi=300)
        plt.close()

    def _generar_reporte(self, score):
        # coef_ tiene forma (2,2): fila 0 = pesos para predecir temperatura,
        # fila 1 = pesos para predecir humedad. Columna 0 = peso de la temp.
        # actual, columna 1 = peso de la humedad actual.
        coef = self.modelo.coef_
        confiabilidad = "alta" if score > 0.7 else "media" if score > 0.4 else "baja"

        interpretacion = "INTERPRETACIÓN DE LOS PESOS DEL MODELO:\n"
        if abs(coef[0][0]) > abs(coef[0][1]):
            interpretacion += "• La temperatura futura depende principalmente de la temperatura actual.\n"
        else:
            interpretacion += "• La temperatura futura está más influenciada por la humedad actual que por la temperatura misma.\n"
        if abs(coef[1][1]) > abs(coef[1][0]):
            interpretacion += "• La humedad futura depende principalmente de la humedad actual.\n"
        else:
            interpretacion += "• La humedad futura está más influenciada por la temperatura actual que por la humedad misma.\n"

        texto = f"""=== REPORTE DEL MODELO DE PREDICCIÓN ===
Se entrenó una Regresión Lineal con el historial real del DHT22: a partir de la
lectura actual de temperatura y humedad, el modelo predice la siguiente lectura.

Precisión del modelo (R²): {score:.3f} (confiabilidad {confiabilidad})

{interpretacion}
¿CÓMO LEER EL GRÁFICO (grafico_prediccion.jpg)?
Arriba se compara la temperatura real contra la predicha, y abajo lo mismo con
la humedad. La línea sólida es lo que realmente midió el sensor y la línea
punteada es lo que el modelo predijo. Mientras más cerca estén ambas líneas,
mejor está aprendiendo el modelo el comportamiento del ambiente. Si la
confiabilidad es baja, las predicciones deben tomarse solo como una referencia
aproximada, no como un valor exacto.
"""
        with open('reporte_prediccion.txt', 'w', encoding='utf-8') as f:
            f.write(texto)

    def predecir_siguiente(self, temp_actual, hum_actual):
        if not self.entrenado:
            print("⚠️ Entrena el modelo primero.")
            return

        pred_temp, pred_hum = self.modelo.predict([[temp_actual, hum_actual]])[0]
        print(f"🤖 Predicción de la siguiente lectura -> Temp: {pred_temp:.1f}°C | Humedad: {pred_hum:.1f}%")

        # --- Interpretación de la predicción, no solo el número crudo ---
        diff_temp = pred_temp - temp_actual
        diff_hum = pred_hum - hum_actual
        print(f"   → Temperatura: {self._describir_tendencia(diff_temp, '°C')}")
        print(f"   → Humedad: {self._describir_tendencia(diff_hum, '%')}")

        prediccion = Medicion(pred_temp, pred_hum)
        nivel = prediccion.nivel_riesgo
        etiqueta_riesgo = "alto" if nivel > 0.7 else "moderado" if nivel > 0.3 else "bajo"
        print(f"   → Riesgo estimado de la próxima lectura: {etiqueta_riesgo} ({nivel:.2f})")

        confiabilidad = "alta" if self.r2 > 0.7 else "media" if self.r2 > 0.4 else "baja"
        print(f"   → Confiabilidad del modelo (R²={self.r2:.2f}): {confiabilidad}."
              f"{' Toma esta predicción solo como referencia.' if confiabilidad == 'baja' else ''}")

    @staticmethod
    def _describir_tendencia(diferencia, unidad):
        if abs(diferencia) < 0.3:
            return f"se mantiene estable (cambio de {diferencia:+.1f}{unidad})"
        direccion = "subir" if diferencia > 0 else "bajar"
        return f"tiende a {direccion} en {abs(diferencia):.1f}{unidad}"

# ==========================================
# 7. GESTOR PRINCIPAL (Singleton)
# ==========================================
class GestorAmbiental:
    _instancia = None

    def __new__(cls, *args, **kwargs):
        if not cls._instancia:
            cls._instancia = super(GestorAmbiental, cls).__new__(cls, *args, **kwargs)
            cls._instancia.lista_sensores = []
            cls._instancia.recolector_json = GestorDatosJSON()
            cls._instancia.motor_ia = MotorPredictivo()
        return cls._instancia

    def añadir_sensor(self, sensor):
        sensor.agregar_observador(self.recolector_json)
        self.lista_sensores.append(sensor)
        print(f' ✅ Conectado: {type(sensor).__name__} (ID: {sensor.id})')

    def buscar_sensor(self, id_sensor):
        for s in self.lista_sensores:
            if s.id == id_sensor:
                return s
        return None

    def realizar_muestreo(self):
        if not self.lista_sensores:
            print(" ❌ Conecta un sensor primero.")
            return
        print("\n--- LEYENDO PUERTOS ---")
        for sen in self.lista_sensores:
            try:
                sen.medir()
            except RuntimeError as error:
                print(f" ⚠️ No se pudo leer {sen.id}: {error}")

# ==========================================
# INTERFAZ CLI
# ==========================================
def menu():
    gestor = GestorAmbiental()

    while True:
        print("\n" + "="*45)
        print(" 🌡️ SISTEMA DE MONITOREO DHT22 🌡️ ")
        print("="*45)
        print("1. Conectar SensorDHT22 (Simulado)")
        print("2. Conectar SensorDHT22 (Real - ESP8266 por cable USB)")
        print("3. Ver sensores conectados")
        print("4. Leer sensores y guardar en JSON")
        print("5. Medir un sensor de forma continua (ENTER para pausar)")
        print("6. Comparar dos mediciones guardadas (usa __lt__ y __add__)")
        print("7. Entrenar modelo de predicción")
        print("8. Predecir siguiente lectura")
        print("9. Salir")

        opcion = input("Opción: ")

        if opcion in ["1", "2"]:
            id_s = input("Asignar ID al sensor: ")
            ub = input("Ubicación física: ")
            if opcion == "1":
                gestor.añadir_sensor(SensorDHT22Simulado(id_s, ub))
            else:
                import serial.tools.list_ports
                puertos = list(serial.tools.list_ports.comports())
                if puertos:
                    print(" Puertos disponibles:")
                    for p in puertos:
                        print(f"   {p.device} - {p.description}")
                else:
                    print(" ⚠️ No se detectó ningún puerto. Revisa que el ESP8266 esté conectado por USB.")
                puerto = input("Puerto del ESP8266 (ej. COM3): ")
                try:
                    gestor.añadir_sensor(SensorDHT22Real(id_s, ub, puerto=puerto.strip()))
                except serial.SerialException as error:
                    print(f" ❌ No se pudo abrir el puerto: {error}")

        elif opcion == "3":
            if not gestor.lista_sensores:
                print(" ❌ No hay sensores conectados.")
            for s in gestor.lista_sensores:
                print(f"   {repr(s)}")

        elif opcion == "4":
            gestor.realizar_muestreo()

        elif opcion == "5":
            id_s = input("ID del sensor a medir de forma continua: ")
            sensor = gestor.buscar_sensor(id_s)
            if not sensor:
                print(" ❌ No existe ese sensor.")
            else:
                detener = threading.Event()

                def ciclo_medicion():
                    while not detener.is_set():
                        try:
                            sensor.medir()
                        except RuntimeError as error:
                            print(f" ⚠️ Lectura fallida, se reintenta en el siguiente ciclo: {error}")
                        detener.wait(3)  # espera 3s entre lecturas, o hasta que se pida detener

                hilo = threading.Thread(target=ciclo_medicion, daemon=True)
                print(" ▶️ Midiendo de forma continua... presiona ENTER para pausar.")
                hilo.start()
                input()
                detener.set()
                hilo.join()
                print(" ⏸️ Medición continua pausada.")

        elif opcion == "6":
            id_s = input("ID del sensor: ")
            sensor = gestor.buscar_sensor(id_s)
            if not sensor:
                print(" ❌ No existe ese sensor.")
            elif len(sensor.historial_mediciones) < 2:
                print(" ❌ Necesitas al menos 2 mediciones guardadas de este sensor (opción 4 o 5).")
            else:
                for i, m in enumerate(sensor.historial_mediciones):
                    print(f"   [{i}] {m}")
                try:
                    i1 = int(input("Índice de la primera medición: "))
                    i2 = int(input("Índice de la segunda medición: "))
                    m1, m2 = sensor.historial_mediciones[i1], sensor.historial_mediciones[i2]
                    print(f" ¿La medición [{i1}] tuvo menor riesgo que la [{i2}]? -> {m1 < m2}")
                    print(f" Promedio combinado (m1 + m2): {m1 + m2}")
                except (ValueError, IndexError):
                    print("Índices inválidos.")

        elif opcion == "7":
            print("\n--- ENTRENANDO MODELO DE PREDICCIÓN ---")
            gestor.motor_ia.entrenar_modelo()

        elif opcion == "8":
            if not gestor.motor_ia.entrenado:
                print("⚠️ Entrena el modelo primero (Opción 7).")
            else:
                try:
                    t = float(input("Temperatura actual (°C): "))
                    h = float(input("Humedad actual (%): "))
                    gestor.motor_ia.predecir_siguiente(t, h)
                except ValueError:
                    print("Por favor, ingrese números válidos.")

        elif opcion == "9":
            break
        else:
            print("Opción no válida.")

if __name__ == "__main__":
    menu()

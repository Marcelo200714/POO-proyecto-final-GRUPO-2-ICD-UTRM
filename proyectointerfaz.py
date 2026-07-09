"""
Interfaz gráfica (Tkinter) del Sistema de Monitoreo DHT22.
No reemplaza el menú de texto de proyecto2.0.py: convive con él y reutiliza
sus mismas clases (GestorAmbiental, SensorDHT22Simulado/Real, MotorPredictivo,
Medicion) para exponer las mismas 9 opciones del menú de forma visual.
"""
import importlib.util
import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

import serial
import serial.tools.list_ports
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

# proyecto2.0.py no se puede "import" directo (el punto en el nombre rompe la sintaxis),
# así que se carga como módulo desde su ruta.
_ruta_core = Path(__file__).parent / "proyecto2.0.py"
_spec = importlib.util.spec_from_file_location("proyecto_core", _ruta_core)
core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(core)


class ConsolaRedirigida:
    """Recibe los print() del programa original y los pasa a una cola thread-safe,
    para mostrarlos en el panel de consola de la GUI sin tocar proyecto2.0.py."""
    def __init__(self, cola):
        self.cola = cola

    def write(self, texto):
        # OJO: print() hace dos escrituras separadas (el texto y luego el "\n" final).
        # Filtrar por texto.strip() descartaba ese "\n" suelto y pegaba todas las
        # mediciones en un solo bloque sin separación entre líneas.
        if texto:
            self.cola.put(texto)

    def flush(self):
        pass


class InterfazGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("🌡️ Sistema de Monitoreo DHT22")
        self.geometry("1000x700")

        self.gestor = core.GestorAmbiental()
        self.cola_log = queue.Queue()
        sys.stdout = ConsolaRedirigida(self.cola_log)

        self.evento_detener = None
        self.hilo_medicion = None
        self._ultimo_largo_grafico = -1

        self._construir_layout()
        self.protocol("WM_DELETE_WINDOW", self._al_cerrar)
        self.after(200, self._revisar_cola_log)
        self.after(1000, self._refrescar_en_vivo)

    # ---------- layout general ----------
    def _construir_layout(self):
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)

        self.tab_sensores = ttk.Frame(notebook)
        self.tab_mediciones = ttk.Frame(notebook)
        self.tab_comparar = ttk.Frame(notebook)
        self.tab_ia = ttk.Frame(notebook)

        notebook.add(self.tab_sensores, text="🔌 Sensores")
        notebook.add(self.tab_mediciones, text="📊 Mediciones")
        notebook.add(self.tab_comparar, text="⚖️ Comparar")
        notebook.add(self.tab_ia, text="🤖 Predicción IA")

        self._construir_tab_sensores()
        self._construir_tab_mediciones()
        self._construir_tab_comparar()
        self._construir_tab_ia()

        marco_log = ttk.LabelFrame(self, text="Consola (misma salida que el menú de texto)")
        marco_log.pack(fill="both", expand=False, padx=8, pady=(0, 8))
        self.texto_log = tk.Text(marco_log, height=10, state="disabled",
                                  bg="#111111", fg="#33ff33", font=("Consolas", 9))
        self.texto_log.pack(fill="both", expand=True, side="left")
        scroll = ttk.Scrollbar(marco_log, command=self.texto_log.yview)
        scroll.pack(side="right", fill="y")
        self.texto_log.config(yscrollcommand=scroll.set)

    # ---------- Tab 1: Sensores ----------
    def _construir_tab_sensores(self):
        marco_form = ttk.LabelFrame(self.tab_sensores, text="Conectar sensor")
        marco_form.pack(fill="x", padx=6, pady=6)

        self.var_tipo = tk.StringVar(value="simulado")
        ttk.Radiobutton(marco_form, text="Simulado", variable=self.var_tipo, value="simulado",
                         command=self._actualizar_estado_puerto).grid(row=0, column=0, padx=6, pady=4, sticky="w")
        ttk.Radiobutton(marco_form, text="Real (ESP8266 por USB)", variable=self.var_tipo, value="real",
                         command=self._actualizar_estado_puerto).grid(row=0, column=1, padx=6, pady=4, sticky="w")

        ttk.Label(marco_form, text="ID:").grid(row=1, column=0, sticky="e")
        self.entry_id = ttk.Entry(marco_form, width=15)
        self.entry_id.grid(row=1, column=1, sticky="w", padx=4)

        ttk.Label(marco_form, text="Ubicación:").grid(row=2, column=0, sticky="e")
        self.entry_ubicacion = ttk.Entry(marco_form, width=25)
        self.entry_ubicacion.grid(row=2, column=1, sticky="w", padx=4)

        ttk.Label(marco_form, text="Puerto:").grid(row=3, column=0, sticky="e")
        self.combo_puertos = ttk.Combobox(marco_form, state="disabled", width=32)
        self.combo_puertos.grid(row=3, column=1, sticky="w", padx=4)
        self.boton_refrescar_puertos = ttk.Button(marco_form, text="🔄 Buscar puertos",
                                                    command=self._refrescar_puertos, state="disabled")
        self.boton_refrescar_puertos.grid(row=3, column=2, padx=4)

        ttk.Button(marco_form, text="Conectar sensor", command=self._conectar_sensor).grid(
            row=4, column=0, columnspan=3, pady=8)

        marco_lista = ttk.LabelFrame(self.tab_sensores, text="Sensores conectados")
        marco_lista.pack(fill="both", expand=True, padx=6, pady=6)
        columnas = ("id", "tipo", "ubicacion")
        self.tree_sensores = ttk.Treeview(marco_lista, columns=columnas, show="headings", height=8)
        for col, texto in zip(columnas, ("ID", "Tipo", "Ubicación")):
            self.tree_sensores.heading(col, text=texto)
        self.tree_sensores.pack(fill="both", expand=True, padx=4, pady=4)

    def _actualizar_estado_puerto(self):
        if self.var_tipo.get() == "real":
            self.combo_puertos.config(state="readonly")
            self.boton_refrescar_puertos.config(state="normal")
            self._refrescar_puertos()
        else:
            self.combo_puertos.config(state="disabled")
            self.boton_refrescar_puertos.config(state="disabled")

    def _refrescar_puertos(self):
        puertos = list(serial.tools.list_ports.comports())
        valores = [f"{p.device} - {p.description}" for p in puertos]
        self.combo_puertos["values"] = valores
        if valores:
            self.combo_puertos.current(0)
        else:
            self.combo_puertos.set("")
            messagebox.showinfo("Sin puertos",
                                 "No se detectó ningún puerto. Revisa que el ESP8266 esté conectado por USB.")

    def _conectar_sensor(self):
        id_s = self.entry_id.get().strip()
        ub = self.entry_ubicacion.get().strip()
        if not id_s or not ub:
            messagebox.showwarning("Datos incompletos", "Ingresa un ID y una ubicación.")
            return

        if self.var_tipo.get() == "simulado":
            self.gestor.añadir_sensor(core.SensorDHT22Simulado(id_s, ub))
        else:
            seleccion = self.combo_puertos.get()
            if not seleccion:
                messagebox.showwarning("Puerto no seleccionado", "Selecciona el puerto del ESP8266.")
                return
            puerto = seleccion.split(" - ")[0]
            try:
                self.gestor.añadir_sensor(core.SensorDHT22Real(id_s, ub, puerto=puerto))
            except serial.SerialException as error:
                messagebox.showerror("Error de conexión", str(error))
                return

        self.entry_id.delete(0, "end")
        self.entry_ubicacion.delete(0, "end")
        self._refrescar_lista_sensores()
        self._refrescar_combos_sensores()

    def _refrescar_lista_sensores(self):
        for item in self.tree_sensores.get_children():
            self.tree_sensores.delete(item)
        for s in self.gestor.lista_sensores:
            self.tree_sensores.insert("", "end", values=(s.id, type(s).__name__, s.ubicacion))

    def _refrescar_combos_sensores(self):
        ids = [s.id for s in self.gestor.lista_sensores]
        self.combo_sensor_medicion["values"] = ids
        self.combo_sensor_comparar["values"] = ids
        if ids and not self.combo_sensor_medicion.get():
            self.combo_sensor_medicion.set(ids[0])
        if ids and not self.combo_sensor_comparar.get():
            self.combo_sensor_comparar.set(ids[0])

    # ---------- Tab 2: Mediciones ----------
    def _construir_tab_mediciones(self):
        frame = self.tab_mediciones

        fila_top = ttk.Frame(frame)
        fila_top.pack(fill="x", padx=6, pady=6)
        ttk.Label(fila_top, text="Sensor:").pack(side="left")
        self.combo_sensor_medicion = ttk.Combobox(fila_top, state="readonly", width=15)
        self.combo_sensor_medicion.pack(side="left", padx=4)
        ttk.Button(fila_top, text="Leer todos los sensores ahora",
                   command=self.gestor.realizar_muestreo).pack(side="left", padx=8)
        self.boton_continuo = ttk.Button(fila_top, text="▶️ Iniciar medición continua",
                                          command=self._toggle_medicion_continua)
        self.boton_continuo.pack(side="left", padx=8)

        fila_labels = ttk.Frame(frame)
        fila_labels.pack(fill="x", padx=6)
        self.label_temp = ttk.Label(fila_labels, text="Temp: —", font=("Segoe UI", 12, "bold"))
        self.label_temp.pack(side="left", padx=12)
        self.label_hum = ttk.Label(fila_labels, text="Humedad: —", font=("Segoe UI", 12, "bold"))
        self.label_hum.pack(side="left", padx=12)
        self.label_riesgo = ttk.Label(fila_labels, text="Riesgo: —", font=("Segoe UI", 12, "bold"))
        self.label_riesgo.pack(side="left", padx=12)

        cuerpo = ttk.Frame(frame)
        cuerpo.pack(fill="both", expand=True, padx=6, pady=6)

        self.figura = Figure(figsize=(5, 3), dpi=90)
        self.ax_temp = self.figura.add_subplot(111)
        self.ax_hum = self.ax_temp.twinx()
        self.canvas_grafico = FigureCanvasTkAgg(self.figura, master=cuerpo)
        self.canvas_grafico.get_tk_widget().pack(side="left", fill="both", expand=True)

        columnas = ("hora", "temp", "hum", "riesgo")
        self.tree_historial = ttk.Treeview(cuerpo, columns=columnas, show="headings", height=12)
        for col, texto in zip(columnas, ("Hora", "Temp °C", "Humedad %", "Riesgo")):
            self.tree_historial.heading(col, text=texto)
            self.tree_historial.column(col, width=80, anchor="center")
        self.tree_historial.pack(side="right", fill="both", expand=True, padx=(8, 0))

    def _toggle_medicion_continua(self):
        if self.hilo_medicion and self.hilo_medicion.is_alive():
            self.evento_detener.set()
            self.hilo_medicion.join(timeout=5)
            self.boton_continuo.config(text="▶️ Iniciar medición continua")
            return

        id_s = self.combo_sensor_medicion.get()
        sensor = self.gestor.buscar_sensor(id_s)
        if not sensor:
            messagebox.showwarning("Sensor no encontrado", "Selecciona un sensor conectado.")
            return

        self.evento_detener = threading.Event()

        def ciclo_medicion():
            while not self.evento_detener.is_set():
                try:
                    sensor.medir()
                except RuntimeError as error:
                    print(f" ⚠️ Lectura fallida, se reintenta en el siguiente ciclo: {error}")
                self.evento_detener.wait(3)

        self.hilo_medicion = threading.Thread(target=ciclo_medicion, daemon=True)
        self.hilo_medicion.start()
        self.boton_continuo.config(text="⏸️ Detener medición continua")

    def _actualizar_grafico(self, sensor):
        historial = sensor.historial_mediciones
        if len(historial) == self._ultimo_largo_grafico:
            return
        self._ultimo_largo_grafico = len(historial)

        self.ax_temp.clear()
        self.ax_hum.clear()
        if historial:
            self.ax_temp.plot([m.temperatura for m in historial], "o-", color="tab:orange", label="Temp °C")
            self.ax_hum.plot([m.humedad for m in historial], "o-", color="tab:blue", label="Humedad %")
        self.ax_temp.set_ylabel("Temp °C", color="tab:orange")
        self.ax_hum.set_ylabel("Humedad %", color="tab:blue")
        self.ax_temp.set_xlabel("Muestra")
        self.figura.tight_layout()
        self.canvas_grafico.draw()

    def _actualizar_treeview_historial(self, sensor):
        if len(sensor.historial_mediciones) == len(self.tree_historial.get_children()):
            return
        for item in self.tree_historial.get_children():
            self.tree_historial.delete(item)
        for m in sensor.historial_mediciones:
            self.tree_historial.insert("", "end", values=(
                m.momento.strftime("%H:%M:%S"), f"{m.temperatura:.1f}", f"{m.humedad:.1f}", f"{m.nivel_riesgo:.2f}"))

    # ---------- Tab 3: Comparar ----------
    def _construir_tab_comparar(self):
        frame = self.tab_comparar

        fila = ttk.Frame(frame)
        fila.pack(fill="x", padx=6, pady=6)
        ttk.Label(fila, text="Sensor:").pack(side="left")
        self.combo_sensor_comparar = ttk.Combobox(fila, state="readonly", width=15)
        self.combo_sensor_comparar.pack(side="left", padx=4)
        self.combo_sensor_comparar.bind("<<ComboboxSelected>>", lambda e: self._refrescar_indices_comparar())
        ttk.Button(fila, text="🔄 Refrescar mediciones",
                   command=self._refrescar_indices_comparar).pack(side="left", padx=8)

        fila2 = ttk.Frame(frame)
        fila2.pack(fill="x", padx=6, pady=6)
        ttk.Label(fila2, text="Medición 1:").pack(side="left")
        self.combo_m1 = ttk.Combobox(fila2, state="readonly", width=42)
        self.combo_m1.pack(side="left", padx=4)
        ttk.Label(fila2, text="Medición 2:").pack(side="left")
        self.combo_m2 = ttk.Combobox(fila2, state="readonly", width=42)
        self.combo_m2.pack(side="left", padx=4)

        ttk.Button(frame, text="Comparar (usa __lt__ y __add__)",
                   command=self._comparar).pack(padx=6, pady=10, anchor="w")
        ttk.Label(frame, text="El resultado aparece en la consola de abajo.",
                  foreground="gray").pack(anchor="w", padx=6)

    def _refrescar_indices_comparar(self):
        sensor = self.gestor.buscar_sensor(self.combo_sensor_comparar.get())
        if not sensor:
            return
        valores = [f"[{i}] {m}" for i, m in enumerate(sensor.historial_mediciones)]
        self.combo_m1["values"] = valores
        self.combo_m2["values"] = valores

    def _comparar(self):
        sensor = self.gestor.buscar_sensor(self.combo_sensor_comparar.get())
        if not sensor:
            messagebox.showwarning("Sensor no encontrado", "Selecciona un sensor.")
            return
        if len(sensor.historial_mediciones) < 2:
            messagebox.showwarning("Faltan datos", "Necesitas al menos 2 mediciones guardadas de este sensor.")
            return
        try:
            i1 = int(self.combo_m1.get().split("]")[0][1:])
            i2 = int(self.combo_m2.get().split("]")[0][1:])
            m1, m2 = sensor.historial_mediciones[i1], sensor.historial_mediciones[i2]
            print(f" ¿La medición [{i1}] tuvo menor riesgo que la [{i2}]? -> {m1 < m2}")
            print(f" Promedio combinado (m1 + m2): {m1 + m2}")
        except (ValueError, IndexError):
            messagebox.showerror("Índices inválidos", "Selecciona dos mediciones válidas.")

    # ---------- Tab 4: Predicción IA ----------
    def _construir_tab_ia(self):
        frame = self.tab_ia

        fila = ttk.Frame(frame)
        fila.pack(fill="x", padx=6, pady=10)
        ttk.Button(fila, text="Entrenar modelo de predicción", command=self._entrenar_modelo).pack(side="left", padx=4)
        ttk.Button(fila, text="Abrir gráfico de predicción", command=self._abrir_grafico).pack(side="left", padx=4)

        self.label_estado_modelo = ttk.Label(frame, text="Entrenado: No     R²: —", font=("Segoe UI", 11, "bold"))
        self.label_estado_modelo.pack(anchor="w", padx=6, pady=(0, 10))

        fila2 = ttk.Frame(frame)
        fila2.pack(fill="x", padx=6, pady=6)
        ttk.Label(fila2, text="Temperatura actual (°C):").pack(side="left")
        self.entry_temp_pred = ttk.Entry(fila2, width=8)
        self.entry_temp_pred.pack(side="left", padx=4)
        ttk.Label(fila2, text="Humedad actual (%):").pack(side="left")
        self.entry_hum_pred = ttk.Entry(fila2, width=8)
        self.entry_hum_pred.pack(side="left", padx=4)
        ttk.Button(fila2, text="Predecir siguiente lectura", command=self._predecir).pack(side="left", padx=8)

        ttk.Label(frame,
                  text="Se necesitan al menos 12 lecturas guardadas para entrenar. El resultado aparece en la consola.",
                  foreground="gray").pack(anchor="w", padx=6, pady=10)

    def _entrenar_modelo(self):
        print("\n--- ENTRENANDO MODELO DE PREDICCIÓN ---")
        self.gestor.motor_ia.entrenar_modelo()
        estado = "Sí" if self.gestor.motor_ia.entrenado else "No"
        self.label_estado_modelo.config(text=f"Entrenado: {estado}     R²: {self.gestor.motor_ia.r2:.3f}")

    def _abrir_grafico(self):
        ruta = Path(__file__).parent / "grafico_prediccion.jpg"
        if not ruta.exists():
            messagebox.showwarning("Sin gráfico", "Entrena el modelo primero.")
            return
        os.startfile(ruta)

    def _predecir(self):
        if not self.gestor.motor_ia.entrenado:
            messagebox.showwarning("Modelo no entrenado", "Entrena el modelo primero.")
            return
        try:
            t = float(self.entry_temp_pred.get())
            h = float(self.entry_hum_pred.get())
        except ValueError:
            messagebox.showerror("Datos inválidos", "Ingresa números válidos de temperatura y humedad.")
            return
        self.gestor.motor_ia.predecir_siguiente(t, h)

    # ---------- refresco periódico y consola ----------
    def _revisar_cola_log(self):
        try:
            while True:
                texto = self.cola_log.get_nowait()
                self.texto_log.config(state="normal")
                self.texto_log.insert("end", texto)
                self.texto_log.see("end")
                self.texto_log.config(state="disabled")
        except queue.Empty:
            pass
        self.after(200, self._revisar_cola_log)

    def _refrescar_en_vivo(self):
        sensor = self.gestor.buscar_sensor(self.combo_sensor_medicion.get())
        if sensor and sensor.historial_mediciones:
            self.label_temp.config(text=f"Temp: {sensor.temperatura:.1f} °C")
            self.label_hum.config(text=f"Humedad: {sensor.humedad:.1f} %")
            self.label_riesgo.config(text=f"Riesgo: {sensor.historial_mediciones[-1].nivel_riesgo:.2f}")
            self._actualizar_grafico(sensor)
            self._actualizar_treeview_historial(sensor)
        self.after(1000, self._refrescar_en_vivo)

    def _al_cerrar(self):
        if self.hilo_medicion and self.hilo_medicion.is_alive():
            self.evento_detener.set()
            self.hilo_medicion.join(timeout=5)
        sys.stdout = sys.__stdout__
        self.destroy()


if __name__ == "__main__":
    app = InterfazGUI()
    app.mainloop()

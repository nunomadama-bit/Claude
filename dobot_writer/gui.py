"""Janela da aplicação (tkinter, incluído no Python para Windows e macOS)."""

import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import jobs, layout
from .protocol import Dobot, DobotError, list_serial_ports


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Dobot Writer — escrever com laser, caneta ou 3D")
        self.geometry("980x640")
        self.dobot = None
        self.worker = None
        self.messages = queue.Queue()

        self.vars = {
            "porta": tk.StringVar(),
            "ferramenta": tk.StringVar(value="laser"),
            "altura": tk.DoubleVar(value=15.0),
            "x": tk.DoubleVar(value=230.0),
            "y": tk.DoubleVar(value=0.0),
            "z": tk.DoubleVar(value=0.0),
            "rotacao": tk.DoubleVar(value=0.0),
            "velocidade": tk.DoubleVar(value=15.0),
            "pausa": tk.IntVar(value=150),
        }
        self._build()
        self.refresh_ports()
        self.update_preview()
        self.after(100, self._drain_messages)

    # --- interface -------------------------------------------------------

    def _build(self):
        left = ttk.Frame(self, padding=10)
        left.pack(side="left", fill="y")
        right = ttk.Frame(self, padding=10)
        right.pack(side="right", fill="both", expand=True)

        ttk.Label(left, text="Texto:").pack(anchor="w")
        self.text = tk.Text(left, width=34, height=4, font=("Helvetica", 14))
        self.text.insert("1.0", "OLÁ DOBOT")
        self.text.pack(fill="x")
        self.text.bind("<KeyRelease>", lambda e: self.update_preview())

        conn = ttk.LabelFrame(left, text="Ligação USB", padding=6)
        conn.pack(fill="x", pady=6)
        self.port_box = ttk.Combobox(conn, textvariable=self.vars["porta"], width=18)
        self.port_box.grid(row=0, column=0)
        ttk.Button(conn, text="↻", width=3, command=self.refresh_ports).grid(row=0, column=1)
        ttk.Button(conn, text="Ligar", command=self.connect).grid(row=0, column=2)
        ttk.Button(conn, text="Diagnóstico", command=self.diagnose).grid(
            row=1, column=0, columnspan=3, sticky="ew", pady=(4, 0))

        tool = ttk.LabelFrame(left, text="Ferramenta", padding=6)
        tool.pack(fill="x", pady=6)
        for value, label in (("laser", "Laser"), ("caneta", "Caneta (teste)")):
            ttk.Radiobutton(tool, text=label, value=value,
                            variable=self.vars["ferramenta"]).pack(side="left")

        params = ttk.LabelFrame(left, text="Posição e tamanho (mm)", padding=6)
        params.pack(fill="x", pady=6)
        rows = [("Altura das letras", "altura"), ("Centro X", "x"),
                ("Centro Y", "y"), ("Z da superfície", "z"),
                ("Rotação (graus)", "rotacao"), ("Velocidade mm/s", "velocidade"),
                ("Pausa laser ms", "pausa")]
        for i, (label, key) in enumerate(rows):
            ttk.Label(params, text=label).grid(row=i, column=0, sticky="w")
            e = ttk.Entry(params, textvariable=self.vars[key], width=10)
            e.grid(row=i, column=1)
            e.bind("<FocusOut>", lambda ev: self.update_preview())
        ttk.Button(params, text="Ler Z do robô", command=self.read_z).grid(
            row=3, column=2, padx=4)

        actions = ttk.Frame(left)
        actions.pack(fill="x", pady=6)
        ttk.Button(actions, text="▶ Escrever", command=self.start_job).pack(fill="x")
        ttk.Button(actions, text="■ PARAR", command=self.stop_job).pack(fill="x", pady=4)
        ttk.Button(actions, text="Exportar STL (3D)", command=self.export_stl).pack(fill="x")
        ttk.Button(actions, text="Exportar G-code (3D)", command=self.export_gcode).pack(fill="x")

        self.canvas = tk.Canvas(right, bg="white", height=360)
        self.canvas.pack(fill="both", expand=True)
        self.status = tk.StringVar(value="Desligado")
        ttk.Label(right, textvariable=self.status).pack(anchor="w")
        self.progress = ttk.Progressbar(right, maximum=1)
        self.progress.pack(fill="x")
        self.log_box = tk.Text(right, height=10, state="disabled")
        self.log_box.pack(fill="both")

    def log(self, msg):
        self.messages.put(("log", msg))

    def _drain_messages(self):
        while not self.messages.empty():
            kind, payload = self.messages.get()
            if kind == "log":
                self.log_box.configure(state="normal")
                self.log_box.insert("end", payload + "\n")
                self.log_box.see("end")
                self.log_box.configure(state="disabled")
            elif kind == "progress":
                n, total = payload
                self.progress.configure(maximum=total, value=n)
            elif kind == "z":
                self.vars["z"].set(round(payload, 2))
        self.after(100, self._drain_messages)

    # --- dados -----------------------------------------------------------

    def _value(self, key):
        try:
            return self.vars[key].get()
        except tk.TclError:
            raise ValueError(f"Valor inválido em '{key}'")

    def _strokes(self):
        text = self.text.get("1.0", "end").rstrip("\n")
        return layout.text_to_strokes(text, self._value("altura"))

    def update_preview(self):
        try:
            strokes = self._strokes()
        except ValueError:
            return
        c = self.canvas
        c.delete("all")
        if not any(len(s) for s in strokes):
            return
        w, h = c.winfo_width() or 600, c.winfo_height() or 360
        x0, y0, x1, y1 = layout.bounds(strokes)
        k = min((w - 40) / max(x1 - x0, 1), (h - 40) / max(y1 - y0, 1))
        for s in strokes:
            pts = [v for x, y in s for v in ((x - x0) * k + 20, (y1 - y) * k + 20)]
            if len(pts) == 2:
                pts += pts
            c.create_line(*pts, width=2, capstyle="round", joinstyle="round")
        length = layout.path_length(strokes)
        c.create_text(10, h - 10, anchor="sw", fill="gray",
                      text=f"{x1 - x0:.0f} × {y1 - y0:.0f} mm — {length:.0f} mm de traço")

    # --- robô ------------------------------------------------------------

    def refresh_ports(self):
        ports = list_serial_ports()
        self.port_box["values"] = ports
        if ports and not self.vars["porta"].get():
            self.vars["porta"].set(ports[0])

    def connect(self):
        if self.dobot:
            self.dobot.close()
            self.dobot = None
        try:
            self.dobot = Dobot(self.vars["porta"].get())
            name = self.dobot.device_name() or "Dobot"
            self.status.set(f"Ligado: {name} em {self.vars['porta'].get()}")
            self.log("Ligado. Feche o DobotStudio/app enquanto usa esta aplicação.")
        except Exception as exc:  # pyserial levanta vários tipos
            self.dobot = None
            messagebox.showerror("Erro de ligação", str(exc))

    def _need_robot(self):
        if not self.dobot:
            messagebox.showwarning("Robô", "Primeiro carregue em 'Ligar'.")
            return False
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("Robô", "Já há um trabalho em curso.")
            return False
        return True

    def _run_in_background(self, func):
        def target():
            try:
                func()
            except DobotError as exc:
                self.log(f"ERRO: {exc}")
        self.worker = threading.Thread(target=target, daemon=True)
        self.worker.start()

    def diagnose(self):
        if self._need_robot():
            test_laser = messagebox.askyesno(
                "Diagnóstico", "Testar também o laser durante 1 segundo?\n"
                "(Use óculos de proteção e tenha uma superfície por baixo.)")
            self._run_in_background(
                lambda: jobs.diagnose(self.dobot, test_laser=test_laser, log=self.log))

    def read_z(self):
        if self._need_robot():
            def job():
                x, y, z, r = self.dobot.get_pose()
                self.messages.put(("z", z))
                self.log(f"Posição: X={x:.1f} Y={y:.1f} Z={z:.1f}")
            self._run_in_background(job)

    def start_job(self):
        if not self._need_robot():
            return
        try:
            strokes = self._strokes()
            placed = layout.to_robot(strokes, self._value("x"), self._value("y"),
                                     self._value("rotacao"))
            z, speed = self._value("z"), self._value("velocidade")
            dwell, tool = self._value("pausa"), self.vars["ferramenta"].get()
        except ValueError as exc:
            messagebox.showerror("Parâmetros", str(exc))
            return
        if not placed:
            return
        bad = layout.out_of_reach(placed)
        if bad:
            messagebox.showerror("Fora de alcance",
                                 f"{len(bad)} pontos fora do alcance do braço.\n"
                                 "Reduza a altura das letras ou ajuste X/Y.")
            return
        if not messagebox.askokcancel(
                "Escrever", f"Ferramenta: {tool}\nZ = {z} mm\n\n"
                "Confirme a altura Z e use óculos de proteção com o laser."):
            return
        self.log(f"A escrever {len(placed)} traços com {tool}...")
        self._run_in_background(lambda: jobs.write_on_robot(
            self.dobot, placed, z, tool=tool, draw_speed=speed, dwell_ms=dwell,
            progress=lambda n, t: self.messages.put(("progress", (n, t))),
            log=self.log))

    def stop_job(self):
        if self.dobot:
            jobs.stop(self.dobot)
            self.log("PARADO.")

    # --- 3D --------------------------------------------------------------

    def export_stl(self):
        path = filedialog.asksaveasfilename(defaultextension=".stl",
                                            filetypes=[("STL", "*.stl")])
        if path:
            tris = jobs.strokes_to_triangles(self._strokes())
            with open(path, "w", encoding="ascii") as f:
                f.write(jobs.to_stl(tris))
            self.log(f"STL gravado em {path}. Abra-o no Repetier-Host (modo 3D).")

    def export_gcode(self):
        path = filedialog.asksaveasfilename(defaultextension=".gcode",
                                            filetypes=[("G-code", "*.gcode")])
        if path:
            with open(path, "w", encoding="ascii") as f:
                f.write(jobs.strokes_to_gcode(self._strokes()))
            self.log(f"G-code gravado em {path}. Confirme as coordenadas no "
                     "Repetier-Host antes de imprimir.")


def run():
    App().mainloop()

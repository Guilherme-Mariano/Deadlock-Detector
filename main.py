import tkinter as tk
from tkinter import ttk, scrolledtext
from tkinter import messagebox
import threading
import time
import random
import networkx as nx
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# Config das Constantes
MAX_RECURSOS = 10
MAX_PROCESSOS = 10

# Uma Lock global tentando garantir integridade de dados compartilhados
global_lock = threading.RLock()

class Logger:
    """
    Simulação do terminal na GUI
    """
    def __init__(self, text_widget):
        self.widget = text_widget

    def log(self, message):
        timestamp = time.strftime("%H:%M:%S")
        full_msg = f"[{timestamp}] {message}\n"

        def _append():
            try:
                self.widget.insert(tk.END, full_msg)
                self.widget.see(tk.END)
            except:
                pass

        self.widget.after(0, _append)


class Recurso:
    def __init__(self, r_id, nome):
        self.id = r_id
        self.nome = nome
        self.dono = None
        # Condition Variable Permite dormir esperando este recurso específico
        self.condicao = threading.Condition(global_lock)

    def __repr__(self):
        return f"Recurso({self.id}, {self.nome})"

class Processo(threading.Thread):
    def __init__(self, p_id, delta_ts, delta_tu, recursos_sistema, logger):
        super().__init__()
        self.p_id = p_id
        self.delta_ts = delta_ts
        self.delta_tu = delta_tu
        self.recursos_sistema = recursos_sistema
        self.logger = logger

        self.recursos_posse = []
        self.recurso_aguardando = None

        self.running = True
        self.daemon = True

    def run(self):
        while self.running:
            # Intervalo de solicitação
            time.sleep(self.delta_ts)

            # Identifica recursos que o processo AINDA NÃO TEM
            with global_lock:
                disponiveis_para_pedir = [r for r in self.recursos_sistema if r not in self.recursos_posse]

            if not disponiveis_para_pedir:
                continue

            # --- SELEÇÃO ALEATÓRIA  ---
            recurso_desejado = random.choice(disponiveis_para_pedir) #

            self.solicitar_recurso(recurso_desejado)

    def solicitar_recurso(self, recurso):
        self.logger.log(f"Processo {self.p_id} SOLICITOU {recurso.nome}.")

        with global_lock:
            # Se o recurso tem dono, bloqueia (dorme)
            while recurso.dono is not None:
                self.recurso_aguardando = recurso
                self.logger.log(f"Processo {self.p_id} BLOQUEADO por {recurso.nome} (Dono: P{recurso.dono.p_id}).")

                # wait() libera o lock e dorme
                recurso.condicao.wait()

            # Recurso livre: toma posse
            recurso.dono = self
            self.recurso_aguardando = None
            self.recursos_posse.append(recurso)
            self.logger.log(f"Processo {self.p_id} PEGOU {recurso.nome}.")

        # --- UTILIZAÇÃO ASSÍNCRONA ---
        # Agenda a liberação para o futuro sem travar a thread.
        timer = threading.Timer(self.delta_tu, self.liberar_recurso_agendado, args=[recurso])
        timer.daemon = True
        timer.start()

    def liberar_recurso_agendado(self, recurso):
        # Libera após Delta Tu
        with global_lock:
            if recurso in self.recursos_posse:
                recurso.dono = None
                self.recursos_posse.remove(recurso)
                self.logger.log(f"Processo {self.p_id} LIBEROU {recurso.nome}.")

                # Acorda processos esperando este recurso
                recurso.condicao.notify_all()

class SistemaOperacional(threading.Thread):
    def __init__(self, intervalo_check, processos, recursos, callback_atualizacao_gui):
        super().__init__()
        self.intervalo = intervalo_check
        self.processos = processos
        self.recursos = recursos
        self.callback = callback_atualizacao_gui
        self.running = True
        self.daemon = True

    def run(self):
        while self.running:
            time.sleep(self.intervalo)
            deadlock_info = self.detectar_deadlock()
            self.callback(deadlock_info)

    def detectar_deadlock(self):
        # Detectar deadlocks utilizando grafos
        G = nx.DiGraph()

        with global_lock:
            for p in self.processos:
                G.add_node(f"P{p.p_id}", type='processo')
            for r in self.recursos:
                G.add_node(f"R{r.id}", type='recurso')

            for r in self.recursos:
                if r.dono:
                    G.add_edge(f"R{r.id}", f"P{r.dono.p_id}")  # Recurso -> Processo

            for p in self.processos:
                if p.recurso_aguardando:
                    G.add_edge(f"P{p.p_id}", f"R{p.recurso_aguardando.id}")  # Processo -> Recurso

        # Detecta ciclos
        try:
            cycles = list(nx.simple_cycles(G))
        except:
            cycles = []

        in_deadlock = set()
        for cycle in cycles:
            for node in cycle:
                if node.startswith("P"):
                    # Coletando processos no ciclo
                    in_deadlock.add(node)

        return {
            "graph": G,
            "cycles": cycles,
            "in_deadlock": list(in_deadlock)
        }


# --- INTERFACE GRÁFICA ---

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Simulação de Deadlock - SO 2025.2")
        self.geometry("1200x800")

        self.recursos = []
        self.processos = []
        self.so_thread = None
        self.temp_process_configs = []

        self.setup_ui()

    def setup_ui(self):
        self.tab_control = ttk.Notebook(self)

        self.tab_config = ttk.Frame(self.tab_control)
        self.tab_sim = ttk.Frame(self.tab_control)

        self.tab_control.add(self.tab_config, text='Configuração')
        self.tab_control.add(self.tab_sim, text='Simulação')
        self.tab_control.pack(expand=1, fill="both")

        self.build_config_tab()
        self.build_sim_tab()

    def build_config_tab(self):
        frame = ttk.LabelFrame(self.tab_config, text="Configuração Inicial")
        frame.pack(padx=10, pady=10, fill="both", expand=True)

        # Recursos
        lbl_res = ttk.Label(frame, text="Adicionar Recurso (Nome):")
        lbl_res.grid(row=0, column=0, padx=5, pady=5)
        self.entry_res_nome = ttk.Entry(frame)
        self.entry_res_nome.grid(row=0, column=1, padx=5, pady=5)
        btn_add_res = ttk.Button(frame, text="Adicionar Recurso", command=self.add_recurso)
        btn_add_res.grid(row=0, column=2, padx=5, pady=5)

        self.listbox_res = tk.Listbox(frame, height=6)
        self.listbox_res.grid(row=1, column=0, columnspan=3, padx=5, pady=5, sticky="ew")

        # SO
        lbl_so = ttk.Label(frame, text="Intervalo SO (Δt seg):")
        lbl_so.grid(row=2, column=0, padx=5, pady=5)
        self.entry_so_time = ttk.Entry(frame)
        self.entry_so_time.insert(0, "1.0")
        self.entry_so_time.grid(row=2, column=1, padx=5, pady=5)

        ttk.Separator(frame, orient='horizontal').grid(row=3, column=0, columnspan=3, pady=10, sticky="ew")

        # Processos
        lbl_proc_desc = ttk.Label(frame, text="Processos:")
        lbl_proc_desc.grid(row=4, column=0, columnspan=3)

        lbl_ts = ttk.Label(frame, text="ΔTs (Solicitação):")
        lbl_ts.grid(row=5, column=0)
        self.entry_ts = ttk.Entry(frame, width=10)
        self.entry_ts.insert(0, "0.5")
        self.entry_ts.grid(row=5, column=1)

        lbl_tu = ttk.Label(frame, text="ΔTu (Utilização):")
        lbl_tu.grid(row=6, column=0)
        self.entry_tu = ttk.Entry(frame, width=10)
        self.entry_tu.insert(0, "50.0")
        self.entry_tu.grid(row=6, column=1)

        btn_add_proc = ttk.Button(frame, text="Adicionar Processo à Fila", command=self.add_processo_config)
        btn_add_proc.grid(row=7, column=0, columnspan=3, pady=5)

        self.listbox_proc = tk.Listbox(frame, height=6)
        self.listbox_proc.grid(row=8, column=0, columnspan=3, padx=5, pady=5, sticky="ew")

        btn_start = ttk.Button(frame, text="INICIAR SIMULAÇÃO", command=self.start_simulation)
        btn_start.grid(row=9, column=0, columnspan=3, pady=20)

    def build_sim_tab(self):
        self.frame_graph = ttk.Frame(self.tab_sim)
        self.frame_graph.pack(side="left", fill="both", expand=True)

        self.frame_info = ttk.Frame(self.tab_sim, width=400)
        self.frame_info.pack(side="right", fill="y")

        lbl_log = ttk.Label(self.frame_info, text="Log de Operações:")
        lbl_log.pack(anchor="w", padx=5)
        self.txt_log = scrolledtext.ScrolledText(self.frame_info, height=15, width=50)
        self.txt_log.pack(padx=5, pady=5)
        self.logger = Logger(self.txt_log)

        lbl_status = ttk.Label(self.frame_info, text="Status Atual:")
        lbl_status.pack(anchor="w", padx=5, pady=(10, 0))
        self.txt_status = scrolledtext.ScrolledText(self.frame_info, height=15, width=50, bg="#f0f0f0")
        self.txt_status.pack(padx=5, pady=5)

        self.lbl_deadlock = ttk.Label(self.frame_info, text="SISTEMA NORMAL", font=("Arial", 14, "bold"),
                                      foreground="green")
        self.lbl_deadlock.pack(pady=20)

        self.fig, self.ax = plt.subplots(figsize=(6, 6))
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.frame_graph)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    def add_recurso(self):
        if len(self.recursos) >= MAX_RECURSOS:
            messagebox.showwarning("Limite", "Máximo de 10 recursos atingido.")
            return
        nome = self.entry_res_nome.get()
        if not nome: return
        rid = len(self.recursos) + 1
        r = Recurso(rid, nome)
        self.recursos.append(r)
        self.listbox_res.insert(tk.END, f"ID: {rid} - {nome}")
        self.entry_res_nome.delete(0, tk.END)

    def add_processo_config(self):
        if len(self.temp_process_configs) >= MAX_PROCESSOS:
            messagebox.showwarning("Limite", "Máximo de 10 processos atingido.")
            return
        try:
            ts = float(self.entry_ts.get())
            tu = float(self.entry_tu.get())
            pid = len(self.temp_process_configs) + 1
            self.temp_process_configs.append({'id': pid, 'ts': ts, 'tu': tu})
            self.listbox_proc.insert(tk.END, f"Proc {pid}: ΔTs={ts}, ΔTu={tu}")
        except ValueError:
            messagebox.showerror("Erro", "Valores numéricos necessários.")

    def start_simulation(self):
        if not self.recursos or not self.temp_process_configs:
            messagebox.showerror("Erro", "Configure recursos e processos.")
            return
        try:
            dt = float(self.entry_so_time.get())
        except ValueError:
            return

        for p_conf in self.temp_process_configs:
            p = Processo(p_conf['id'], p_conf['ts'], p_conf['tu'], self.recursos, self.logger)
            self.processos.append(p)

        self.so_thread = SistemaOperacional(dt, self.processos, self.recursos, self.update_gui_callback)

        for p in self.processos:
            p.start()
        self.so_thread.start()

        self.tab_config.state(["disabled"])
        self.tab_control.select(self.tab_sim)
        self.logger.log("Simulação Iniciada.")

    def update_gui_callback(self, data):
        self.after(0, self.render_graph_and_status, data)

    def render_graph_and_status(self, data):
        G = data['graph']
        cycles = data['cycles']
        in_deadlock = data['in_deadlock']

        self.ax.clear()
        pos = nx.circular_layout(G) if len(G.nodes) > 0 else {}

        color_map = []
        for node in G.nodes():
            if node in in_deadlock or any(node in c for c in cycles):
                color_map.append('red')
            elif G.nodes[node].get('type') == 'processo':
                color_map.append('skyblue')
            else:
                color_map.append('lightgreen')

        nx.draw(G, pos, ax=self.ax, with_labels=True, node_color=color_map,
                node_size=1200, font_size=9, font_weight='bold', arrowsize=20, arrowstyle='-|>')
        self.canvas.draw()

        self.txt_status.delete(1.0, tk.END)
        status_msg = "--- PROCESSOS ---\n"
        for p in self.processos:
            state = "RODANDO"
            if p.recurso_aguardando: state = "BLOQUEADO"

            held = [r.nome for r in p.recursos_posse]
            p_name = f"P{p.p_id}"
            deadlock_mark = " [DEADLOCK]" if p_name in in_deadlock else ""

            status_msg += f"{p_name}{deadlock_mark}: {state}\n"
            status_msg += f"   Posse: {held}\n"
            if p.recurso_aguardando:
                status_msg += f"   Esperando: {p.recurso_aguardando.nome}\n"
            status_msg += "\n"

        self.txt_status.insert(tk.END, status_msg)

        if cycles:
            self.lbl_deadlock.config(text=f"DEADLOCK DETECTADO!\nProcessos Parados: {', '.join(in_deadlock)}",
                                     foreground="red")
        else:
            self.lbl_deadlock.config(text="SISTEMA NORMAL", foreground="green")


if __name__ == "__main__":
    app = App()
    app.mainloop()
#!/usr/bin/env python3
"""Ícone na bandeja do sistema (igual ao Flameshot) — clica e aparecem as opções no menu.

Uso: python3 gui.py (ou dá duplo clique no atalho de desktop)
Depende de: pip install --user pystray  +  sudo apt install gir1.2-ayatanaappindicator3-0.1
"""
import json
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import ttk

WRITE_RE = re.compile(r"^::WRITE:(\S+)")

import pystray
from PIL import Image, ImageDraw

FROZEN = getattr(sys, "frozen", False)
HERE = Path(sys.executable).parent if FROZEN else Path(__file__).parent
CONFIG_FILE = HERE / "config.json"


def script_cmd(basename, *args):
    """Monta o comando pra rodar sync-prazo/tempo-status/corrige-datas-fechadas — tanto
    rodando a partir do código-fonte (python3 arquivo.py) quanto empacotado como um .exe
    (nesse caso cada script foi compilado num executável irmão, sem depender de haver um
    interpretador Python instalado na máquina)."""
    if FROZEN:
        ext = ".exe" if sys.platform == "win32" else ""
        return [str(HERE / f"{basename}{ext}"), *args]
    return [sys.executable, str(HERE / f"{basename}.py"), *args]


def load_config():
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {"org": "ContatoSeguro", "default_repo": "", "produto": {}, "squads": {}}


def resolve_fields(org, number):
    out = subprocess.run(script_cmd("sync-prazo", "--resolve-fields", org, str(number)),
                          cwd=HERE, capture_output=True, text=True)
    data = json.loads(out.stdout)
    return data["title"], data["fields"]


def fetch_status_options(org, number, field_name):
    out = subprocess.run(script_cmd("sync-prazo", "--status-options", org, str(number), field_name),
                          cwd=HERE, capture_output=True, text=True)
    return json.loads(out.stdout)["options"]


def guess(names, *keywords):
    for kw in keywords:
        for n in names:
            if kw.lower() in n.lower():
                return n
    return names[0] if names else ""


def make_icon_image():
    """Um ícone simples gerado na hora (círculo com um "S") — sem depender de arquivo externo."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((2, 2, 62, 62), fill=(58, 90, 114, 255))
    draw.text((22, 16), "S", fill=(255, 255, 255, 255))
    return img


class LogPanel(tk.Toplevel):
    """Janelinha de log — some sozinha quando você fecha, só existe enquanto uma ação
    está rodando ou acabou de rodar. Não é a janela principal do app (não tem uma)."""

    def __init__(self, master, title):
        super().__init__(master)
        self.title(title)
        self.attributes("-topmost", True)
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        self.geometry(f"520x300+{sw - 540}+60")

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        scrollbar = ttk.Scrollbar(body)
        scrollbar.pack(side="right", fill="y")
        self.text = tk.Text(body, wrap="word", bg="#1c1c1a", fg="#e8e6e0",
                             insertbackground="#e8e6e0", font=("Consolas", 9), padx=10, pady=8,
                             yscrollcommand=scrollbar.set)
        self.text.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.text.yview)

        self.close_btn = ttk.Button(self, text="Fechar", command=self.destroy, state="disabled")
        self.close_btn.pack(pady=6)

    def write(self, line):
        if WRITE_RE.match(line):
            return  # marcador técnico, só usado pelo ProgressPanel — não é pra leitura humana
        self.text.insert("end", line)
        self.text.see("end")

    def finished(self):
        self.close_btn.config(state="normal")


class ConfigWizard(tk.Toplevel):
    """Assistente passo a passo pra adicionar/reconfigurar um squad — só pede número do
    Project e deixa escolher os campos numa lista (nunca ID interno). O Produto (sempre o
    mesmo) só é perguntado na 1a vez; da 2a squad em diante, pula direto pra squad nova."""

    def __init__(self, master, on_done):
        super().__init__(master)
        self.title("Configurar squad")
        self.geometry("480x380")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.on_done = on_done
        self.cfg = load_config()
        self.container = ttk.Frame(self, padding=16)
        self.container.pack(fill="both", expand=True)
        self.step_squad_intro() if self.cfg.get("produto", {}).get("project_number") else self.step_org()

    def clear(self):
        for w in self.container.winfo_children():
            w.destroy()

    def _loading(self, msg="Buscando no GitHub..."):
        self.clear()
        ttk.Label(self.container, text=msg).pack(pady=40)

    def _fetch_async(self, org, number, on_ok):
        self._loading()
        q = queue.Queue()

        def worker():
            try:
                title, field_ids = resolve_fields(org, number)
                q.put(("ok", title, field_ids))
            except Exception as e:
                q.put(("err", str(e), None))

        threading.Thread(target=worker, daemon=True).start()

        def poll():
            try:
                kind, a, b = q.get_nowait()
            except queue.Empty:
                self.after(150, poll)
                return
            if kind == "err":
                self.clear()
                ttk.Label(self.container, text=f"Erro: {a}", foreground="red", wraplength=420).pack(pady=20)
                ttk.Button(self.container, text="Voltar", command=self.step_org).pack()
            else:
                on_ok(a, b)

        poll()

    def step_org(self):
        self.clear()
        ttk.Label(self.container, text="Organização do GitHub:").pack(anchor="w")
        org_e = ttk.Entry(self.container, width=40)
        org_e.insert(0, self.cfg.get("org") or "ContatoSeguro")
        org_e.pack(anchor="w", pady=(0, 12))

        ttk.Label(self.container, text="Repositório padrão (atalho pra consultar 1 issue):").pack(anchor="w")
        repo_e = ttk.Entry(self.container, width=40)
        repo_e.insert(0, self.cfg.get("default_repo") or "")
        repo_e.pack(anchor="w", pady=(0, 12))

        def next_():
            self.cfg["org"] = org_e.get().strip()
            self.cfg["default_repo"] = repo_e.get().strip()
            self._ask_produto_number()

        ttk.Button(self.container, text="Avançar »", command=next_).pack(pady=10)

    def _ask_produto_number(self):
        self.clear()
        ttk.Label(self.container, text="Número do Project 'Produto' (funil de PRD/Épico/US):").pack(anchor="w")
        num_e = ttk.Entry(self.container, width=10)
        num_e.pack(anchor="w", pady=(0, 12))
        def next_():
            number = num_e.get()
            self._fetch_async(self.cfg["org"], number,
                lambda title, fields: self._pick_produto_fields(number, title, fields))

        ttk.Button(self.container, text="Buscar campos »", command=next_).pack()

    def _pick_produto_fields(self, number, title, field_ids):
        self.clear()
        names = sorted(field_ids)
        ttk.Label(self.container, text=f'"{title}" — escolha os campos:', wraplength=440).pack(anchor="w", pady=(0, 8))

        vars_ = {}
        for role, label, kws in [
            ("start", "Data de início", ["início", "start"]),
            ("due", "Previsão de entrega", ["previsão", "entrega", "due"]),
            ("estimativa", "Estimativa", ["estimativa"]),
        ]:
            ttk.Label(self.container, text=label + ":").pack(anchor="w")
            var = tk.StringVar(value=guess(names, *kws))
            ttk.Combobox(self.container, textvariable=var, values=names, state="readonly", width=40).pack(anchor="w", pady=(0, 8))
            vars_[role] = var

        def next_():
            self.cfg["produto"] = {
                "project_number": int(number),
                "fields": {role: v.get() for role, v in vars_.items()},
            }
            self.step_squad_intro()

        ttk.Button(self.container, text="Avançar »", command=next_).pack(pady=10)

    def step_squad_intro(self):
        self.clear()
        ttk.Label(self.container, text="Nome curto do squad (ex: vox, orbit):").pack(anchor="w")
        name_e = ttk.Entry(self.container, width=20)
        name_e.pack(anchor="w", pady=(0, 12))

        ttk.Label(self.container, text="Número do Project do squad (board de dev):").pack(anchor="w")
        num_e = ttk.Entry(self.container, width=10)
        num_e.pack(anchor="w", pady=(0, 12))

        def next_():
            squad_name = name_e.get().strip().lower().replace(" ", "-")
            number = num_e.get()
            self._fetch_async(self.cfg["org"], number,
                lambda title, fields: self._pick_squad_fields(squad_name, number, title, fields))

        ttk.Button(self.container, text="Buscar campos »", command=next_).pack()

    def _pick_squad_fields(self, squad_name, number, title, field_ids):
        self.clear()
        names = sorted(field_ids)
        ttk.Label(self.container, text=f'"{title}" — escolha os campos:', wraplength=440).pack(anchor="w", pady=(0, 8))

        vars_ = {}
        for role, label, kws in [
            ("start", "Start date", ["start"]),
            ("due", "Due date", ["due"]),
            ("estimativa", "Estimativa", ["estimativa", "estimate"]),
            ("status", "Status", ["status"]),
        ]:
            ttk.Label(self.container, text=label + ":").pack(anchor="w")
            var = tk.StringVar(value=guess(names, *kws))
            ttk.Combobox(self.container, textvariable=var, values=names, state="readonly", width=40).pack(anchor="w", pady=(0, 8))
            vars_[role] = var

        def next_():
            fields = {role: v.get() for role, v in vars_.items()}
            self._fetch_status_options(squad_name, number, fields)

        ttk.Button(self.container, text="Avançar »", command=next_).pack(pady=10)

    def _fetch_status_options(self, squad_name, number, fields):
        self._loading("Buscando valores do campo de Status...")
        q = queue.Queue()

        def worker():
            q.put(fetch_status_options(self.cfg["org"], number, fields["status"]))

        threading.Thread(target=worker, daemon=True).start()

        def poll():
            try:
                options = q.get_nowait()
            except queue.Empty:
                self.after(150, poll)
                return
            self._final_step(squad_name, number, fields, options)

        poll()

    def _final_step(self, squad_name, number, fields, options):
        self.clear()
        ttk.Label(self.container, text="Qual valor de Status representa 'em desenvolvimento'\n(dispara o cálculo de prazo)?", wraplength=440).pack(anchor="w", pady=(0, 6))
        wip_var = tk.StringVar(value=guess(options, "progress", "andamento") if options else "WORK IN PROGRESS")
        if options:
            ttk.Combobox(self.container, textvariable=wip_var, values=options, state="readonly", width=40).pack(anchor="w", pady=(0, 12))
        else:
            ttk.Entry(self.container, textvariable=wip_var, width=40).pack(anchor="w", pady=(0, 12))

        ttk.Label(self.container, text="Labels que identificam uma US (separadas por vírgula):").pack(anchor="w")
        labels_e = ttk.Entry(self.container, width=40)
        labels_e.insert(0, "feature,bug,task")
        labels_e.pack(anchor="w", pady=(0, 12))

        def save():
            self.cfg.setdefault("squads", {})[squad_name] = {
                "project_number": int(number),
                "fields": fields,
                "wip_status": wip_var.get(),
                "us_labels": [l.strip() for l in labels_e.get().split(",") if l.strip()],
            }
            CONFIG_FILE.write_text(json.dumps(self.cfg, indent=2, ensure_ascii=False) + "\n")
            self.on_done()
            self.destroy()

        ttk.Button(self.container, text="Salvar", command=save).pack(pady=10)


class ProgressPanel(tk.Toplevel):
    """Painel compacto pra "Sincronizar agora" — em vez de despejar o log inteiro, mostra
    só um contador (N de M issues atualizadas) e vai marcando ✓ conforme cada issue é
    processada. Bem menor que o LogPanel."""

    def __init__(self, master, title):
        super().__init__(master)
        self.title(title)
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        self.geometry(f"340x220+{sw - 360}+60")

        frame = ttk.Frame(self, padding=14)
        frame.pack(fill="both", expand=True)

        self.status_var = tk.StringVar(value="Calculando o que precisa mudar...")
        ttk.Label(frame, textvariable=self.status_var, font=("", 11, "bold"), wraplength=300).pack(anchor="w")

        self.ticks_text = tk.Text(frame, height=6, wrap="word", bg="#f4f3ef", relief="flat",
                                   state="disabled", font=("Consolas", 9))
        self.ticks_text.pack(fill="both", expand=True, pady=(10, 10))

        self.close_btn = ttk.Button(frame, text="Fechar", command=self.destroy, state="disabled")
        self.close_btn.pack()

    def set_total(self, total):
        self.total = total
        self.done = 0
        if total == 0:
            self.status_var.set("Tudo já está sincronizado — nada pra atualizar.")
        else:
            self.status_var.set(f"0 de {total} issues atualizadas")

    def tick(self, number):
        self.done += 1
        self.status_var.set(f"{self.done} de {self.total} issues atualizadas")
        self.ticks_text.config(state="normal")
        self.ticks_text.insert("end", f"✓ #{number}  ")
        self.ticks_text.see("end")
        self.ticks_text.config(state="disabled")

    def finished(self):
        if getattr(self, "total", 0):
            self.status_var.set(f"Concluído — {self.done} de {self.total} issues atualizadas")
        self.close_btn.config(state="normal")


class CsvDatePicker(tk.Toplevel):
    """Antes de gerar o relatório, deixa escolher um período — por padrão gera tudo."""

    def __init__(self, master, on_confirm):
        super().__init__(master)
        self.title("Gerar relatório")
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.on_confirm = on_confirm

        frame = ttk.Frame(self, padding=16)
        frame.pack()

        self.mode = tk.StringVar(value="all")
        ttk.Radiobutton(frame, text="Todas as issues (sem filtro)", variable=self.mode,
                        value="all", command=self._toggle).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(frame, text="Abertas + concluídas num período:", variable=self.mode,
                        value="period", command=self._toggle).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Label(frame, text="De:").grid(row=2, column=0, sticky="e", padx=(20, 6))
        self.since_e = ttk.Entry(frame, width=14, state="disabled")
        self.since_e.grid(row=2, column=1, sticky="w", pady=4)

        ttk.Label(frame, text="Até (opcional, padrão hoje):").grid(row=3, column=0, sticky="e", padx=(20, 6))
        self.until_e = ttk.Entry(frame, width=14, state="disabled")
        self.until_e.grid(row=3, column=1, sticky="w", pady=4)

        ttk.Label(frame, text="formato: AAAA-MM-DD", foreground="#888").grid(row=4, column=0, columnspan=2, pady=(0, 8))

        self.error_var = tk.StringVar()
        ttk.Label(frame, textvariable=self.error_var, foreground="red", wraplength=280).grid(row=5, column=0, columnspan=2)

        ttk.Button(frame, text="Gerar relatório", command=self._confirm).grid(row=6, column=0, columnspan=2, pady=(10, 0))

    def _toggle(self):
        state = "normal" if self.mode.get() == "period" else "disabled"
        self.since_e.config(state=state)
        self.until_e.config(state=state)

    def _confirm(self):
        if self.mode.get() == "all":
            self.on_confirm(None, None)
            self.destroy()
            return
        since_raw, until_raw = self.since_e.get().strip(), self.until_e.get().strip()
        try:
            date.fromisoformat(since_raw)
            if until_raw:
                date.fromisoformat(until_raw)
        except ValueError:
            self.error_var.set("Data inválida — use o formato AAAA-MM-DD.")
            return
        self.on_confirm(since_raw, until_raw or None)
        self.destroy()


class TrayApp:
    """Fica só na bandeja do sistema — sem janela nenhuma até você clicar. As ações e o
    assistente de configuração abrem em janelas do Tkinter, criadas sob demanda a partir
    do clique no menu (que roda numa thread separada da interface, por isso passa pela
    fila 'commands' em vez de tocar direto no Tkinter)."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()  # sem janela principal — só a bandeja
        self.active_squad = self._squads()[0] if self._squads() else None
        self.commands = queue.Queue()

        self.icon = pystray.Icon("sync-produto-squad", make_icon_image(), "Sync Produto x Squad",
                                  menu=pystray.Menu(self._build_menu))
        threading.Thread(target=self.icon.run, daemon=True).start()
        self.root.after(150, self._poll_commands)

    def _squads(self):
        return list(load_config().get("squads", {}))

    def _build_menu(self):
        squads = self._squads()
        squad_items = [
            pystray.MenuItem(name, self._make_select_squad(name), radio=True,
                              checked=lambda item, n=name: self.active_squad == n)
            for name in squads
        ] or [pystray.MenuItem("(nenhuma squad configurada)", None, enabled=False)]

        return (
            pystray.MenuItem("Squad", pystray.Menu(*squad_items)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Ver o que mudaria (dry-run)", self._cmd("dry_run")),
            pystray.MenuItem("Sincronizar agora", self._cmd("sync")),
            pystray.MenuItem("Gerar relatório de ciclo de vida (CSV)", self._cmd("csv")),
            pystray.MenuItem("Corrigir datas de issues fechadas", self._cmd("fix_closed")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Configurar / adicionar squad", self._cmd("configure")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Sair", self._cmd("quit")),
        )

    def _make_select_squad(self, name):
        def handler(icon, item):
            self.active_squad = name
        return handler

    def _cmd(self, name):
        def handler(icon, item):
            self.commands.put(name)
        return handler

    def _poll_commands(self):
        try:
            while True:
                cmd = self.commands.get_nowait()
                self._dispatch(cmd)
        except queue.Empty:
            pass
        self.root.after(150, self._poll_commands)

    def _dispatch(self, cmd):
        if cmd == "quit":
            self.icon.stop()
            self.root.quit()
        elif cmd == "configure":
            ConfigWizard(self.root, on_done=lambda: self.icon.update_menu())
        elif cmd == "dry_run":
            self._run_with_log("Ver o que mudaria", script_cmd("sync-prazo", "--squad", self.active_squad, "--dry-run"))
        elif cmd == "sync":
            self._run_sync_progress()
        elif cmd == "fix_closed":
            self._run_with_log("Corrigindo datas de issues fechadas",
                                script_cmd("corrige-datas-fechadas", "--squad", self.active_squad))
        elif cmd == "csv":
            if self._require_squad():
                CsvDatePicker(self.root, on_confirm=self._run_csv)

    def _require_squad(self):
        if self.active_squad:
            return True
        panel = LogPanel(self.root, "Erro")
        panel.write("Nenhuma squad configurada ainda — usa 'Configurar / adicionar squad' no menu.\n")
        panel.finished()
        return False

    def _stream(self, args, on_line, on_done):
        """Roda um script em background e entrega cada linha de saída (via after(), já na
        thread principal) — usado tanto pelo LogPanel quanto pelo ProgressPanel."""
        q = queue.Queue()

        def worker():
            proc = subprocess.Popen(
                args, cwd=HERE,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
            )
            for line in proc.stdout:
                q.put(line)
            proc.wait()
            q.put(None)

        threading.Thread(target=worker, daemon=True).start()

        def poll():
            try:
                while True:
                    line = q.get_nowait()
                    if line is None:
                        on_done()
                        return
                    on_line(line)
            except queue.Empty:
                pass
            self.root.after(100, poll)

        poll()

    def _run_with_log(self, title, args):
        if not self._require_squad():
            return
        panel = LogPanel(self.root, title)
        self._stream(args, panel.write, panel.finished)

    def _run_csv(self, since, until):
        extra = ["--squad", self.active_squad, "--all"]
        if since:
            extra += ["--since", since]
        if until:
            extra += ["--until", until]
        extra += ["--csv", "ciclo-vida.csv"]
        self._run_with_log("Gerando relatório de ciclo de vida", script_cmd("tempo-status", *extra))

    def _run_sync_progress(self):
        if not self._require_squad():
            return
        panel = ProgressPanel(self.root, "Sincronizando")
        squad = self.active_squad

        def after_dry_run(planned):
            panel.set_total(len(planned))
            done = set()

            def on_line(line):
                m = WRITE_RE.match(line)
                if m and m.group(1) not in done:
                    done.add(m.group(1))
                    panel.tick(m.group(1))

            self._stream(script_cmd("sync-prazo", "--squad", squad), on_line, panel.finished)

        # 1a passada, em dry-run, só pra saber quantas issues serão tocadas de verdade
        planned = set()

        def collect(line):
            m = WRITE_RE.match(line)
            if m:
                planned.add(m.group(1))

        self._stream(
            script_cmd("sync-prazo", "--squad", squad, "--dry-run"),
            collect,
            lambda: after_dry_run(planned),
        )

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    TrayApp().run()

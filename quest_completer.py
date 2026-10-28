import os
import sys
import glob
import json
import shutil
import time
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox

# --- CONFIGURATION & CONSTANTES ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GAMES_JSON_FILE = os.path.join(BASE_DIR, "detectable.json")
CONFIG_JSON_FILE = os.path.join(BASE_DIR, "config.json")
GAMES_DIR = os.path.join(BASE_DIR, "games")

VALID_WINDOWS_OS = {"win32", "win64", "windows", "win"}
SAFE_FILENAME_CHARS = set(" _-")
SAFE_PATH_CHARS = set(" _-.()")


class DiscordQuestCompleterGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Discord Quest Completer")
        self.root.geometry("540x760")
        self.root.resizable(False, False)

        # Variables d'état
        self.games = []
        self.all_game_entries = []  # Format: (index, display_text, search_blob)
        self.visible_game_indices = []
        self.running_process = None
        self.auto_processes = []
        self.running_game_index = None
        self.auto_thread = None
        self.is_auto_running = False
        self.stop_auto_event = threading.Event()
        self._resolved_exe_cache = {}
        self._search_timer = None

        # Suivi du temps
        self.session_start_time = None
        self.target_duration = 0

        # Préparation de l'environnement Python & des DLLs pour le spoofing
        self._source_exe, self._required_dlls, self._child_env = self._prepare_python_env()
        self._startupinfo, self._creationflags = self._init_subprocess_params()

        # Chargement des données
        self.load_games()
        self.config = self.load_config()

        # Construction de l'interface
        self.setup_ui()

        # Nettoyage à la fermeture
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    @staticmethod
    def _prepare_python_env():
        """Configure l'exécutable source, repère les DLLs Python et prépare l'environnement."""
        exe_dir = os.path.dirname(sys.executable)
        base_prefix = getattr(sys, "base_prefix", exe_dir)

        # Préférence pour pythonw.exe (sans console)
        pythonw_candidates = [
            os.path.join(exe_dir, "pythonw.exe"),
            os.path.join(base_prefix, "pythonw.exe"),
        ]
        source_exe = next((p for p in pythonw_candidates if os.path.exists(p)), sys.executable)

        # Recherche des DLLs indispensables (python314.dll, python3.dll, vcruntime*.dll)
        search_dirs = {exe_dir, base_prefix, os.path.dirname(source_exe)}
        dll_files = {}
        for d in search_dirs:
            if not os.path.isdir(d):
                continue
            for pattern in ("python*.dll", "vcruntime*.dll"):
                for dll_path in glob.glob(os.path.join(d, pattern)):
                    dll_name = os.path.basename(dll_path).lower()
                    if dll_name not in dll_files:
                        dll_files[dll_name] = dll_path

        # Mise à jour de l'environnement pour que Windows et Python trouvent tout
        env = os.environ.copy()
        extra_paths = [
            exe_dir,
            base_prefix,
            os.path.join(base_prefix, "DLLs"),
            os.path.join(base_prefix, "Library", "bin"),
        ]
        valid_paths = [p for p in extra_paths if os.path.isdir(p)]
        env["PATH"] = os.pathsep.join(valid_paths) + os.pathsep + env.get("PATH", "")
        env["PYTHONHOME"] = base_prefix

        # On injecte aussi dans le processus courant pour aider CreateProcess sous Windows
        os.environ["PATH"] = env["PATH"]

        return source_exe, list(dll_files.values()), env

    @staticmethod
    def _init_subprocess_params():
        """Prépare les paramètres subprocess Windows une seule fois."""
        if os.name != "nt":
            return None, 0

        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 7  # SW_SHOWMINNOACTIVE (minimisé sans voler le focus)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        return startupinfo, creationflags

    @staticmethod
    def _fast_link_or_copy(src, dst):
        """Crée un hardlink (0 Mo utilisé, instantané) ou copie le fichier en secours."""
        if os.path.exists(dst):
            return
        try:
            os.link(src, dst)
        except OSError:
            shutil.copyfile(src, dst)

    def load_games(self):
        """Charge les jeux depuis detectable.json et pré-calcule l'index de recherche."""
        if not os.path.exists(GAMES_JSON_FILE):
            messagebox.showerror("Error", f"Could not find '{GAMES_JSON_FILE}'.")
            sys.exit(1)

        try:
            with open(GAMES_JSON_FILE, "r", encoding="utf-8") as f:
                raw_games = json.load(f)

            self.games = [
                game for game in raw_games
                if isinstance(game.get("executables"), list) and game["executables"]
            ]
        except Exception as e:
            messagebox.showerror("Error", f"Failed to parse '{GAMES_JSON_FILE}':\n{e}")
            sys.exit(1)

        self._resolved_exe_cache.clear()
        self.all_game_entries = []

        for idx, game in enumerate(self.games, start=1):
            name = game.get("name", "Unknown Game")
            game_id = str(game.get("id", ""))
            exe_names = " ".join(
                exe.get("name", "") for exe in game.get("executables", []) if isinstance(exe, dict)
            )
            display_text = f"{idx}. {name}"
            search_blob = f"{display_text} {game_id} {exe_names}".lower()
            self.all_game_entries.append((idx - 1, display_text, search_blob))

    def load_config(self):
        """Charge ou crée config.json."""
        defaults = {
            "start_iteration": 1,
            "end_iteration": len(self.games),
            "run_time": 15,
            "runtime_unit": "minutes",
            "increment": 1,
            "increment_delay": 1.0,
            "manual_auto_stop": False,
        }

        if os.path.exists(CONFIG_JSON_FILE):
            try:
                with open(CONFIG_JSON_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                if isinstance(saved, dict):
                    defaults.update(saved)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass

        if defaults.get("runtime_unit") not in {"minutes", "seconds"}:
            defaults["runtime_unit"] = "minutes"

        self._write_config(defaults)
        return defaults

    def _write_config(self, data):
        try:
            with open(CONFIG_JSON_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
                f.write("\n")
        except OSError:
            pass

    def save_config(self):
        try:
            config = {
                "start_iteration": int(self.start_iter_entry.get()),
                "end_iteration": int(self.end_iter_entry.get()),
                "run_time": int(self.runtime_entry.get()),
                "runtime_unit": self.runtime_unit_var.get(),
                "increment": int(self.increment_entry.get()),
                "increment_delay": float(self.increment_delay_entry.get()),
                "manual_auto_stop": bool(self.manual_timer_var.get()),
            }
            self._write_config(config)
        except (TypeError, ValueError):
            pass

    def setup_ui(self):
        # ---------------- EN-TÊTE & STATUT ----------------
        header_frame = tk.Frame(self.root, pady=10, padx=10)
        header_frame.pack(fill=tk.X)

        tk.Label(header_frame, text="Discord Quest Completer", font=("Segoe UI", 14, "bold")).pack(side=tk.LEFT)

        self.status_frame = tk.Frame(header_frame)
        self.status_frame.pack(side=tk.RIGHT)

        self.timer_label = tk.Label(self.status_frame, text="", font=("Consolas", 10, "bold"), fg="#555555")
        self.timer_label.pack(side=tk.LEFT, padx=(0, 8))

        self.status_canvas = tk.Canvas(self.status_frame, width=16, height=16, highlightthickness=0)
        self.status_canvas.pack(side=tk.LEFT, padx=(0, 5))
        self.status_dot = self.status_canvas.create_oval(2, 2, 14, 14, fill="red")

        self.status_label = tk.Label(self.status_frame, text="Offline", font=("Segoe UI", 10, "bold"), fg="red")
        self.status_label.pack(side=tk.LEFT)

        ttk.Separator(self.root, orient="horizontal").pack(fill=tk.X, padx=10, pady=2)

        # ---------------- LISTE DES JEUX & RECHERCHE ----------------
        list_frame = tk.Frame(self.root, padx=10, pady=5)
        list_frame.pack(fill=tk.BOTH, expand=True)

        top_list_bar = tk.Frame(list_frame)
        top_list_bar.pack(fill=tk.X, pady=(0, 4))

        tk.Label(
            top_list_bar,
            text="Available Games (Click to Launch / Right-Click for Options):",
            anchor="w",
            font=("Segoe UI", 9, "bold")
        ).pack(side=tk.LEFT)

        self.count_label = tk.Label(top_list_bar, text="", font=("Segoe UI", 8), fg="#666666")
        self.count_label.pack(side=tk.RIGHT)

        # Barre de recherche avec bouton 'X' pour effacer rapidement
        search_container = tk.Frame(list_frame)
        search_container.pack(fill=tk.X, pady=(0, 5))

        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(search_container, textvariable=self.search_var, font=("Segoe UI", 10))
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.search_entry.bind("<KeyRelease>", self.filter_game_list)

        clear_search_btn = tk.Button(
            search_container, text="✕", width=3, command=self.clear_search, relief=tk.FLAT
        )
        clear_search_btn.pack(side=tk.RIGHT, padx=(4, 0))

        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.game_listbox = tk.Listbox(
            list_frame,
            yscrollcommand=scrollbar.set,
            font=("Segoe UI", 10),
            selectmode=tk.SINGLE,
            activestyle="none"
        )
        self.game_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.game_listbox.yview)

        # Menu contextuel (Clic droit)
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Set as Start Iteration", command=self.set_selected_as_start)
        self.context_menu.add_command(label="Set as End Iteration", command=self.set_selected_as_end)

        self.refresh_game_list()
        self.game_listbox.bind("<ButtonRelease-1>", self.on_game_click)
        self.game_listbox.bind("<Button-3>", self.show_context_menu)

        # ---------------- BARRE DE PROGRESSION ----------------
        progress_frame = tk.Frame(self.root, padx=10, pady=2)
        progress_frame.pack(fill=tk.X)
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100.0)
        self.progress_bar.pack(fill=tk.X)

        # ---------------- PARAMÈTRES ----------------
        config_frame = tk.LabelFrame(self.root, text=" Settings ", padx=10, pady=8)
        config_frame.pack(fill=tk.X, padx=10, pady=8)

        vcmd = (self.root.register(self.validate_integer), "%P")
        float_vcmd = (self.root.register(self.validate_float), "%P")

        tk.Label(config_frame, text="Start Iteration:").grid(row=0, column=0, sticky="e", padx=5, pady=4)
        self.start_iter_entry = tk.Entry(config_frame, validate="key", validatecommand=vcmd, width=10)
        self.start_iter_entry.insert(0, str(self.config["start_iteration"]))
        self.start_iter_entry.grid(row=0, column=1, sticky="w", padx=5, pady=4)

        tk.Label(config_frame, text="End Iteration:").grid(row=0, column=2, sticky="e", padx=5, pady=4)
        self.end_iter_entry = tk.Entry(config_frame, validate="key", validatecommand=vcmd, width=10)
        self.end_iter_entry.insert(0, str(self.config["end_iteration"]))
        self.end_iter_entry.grid(row=0, column=3, sticky="w", padx=5, pady=4)

        tk.Label(config_frame, text="Run Time:").grid(row=1, column=0, sticky="e", padx=5, pady=4)
        self.runtime_entry = tk.Entry(config_frame, validate="key", validatecommand=vcmd, width=10)
        self.runtime_entry.insert(0, str(self.config["run_time"]))
        self.runtime_entry.grid(row=1, column=1, sticky="w", padx=5, pady=4)

        self.runtime_unit_var = tk.StringVar(value=self.config["runtime_unit"])
        self.runtime_unit_menu = ttk.Combobox(
            config_frame,
            textvariable=self.runtime_unit_var,
            values=["minutes", "seconds"],
            state="readonly",
            width=9
        )
        self.runtime_unit_menu.grid(row=1, column=2, sticky="w", padx=(5, 5), pady=4)

        tk.Label(config_frame, text="Increment:").grid(row=2, column=0, sticky="e", padx=5, pady=4)
        self.increment_entry = tk.Entry(config_frame, validate="key", validatecommand=vcmd, width=10)
        self.increment_entry.insert(0, str(self.config["increment"]))
        self.increment_entry.grid(row=2, column=1, sticky="w", padx=5, pady=4)

        tk.Label(config_frame, text="Increment Delay (s):").grid(row=2, column=2, sticky="e", padx=5, pady=4)
        self.increment_delay_entry = tk.Entry(config_frame, validate="key", validatecommand=float_vcmd, width=10)
        self.increment_delay_entry.insert(0, str(self.config["increment_delay"]))
        self.increment_delay_entry.grid(row=2, column=3, sticky="w", padx=5, pady=4)

        self.manual_timer_var = tk.BooleanVar(value=self.config.get("manual_auto_stop", False))
        tk.Checkbutton(
            config_frame,
            text="Auto-stop manual game after 'Run Time'",
            variable=self.manual_timer_var
        ).grid(row=3, column=0, columnspan=4, sticky="w", padx=5, pady=(4, 0))

        # ---------------- BOUTONS ----------------
        btn_frame = tk.Frame(self.root, padx=10, pady=8)
        btn_frame.pack(fill=tk.X)

        self.clear_btn = tk.Button(btn_frame, text="Stop / Clear", width=13, command=self.stop_current_game)
        self.clear_btn.pack(side=tk.LEFT, padx=5)

        self.start_auto_btn = tk.Button(
            btn_frame, text="Start Auto", width=15, bg="#27ae60", fg="white",
            font=("Segoe UI", 9, "bold"), command=self.start_auto
        )
        self.start_auto_btn.pack(side=tk.LEFT, padx=5)

        self.abort_auto_btn = tk.Button(
            btn_frame, text="Abort Auto", width=15, state=tk.DISABLED, bg="#c0392b", fg="white",
            font=("Segoe UI", 9, "bold"), command=self.abort_auto
        )
        self.abort_auto_btn.pack(side=tk.LEFT, padx=5)

    # ---------------- VALIDATION & RECHERCHE ----------------
    @staticmethod
    def validate_integer(P):
        return P == "" or P.isdigit()

    @staticmethod
    def validate_float(P):
        if P == "":
            return True
        return P.count(".") <= 1 and P.replace(".", "", 1).isdigit()

    def clear_search(self):
        self.search_var.set("")
        self.refresh_game_list("")

    def filter_game_list(self, event=None):
        if self._search_timer is not None:
            self.root.after_cancel(self._search_timer)
        query = self.search_var.get().strip().lower()
        self._search_timer = self.root.after(200, self.refresh_game_list, query)

    def refresh_game_list(self, query=""):
        self.game_listbox.delete(0, tk.END)

        if not query:
            self.visible_game_indices = [idx for idx, _, _ in self.all_game_entries]
            display_items = [text for _, text, _ in self.all_game_entries]
        else:
            filtered = [
                (idx, text) for idx, text, blob in self.all_game_entries
                if query in blob
            ]
            self.visible_game_indices = [idx for idx, _ in filtered]
            display_items = [text for _, text in filtered]

        self.count_label.config(text=f"{len(display_items)} / {len(self.games)} games")

        if display_items:
            self.game_listbox.insert(tk.END, *display_items)
            self.game_listbox.select_set(0)

            if self.running_game_index is not None:
                vis_pos = self.get_visible_position(self.running_game_index)
                if vis_pos is not None:
                    self.game_listbox.itemconfig(vis_pos, fg="green")

    def get_visible_position(self, original_index):
        try:
            return self.visible_game_indices.index(original_index)
        except ValueError:
            return None

    def show_context_menu(self, event):
        idx = self.game_listbox.nearest(event.y)
        if idx >= 0 and idx < len(self.visible_game_indices):
            self.game_listbox.selection_clear(0, tk.END)
            self.game_listbox.selection_set(idx)
            self.context_menu.tk_popup(event.x_root, event.y_root)

    def set_selected_as_start(self):
        sel = self.game_listbox.curselection()
        if sel:
            real_idx = self.visible_game_indices[sel[0]] + 1
            self.start_iter_entry.delete(0, tk.END)
            self.start_iter_entry.insert(0, str(real_idx))

    def set_selected_as_end(self):
        sel = self.game_listbox.curselection()
        if sel:
            real_idx = self.visible_game_indices[sel[0]] + 1
            self.end_iter_entry.delete(0, tk.END)
            self.end_iter_entry.insert(0, str(real_idx))

    # ---------------- GESTION DES CHEMINS & SPOOFING ----------------
    @staticmethod
    def sanitize_filename(name):
        return "".join(c for c in name if c.isalnum() or c in SAFE_FILENAME_CHARS).strip()

    def choose_executable_path(self, game_data):
        game_id = str(game_data.get("id", ""))
        if game_id and game_id in self._resolved_exe_cache:
            return self._resolved_exe_cache[game_id]

        executables = game_data.get("executables") or []
        preferred_candidates = [
            exe["name"] for exe in executables
            if isinstance(exe, dict) and exe.get("name")
            and (not exe.get("os") or str(exe["os"]).lower() in VALID_WINDOWS_OS)
        ]

        if not preferred_candidates:
            preferred_candidates = [
                exe["name"] for exe in executables
                if isinstance(exe, dict) and exe.get("name")
            ]

        fallback = f"{self.sanitize_filename(game_data.get('name', 'Game'))}.exe"

        for exe_name in preferred_candidates:
            normalized = exe_name.replace("/", os.sep).replace("\\", os.sep).lstrip(".\\>")
            parts = [
                "".join(ch for ch in part if ch.isalnum() or ch in SAFE_PATH_CHARS)
                for part in normalized.split(os.sep)
            ]
            parts = [p for p in parts if p]
            if parts:
                candidate = os.path.join(*parts)
                if os.path.basename(candidate):
                    if game_id:
                        self._resolved_exe_cache[game_id] = candidate
                    return candidate

        if game_id:
            self._resolved_exe_cache[game_id] = fallback
        return fallback

    def fake_game(self, game_data):
        """Crée l'exécutable + ses DLLs liées et lance le processus factice sans erreur."""
        game_id = str(game_data.get("id"))
        raw_name = game_data.get("name", "Game")

        exe_relative_path = self.choose_executable_path(game_data)
        if not os.path.splitext(exe_relative_path)[1]:
            exe_relative_path = f"{exe_relative_path}.exe"

        target_exe = os.path.join(GAMES_DIR, game_id, exe_relative_path)
        target_exe_dir = os.path.dirname(target_exe)
        os.makedirs(target_exe_dir, exist_ok=True)

        # 1. Lien physique (ou copie) de pythonw.exe vers le nom du jeu (ex: wow-64.exe)
        self._fast_link_or_copy(self._source_exe, target_exe)

        # 2. Lien physique (ou copie) des DLLs Python (ex: python314.dll) dans le même dossier
        for dll_src in self._required_dlls:
            dll_dst = os.path.join(target_exe_dir, os.path.basename(dll_src))
            self._fast_link_or_copy(dll_src, dll_dst)

        safe_title = raw_name.replace("\\", "\\\\").replace("'", "\\'")
        window_script = (
            "import tkinter as tk; "
            "root = tk.Tk(); "
            f"root.title('{safe_title}'); "
            "root.geometry('300x150'); "
            "tk.Label(root, text='Spoofed Process Running...', font=('Segoe UI', 10)).pack(expand=True); "
            "root.wm_state('iconic'); "
            "root.mainloop()"
        )

        return subprocess.Popen(
            [target_exe, "-c", window_script],
            startupinfo=self._startupinfo,
            creationflags=self._creationflags,
            env=self._child_env,
            cwd=target_exe_dir
        )

    # ---------------- SURVEILLANCE & CONTRÔLES MANUELS ----------------
    @staticmethod
    def _format_seconds(seconds):
        seconds = max(0, int(seconds))
        mins, secs = divmod(seconds, 60)
        hrs, mins = divmod(mins, 60)
        if hrs > 0:
            return f"{hrs:02d}:{mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}"

    def _get_configured_runtime_seconds(self):
        try:
            val = max(1, int(self.runtime_entry.get()))
        except ValueError:
            val = 15
        return val * 60 if self.runtime_unit_var.get() == "minutes" else val

    def check_process_status(self):
        """Vérifie périodiquement le processus manuel et met à jour le chronomètre."""
        if self.running_process is None:
            return

        if self.running_process.poll() is not None:
            self.stop_current_game()
            return

        elapsed = time.time() - (self.session_start_time or time.time())

        if self.manual_timer_var.get() and self.target_duration > 0:
            remaining = self.target_duration - elapsed
            if remaining <= 0:
                self.stop_current_game()
                return
            pct = min(100.0, (elapsed / self.target_duration) * 100.0)
            self.progress_var.set(pct)
            self.timer_label.config(text=f"⏳ {self._format_seconds(remaining)}")
        else:
            self.timer_label.config(text=f"⏱ {self._format_seconds(elapsed)}")

        self.root.after(500, self.check_process_status)

    def launch_game_by_index(self, index):
        if self.running_process is not None:
            self.stop_current_game()

        try:
            self.running_process = self.fake_game(self.games[index])
            self.running_game_index = index
            self.session_start_time = time.time()
            self.target_duration = self._get_configured_runtime_seconds()

            visible_position = self.get_visible_position(index)
            if visible_position is not None:
                self.game_listbox.itemconfig(visible_position, fg="green")

            self.update_status(True)
            self.check_process_status()
            return True
        except Exception as e:
            messagebox.showerror("Launch Error", f"Failed to start game:\n{e}")
            return False

    def stop_current_game(self):
        proc_to_stop = self.running_process
        self.running_process = None
        self.session_start_time = None

        if proc_to_stop is not None:
            threading.Thread(target=self._terminate_single_process, args=(proc_to_stop,), daemon=True).start()

        if self.running_game_index is not None:
            visible_position = self.get_visible_position(self.running_game_index)
            if visible_position is not None:
                self.game_listbox.itemconfig(visible_position, fg="black")
            self.running_game_index = None

        if not self.is_auto_running:
            self.progress_var.set(0.0)
            self.timer_label.config(text="")
            self.update_status(False)

    @staticmethod
    def _terminate_single_process(proc):
        try:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=1.5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def update_status(self, is_running):
        color = "#2ecc71" if is_running else "red"
        text = "Running" if is_running else "Offline"
        self.status_canvas.itemconfig(self.status_dot, fill=color)
        self.status_label.config(text=text, fg=color)

    def on_game_click(self, event):
        if self.is_auto_running:
            return

        selection = self.game_listbox.curselection()
        if not selection:
            return

        clicked_index = self.visible_game_indices[selection[0]]
        if clicked_index == self.running_game_index:
            self.stop_current_game()
        else:
            self.launch_game_by_index(clicked_index)

    # ---------------- LOGIQUE AUTO RUN ----------------
    def start_auto(self):
        if self.is_auto_running:
            return

        try:
            start_iter = int(self.start_iter_entry.get())
            end_iter = int(self.end_iter_entry.get())
            run_time = int(self.runtime_entry.get())
            increment = int(self.increment_entry.get())
            increment_delay = float(self.increment_delay_entry.get())
        except ValueError:
            messagebox.showerror("Input Error", "Please fill all input fields with valid numbers.")
            return

        total_games = len(self.games)

        if increment < 1:
            messagebox.showerror("Input Error", "Increment must be at least 1.")
            return
        if increment_delay < 0:
            messagebox.showerror("Input Error", "Increment Delay cannot be negative.")
            return
        if run_time < 1:
            messagebox.showerror("Input Error", "Run Time must be at least 1.")
            return

        start_iter = max(1, start_iter)
        end_iter = min(total_games, end_iter)

        self.start_iter_entry.delete(0, tk.END)
        self.start_iter_entry.insert(0, str(start_iter))
        self.end_iter_entry.delete(0, tk.END)
        self.end_iter_entry.insert(0, str(end_iter))

        if start_iter > end_iter:
            messagebox.showerror("Input Error", "Start Iteration cannot be greater than End Iteration.")
            return

        self.save_config()
        self.stop_current_game()

        run_time_seconds = run_time * 60 if self.runtime_unit_var.get() == "minutes" else run_time

        self.is_auto_running = True
        self.stop_auto_event.clear()

        self.start_auto_btn.config(text="Auto Running...", state=tk.DISABLED)
        self.abort_auto_btn.config(state=tk.NORMAL)
        self.clear_btn.config(state=tk.DISABLED)

        self.auto_thread = threading.Thread(
            target=self._auto_runner_loop,
            args=(start_iter, end_iter, run_time_seconds, increment, increment_delay),
            daemon=True
        )
        self.auto_thread.start()

    def _auto_runner_loop(self, start_iter, end_iter, duration_seconds, increment, increment_delay):
        total_items = max(1, end_iter - (start_iter - 1))

        for batch_start in range(start_iter - 1, end_iter, increment):
            if self.stop_auto_event.is_set():
                break

            batch_end = min(batch_start + increment, end_iter)
            batch_processes = []

            for current_idx in range(batch_start, batch_end):
                if self.stop_auto_event.is_set():
                    break

                try:
                    process = self.fake_game(self.games[current_idx])
                    self.auto_processes.append(process)
                    batch_processes.append(process)
                    done_count = (current_idx - (start_iter - 1)) + 1
                    pct = (done_count / total_items) * 100.0
                    self.root.after(0, self._highlight_auto_game, current_idx, pct)
                except Exception as e:
                    self.root.after(0, lambda err=e: messagebox.showerror("Launch Error", f"Failed to start game:\n{err}"))
                    break

                if current_idx < batch_end - 1 and self.stop_auto_event.wait(increment_delay):
                    break

            if self.stop_auto_event.is_set() or len(batch_processes) != (batch_end - batch_start):
                self._stop_processes(batch_processes)
                break

            # Compte à rebours fluide pour l'interface
            batch_start_time = time.time()
            while not self.stop_auto_event.is_set():
                elapsed = time.time() - batch_start_time
                remaining = duration_seconds - elapsed
                if remaining <= 0:
                    break
                self.root.after(
                    0,
                    lambda r=remaining, b_end=batch_end: self.timer_label.config(
                        text=f"[{b_end}/{end_iter}] ⏳ {self._format_seconds(r)}"
                    )
                )
                if self.stop_auto_event.wait(min(0.5, remaining)):
                    break

            self._stop_processes(batch_processes)

            if self.stop_auto_event.wait(0.3):
                break

        self.root.after(0, self._reset_auto_ui)

    def _highlight_auto_game(self, index, progress_pct):
        self.update_status(True)
        self.progress_var.set(progress_pct)
        visible_position = self.get_visible_position(index)
        if visible_position is not None:
            self.game_listbox.selection_clear(0, tk.END)
            self.game_listbox.selection_set(visible_position)
            self.game_listbox.see(visible_position)

    def abort_auto(self):
        if self.is_auto_running:
            self.stop_auto_event.set()
            procs = list(self.auto_processes)
            self.auto_processes.clear()
            threading.Thread(target=self._stop_processes, args=(procs,), daemon=True).start()

    def _stop_processes(self, processes):
        if not processes:
            return

        alive_procs = []
        for proc in processes:
            try:
                if proc.poll() is None:
                    proc.terminate()
                    alive_procs.append(proc)
            except Exception:
                pass

        for proc in alive_procs:
            try:
                proc.wait(timeout=1.5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        stopped_set = set(processes)
        self.auto_processes = [p for p in self.auto_processes if p not in stopped_set]

        if not self.auto_processes and not self.running_process:
            self.root.after(0, self.update_status, False)

    def _reset_auto_ui(self):
        self.is_auto_running = False
        self.progress_var.set(0.0)
        self.timer_label.config(text="")
        self.update_status(False)
        self.start_auto_btn.config(text="Start Auto", state=tk.NORMAL)
        self.abort_auto_btn.config(state=tk.DISABLED)
        self.clear_btn.config(state=tk.NORMAL)

    def on_closing(self):
        """Sauvegarde, arrête les processus et nettoie le dossier games."""
        self.save_config()
        self.stop_auto_event.set()
        self._stop_processes(list(self.auto_processes))
        if self.running_process is not None:
            self._terminate_single_process(self.running_process)

        if os.path.exists(GAMES_DIR):
            shutil.rmtree(GAMES_DIR, ignore_errors=True)

        self.root.destroy()


if __name__ == "__main__":
    os.makedirs(GAMES_DIR, exist_ok=True)
    root = tk.Tk()
    app = DiscordQuestCompleterGUI(root)
    root.mainloop()
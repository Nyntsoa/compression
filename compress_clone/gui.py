"""Desktop application for file compression and archive management."""

from __future__ import annotations

import queue
import shutil
import threading
import tkinter as tk
import time
from pathlib import Path
from tkinter import filedialog, ttk
from typing import cast

from . import engine
from .state import add_failure, add_history, load_history, load_settings, save_settings
from .theme import FONTS, SPACE, apply_theme, resolve_theme


FORMATS = ("bz2", "xz", "lzma", "7z")
DICTIONARY_MIB_OPTIONS = (8, 16, 32, 64, 128)
COMPRESSION_LEVELS = ("Faible", "Moyen", "Élevé", "Très élevé")
COMPRESSION_LEVEL_VALUES = {"Faible": 1, "Moyen": 6, "Élevé": 7, "Très élevé": 9}
THEME_IDS = {"Clair": "light", "Sombre": "dark", "Automatique": "system"}
THEME_NAMES = {value: key for key, value in THEME_IDS.items()}


def _human_size(value: int | None) -> str:
    if value is None:
        return "—"
    units = ("octets", "Ko", "Mo", "Go", "To")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}" if unit != "octets" else f"{int(amount)} octets"
        amount /= 1024
    return f"{value} octets"


def _compression_level_name(value: int) -> str:
    """Translate a saved engine level to the nearest user-facing preset."""
    return min(COMPRESSION_LEVELS, key=lambda name: abs(COMPRESSION_LEVEL_VALUES[name] - value))


class CompressionApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Mihena")
        self._blank_window_icon = tk.PhotoImage(width=1, height=1)
        self._blank_window_icon.put("#FFFFFF", to=(0, 0))
        self._blank_window_icon.transparency_set(0, 0, True)
        self.root.iconphoto(True, self._blank_window_icon)
        self.root.geometry("1160x800")
        self.root.minsize(480, 440)

        self.settings = load_settings()
        self.theme_mode = tk.StringVar(value=str(self.settings["theme"]))
        self.current_page = "dashboard"
        self.nav_buttons: dict[str, ttk.Button] = {}
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.cancel_event: threading.Event | None = None
        self.busy = False
        self.active_context: dict = {}
        self.active_started = 0.0
        self.cancel_is_deferred = False
        self.archive_path: Path | None = None
        self.archive_entries: tuple[engine.ArchiveEntry, ...] = ()
        self.archive_sort_column = "name"
        self.archive_sort_reverse = False
        self.archive_tree_names: dict[str, str] = {}

        self.mode = tk.StringVar(value="Compresser")
        self.format = tk.StringVar(value=str(self.settings["format"]))
        self.sources: list[Path] = []
        self.output = tk.StringVar()
        self.level = tk.StringVar(value=_compression_level_name(int(self.settings["level"])))
        saved_dictionary_mib = max(1, int(self.settings["dictionary_kib"]) // 1024)
        dictionary_mib = min(DICTIONARY_MIB_OPTIONS, key=lambda value: abs(value - saved_dictionary_mib))
        self.dictionary_mib = tk.IntVar(value=dictionary_mib)
        self.dictionary_choice_buttons: dict[int, ttk.Button] = {}
        self.password = tk.StringVar()
        self.show_password = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Prêt")
        self.operation_summary = tk.StringVar(value="Le résultat apparaîtra ici après l’opération.")
        self.progress_percent = tk.DoubleVar(value=0.0)
        self.settings_max_files = tk.IntVar(value=int(self.settings["max_files"]))
        self.settings_max_mib = tk.IntVar(value=int(self.settings["max_uncompressed_mib"]))
        self.settings_default_format = tk.StringVar(value=str(self.settings["format"]))
        self.settings_default_level = tk.StringVar(value=_compression_level_name(int(self.settings["level"])))
        self.settings_theme = tk.StringVar(value=THEME_NAMES.get(str(self.settings["theme"]), "Automatique"))
        self.archive_password = tk.StringVar()
        self.archive_output = tk.StringVar()
        self.archive_search = tk.StringVar()

        self._style()
        self._build()
        self.status.trace_add("write", self._refresh_status_style)
        self._apply_theme()
        self._refresh_status_style()
        self._refresh_mode()
        self._refresh_history()
        self._show_page("dashboard")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _style(self) -> None:
        self.palette = apply_theme(self.root, self.theme_mode.get())

    def _build(self) -> None:
        """Construit le cadre de l’application et relie ses vues principales."""
        self.shell = ttk.Frame(self.root, style="Shell.TFrame")
        self.shell.pack(fill="both", expand=True, padx=12, pady=12)
        self.shell.columnconfigure(1, weight=1)
        self.shell.rowconfigure(0, weight=1)

        self.sidebar = ttk.Frame(self.shell, style="Sidebar.TFrame", padding=(SPACE["md"], SPACE["lg"]))
        self.sidebar.grid(row=0, column=0, sticky="ns")
        self.sidebar.grid_propagate(False)
        self.sidebar.configure(width=190)
        ttk.Label(self.sidebar, text="Mihena", style="Brand.TLabel").pack(anchor="w", padx=10, pady=(2, 4))
        navigation = (
            ("dashboard", "Accueil"),
            ("compress", "Compresser"),
            ("extract", "Extraire"),
        )
        for page, label in navigation:
            button = ttk.Button(self.sidebar, text=label, style="Nav.TButton",
                                command=lambda selected=page: self._show_page(selected))
            button.pack(fill="x", pady=2)
            self.nav_buttons[page] = button
        ttk.Separator(self.sidebar).pack(fill="x", pady=(14, 10))
        ttk.Label(self.sidebar, text="AUTRES OUTILS", style="Sidebar.TLabel", font=FONTS["tiny"]).pack(anchor="w", padx=10, pady=(0, 5))
        for page, label in (("archive", "Archives 7z"), ("history", "Historique")):
            button = ttk.Button(self.sidebar, text=label, style="Nav.TButton",
                                command=lambda selected=page: self._show_page(selected))
            button.pack(fill="x", pady=2)
            self.nav_buttons[page] = button
        ttk.Frame(self.sidebar, style="Sidebar.TFrame").pack(fill="both", expand=True)
        ttk.Separator(self.sidebar).pack(fill="x", pady=(8, 10))
        settings_button = ttk.Button(self.sidebar, text="Paramètres", style="Nav.TButton",
                                     command=lambda: self._show_page("settings"))
        settings_button.pack(fill="x", pady=2)
        self.nav_buttons["settings"] = settings_button

        self.main = ttk.Frame(self.shell, style="Surface.TFrame", padding=(SPACE["xl"], 18, SPACE["xl"], SPACE["md"]))
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.columnconfigure(0, weight=1)
        self.main.rowconfigure(1, weight=1)
        self.header = ttk.Frame(self.main, style="Surface.TFrame")
        self.header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self.header.columnconfigure(0, weight=1)
        self.page_title = ttk.Label(self.header, text="Accueil", style="Title.TLabel")
        self.page_title.grid(row=0, column=0, sticky="w")
        self.nav_choice = tk.StringVar(value="Accueil")
        self.compact_nav = ttk.Combobox(
            self.header, textvariable=self.nav_choice,
            values=("Accueil", "Compresser", "Extraire", "Archives 7z", "Historique", "Paramètres"),
            state="readonly", width=15, style="NavSelect.TCombobox",
        )
        self.compact_nav.grid(row=0, column=1, sticky="e", padx=(8, 0))
        self.compact_nav.bind("<<ComboboxSelected>>", self._on_compact_nav)
        self.page_subtitle = ttk.Label(self.header, text="Compressez ou retrouvez vos fichiers en quelques clics.", style="Muted.TLabel", wraplength=900)
        self.page_subtitle.grid(row=1, column=0, columnspan=2, sticky="w", pady=(3, 0))

        self.page_host = ttk.Frame(self.main, style="Surface.TFrame")
        self.page_host.grid(row=1, column=0, sticky="nsew")
        self.page_host.columnconfigure(0, weight=1)
        self.page_host.rowconfigure(0, weight=1)
        self.dashboard_tab = ttk.Frame(self.page_host, style="Surface.TFrame", padding=2)
        self.work_tab = ttk.Frame(self.page_host, style="Surface.TFrame", padding=2)
        self.archive_tab = ttk.Frame(self.page_host, style="Surface.TFrame", padding=2)
        self.history_tab = ttk.Frame(self.page_host, style="Surface.TFrame", padding=2)
        self.settings_tab = ttk.Frame(self.page_host, style="Surface.TFrame", padding=2)

        self._build_work_tab()
        self._build_archive_tab()
        self._build_history_tab()
        self._build_settings_tab()
        self._build_dashboard()

        footer = ttk.Frame(self.main, style="Surface.TFrame")
        footer.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.footer_status = ttk.Label(footer, textvariable=self.status, style="StatusMuted.TLabel", wraplength=700)
        self.footer_status.pack(side="left", fill="x", expand=True)
        self.cancel_button = ttk.Button(footer, text="Annuler", command=self._cancel, state="disabled")
        self.root.bind_all("<Control-o>", self._shortcut_open_archive)
        self.root.bind_all("<Control-Return>", self._shortcut_start)
        self.root.bind_all("<Escape>", self._shortcut_cancel)
        self.root.bind_all("<MouseWheel>", self._on_mousewheel)
        self.root.bind_all("<Button-4>", lambda event: self._on_mousewheel(event, -1))
        self.root.bind_all("<Button-5>", lambda event: self._on_mousewheel(event, 1))
        self.root.bind("<Configure>", self._adapt_shell, add="+")

    def _on_compact_nav(self, _event=None) -> None:
        pages = {
            "Accueil": "dashboard", "Compresser": "compress", "Extraire": "extract",
            "Archives 7z": "archive", "Historique": "history", "Paramètres": "settings",
        }
        self._show_page(pages.get(self.nav_choice.get(), "dashboard"))

    def _adapt_shell(self, _event=None) -> None:
        """Réduit la navigation en menu lorsque la fenêtre devient étroite."""
        width = max(1, self.root.winfo_width())
        compact = width < 820
        if compact != getattr(self, "_shell_compact", None):
            self._shell_compact = compact
            if compact:
                self.sidebar.grid_remove()
                self.shell.columnconfigure(0, weight=1)
                self.shell.columnconfigure(1, weight=0)
                self.main.grid_configure(row=0, column=0)
                self.compact_nav.grid()
            else:
                self.sidebar.grid(row=0, column=0, sticky="ns")
                self.shell.columnconfigure(0, weight=0)
                self.shell.columnconfigure(1, weight=1)
                self.main.grid_configure(row=0, column=1)
                self.compact_nav.grid_remove()
        if compact:
            self.main.configure(padding=(8, 10, 8, 8) if width < 580 else (12, 14, 12, 10))
        else:
            self.main.configure(padding=(SPACE["xl"], 18, SPACE["xl"], SPACE["md"]))
        self.page_subtitle.configure(wraplength=max(220, width - (36 if compact else 245)))
        self.footer_status.configure(wraplength=max(180, width - (110 if compact else 300)))
        if hasattr(self, "dashboard_tab"):
            self._adapt_dashboard(width)
        if hasattr(self, "archive_tab"):
            self._adapt_archive_layout(self.archive_tab)
        if hasattr(self, "settings_tab"):
            self._adapt_settings_layout(self.settings_tab)

    def _on_mousewheel(self, event, direction=None):
        if self.current_page == "settings":
            target = self.settings_canvas
        elif self.current_page in ("compress", "extract"):
            widget_path = str(event.widget)
            tree_path = str(self.source_tree)
            if widget_path == tree_path or widget_path.startswith(tree_path + "."):
                target = self.source_tree
            else:
                target = self.work_canvas
        else:
            return None
        if direction is None:
            direction = -1 if event.delta > 0 else 1
        if target is self.source_tree:
            target.yview_scroll(direction, "units")
        else:
            target.yview_scroll(direction * 3, "units")
        return "break"

    def _build_dashboard(self) -> None:
        tab = self.dashboard_tab
        tab.columnconfigure(0, weight=1)
        self.dashboard_chooser = ttk.Frame(tab, style="Surface.TFrame", padding=16)
        self.dashboard_chooser.grid(row=0, column=0, sticky="ew")
        self.dashboard_chooser.columnconfigure(0, weight=1, uniform="main-action")
        self.dashboard_chooser.columnconfigure(1, weight=1, uniform="main-action")
        ttk.Label(self.dashboard_chooser, text="Que souhaitez-vous faire ?", style="Section.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 18))

        self.dashboard_compress = ttk.Frame(self.dashboard_chooser, style="Card.TFrame", padding=14)
        self.dashboard_compress.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        ttk.Label(self.dashboard_compress, text="Réduire la taille de fichiers", style="Section.TLabel").pack(anchor="w")
        self.dashboard_compress_hint = ttk.Label(self.dashboard_compress, text="Choisissez vos fichiers et le format de compression.",
                  style="Hint.TLabel", wraplength=310)
        self.dashboard_compress_hint.pack(anchor="w", pady=(6, 12))
        ttk.Button(self.dashboard_compress, text="Compresser des fichiers",
                   command=lambda: self._show_page("compress")).pack(anchor="w")

        self.dashboard_extract = ttk.Frame(self.dashboard_chooser, style="Card.TFrame", padding=14)
        self.dashboard_extract.grid(row=1, column=1, sticky="nsew", padx=(6, 0))
        ttk.Label(self.dashboard_extract, text="Récupérer des fichiers", style="Section.TLabel").pack(anchor="w")
        self.dashboard_extract_hint = ttk.Label(self.dashboard_extract, text="Ouvrez un fichier compressé ou une archive 7z.",
                  style="Hint.TLabel", wraplength=310)
        self.dashboard_extract_hint.pack(anchor="w", pady=(6, 12))
        ttk.Button(self.dashboard_extract, text="Extraire des fichiers",
                   command=lambda: self._show_page("extract")).pack(anchor="w")

        self.dashboard_note = ttk.Label(self.dashboard_chooser, text="Les fichiers restent sur votre appareil.", style="Hint.TLabel")
        self.dashboard_note.grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(16, 0))
        tab.bind("<Configure>", lambda event: self._adapt_dashboard(event.width), add="+")

    def _adapt_dashboard(self, width: int) -> None:
        compact = width < 660
        self.dashboard_chooser.configure(padding=12 if compact else 16)
        self.dashboard_compress.grid_configure(row=1, column=0, padx=(0, 0 if compact else 6), pady=(0, 8 if compact else 0))
        self.dashboard_extract.grid_configure(
            row=2 if compact else 1, column=0 if compact else 1,
            padx=(0, 0) if compact else (6, 0), pady=0,
        )
        self.dashboard_chooser.columnconfigure(0, weight=1, uniform="main-action")
        self.dashboard_chooser.columnconfigure(1, weight=0 if compact else 1, uniform="main-action")
        self.dashboard_note.grid_configure(row=3 if compact else 2, column=0, columnspan=2, pady=(10, 0))
        wraplength = max(220, width - 64) if compact else max(250, width // 2 - 48)
        self.dashboard_compress_hint.configure(wraplength=wraplength)
        self.dashboard_extract_hint.configure(wraplength=wraplength)

    def _show_page(self, page: str) -> None:
        frames = {
            "dashboard": self.dashboard_tab, "compress": self.work_tab, "extract": self.work_tab,
            "archive": self.archive_tab, "history": self.history_tab, "settings": self.settings_tab,
        }
        titles = {
            "dashboard": ("Accueil", "Compressez ou retrouvez vos fichiers en quelques clics."),
            "compress": ("Compresser", "Choisissez vos fichiers, puis cliquez sur Compresser."),
            "extract": ("Extraire", "Choisissez un fichier compressé, puis cliquez sur Extraire."),
            "archive": ("Archives 7z", "Parcourez une archive et choisissez les fichiers à extraire."),
            "history": ("Historique", "Consultez les opérations enregistrées sur cet appareil."),
            "settings": ("Paramètres", "Réglez l’apparence et les limites de sécurité de l’application."),
        }
        if page not in frames:
            return
        for frame in set(frames.values()):
            frame.grid_remove()
        frames[page].grid(row=0, column=0, sticky="nsew")
        self.current_page = page
        self.page_title.configure(text=titles[page][0])
        self.page_subtitle.configure(text=titles[page][1])
        compact_titles = {
            "dashboard": "Accueil", "compress": "Compresser", "extract": "Extraire",
            "archive": "Archives 7z", "history": "Historique", "settings": "Paramètres",
        }
        self.nav_choice.set(compact_titles[page])
        if page in ("compress", "extract"):
            next_mode = "Compresser" if page == "compress" else "Extraire"
            if self.mode.get() != next_mode:
                self._clear_sources()
                self.output.set("")
            self.mode.set(next_mode)
            if page == "compress" and self.format.get() == "Automatique":
                self.format.set(str(self.settings["format"]))
            if page == "extract":
                self.format.set("Automatique")
            self._refresh_mode()
        for key, button in self.nav_buttons.items():
            active = key == page or (key in ("compress", "extract") and page == key)
            button.configure(style="NavActive.TButton" if active else "Nav.TButton")

    def _toggle_advanced(self) -> None:
        self.advanced_open = not self.advanced_open
        if self.advanced_open:
            self.advanced_frame.grid()
            self.advanced_toggle.configure(text="Masquer les options")
        else:
            self.advanced_frame.grid_remove()
            self.advanced_toggle.configure(text="Plus d’options")

    def _apply_theme(self) -> None:
        self.palette = apply_theme(self.root, self.theme_mode.get())
        if hasattr(self, "work_canvas"):
            self.work_canvas.configure(background=self.palette["surface"])
        if hasattr(self, "settings_canvas"):
            self.settings_canvas.configure(background=self.palette["surface"])
        self.resolved_theme = resolve_theme(self.theme_mode.get())
        if self.theme_mode.get() == "system":
            self._system_theme_check_id = self.root.after(3000, self._check_system_theme)
        else:
            self._system_theme_check_id = None
        if hasattr(self, "status"):
            self._refresh_status_style()

    def _refresh_status_style(self, *_args) -> None:
        message = self.status.get().casefold()
        if any(word in message for word in ("échec", "échoué", "impossible", "erreur")):
            style = "StatusError.TLabel"
        elif any(word in message for word in ("annul", "demande", "attention")):
            style = "StatusWarning.TLabel"
        elif any(word in message for word in ("en cours", "chargement", "lecture")):
            style = "StatusActive.TLabel"
        elif any(word in message for word in ("terminé", "réussi", "prêt", "chargée", "copié")):
            style = "StatusSuccess.TLabel"
        else:
            style = "StatusMuted.TLabel"
        for label in (getattr(self, "footer_status", None), getattr(self, "activity_status", None)):
            if label:
                label.configure(style=style)

    def _check_system_theme(self) -> None:
        if self.theme_mode.get() != "system":
            return
        if resolve_theme("system") != self.resolved_theme:
            self._apply_theme()
        else:
            self._system_theme_check_id = self.root.after(3000, self._check_system_theme)

    def _on_theme_selected(self, _event=None) -> None:
        self.theme_mode.set(THEME_IDS.get(self.settings_theme.get(), "system"))
        self.settings["theme"] = self.theme_mode.get()
        self._apply_theme()
        try:
            save_settings({"theme": self.theme_mode.get()})
        except OSError as exc:
            self._dialog("error", "Thème non enregistré", f"Le thème est appliqué, mais sa mémorisation a échoué.\n{exc}")

    def _build_work_tab(self) -> None:
        """Assemble l’écran de compression et ses zones défilantes."""
        self.work_tab.columnconfigure(0, weight=1)
        self.work_tab.rowconfigure(0, weight=1)
        self.work_canvas = tk.Canvas(
            self.work_tab,
            highlightthickness=0,
            borderwidth=0,
            background=self.palette["surface"],
        )
        self.work_canvas.grid(row=0, column=0, sticky="nsew")
        self.work_scrollbar = ttk.Scrollbar(
            self.work_tab,
            orient="vertical",
            command=self.work_canvas.yview,
        )
        self.work_scrollbar.grid(row=0, column=1, sticky="ns")
        self.work_canvas.configure(yscrollcommand=self.work_scrollbar.set)
        self.work_content = ttk.Frame(self.work_canvas, style="Surface.TFrame", padding=2)
        self.work_canvas_window = self.work_canvas.create_window((0, 0), window=self.work_content, anchor="nw")
        self.work_content.bind("<Configure>", self._update_work_scroll, add="+")
        self.work_canvas.bind("<Configure>", self._resize_work_canvas, add="+")
        self.work_content.columnconfigure(0, weight=1)
        self.work_content.rowconfigure(1, weight=1)

        self._build_compression_controls(self.work_content)
        self._build_source_picker(self.work_content)
        self._build_operation_actions(self.work_content)

    def _build_compression_controls(self, parent: ttk.Frame) -> None:
        """Crée les réglages de format et les options de compression."""
        self.controls = ttk.Frame(parent, style="Surface.TFrame", padding=14)
        self.controls.grid(row=0, column=0, sticky="ew")
        self.controls.columnconfigure(1, weight=1)
        ttk.Label(self.controls, text="Format", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 12), pady=5
        )
        self.format_box = ttk.Combobox(
            self.controls,
            textvariable=self.format,
            values=FORMATS,
            state="readonly",
            width=15,
        )
        self.format_box.grid(row=0, column=1, sticky="w", pady=5)
        self.format_box.bind("<<ComboboxSelected>>", lambda _event: self._refresh_mode())
        self.format_description = ttk.Label(
            self.controls, text="", style="Hint.TLabel", wraplength=650
        )
        self.format_description.grid(row=1, column=0, columnspan=3, sticky="w", pady=(5, 0))
        self.advanced_open = False
        self.advanced_toggle = ttk.Button(
            self.controls,
            text="Plus d’options",
            command=self._toggle_advanced,
        )
        self.advanced_toggle.grid(row=0, column=2, sticky="e", padx=(12, 0), pady=5)
        self.advanced_frame = ttk.Frame(self.controls, style="Surface.TFrame")
        self.advanced_frame.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        self.advanced_frame.columnconfigure(0, weight=1, uniform="advanced")
        self.advanced_frame.columnconfigure(1, weight=1, uniform="advanced")
        self.level_label = ttk.Label(self.advanced_frame, text="Intensité", style="Surface.TLabel")
        self.level_label.grid(row=0, column=0, sticky="w", padx=(0, 10), pady=(0, 4))
        self.level_box = ttk.Combobox(
            self.advanced_frame,
            textvariable=self.level,
            values=COMPRESSION_LEVELS,
            state="readonly",
            width=13,
        )
        self.level_box.grid(row=1, column=0, sticky="ew", padx=(0, 12), pady=(0, 10))
        self.dictionary_label = ttk.Label(self.advanced_frame, text="Dictionnaire (Mo)", style="Surface.TLabel")
        self.dictionary_label.grid(row=0, column=1, sticky="w", padx=(0, 8), pady=(0, 4))
        self.dictionary_choices = ttk.Frame(self.advanced_frame, style="Surface.TFrame")
        self.dictionary_choices.grid(row=1, column=1, sticky="w", pady=(0, 10))
        for column, value in enumerate(DICTIONARY_MIB_OPTIONS):
            button = ttk.Button(
                self.dictionary_choices,
                text=str(value),
                width=4,
                style="Primary.TButton" if value == self.dictionary_mib.get() else "TButton",
                command=lambda choice=value: self._set_dictionary_choice(choice),
            )
            button.grid(row=0, column=column, padx=(0 if column == 0 else 3, 0), sticky="ew")
            self.dictionary_choice_buttons[value] = button
        self.password_label = ttk.Label(self.advanced_frame, text="Mot de passe 7z", style="Surface.TLabel")
        self.password_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 4))
        self.password_entry = ttk.Entry(
            self.advanced_frame,
            textvariable=self.password,
            show="•",
            width=19,
        )
        self.password_entry.grid(row=3, column=0, sticky="ew", padx=(0, 12))
        self.show_password_check = ttk.Checkbutton(
            self.advanced_frame,
            text="Afficher",
            variable=self.show_password,
            command=self._toggle_password,
        )
        self.show_password_check.grid(row=3, column=1, sticky="w")
        self.advanced_frame.grid_remove()

    def _build_source_picker(self, parent: ttk.Frame) -> None:
        """Crée la zone d’ajout des fichiers, la liste et la destination."""
        files = ttk.Frame(parent, style="Surface.TFrame", padding=16)
        files.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        files.columnconfigure(0, weight=1)
        files.rowconfigure(3, weight=1)
        self.sources_heading = ttk.Label(files, text="Fichiers à traiter", style="Section.TLabel")
        self.sources_heading.grid(row=0, column=0, sticky="w", pady=(0, 9))
        self.source_count = tk.StringVar(value="Aucun fichier sélectionné")
        ttk.Label(files, textvariable=self.source_count, style="Hint.TLabel").grid(
            row=0, column=1, sticky="e", pady=(0, 9))
        self.drop_zone = ttk.Frame(files, style="Drop.TFrame", padding=(SPACE["lg"], SPACE["md"]))
        self.drop_zone.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        self.drop_zone.columnconfigure(0, weight=1)
        self.drop_title = ttk.Label(
            self.drop_zone,
            text="Ajoutez un ou plusieurs fichiers",
            style="Drop.TLabel",
            font=FONTS["strong"],
        )
        self.drop_title.grid(row=0, column=0, sticky="w")
        self.drop_hint = ttk.Label(
            self.drop_zone,
            text="Vous pouvez aussi les déposer ici.",
            style="Drop.TLabel",
            font=FONTS["small"],
        )
        self.drop_hint.grid(row=1, column=0, sticky="w", pady=(3, 0))
        self.add_files_button = ttk.Button(
            self.drop_zone,
            text="Choisir des fichiers…",
            style="Primary.TButton",
            command=self._add_files,
        )
        self.add_files_button.grid(row=0, column=1, rowspan=2, sticky="e", padx=(16, 0))

        self.source_buttons = ttk.Frame(files, style="Surface.TFrame")
        self.source_buttons.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.source_buttons.columnconfigure(0, weight=1)
        self.source_buttons.columnconfigure(1, weight=0)
        self.add_folder_button = ttk.Button(self.source_buttons, text="Choisir un dossier", command=self._add_folder)
        self.add_folder_button.grid(row=0, column=0, sticky="w")
        self.clear_sources_button = ttk.Button(self.source_buttons, text="Vider la liste", command=self._clear_sources)
        self.clear_sources_button.grid(row=0, column=1, sticky="e")
        self.add_folder_button.grid_remove()

        source_columns = ("name", "location", "size")
        self.source_tree = ttk.Treeview(files, columns=source_columns, show="headings",
                                        selectmode="extended", height=5)
        self.source_tree.heading("name", text="Fichier")
        self.source_tree.heading("location", text="Emplacement")
        self.source_tree.heading("size", text="Taille")
        self.source_tree.column("name", width=180, minwidth=130, anchor="w")
        self.source_tree.column("location", width=280, minwidth=160, anchor="w")
        self.source_tree.column("size", width=90, minwidth=75, anchor="e", stretch=False)
        self.source_tree.grid(row=3, column=0, sticky="nsew")
        self.source_tree.bind("<Delete>", self._remove_sources)
        self.source_empty_label = ttk.Label(files, text="Les fichiers sélectionnés apparaîtront ici.", style="Hint.TLabel")
        self.source_empty_label.grid(row=3, column=0)
        source_scroll = ttk.Scrollbar(files, orient="vertical", command=self.source_tree.yview)
        source_scroll.grid(row=3, column=0, sticky="nse")
        self.source_tree.configure(yscrollcommand=source_scroll.set)
        source_xscroll = ttk.Scrollbar(files, orient="horizontal", command=self.source_tree.xview)
        source_xscroll.grid(row=4, column=0, columnspan=2, sticky="ew")
        self.source_tree.configure(xscrollcommand=source_xscroll.set)

        self.destination = ttk.Frame(files, style="Surface.TFrame")
        self.destination.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.destination.columnconfigure(1, weight=1)
        self.destination_label = ttk.Label(self.destination, text="Destination", style="Section.TLabel")
        self.destination_label.grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.output_entry = ttk.Entry(self.destination, textvariable=self.output)
        self.output_entry.grid(row=0, column=1, sticky="ew")
        self.output_button = ttk.Button(self.destination, text="Choisir…", command=self._choose_output)
        self.output_button.grid(row=0, column=2, padx=(8, 0))
        self.destination_hint = ttk.Label(self.destination, text="Laissez vide pour enregistrer à côté des fichiers d’origine.", style="Hint.TLabel")
        self.destination_hint.grid(row=1, column=1, columnspan=2, sticky="w", pady=(5, 0))
        self._enable_drag_drop()

    def _build_operation_actions(self, parent: ttk.Frame) -> None:
        """Crée le bouton de lancement, la progression et le résumé de résultat."""
        actions = ttk.Frame(parent)
        actions.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        self.run_button = ttk.Button(actions, text="Compresser", style="Primary.TButton", command=self._start)
        self.run_button.pack(side="right")
        self.progressbar = ttk.Progressbar(actions, mode="determinate", maximum=100, variable=self.progress_percent, length=260)
        self.progressbar.pack(side="right", padx=(0, 12), fill="x")
        self.progress_label = ttk.Label(actions, text="0 %")
        self.progress_label.pack(side="right", padx=(0, 8))

        self.operation_report = ttk.Frame(parent, style="Surface.TFrame", padding=(SPACE["md"], 10))
        self.operation_report.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        self.operation_report_label = ttk.Label(
            self.operation_report, textvariable=self.operation_summary,
            style="Hint.TLabel", wraplength=900,
        )
        self.operation_report_label.pack(anchor="w", fill="x")
        self.operation_report.grid_remove()
    def _adapt_work_layout(self, event=None) -> None:
        """Réorganise les réglages selon la largeur disponible."""
        width = max(1, self.work_canvas.winfo_width())
        compact = width < 650
        narrow = width < 460
        layout = (compact, narrow)
        self._work_layout = layout

        if compact:
            self.format_box.grid_configure(row=1, column=0, columnspan=2, sticky="ew", padx=0)
            self.advanced_toggle.grid_configure(row=0, column=1, columnspan=1, sticky="e")
            self.format_description.grid_configure(row=2, column=0, columnspan=2)
            self.advanced_frame.grid_configure(row=3, column=0, columnspan=2)
            self.controls.columnconfigure(0, weight=1)
            self.controls.columnconfigure(1, weight=0)
        else:
            self.format_box.grid_configure(row=0, column=1, columnspan=1, sticky="w", padx=0)
            self.advanced_toggle.grid_configure(row=0, column=2, columnspan=1, sticky="e")
            self.format_description.grid_configure(row=1, column=0, columnspan=3)
            self.advanced_frame.grid_configure(row=2, column=0, columnspan=3)
            self.controls.columnconfigure(0, weight=0)
            self.controls.columnconfigure(1, weight=1)

        if narrow:
            self.dictionary_label.grid_configure(row=2, column=0, columnspan=1, pady=(0, 4))
            self.dictionary_choices.grid_configure(row=3, column=0, columnspan=1, padx=0)
            self.password_label.grid_configure(row=4, column=0, columnspan=1)
            self.password_entry.grid_configure(row=5, column=0, columnspan=1, padx=0, pady=(0, 6))
            self.show_password_check.grid_configure(row=6, column=0, columnspan=1)
            self.advanced_frame.columnconfigure(0, weight=1)
            self.advanced_frame.columnconfigure(1, weight=0)
        else:
            self.dictionary_label.grid_configure(row=0, column=1, columnspan=1, pady=(0, 4))
            self.dictionary_choices.grid_configure(row=1, column=1, columnspan=1, padx=0)
            self.password_label.grid_configure(row=2, column=0, columnspan=2)
            self.password_entry.grid_configure(row=3, column=0, columnspan=1, padx=(0, 12), pady=0)
            self.show_password_check.grid_configure(row=3, column=1, columnspan=1)
            self.advanced_frame.columnconfigure(0, weight=1)
            self.advanced_frame.columnconfigure(1, weight=1)

        if width < 500:
            self.add_files_button.grid_configure(row=2, column=0, rowspan=1, sticky="w", padx=0, pady=(10, 0))
        else:
            self.add_files_button.grid_configure(row=0, column=1, rowspan=2, sticky="e", padx=(16, 0), pady=0)

        if compact:
            self.destination_label.grid_configure(row=0, column=0, columnspan=2, padx=0, pady=(0, 5))
            self.output_entry.grid_configure(row=1, column=0, columnspan=1, sticky="ew")
            self.output_button.grid_configure(row=1, column=1, columnspan=1, padx=(8, 0))
            self.destination_hint.grid_configure(row=2, column=0, columnspan=2, padx=0, pady=(5, 0))
            self.destination.columnconfigure(0, weight=1)
            self.destination.columnconfigure(1, weight=0)
            self.destination.columnconfigure(2, weight=0)
        else:
            self.destination_label.grid_configure(row=0, column=0, columnspan=1, padx=(0, 10), pady=0)
            self.output_entry.grid_configure(row=0, column=1, columnspan=1, sticky="ew")
            self.output_button.grid_configure(row=0, column=2, columnspan=1, padx=(8, 0))
            self.destination_hint.grid_configure(row=1, column=1, columnspan=2, padx=0, pady=(5, 0))
            self.destination.columnconfigure(0, weight=0)
            self.destination.columnconfigure(1, weight=1)
            self.destination.columnconfigure(2, weight=0)

        self.format_description.configure(wraplength=max(240, width - 56))
        self.destination_hint.configure(wraplength=max(240, width - 56))
        self.operation_report_label.configure(wraplength=max(240, width - 56))
        self.progressbar.configure(length=max(90, min(260, width // 3)))
        self.source_tree.column("name", width=max(100, int((width - 70) * 0.34)))
        self.source_tree.column("location", width=max(130, int((width - 70) * 0.48)))
        self.source_tree.column("size", width=max(75, int((width - 70) * 0.18)))

    def _update_work_scroll(self, _event=None) -> None:
        height = max(self.work_canvas.winfo_height(), self.work_content.winfo_reqheight())
        self.work_canvas.itemconfigure(self.work_canvas_window, height=height)
        self.work_canvas.configure(scrollregion=self.work_canvas.bbox("all"))
        self.root.after_idle(self._sync_work_scrollbar)

    def _resize_work_canvas(self, event) -> None:
        height = max(event.height, self.work_content.winfo_reqheight())
        self.work_canvas.itemconfigure(self.work_canvas_window, width=event.width, height=height)
        self._adapt_work_layout()

    def _sync_work_scrollbar(self) -> None:
        bounds = self.work_canvas.bbox("all")
        height = bounds[3] - bounds[1] if bounds else 0
        if height > self.work_canvas.winfo_height() + 2:
            self.work_scrollbar.grid(row=0, column=1, sticky="ns")
        else:
            self.work_scrollbar.grid_remove()

    def _enable_drag_drop(self) -> None:
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD
            TkinterDnD.require(self.root)
            for widget in (self.drop_zone, self.source_tree):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)
            self.drop_zone.dnd_bind("<<DropEnter>>", self._on_drop_enter)
            self.drop_zone.dnd_bind("<<DropLeave>>", self._on_drop_leave)
            self.drop_enabled = True
        except (ImportError, RuntimeError, tk.TclError, AttributeError):
            self.drop_enabled = False
            self.drop_hint.configure(text="Le glisser-déposer n’est pas disponible ici. Utilisez le bouton pour choisir vos fichiers.")

    def _on_drop(self, event) -> str:
        self._set_drop_highlight(True)
        self.root.after(650, lambda: self._set_drop_highlight(False))
        try:
            paths = [Path(value).expanduser() for value in self.root.tk.splitlist(event.data)]
            if not paths or any(not path.exists() for path in paths):
                self._dialog("warning", "Fichiers indisponibles", "Certains éléments déposés sont introuvables.")
                return "break"
            folders = [path for path in paths if path.is_dir()]
            if folders and (self.mode.get() != "Compresser" or self.format.get() != "7z"):
                self._dialog("warning", "Dossier non pris en charge",
                             "Les dossiers peuvent être ajoutés uniquement pour créer une archive 7z.")
                return "break"
            self._append_sources(paths)
        except (OSError, tk.TclError, ValueError) as exc:
            self._dialog("error", "Dépôt impossible", str(exc))
        return "copy"

    def _on_drop_enter(self, _event=None) -> str:
        self._set_drop_highlight(True)
        return "copy"

    def _on_drop_leave(self, _event=None) -> str:
        self._set_drop_highlight(False)
        return "copy"

    def _set_drop_highlight(self, active: bool) -> None:
        if not getattr(self, "drop_enabled", False):
            return
        self.drop_zone.configure(style="DropActive.TFrame" if active else "Drop.TFrame")
        for child in self.drop_zone.winfo_children():
            if isinstance(child, ttk.Label):
                child.configure(style="DropActive.TLabel" if active else "Drop.TLabel")

    def _build_archive_tab(self) -> None:
        tab = self.archive_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        self.archive_toolbar = ttk.Frame(tab, style="Surface.TFrame", padding=10)
        self.archive_toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.archive_open_button = ttk.Button(self.archive_toolbar, text="Ouvrir une archive 7z…", style="Primary.TButton", command=self._open_archive)
        self.archive_open_button.grid(row=0, column=0, sticky="w")
        self.archive_password_label = ttk.Label(self.archive_toolbar, text="Mot de passe", style="Surface.TLabel")
        self.archive_password_label.grid(row=0, column=1, sticky="w", padx=(12, 5))
        self.archive_password_entry = ttk.Entry(self.archive_toolbar, textvariable=self.archive_password, show="•", width=20)
        self.archive_password_entry.grid(row=0, column=2, sticky="ew")
        self.archive_search_label = ttk.Label(self.archive_toolbar, text="Rechercher", style="Surface.TLabel")
        self.archive_search_label.grid(row=0, column=3, sticky="w", padx=(12, 5))
        self.archive_search_entry = ttk.Entry(self.archive_toolbar, textvariable=self.archive_search, width=20)
        self.archive_search_entry.grid(row=0, column=4, sticky="ew")
        self.archive_search_entry.bind("<KeyRelease>", lambda _event: self._filter_archive())
        self.archive_toolbar.columnconfigure(2, weight=1)
        self.archive_toolbar.columnconfigure(4, weight=1)

        columns = ("extension", "size", "packed", "modified", "path")
        self.archive_tree = ttk.Treeview(tab, columns=columns, show="tree headings", selectmode="extended")
        self.archive_tree.heading("#0", text="Nom", command=lambda: self._sort_archive("name"))
        self.archive_tree.column("#0", width=195, minwidth=135, anchor="w")
        specs = (("extension", "Extension", 85, "w"), ("size", "Taille", 105, "e"), ("packed", "Compressé", 105, "e"), ("modified", "Date disponible", 155, "w"), ("path", "Chemin dans l’archive", 270, "w"))
        for col, title, width, anchor in specs:
            self.archive_tree.heading(col, text=title, command=lambda selected=col: self._sort_archive(selected))
            self.archive_tree.column(col, width=width, anchor=anchor)
        self.archive_tree.grid(row=1, column=0, sticky="nsew")
        self.archive_tree.bind("<Button-3>", self._archive_context_menu)
        self.archive_tree.bind("<Shift-F10>", self._archive_context_menu)
        self.archive_empty_text = tk.StringVar(value="Ouvrez une archive 7z pour afficher son contenu.")
        self.archive_empty_label = ttk.Label(tab, textvariable=self.archive_empty_text, style="Muted.TLabel")
        self.archive_empty_label.grid(row=1, column=0)
        scroll = ttk.Scrollbar(tab, orient="vertical", command=self.archive_tree.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.archive_tree.configure(yscrollcommand=scroll.set)
        horizontal = ttk.Scrollbar(tab, orient="horizontal", command=self.archive_tree.xview)
        horizontal.grid(row=2, column=0, sticky="ew")
        self.archive_tree.configure(xscrollcommand=horizontal.set)

        self.archive_bottom = ttk.Frame(tab, style="Surface.TFrame", padding=10)
        bottom = self.archive_bottom
        bottom.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.archive_destination_label = ttk.Label(bottom, text="Dossier d’extraction", style="Surface.TLabel")
        self.archive_destination_label.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.archive_output_entry = ttk.Entry(bottom, textvariable=self.archive_output)
        self.archive_output_entry.grid(row=0, column=1, sticky="ew")
        self.archive_browse_button = ttk.Button(bottom, text="Parcourir…", command=self._choose_archive_output)
        self.archive_browse_button.grid(row=0, column=2, padx=(8, 0))
        self.archive_extract_button = ttk.Button(bottom, text="Extraire la sélection", style="Primary.TButton", command=self._extract_selected)
        self.archive_extract_button.grid(row=0, column=3, padx=(8, 0))
        bottom.columnconfigure(1, weight=1)
        self.archive_summary = ttk.Label(tab, text="Aucune archive ouverte.")
        self.archive_summary.grid(row=4, column=0, sticky="w", pady=(8, 0))
        tab.bind("<Configure>", self._adapt_archive_layout, add="+")

    def _adapt_archive_layout(self, _event=None) -> None:
        width = self.archive_tab.winfo_width()
        compact = width < 740
        if compact:
            self.archive_open_button.grid_configure(row=0, column=0, columnspan=2, sticky="ew", padx=0)
            self.archive_password_label.grid_configure(row=1, column=0, padx=(0, 6), pady=(8, 0))
            self.archive_password_entry.grid_configure(row=1, column=1, sticky="ew", pady=(8, 0))
            self.archive_search_label.grid_configure(row=2, column=0, padx=(0, 6), pady=(8, 0))
            self.archive_search_entry.grid_configure(row=2, column=1, sticky="ew", pady=(8, 0))
            self.archive_toolbar.columnconfigure(0, weight=0)
            self.archive_toolbar.columnconfigure(1, weight=1)
            self.archive_toolbar.columnconfigure(2, weight=0)
            self.archive_toolbar.columnconfigure(3, weight=0)
            self.archive_toolbar.columnconfigure(4, weight=0)
            self.archive_destination_label.grid_configure(row=0, column=0, columnspan=2, padx=0, pady=(0, 5))
            self.archive_output_entry.grid_configure(row=1, column=0, columnspan=2, sticky="ew")
            self.archive_browse_button.grid_configure(row=2, column=0, sticky="w", padx=0, pady=(6, 0))
            self.archive_extract_button.grid_configure(row=2, column=1, sticky="e", padx=0, pady=(6, 0))
            self.archive_bottom.columnconfigure(1, weight=1)
        else:
            self.archive_open_button.grid_configure(row=0, column=0, columnspan=1, sticky="w")
            self.archive_password_label.grid_configure(row=0, column=1, padx=(12, 5), pady=0)
            self.archive_password_entry.grid_configure(row=0, column=2, sticky="ew", pady=0)
            self.archive_search_label.grid_configure(row=0, column=3, padx=(12, 5), pady=0)
            self.archive_search_entry.grid_configure(row=0, column=4, sticky="ew", pady=0)
            self.archive_toolbar.columnconfigure(1, weight=0)
            self.archive_toolbar.columnconfigure(2, weight=1)
            self.archive_toolbar.columnconfigure(4, weight=1)
            self.archive_destination_label.grid_configure(row=0, column=0, columnspan=1, padx=(0, 8), pady=0)
            self.archive_output_entry.grid_configure(row=0, column=1, columnspan=1, sticky="ew")
            self.archive_browse_button.grid_configure(row=0, column=2, sticky="w", padx=(8, 0), pady=0)
            self.archive_extract_button.grid_configure(row=0, column=3, sticky="e", padx=(8, 0), pady=0)
            self.archive_bottom.columnconfigure(1, weight=1)
        self.archive_summary.configure(wraplength=max(220, width - 24))

    def _build_history_tab(self) -> None:
        tab = self.history_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        columns = ("when", "action", "format", "source", "sizes", "duration", "status")
        self.history_tree = ttk.Treeview(tab, columns=columns, show="headings")
        specs = (("when", "Date", 160), ("action", "Action", 100), ("format", "Format", 75), ("source", "Source", 270), ("sizes", "Tailles", 160), ("duration", "Durée", 80), ("status", "Résultat", 120))
        for col, title, width in specs:
            self.history_tree.heading(col, text=title)
            self.history_tree.column(col, width=width, anchor="w")
        self.history_tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(tab, orient="vertical", command=self.history_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.history_tree.configure(yscrollcommand=scroll.set)
        horizontal = ttk.Scrollbar(tab, orient="horizontal", command=self.history_tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.history_tree.configure(xscrollcommand=horizontal.set)
        ttk.Button(tab, text="Effacer l’historique", command=self._clear_history).grid(row=2, column=0, sticky="e", pady=(10, 0))

    def _build_settings_tab(self) -> None:
        tab = self.settings_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        self.settings_canvas = tk.Canvas(tab, highlightthickness=0, borderwidth=0, background=self.palette["surface"])
        self.settings_canvas.grid(row=0, column=0, sticky="nsew")
        settings_scroll = ttk.Scrollbar(tab, orient="vertical", command=self.settings_canvas.yview)
        settings_scroll.grid(row=0, column=1, sticky="ns")
        self.settings_canvas.configure(yscrollcommand=settings_scroll.set)
        self.settings_content = ttk.Frame(self.settings_canvas, style="Surface.TFrame")
        self.settings_window = self.settings_canvas.create_window((0, 0), window=self.settings_content, anchor="nw")
        self.settings_content.bind(
            "<Configure>", lambda _event: self.settings_canvas.configure(scrollregion=self.settings_canvas.bbox("all"))
        )
        self.settings_canvas.bind(
            "<Configure>", lambda event: self.settings_canvas.itemconfigure(self.settings_window, width=event.width)
        )
        panel = ttk.Frame(self.settings_content, style="Surface.TFrame", padding=14)
        self.settings_panel = panel
        panel.pack(fill="x", anchor="n")
        panel.columnconfigure(0, weight=1)
        panel.columnconfigure(1, weight=0)
        ttk.Label(panel, text="Apparence et valeurs par défaut", style="Section.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        ttk.Label(panel, text="Thème de l’application", style="Surface.TLabel").grid(row=1, column=0, sticky="w", pady=6)
        theme_box = ttk.Combobox(panel, textvariable=self.settings_theme, values=tuple(THEME_IDS), state="readonly", width=14)
        theme_box.grid(row=1, column=1, sticky="w", pady=6)
        theme_box.bind("<<ComboboxSelected>>", self._on_theme_selected)
        ttk.Label(panel, text="Le mode automatique suit le thème Windows lorsqu’il est disponible. Les sélecteurs de fichiers restent gérés par Windows.", style="Hint.TLabel", wraplength=700).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Label(panel, text="Format préféré", style="Surface.TLabel").grid(row=3, column=0, sticky="w", pady=6)
        ttk.Combobox(panel, textvariable=self.settings_default_format, values=FORMATS, state="readonly", width=14).grid(row=3, column=1, sticky="w", pady=6)
        ttk.Label(panel, text="Intensité par défaut", style="Surface.TLabel").grid(row=4, column=0, sticky="w", pady=6)
        ttk.Combobox(panel, textvariable=self.settings_default_level, values=COMPRESSION_LEVELS, state="readonly", width=13).grid(row=4, column=1, sticky="w", pady=6)
        ttk.Label(panel, text="Limite d’éléments par archive", style="Surface.TLabel").grid(row=5, column=0, sticky="w", pady=6)
        ttk.Spinbox(panel, from_=1, to=1000000, textvariable=self.settings_max_files, width=12).grid(row=5, column=1, sticky="w", pady=6)
        ttk.Label(panel, text="Taille décompressée maximale (Mo)", style="Surface.TLabel").grid(row=6, column=0, sticky="w", pady=6)
        ttk.Spinbox(panel, from_=1, to=1048576, textvariable=self.settings_max_mib, width=12).grid(row=6, column=1, sticky="w", pady=6)
        ttk.Button(panel, text="Enregistrer les paramètres", style="Primary.TButton", command=self._save_settings).grid(row=7, column=1, sticky="w", pady=(12, 0))

        engine_panel = ttk.Frame(self.settings_content, style="Surface.TFrame", padding=14)
        self.engine_panel = engine_panel
        engine_panel.pack(fill="x", pady=(12, 0))
        ttk.Label(engine_panel, text="Moteur 7z", style="Section.TLabel").pack(anchor="w")
        external = shutil.which("7zz") or shutil.which("7z") or shutil.which("7za")
        try:
            import py7zr
            py7zr_version = getattr(py7zr, "__version__", "")
            version_label = f" {py7zr_version}" if py7zr_version else ""
            library_status = f"Bibliothèque py7zr{version_label} disponible."
        except ImportError:
            library_status = "Bibliothèque py7zr absente ; installez les dépendances du projet."
        engine_status = (f"{library_status} Exécutable 7-Zip détecté ({external}) ; ce build utilise py7zr."
                         if external else f"{library_status} Exécutable 7-Zip externe absent.")
        ttk.Label(engine_panel, text=engine_status, style="Hint.TLabel").pack(anchor="w", pady=(5, 0))
        ttk.Label(engine_panel, text="Le chiffrement 7z est pris en charge. Les archives multiparties et les fonctions propres au programme 7-Zip nécessitent un moteur externe.", style="Hint.TLabel", wraplength=850).pack(anchor="w", pady=(4, 0))

    def _adapt_settings_layout(self, _event=None) -> None:
        width = max(1, self.settings_tab.winfo_width())
        half = max(140, width // 2 - 28)
        full = max(220, width - 36)
        for child in self.settings_panel.winfo_children():
            if isinstance(child, ttk.Label):
                child.configure(wraplength=full if child.cget("style") == "Hint.TLabel" else half)
        for child in self.engine_panel.winfo_children():
            if isinstance(child, ttk.Label):
                child.configure(wraplength=full)

    def _set_dictionary_choice(self, value: int) -> None:
        self.dictionary_mib.set(value)
        for choice, button in self.dictionary_choice_buttons.items():
            button.configure(style="Primary.TButton" if choice == value else "TButton")

    def _refresh_mode(self) -> None:
        compressing = self.mode.get() == "Compresser"
        self.format_box.configure(values=FORMATS if compressing else ("Automatique", *FORMATS))
        if not compressing and self.format.get() not in ("Automatique", *FORMATS):
            self.format.set("Automatique")
        elif compressing and self.format.get() not in FORMATS:
            self.format.set("xz")
        self.level_box.configure(state="readonly" if compressing else "disabled")
        use_lzma = self.format.get() in ("xz", "lzma", "7z") and compressing
        for button in self.dictionary_choice_buttons.values():
            button.configure(state="normal" if use_lzma else "disabled")
        self.dictionary_label.configure(state="normal" if use_lzma else "disabled")
        folders_allowed = compressing and self.format.get() == "7z"
        if folders_allowed:
            self.source_buttons.columnconfigure(1, weight=1)
            self.add_folder_button.grid()
            self.clear_sources_button.grid_configure(column=1)
        else:
            self.source_buttons.columnconfigure(1, weight=0)
            self.add_folder_button.grid_remove()
            self.clear_sources_button.grid_configure(column=0)
        self.clear_sources_button.configure(state="normal" if self.sources else "disabled")
        password_available = self.format.get() in ("7z", "Automatique")
        self.password_entry.configure(state="normal" if password_available else "disabled")
        self.show_password_check.configure(state="normal" if password_available else "disabled")
        self.output_button.configure(text="Nom de l’archive…" if compressing and self.format.get() == "7z" else "Choisir…")
        descriptions = {
            "bz2": "Fichier .bz2. Chaque fichier est compressé séparément.",
            "xz": "Fichier .xz. Un bon choix pour la plupart des fichiers.",
            "lzma": "Fichier .lzma. Chaque fichier est compressé séparément.",
            "7z": "Archive .7z. Regroupe plusieurs fichiers ou dossiers dans un seul fichier.",
            "Automatique": "Le format est reconnu automatiquement à partir du fichier choisi.",
        }
        self.format_description.configure(text=descriptions.get(self.format.get(), ""))
        self.sources_heading.configure(text="Fichiers à compresser" if compressing else "Fichiers à extraire")
        self.drop_title.configure(text="Ajoutez un ou plusieurs fichiers" if compressing else "Choisissez un fichier compressé ou une archive 7z")
        hint_parts = []
        if compressing and not folders_allowed:
            hint_parts.append("Pour un dossier entier, choisissez le format 7z.")
        hint_parts.append("Vous pouvez aussi déposer les fichiers ici." if self.drop_enabled
                          else "Utilisez le bouton pour choisir les fichiers.")
        self.drop_hint.configure(text=" ".join(hint_parts))
        self.add_files_button.configure(text="Choisir des fichiers…" if compressing else "Choisir les fichiers à extraire…")
        self.destination_hint.configure(text=("Laissez vide pour enregistrer à côté des fichiers d’origine."
                                              if compressing and self.format.get() != "7z"
                                              else "Laissez vide pour créer l’archive à côté du premier fichier."
                                              if compressing else "Laissez vide pour extraire à côté de l’archive."))
        self.run_button.configure(text="Compresser" if compressing else "Extraire")
        self.page_title.configure(text="Compresser" if compressing else "Extraire")
        self.page_subtitle.configure(text=("Ajoutez vos fichiers, vérifiez le format, puis lancez la compression."
                                          if compressing else "Choisissez les fichiers à ouvrir, puis lancez l’extraction."))

    def _dialog(self, kind: str, title: str, message: str) -> bool:
        """Show a compact, themed dialog; return the user's yes/no choice."""
        asking = kind == "askyesno"
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.configure(background=self.palette["surface"])
        result = tk.BooleanVar(value=False)
        panel = ttk.Frame(dialog, padding=(SPACE["xl"], 20))
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text=title, font=FONTS["dialog_title"]).pack(anchor="w")
        ttk.Label(panel, text=message, wraplength=470, justify="left").pack(anchor="w", pady=(10, 19))
        buttons = ttk.Frame(panel)
        buttons.pack(fill="x")

        def finish(value: bool) -> None:
            result.set(value)
            dialog.destroy()

        if asking:
            ttk.Button(buttons, text="Annuler", command=lambda: finish(False)).pack(side="right", padx=(8, 0))
            ttk.Button(buttons, text="Confirmer", style="Primary.TButton",
                       command=lambda: finish(True)).pack(side="right")
            dialog.bind("<Return>", lambda _event: finish(True))
            dialog.bind("<Escape>", lambda _event: finish(False))
        else:
            ttk.Button(buttons, text="OK", style="Primary.TButton",
                       command=lambda: finish(True)).pack(side="right")
            dialog.bind("<Return>", lambda _event: finish(True))
            dialog.bind("<Escape>", lambda _event: finish(True))
        dialog.protocol("WM_DELETE_WINDOW", lambda: finish(False))
        dialog.update_idletasks()
        width, height = max(390, dialog.winfo_reqwidth()), dialog.winfo_reqheight()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        dialog.grab_set()
        dialog.focus_set()
        self.root.wait_window(dialog)
        return result.get()

    def _shortcut_open_archive(self, _event=None) -> str:
        self._show_page("archive")
        self._open_archive()
        return "break"

    def _shortcut_start(self, _event=None) -> str:
        if self.current_page in ("compress", "extract"):
            self._start()
        return "break"

    def _shortcut_cancel(self, _event=None) -> str | None:
        if self.busy:
            self._cancel()
            return "break"
        return None

    def _toggle_password(self) -> None:
        show = "" if self.show_password.get() else "•"
        self.password_entry.configure(show=show)
        self.archive_password_entry.configure(show=show)

    def _add_files(self) -> None:
        extracting = self.mode.get() == "Extraire"
        title = "Choisir les fichiers à extraire" if extracting else "Choisir les fichiers à compresser"
        if extracting:
            paths = filedialog.askopenfilenames(
                title=title,
                filetypes=(("Fichiers compressés", "*.bz2 *.xz *.lzma *.7z"), ("Tous les fichiers", "*.*")),
            )
        else:
            paths = filedialog.askopenfilenames(title=title)
        self._append_sources(Path(path) for path in paths)

    def _add_folder(self) -> None:
        path = filedialog.askdirectory(title="Choisir un dossier à archiver")
        if path:
            self._append_sources([Path(path)])

    def _append_sources(self, paths) -> None:
        known = {str(path.resolve()).casefold() for path in self.sources}
        for path in paths:
            resolved = path.expanduser().resolve()
            if str(resolved).casefold() not in known:
                self.sources.append(resolved)
                try:
                    size = "Dossier" if resolved.is_dir() else _human_size(resolved.stat().st_size)
                except OSError:
                    size = "Indisponible"
                self.source_tree.insert("", "end", values=(resolved.name, str(resolved.parent), size))
                known.add(str(resolved).casefold())
        if self.sources:
            self.source_empty_label.grid_remove()
        self._refresh_source_count()
        self.clear_sources_button.configure(state="normal" if self.sources else "disabled")

    def _remove_sources(self, _event=None) -> str:
        selected = sorted(
            ((self.source_tree.index(item), item) for item in self.source_tree.selection()),
            reverse=True,
        )
        for index, item in selected:
            self.source_tree.delete(item)
            del self.sources[index]
        if not self.sources:
            self.source_empty_label.grid()
        self._refresh_source_count()
        self.clear_sources_button.configure(state="normal" if self.sources else "disabled")
        return "break"

    def _clear_sources(self) -> None:
        self.sources.clear()
        self.source_tree.delete(*self.source_tree.get_children())
        self.source_empty_label.grid()
        self._refresh_source_count()
        self.clear_sources_button.configure(state="disabled")

    def _refresh_source_count(self) -> None:
        count = len(self.sources)
        if count == 0:
            label = "Aucun fichier sélectionné"
        elif count == 1:
            label = "1 élément sélectionné"
        else:
            label = f"{count} éléments sélectionnés"
        self.source_count.set(label)

    def _choose_output(self) -> None:
        if self.mode.get() == "Compresser" and self.format.get() == "7z":
            path = filedialog.asksaveasfilename(title="Créer une archive 7z", defaultextension=".7z", filetypes=(("Archive 7z", "*.7z"),))
        else:
            path = filedialog.askdirectory(title="Choisir le dossier de destination")
        if path:
            self.output.set(path)

    def _choose_archive_output(self) -> None:
        path = filedialog.askdirectory(title="Choisir le dossier d’extraction")
        if path:
            self.archive_output.set(path)

    def _start(self) -> None:
        """Valide les choix de l’utilisateur puis prépare la tâche en arrière-plan."""
        if self.busy:
            return
        if not self.sources:
            self._dialog("warning", "Aucun fichier choisi", "Choisissez au moins un fichier pour continuer.")
            return
        kind = self.format.get()
        if self.mode.get() == "Compresser":
            try:
                level = COMPRESSION_LEVEL_VALUES[self.level.get()]
                dictionary_kib = int(self.dictionary_mib.get()) * 1024
                if not 1 <= level <= 9 or dictionary_kib < 64:
                    raise ValueError
            except (ValueError, tk.TclError):
                self._dialog("error", "Paramètres invalides", "Vérifiez l’intensité choisie et la taille du dictionnaire.")
                return
        else:
            level, dictionary_kib = 6, int(self.dictionary_mib.get()) * 1024
            if kind == "Automatique":
                for path in self.sources:
                    try:
                        engine.infer_format(path)
                    except ValueError as exc:
                        self._dialog("error", "Format inconnu", f"{exc}\nChoisissez un format explicite.")
                        return
        output_text = self.output.get().strip()
        overwrite = False
        if self.mode.get() == "Extraire" and output_text and Path(output_text).exists():
            overwrite = self._dialog("askyesno", "Destination existante", "Le dossier choisi existe. Si des noms sont déjà présents, voulez-vous les remplacer ?")
            if not overwrite:
                return
        elif self.mode.get() == "Extraire" and not output_text:
            potential_collisions = []
            for source in self.sources:
                try:
                    source_kind = kind if kind != "Automatique" else engine.infer_format(source)
                except ValueError:
                    continue
                if source_kind == "7z":
                    default_dir = source.with_name(source.stem)
                    if default_dir.exists():
                        potential_collisions.append(default_dir)
                else:
                    suffix = {"bz2": ".bz2", "xz": ".xz", "lzma": ".lzma"}.get(source_kind)
                    if suffix:
                        output_file = source.with_name(source.name[:-len(suffix)] if source.name.lower().endswith(suffix) else source.stem)
                        if output_file.exists():
                            potential_collisions.append(output_file)
            if potential_collisions:
                overwrite = self._dialog(
                    "askyesno",
                    "Fichiers existants",
                    f"Une ou plusieurs sorties existent déjà, par exemple :\n{potential_collisions[0]}\n\nVoulez-vous les remplacer ?",
                )
                if not overwrite:
                    return
        self._begin_worker({
            "kind": "operation", "mode": self.mode.get(), "sources": list(self.sources),
            "format": kind, "output": Path(output_text) if output_text else None,
            "level": level, "dictionary_kib": dictionary_kib,
            "password": (self.password.get() or None) if kind == "7z" or self.mode.get() == "Extraire" else None,
            "overwrite": overwrite,
            "max_bytes": int(self.settings_max_mib.get()) * 1024**2,
            "max_files": int(self.settings_max_files.get()),
        })

    def _begin_worker(self, task: dict) -> None:
        """Démarre le traitement sans bloquer la boucle de l’interface."""
        if self.busy:
            return
        self.busy = True
        self.cancel_event = threading.Event()
        self.active_started = time.monotonic()
        if task["kind"] == "archive_extract":
            self.active_context = {"action": "extract", "format": "7z", "sources": [task["source"]]}
            self.cancel_is_deferred = True
        elif task["kind"] == "operation":
            self.active_context = {
                "action": "compress" if task["mode"] == "Compresser" else "extract",
                "format": task["format"], "sources": task["sources"],
            }
            self.cancel_is_deferred = task["mode"] == "Extraire" and any(
                (task["format"] == "7z") or (task["format"] == "Automatique" and source.suffix.lower() == ".7z")
                for source in task["sources"]
            )
        else:
            self.active_context = {"action": "inspecter", "format": "7z", "sources": [task["source"]]}
            self.cancel_is_deferred = False
        self.run_button.configure(state="disabled")
        if task["kind"] != "inspect":
            self.cancel_button.configure(state="normal")
            self.cancel_button.pack(side="right", padx=(SPACE["sm"], 0))
        self.archive_open_button.configure(state="disabled")
        self.archive_extract_button.configure(state="disabled")
        self.progress_percent.set(0)
        self.progressbar.configure(mode="determinate")
        self.status.set("Opération en cours…")
        self.operation_summary.set("Traitement en arrière-plan ; l’interface reste disponible.")
        threading.Thread(target=self._worker, args=(task, self.cancel_event), daemon=True).start()
        self.root.after(100, self._poll)

    def _worker(self, task: dict, cancel_event: threading.Event) -> None:
        """Exécute une tâche dans un fil secondaire et publie ses événements."""
        completed_results: list[engine.OperationResult] = []

        def progress(event: engine.Progress) -> None:
            self.events.put(("progress", event))

        try:
            if task["kind"] == "inspect":
                entries = engine.inspect_archive(task["source"], password=task["password"],
                                                 max_files=task["max_files"], max_uncompressed_bytes=task["max_bytes"])
                self.events.put(("inspected", (task["source"], entries)))
                return
            if task["kind"] == "archive_extract":
                result = engine.extract_archive(
                    task["source"], output=task["output"], selected=task["selected"],
                    password=task["password"], overwrite=task["overwrite"],
                    max_files=task["max_files"], max_uncompressed_bytes=task["max_bytes"],
                    progress=progress, cancel=cancel_event.is_set,
                )
                self.events.put(("result", result))
                return
            if task["mode"] == "Compresser":
                result = engine.compress(
                    task["sources"], task["format"], output=task["output"], level=task["level"],
                    dictionary_kib=task["dictionary_kib"], password=task["password"],
                    progress=progress, cancel=cancel_event.is_set,
                )
                self.events.put(("result", result))
                return
            for source in task["sources"]:
                if cancel_event.is_set():
                    raise engine.OperationCancelled("Opération annulée.")
                kind = None if task["format"] == "Automatique" else task["format"]
                actual_kind = kind or engine.infer_format(source)
                if actual_kind == "7z":
                    result = engine.extract_archive(
                        source, output=task["output"], password=task["password"],
                        overwrite=task["overwrite"], max_files=task["max_files"],
                        max_uncompressed_bytes=task["max_bytes"], progress=progress,
                        cancel=cancel_event.is_set,
                    )
                else:
                    suffix = {"bz2": ".bz2", "xz": ".xz", "lzma": ".lzma"}[actual_kind]
                    target = (task["output"] / (source.name[:-len(suffix)] if source.name.lower().endswith(suffix) else source.stem)) if task["output"] else None
                    result = engine.decompress_file(
                        source, kind=actual_kind, output=target, overwrite=task["overwrite"],
                        max_bytes=task["max_bytes"], progress=progress, cancel=cancel_event.is_set,
                    )
                completed_results.append(result)
            self.events.put(("results", completed_results))
        except engine.OperationCancelled as exc:
            if completed_results:
                self.events.put(("partial_cancelled", (str(exc), completed_results)))
            else:
                self.events.put(("cancelled", str(exc)))
        except Exception as exc:
            message = f"{type(exc).__name__} : {exc}"
            if completed_results:
                self.events.put(("partial_error", (message, completed_results)))
            else:
                self.events.put(("error", message))

    def _poll(self) -> None:
        """Traite dans le fil graphique les événements envoyés par le worker."""
        try:
            kind, payload = self.events.get_nowait()
        except queue.Empty:
            if self.busy:
                self.root.after(100, self._poll)
            return

        if kind == "progress":
            self._show_progress(cast(engine.Progress, payload))
            self.root.after(100, self._poll)
            return

        self._handle_worker_event(kind, payload)

    def _show_progress(self, event: engine.Progress) -> None:
        """Met à jour la barre et le texte de progression d’une opération."""
        if event.total:
            self.progressbar.stop()
            self.progressbar.configure(mode="determinate")
            value = min(100.0, event.done * 100 / event.total)
            self.progress_percent.set(value)
            self.progress_label.configure(text=f"{value:.0f} %")
        else:
            self.progressbar.configure(mode="indeterminate")
            self.progressbar.start(12)
            self.progress_label.configure(text=_human_size(event.done))
        rate = f" · {_human_size(int(event.rate))}/s" if event.rate else ""
        self.status.set(
            f"{event.current} · {_human_size(event.done)} / "
            f"{_human_size(event.total)}{rate}"
        )

    def _handle_worker_event(self, kind: str, payload: object) -> None:
        """Distribue les événements terminaux vers leur traitement d’interface."""
        if kind == "inspected":
            self._handle_inspected(payload)
            return
        if kind in ("result", "results"):
            results = [cast(engine.OperationResult, payload)] if kind == "result" else cast(
                list[engine.OperationResult], payload
            )
            self._handle_results(results)
            return
        if kind in ("partial_error", "partial_cancelled"):
            self._handle_partial_result(kind, payload)
            return
        if kind == "cancelled":
            self._handle_cancelled(str(payload))
            return
        if kind == "error":
            self._handle_error(str(payload))

    def _handle_inspected(self, payload: object) -> None:
        """Enregistre les métadonnées et affiche l’archive qui vient d’être lue."""
        source, entries = cast(
            tuple[Path, tuple[engine.ArchiveEntry, ...]], payload
        )
        self.archive_path = source
        self.archive_entries = entries
        self._render_archive()
        file_count = sum(not item.is_directory for item in entries)
        directory_count = sum(item.is_directory for item in entries)
        total = sum(item.size for item in entries if not item.is_directory)
        self.archive_summary.configure(
            text=(
                f"{source.name} · {file_count} fichiers · {directory_count} dossiers · "
                f"{_human_size(total)} décompressés annoncés"
            )
        )
        self.status.set("Archive chargée. Les tailles proviennent des métadonnées de l’archive.")
        self._finish_worker()

    def _handle_results(self, results: list[engine.OperationResult]) -> None:
        """Enregistre les opérations réussies puis actualise leurs résumés."""
        for result in results:
            add_history(result)
        self._show_results(results)
        self._refresh_history()
        self.status.set("Opération terminée.")
        self._finish_worker()

    def _handle_partial_result(self, kind: str, payload: object) -> None:
        """Présente les sorties réussies avant une erreur ou une annulation partielle."""
        detail, results = cast(tuple[str, list[engine.OperationResult]], payload)
        for result in results:
            add_history(result)
        self._show_results(results)
        failure_status = (
            "Échec partiel" if kind == "partial_error"
            else "Annulé après traitement partiel"
        )
        self._record_failure(failure_status, detail)
        self.status.set("Opération partielle : les sorties listées ci-dessous sont terminées.")
        if kind == "partial_error":
            self._dialog(
                "error",
                "Opération partielle",
                f"{detail}\n\nLes fichiers déjà terminés restent disponibles. "
                "Voir le résumé ci-dessous.",
            )
        else:
            summary = self.operation_summary.get()
            self.operation_summary.set(
                f"{summary}\n\n{detail} Les fichiers déjà terminés restent disponibles."
            )
        self._refresh_history()
        self._finish_worker()

    def _handle_cancelled(self, detail: str) -> None:
        """Affiche le résultat d’une annulation sans sorties terminées."""
        self._record_failure("Annulé", detail)
        self.status.set(
            "Opération annulée. Les sorties partielles ont été nettoyées "
            "lorsqu’elles étaient temporaires."
        )
        self.operation_summary.set(detail)
        self.operation_report.grid()
        self._finish_worker()

    def _handle_error(self, message: str) -> None:
        """Affiche une erreur reçue du fil de traitement."""
        self._record_failure("Échec", message)
        self.status.set("L’opération a échoué.")
        self.operation_summary.set(message)
        self.operation_report.grid()
        self._dialog("error", "Échec de l’opération", message)
        self._finish_worker()

    def _finish_worker(self) -> None:
        self.busy = False
        self.cancel_event = None
        self.progressbar.stop()
        self.progressbar.configure(mode="determinate")
        self.run_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.cancel_button.pack_forget()
        self.archive_open_button.configure(state="normal")
        self.archive_extract_button.configure(state="normal")

    def _cancel(self) -> None:
        if self.cancel_event:
            self.cancel_event.set()
            if self.cancel_is_deferred:
                self.status.set("Annulation demandée… py7zr ne peut interrompre le bloc en cours ; les sorties temporaires seront supprimées avant validation.")
            else:
                self.status.set("Annulation demandée… l’opération s’arrêtera au prochain point sûr.")

    def _record_failure(self, status: str, detail: str) -> None:
        try:
            add_failure(self.active_context.get("action", "opération"),
                        str(self.active_context.get("format", "—")),
                        list(self.active_context.get("sources", [])), status, detail,
                        time.monotonic() - self.active_started)
            self._refresh_history()
        except OSError:
            pass

    def _show_results(self, results: list[engine.OperationResult]) -> None:
        lines = []
        for result in results:
            lines.append(f"{result.action.capitalize()} {result.format} : {_human_size(result.input_bytes)} → {_human_size(result.output_bytes)} en {result.duration_seconds:.2f} s")
            if result.reduction_percent is not None:
                lines.append(f"Réduction mesurée : {result.reduction_percent:.1f} %" if result.reduction_percent >= 0 else f"Taille augmentée de {-result.reduction_percent:.1f} %")
            lines.extend(f"Sortie : {path}" for path in result.output_paths)
        self.operation_summary.set("\n".join(lines))
        self.operation_report.grid()

    def _open_archive(self) -> None:
        if self.busy:
            return
        path = filedialog.askopenfilename(title="Ouvrir une archive 7z", filetypes=(("Archives 7z", "*.7z"), ("Tous les fichiers", "*.*")))
        if not path:
            return
        source = Path(path)
        self.status.set("Lecture des métadonnées de l’archive…")
        self._begin_worker({"kind": "inspect", "source": source, "password": self.archive_password.get() or None,
                            "max_files": int(self.settings_max_files.get()),
                            "max_bytes": int(self.settings_max_mib.get()) * 1024**2})

    def _render_archive(self) -> None:
        """Affiche les entrées de l’archive avec le tri et les filtres actifs."""
        for item in self.archive_tree.get_children():
            self.archive_tree.delete(item)
        self.archive_tree_names.clear()
        query = self.archive_search.get().casefold().strip()
        entries = list(enumerate(self.archive_entries))
        keys = {
            "name": lambda item: item[1].name.casefold(),
            "extension": lambda item: item[1].extension.casefold(),
            "size": lambda item: item[1].size,
            "packed": lambda item: item[1].compressed_size if item[1].compressed_size is not None else -1,
            "modified": lambda item: item[1].timestamp.casefold(),
            "path": lambda item: item[1].name.casefold(),
        }
        entries.sort(key=keys.get(self.archive_sort_column, keys["name"]), reverse=self.archive_sort_reverse)
        folder_ids: dict[str, str] = {}

        def ensure_folder(path: str, parent: str) -> str:
            if path in folder_ids:
                return folder_ids[path]
            iid = f"folder_{len(folder_ids)}"
            segment = path.rsplit("/", 1)[-1]
            self.archive_tree.insert(parent, "end", iid=iid, text=segment,
                                     values=("dossier", "—", "—", "—", path), open=True)
            folder_ids[path] = iid
            self.archive_tree_names[iid] = path
            return iid

        for index, entry in entries:
            if query and query not in entry.name.casefold():
                continue
            parts = [part for part in entry.name.replace("\\", "/").split("/") if part]
            if not parts:
                continue
            parent = ""
            for level in range(1, len(parts)):
                parent = ensure_folder("/".join(parts[:level]), parent)
            archive_path = "/".join(parts)
            if entry.is_directory:
                iid = ensure_folder(archive_path, parent)
                self.archive_tree.item(iid, text=parts[-1], values=(
                    "dossier", _human_size(entry.size), _human_size(entry.compressed_size),
                    entry.timestamp or "—", entry.name,
                ))
                self.archive_tree_names[iid] = entry.name
            else:
                iid = f"file_{index}"
                self.archive_tree.insert(parent, "end", iid=iid, text=parts[-1], values=(
                    entry.extension or "—", _human_size(entry.size), _human_size(entry.compressed_size),
                    entry.timestamp or "—", entry.name,
                ))
                self.archive_tree_names[iid] = entry.name
        if self.archive_tree.get_children(""):
            self.archive_empty_label.grid_remove()
        else:
            self.archive_empty_text.set(
                "Aucun élément ne correspond à la recherche." if query
                else "Cette archive ne contient aucun élément." if self.archive_path
                else "Ouvrez une archive 7z pour afficher son contenu."
            )
            self.archive_empty_label.grid()

    def _sort_archive(self, column: str) -> None:
        if self.archive_sort_column == column:
            self.archive_sort_reverse = not self.archive_sort_reverse
        else:
            self.archive_sort_column = column
            self.archive_sort_reverse = False
        self._render_archive()

    def _filter_archive(self) -> None:
        self._render_archive()

    def _archive_context_menu(self, event) -> str:
        row = self.archive_tree.identify_row(event.y)
        if row and row not in self.archive_tree.selection():
            self.archive_tree.selection_set(row)
        menu = tk.Menu(
            self.root, tearoff=False, background=self.palette["surface"],
            foreground=self.palette["text"], activebackground=self.palette["accent_soft"],
            activeforeground=self.palette["text"], borderwidth=1,
        )
        menu.add_command(label="Extraire la sélection", command=self._extract_selected)
        menu.add_command(label="Copier le chemin", command=self._copy_archive_paths)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def _copy_archive_paths(self) -> None:
        paths = [self.archive_tree_names[row] for row in self.archive_tree.selection()
                 if row in self.archive_tree_names]
        if paths:
            self.root.clipboard_clear()
            self.root.clipboard_append("\n".join(paths))
            self.status.set("Chemin copié dans le presse-papiers.")

    def _extract_selected(self) -> None:
        if self.busy:
            return
        if not self.archive_path:
            self._dialog("info", "Aucune archive", "Ouvrez d’abord une archive 7z.")
            return
        rows = self.archive_tree.selection()
        if not rows and not self._dialog("askyesno", "Aucune sélection", "Aucun élément n’est sélectionné. Extraire toute l’archive ?"):
            return
        selected = [self.archive_tree_names[row] for row in rows if row in self.archive_tree_names] if rows else None
        output_text = self.archive_output.get().strip()
        output = Path(output_text) if output_text else self.archive_path.with_name(self.archive_path.stem)
        overwrite = False
        if output.exists():
            overwrite = self._dialog("askyesno", "Dossier existant", "Si des noms identiques existent, voulez-vous les remplacer ?")
            if not overwrite:
                return
        self._begin_worker({"kind": "archive_extract", "source": self.archive_path, "output": output,
                            "selected": selected, "password": self.archive_password.get() or None,
                            "overwrite": overwrite, "max_files": int(self.settings_max_files.get()),
                            "max_bytes": int(self.settings_max_mib.get()) * 1024**2})

    def _refresh_history(self) -> None:
        history = load_history()
        if getattr(self, "history_tree", None):
            for item in self.history_tree.get_children():
                self.history_tree.delete(item)
        for item in history[:50]:
            when = str(item.get("when", "")).replace("T", " ")[:19]
            sources = item.get("sources", [])
            source = Path(sources[0]).name if sources else "—"
            sizes = f"{_human_size(item.get('input_bytes', 0))} → {_human_size(item.get('output_bytes', 0))}"
            duration = f"{float(item.get('duration_seconds', 0)):.2f} s"
            if getattr(self, "history_tree", None):
                status = str(item.get("status", ""))
                self.history_tree.insert("", "end", values=(when, item.get("action", ""), item.get("format", ""), source, sizes, duration, status))

    def _clear_history(self) -> None:
        if not self._dialog("askyesno", "Effacer l’historique", "Supprimer l’historique enregistré ?"):
            return
        from .state import app_data_dir
        (app_data_dir() / "history.json").unlink(missing_ok=True)
        self._refresh_history()

    def _save_settings(self) -> None:
        try:
            data = {
                "format": self.settings_default_format.get(),
                "level": COMPRESSION_LEVEL_VALUES[self.settings_default_level.get()],
                "dictionary_kib": int(self.dictionary_mib.get()) * 1024,
                "max_files": int(self.settings_max_files.get()),
                "max_uncompressed_mib": int(self.settings_max_mib.get()),
                "theme": self.theme_mode.get(),
            }
            if not 1 <= data["level"] <= 9 or data["max_files"] < 1 or data["max_uncompressed_mib"] < 1:
                raise ValueError
            save_settings(data)
        except (ValueError, tk.TclError, OSError) as exc:
            self._dialog("error", "Paramètres invalides", f"Vérifiez les valeurs saisies.\n{exc}")
            return
        self.settings.update(data)
        self.format.set(data["format"])
        self.level.set(_compression_level_name(data["level"]))
        self.settings_theme.set(THEME_NAMES.get(self.theme_mode.get(), "Automatique"))
        self._dialog("info", "Paramètres", "Paramètres enregistrés.")

    def _on_close(self) -> None:
        if self.busy:
            if self._dialog("askyesno", "Opération en cours", "Demander l’annulation ? La fenêtre restera ouverte jusqu’au nettoyage sûr de l’opération."):
                if self.cancel_event:
                    self.cancel_event.set()
                self.status.set("Annulation demandée… attente du nettoyage de l’opération.")
            return
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    CompressionApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

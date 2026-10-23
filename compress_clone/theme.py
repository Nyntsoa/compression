"""Central color tokens and native ttk theme application."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


FONTS = {
    "body": ("Segoe UI", 10), "small": ("Segoe UI", 9), "tiny": ("Segoe UI", 8),
    "strong": ("Segoe UI", 10, "bold"),
    "section": ("Segoe UI", 11, "bold"), "title": ("Segoe UI", 21, "bold"),
    "metric": ("Segoe UI", 21, "bold"), "dialog_title": ("Segoe UI", 12, "bold"),
}
SPACE = {"xs": 4, "sm": 7, "md": 10, "lg": 14, "xl": 20}


PALETTES = {
    "light": {
        "window": "#E7F0F4", "frame": "#102A35", "surface": "#FFFFFF", "surface_alt": "#F3F6F7",
        "sidebar": "#134E4A", "text": "#1F2937", "muted": "#5B6870",
        "window_muted": "#425A63", "sidebar_muted": "#D0E2DE",
        "border": "#DCE5E8", "accent": "#134E4A", "accent_hover": "#103F3C",
        "accent_pressed": "#0A3432", "brand": "#FFFFFF", "accent_soft": "#E7F2F0",
        "secondary": "#14B8A6",
        "status_success": "#14532D", "status_warning": "#713F12",
        "status_error": "#7F1D1D", "status_info": "#134E4A",
        "success": "#166534", "success_text": "#166534", "warning": "#854D0E",
        "error": "#B42318", "info": "#134E4A", "selection": "#D9EEEA",
        "selection_text": "#1F2937", "hover": "#F0F5F4", "pressed": "#E2ECEA",
        "inverse": "#FFFFFF", "inverse_hover": "#FFFFFF",
    },
    "dark": {
        "window": "#101A1E", "frame": "#07171C", "surface": "#17262B", "surface_alt": "#203137",
        "sidebar": "#134E4A", "text": "#E9F0F2", "muted": "#B0BEC3",
        "window_muted": "#B0BEC3", "sidebar_muted": "#D0E2DE",
        "border": "#35494F", "accent": "#5EEAD4", "accent_hover": "#99F6E4",
        "accent_pressed": "#CCFBF1", "brand": "#D8F8F2", "accent_soft": "#123B37",
        "secondary": "#14B8A6",
        "status_success": "#34D399", "status_warning": "#FBBF24",
        "status_error": "#F87171", "status_info": "#5EEAD4",
        "success": "#4ADE80", "success_text": "#4ADE80", "warning": "#FBBF24",
        "error": "#F87171", "info": "#5EEAD4", "selection": "#16433D",
        "selection_text": "#E9F0F2", "hover": "#243539", "pressed": "#2B3E43",
        "inverse": "#0F2926", "inverse_hover": "#0F2926",
    },
}


def system_prefers_dark() -> bool:
    """Read the Windows app theme when available; default to light elsewhere."""
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return value == 0
    except (ImportError, OSError):
        return False


def resolve_theme(mode: str) -> str:
    if mode == "dark":
        return "dark"
    if mode == "system":
        return "dark" if system_prefers_dark() else "light"
    return "light"


def apply_theme(root: tk.Misc, mode: str) -> dict[str, str]:
    """Apply a palette consistently to ttk and classic Tk widgets."""
    palette = PALETTES[resolve_theme(mode)]
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", background=palette["window"], foreground=palette["text"], font=FONTS["body"])
    style.configure("TFrame", background=palette["surface"])
    style.configure("Shell.TFrame", background=palette["frame"], padding=8)
    style.configure("Surface.TFrame", background=palette["surface"])
    style.configure("Sidebar.TFrame", background=palette["sidebar"])
    style.configure("Card.TFrame", background=palette["surface_alt"], borderwidth=1,
                    relief="solid", bordercolor=palette["border"])
    style.configure("Drop.TFrame", background=palette["surface_alt"], borderwidth=1,
                    relief="solid", bordercolor=palette["border"])
    style.configure("DropActive.TFrame", background=palette["accent_soft"], borderwidth=1,
                    relief="solid", bordercolor=palette["accent"])
    style.configure("TLabel", background=palette["surface"], foreground=palette["text"], font=FONTS["body"])
    style.configure("Surface.TLabel", background=palette["surface"], foreground=palette["text"])
    style.configure("Sidebar.TLabel", background=palette["sidebar"], foreground=palette["sidebar_muted"])
    style.configure("Brand.TLabel", background=palette["sidebar"], foreground=palette["brand"],
                    font=("Segoe UI", 18, "bold"))
    style.configure("Drop.TLabel", background=palette["surface_alt"], foreground=palette["text"])
    style.configure("DropActive.TLabel", background=palette["accent_soft"], foreground=palette["accent"])
    style.configure("Title.TLabel", background=palette["surface"], foreground=palette["text"],
                    font=FONTS["title"])
    style.configure("Section.TLabel", background=palette["surface"], foreground=palette["text"],
                    font=FONTS["section"])
    style.configure("Hint.TLabel", background=palette["surface"], foreground=palette["muted"],
                    font=FONTS["small"])
    style.configure("Muted.TLabel", background=palette["surface"], foreground=palette["muted"])
    style.configure("StatusMuted.TLabel", background=palette["surface"], foreground=palette["muted"])
    style.configure("StatusActive.TLabel", background=palette["surface"], foreground=palette["status_info"])
    style.configure("StatusSuccess.TLabel", background=palette["surface"], foreground=palette["status_success"])
    style.configure("StatusWarning.TLabel", background=palette["surface"], foreground=palette["status_warning"])
    style.configure("StatusError.TLabel", background=palette["surface"], foreground=palette["status_error"])
    style.configure("MetricValue.TLabel", background=palette["surface"], foreground=palette["text"],
                    font=FONTS["metric"])
    style.configure("MetricLabel.TLabel", background=palette["surface"], foreground=palette["muted"],
                    font=FONTS["small"])
    style.configure("TButton", background=palette["surface"], foreground=palette["text"],
                    bordercolor=palette["border"], padding=(SPACE["md"], SPACE["sm"]), font=FONTS["small"])
    style.map("TButton", background=[("disabled", palette["surface_alt"]),
                                     ("pressed", palette["pressed"]),
                                     ("active", palette["hover"])],
              foreground=[("disabled", palette["muted"])])
    style.configure("Primary.TButton", background=palette["accent"], foreground=palette["inverse"],
                    bordercolor=palette["accent"], padding=(SPACE["lg"], 9), font=("Segoe UI", 10, "bold"))
    style.map("Primary.TButton", background=[("disabled", palette["muted"]),
                                              ("pressed", palette["accent_pressed"]),
                                              ("active", palette["accent_hover"])],
              foreground=[("disabled", palette["inverse_hover"]),
                          ("pressed", palette["inverse_hover"]),
                          ("active", palette["inverse_hover"])])
    style.configure("Nav.TButton", background=palette["sidebar"], foreground=palette["sidebar_muted"],
                    anchor="w", padding=(SPACE["md"], 9), borderwidth=0, font=FONTS["body"])
    style.map("Nav.TButton", background=[("active", palette["hover"])],
              foreground=[("active", palette["text"])])
    style.configure("NavActive.TButton", background=palette["accent_soft"], foreground=palette["accent"],
                    anchor="w", padding=(SPACE["md"], 9), borderwidth=0, font=("Segoe UI", 10, "bold"))
    style.map("NavActive.TButton", background=[("active", palette["accent_soft"])])
    style.configure("TEntry", fieldbackground=palette["surface"], foreground=palette["text"],
                    insertcolor=palette["text"], bordercolor=palette["border"], padding=6)
    style.configure("TCombobox", fieldbackground=palette["surface"], foreground=palette["text"],
                    background=palette["surface_alt"], arrowcolor=palette["muted"], padding=5)
    style.map("TCombobox", fieldbackground=[("readonly", palette["surface"])],
              selectbackground=[("readonly", palette["selection"])],
              selectforeground=[("readonly", palette["text"])])
    style.configure("NavSelect.TCombobox", fieldbackground=palette["surface"],
                    foreground=palette["text"], background=palette["surface"],
                    arrowcolor=palette["accent"], bordercolor=palette["border"], padding=(8, 5))
    style.map("NavSelect.TCombobox", fieldbackground=[("readonly", palette["surface"])],
              selectbackground=[("readonly", palette["selection"])],
              selectforeground=[("readonly", palette["text"])])
    style.configure("TSpinbox", fieldbackground=palette["surface"], foreground=palette["text"],
                    arrowcolor=palette["muted"], padding=5)
    style.configure("TCheckbutton", background=palette["surface"], foreground=palette["text"])
    style.map("TCheckbutton", background=[("active", palette["surface"])])
    style.configure("Treeview", rowheight=32, font=FONTS["small"], background=palette["surface"],
                    fieldbackground=palette["surface"], foreground=palette["text"], bordercolor=palette["border"],
                    borderwidth=0, relief="flat", focuscolor=palette["border"],
                    lightcolor=palette["border"], darkcolor=palette["border"])
    style.map("Treeview", background=[("selected", palette["selection"])],
              foreground=[("selected", palette["selection_text"])])
    style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"),
                    background=palette["surface_alt"], foreground=palette["muted"], relief="flat")
    style.map("Treeview.Heading", background=[("active", palette["border"])])
    style.configure("TProgressbar", background=palette["secondary"], troughcolor=palette["surface_alt"],
                    bordercolor=palette["surface_alt"], lightcolor=palette["secondary"],
                    darkcolor=palette["secondary"])
    style.configure("TScrollbar", background=palette["surface_alt"], troughcolor=palette["surface"],
                    arrowcolor=palette["muted"], bordercolor=palette["surface"],
                    lightcolor=palette["surface_alt"], darkcolor=palette["surface_alt"],
                    relief="flat", width=12)
    style.configure("Vertical.TScrollbar", background=palette["surface_alt"], troughcolor=palette["surface"],
                    arrowcolor=palette["muted"], bordercolor=palette["surface"],
                    lightcolor=palette["surface_alt"], darkcolor=palette["surface_alt"], relief="flat")
    style.configure("Horizontal.TScrollbar", background=palette["surface_alt"], troughcolor=palette["surface"],
                    arrowcolor=palette["muted"], bordercolor=palette["surface"],
                    lightcolor=palette["surface_alt"], darkcolor=palette["surface_alt"], relief="flat")
    style.configure("TSeparator", background=palette["border"])

    root.configure(background=palette["window"])
    _apply_classic_widget_colors(root, palette)
    return palette


def _apply_classic_widget_colors(widget: tk.Misc, palette: dict[str, str]) -> None:
    if isinstance(widget, tk.Listbox):
        widget.configure(background=palette["surface"], foreground=palette["text"],
                         selectbackground=palette["selection"], selectforeground=palette["selection_text"],
                         highlightbackground=palette["border"], highlightcolor=palette["accent"],
                         relief="flat", borderwidth=0)
    elif isinstance(widget, tk.Text):
        widget.configure(background=palette["surface"], foreground=palette["text"],
                         insertbackground=palette["text"], selectbackground=palette["selection"])
    elif isinstance(widget, ttk.Treeview):
        for tag, color in (("success", palette["success_text"]), ("warning", palette["warning"]),
                           ("error", palette["error"])):
            widget.tag_configure(tag, foreground=color)
    for child in widget.winfo_children():
        _apply_classic_widget_colors(child, palette)

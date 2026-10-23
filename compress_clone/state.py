"""Small JSON settings and operation history stored outside the project folder."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .engine import OperationResult


DEFAULT_SETTINGS = {
    "format": "xz",
    "level": 6,
    "dictionary_kib": 8192,
    "max_files": 10000,
    "max_uncompressed_mib": 10240,
    "theme": "system",
}
SETTING_LIMITS = {
    "level": (1, 9),
    "max_files": (1, 1_000_000),
    "max_uncompressed_mib": (1, 1_048_576),
    "dictionary_kib": (64, 262_144),
}
NUMERIC_FALLBACKS = {
    "level": 6,
    "max_files": 10_000,
    "max_uncompressed_mib": 10_240,
    "dictionary_kib": 8192,
}
ALLOWED_SETTING_KEYS = set(DEFAULT_SETTINGS)


def app_data_dir() -> Path:
    """Crée et renvoie le dossier où l’application garde ses données."""
    base = Path(os.environ.get("APPDATA", Path.home() / ".config"))
    path = base / "CompressClone"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_json(path: Path, fallback: Any) -> Any:
    """Lit un fichier JSON et renvoie une valeur de secours s’il est illisible."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _write_json(path: Path, value: Any) -> None:
    """Écrit d’abord dans un fichier voisin, puis remplace la version précédente."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def load_settings() -> dict[str, Any]:
    """Charge les réglages et remplace les valeurs invalides par des valeurs sûres."""
    # Une copie évite de modifier les valeurs par défaut partagées entre appels.
    defaults = DEFAULT_SETTINGS.copy()
    stored = _read_json(app_data_dir() / "settings.json", {})
    if isinstance(stored, dict):
        defaults.update({key: value for key, value in stored.items() if key in defaults})
    supported_formats = {"bz2", "xz", "lzma", "7z"}
    if not isinstance(defaults["format"], str) or defaults["format"] not in supported_formats:
        defaults["format"] = "xz"
    supported_themes = {"light", "dark", "system"}
    if not isinstance(defaults["theme"], str) or defaults["theme"] not in supported_themes:
        defaults["theme"] = "system"

    # Les bornes empêchent un réglage corrompu d’imposer des valeurs extrêmes.
    for key, (minimum, maximum) in SETTING_LIMITS.items():
        try:
            value = int(defaults[key])
        except (TypeError, ValueError):
            value = NUMERIC_FALLBACKS[key]
        defaults[key] = min(maximum, max(minimum, value))
    return defaults


def save_settings(settings: dict[str, Any]) -> None:
    """Met à jour uniquement les clés de réglages connues."""
    merged = load_settings()
    merged.update({key: settings[key] for key in ALLOWED_SETTING_KEYS if key in settings})
    _write_json(app_data_dir() / "settings.json", merged)


def load_history() -> list[dict[str, Any]]:
    """Charge au maximum les 50 dernières opérations enregistrées."""
    value = _read_json(app_data_dir() / "history.json", [])
    return [item for item in value[:50] if isinstance(item, dict)] if isinstance(value, list) else []


def add_history(result: OperationResult, *, status: str = "Réussi", detail: str = "") -> None:
    entry = {
        "when": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "action": result.action,
        "format": result.format,
        "sources": list(result.source_names),
        "outputs": [str(path) for path in result.output_paths],
        "input_bytes": result.input_bytes,
        "output_bytes": result.output_bytes,
        "duration_seconds": round(result.duration_seconds, 3),
        "status": status,
        "detail": detail[:500],
        # Les mots de passe ne font pas partie des données enregistrées.
    }
    _store_history_entry(entry)


def add_failure(action: str, kind: str, sources: list[Path], status: str, detail: str,
                duration_seconds: float) -> None:
    entry = {
        "when": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "action": action,
        "format": kind,
        "sources": [str(path) for path in sources],
        "outputs": [],
        "input_bytes": 0,
        "output_bytes": 0,
        "duration_seconds": round(duration_seconds, 3),
        "status": status,
        "detail": detail[:500],
    }
    _store_history_entry(entry)


def _store_history_entry(entry: dict[str, Any]) -> None:
    """Ajoute une entrée au début de l’historique et garde les 50 plus récentes."""
    history = load_history()
    history.insert(0, entry)
    _write_json(app_data_dir() / "history.json", history[:50])


from pathlib import Path

from compress_clone import state
from compress_clone.engine import OperationResult


def test_history_records_operation_without_secret_fields(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(state, "app_data_dir", lambda: tmp_path)
    result = OperationResult("compress", "7z", ("secret.txt",), (tmp_path / "secret.7z",),
                             20, 30, 0.12, False)

    state.add_history(result)

    saved = (tmp_path / "history.json").read_text(encoding="utf-8")
    assert '"status": "Réussi"' in saved
    assert "password" not in saved.lower()
    assert "correct horse" not in saved


def test_corrupt_settings_fall_back_to_safe_values(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(state, "app_data_dir", lambda: tmp_path)
    (tmp_path / "settings.json").write_text('{"format": [], "max_files": "bad", "level": 90}', encoding="utf-8")

    settings = state.load_settings()

    assert settings["format"] == "xz"
    assert settings["max_files"] == 10_000
    assert settings["level"] == 9


def test_theme_is_persisted_without_clearing_other_settings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(state, "app_data_dir", lambda: tmp_path)
    state.save_settings({"format": "bz2", "level": 8, "theme": "dark"})
    state.save_settings({"theme": "light"})

    settings = state.load_settings()

    assert settings["theme"] == "light"
    assert settings["format"] == "bz2"
    assert settings["level"] == 8


def test_invalid_theme_falls_back_to_system(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(state, "app_data_dir", lambda: tmp_path)
    (tmp_path / "settings.json").write_text('{"theme": []}', encoding="utf-8")

    assert state.load_settings()["theme"] == "system"

from pathlib import Path

from compress_clone.cli import main


def test_cli_compresses_and_restores_file(tmp_path: Path, capsys) -> None:
    source = tmp_path / "cli sample.txt"
    source.write_text("CLI round trip", encoding="utf-8")
    compressed = tmp_path / "compressed.bz2"
    restored = tmp_path / "restored.txt"

    assert main(["compress", str(source), "--format", "bz2", "--output", str(compressed)]) == 0
    assert main(["decompress", str(compressed), "--output", str(restored)]) == 0
    assert restored.read_text(encoding="utf-8") == "CLI round trip"
    assert "Réduction mesurée" in capsys.readouterr().out

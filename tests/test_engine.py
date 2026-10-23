from __future__ import annotations

import os
import struct
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from compress_clone import engine


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


PNG_SAMPLE = (
    b"\x89PNG\r\n\x1a\n"
    + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
    + _png_chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00\xff"))
    + _png_chunk(b"IEND", b"")
)


@pytest.mark.parametrize("kind", ["bz2", "xz", "lzma"])
def test_stream_round_trip_text(kind: str, tmp_path: Path) -> None:
    source = tmp_path / "été avec espaces.txt"
    payload = ("Bonjour — compression !\n" * 300).encode("utf-8")
    source.write_bytes(payload)
    compressed_dir = tmp_path / "compressed"

    result = engine.compress([source], kind, output=compressed_dir, level=6)
    restored = tmp_path / f"restored-{kind}.txt"
    extracted = engine.decompress_file(result.output_paths[0], output=restored)

    assert restored.read_bytes() == payload
    assert extracted.integrity_checked
    assert result.input_bytes == len(payload)
    assert result.output_bytes == result.output_paths[0].stat().st_size


@pytest.mark.parametrize("kind", ["bz2", "xz", "lzma"])
def test_image_bytes_round_trip(kind: str, tmp_path: Path) -> None:
    source = tmp_path / "image test.png"
    source.write_bytes(PNG_SAMPLE)
    compressed = engine.compress([source], kind).output_paths[0]
    restored = tmp_path / "restored.png"
    engine.decompress_file(compressed, output=restored)
    assert restored.read_bytes() == PNG_SAMPLE


def test_empty_file_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "empty.txt"
    source.write_bytes(b"")
    compressed = engine.compress([source], "bz2").output_paths[0]
    restored = tmp_path / "empty-restored.txt"
    engine.decompress_file(compressed, output=restored)
    assert restored.read_bytes() == b""


def test_large_file_streams_without_changing_original(tmp_path: Path) -> None:
    source = tmp_path / "large.bin"
    payload = bytes(range(256)) * (3 * 1024 * 1024 // 256)
    source.write_bytes(payload)
    result = engine.compress([source], "xz")
    assert source.read_bytes() == payload
    restored = tmp_path / "large-restored.bin"
    engine.decompress_file(result.output_paths[0], output=restored, max_bytes=len(payload) + 1)
    assert restored.read_bytes() == payload


@pytest.mark.parametrize("kind", ["bz2", "lzma"])
def test_multiple_files_are_compressed_individually(kind: str, tmp_path: Path) -> None:
    first, second = tmp_path / "first.txt", tmp_path / "second.txt"
    first.write_text("one", encoding="utf-8")
    second.write_text("two", encoding="utf-8")
    output = tmp_path / "out"
    result = engine.compress([first, second], kind, output=output)
    assert len(result.output_paths) == 2
    assert {p.name for p in output.iterdir()} == {"first.txt." + kind, "second.txt." + kind}


def test_duplicate_output_names_are_detected_before_writing(tmp_path: Path) -> None:
    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir()
    right.mkdir()
    (left / "same.txt").write_text("left", encoding="utf-8")
    (right / "same.txt").write_text("right", encoding="utf-8")
    output = tmp_path / "out"

    with pytest.raises(ValueError, match="même fichier"):
        engine.compress([left / "same.txt", right / "same.txt"], "bz2", output=output)
    assert not output.exists()


def test_compress_directory_and_extract_archive(tmp_path: Path) -> None:
    folder = tmp_path / "un dossier"
    (folder / "sous-dossier").mkdir(parents=True)
    (folder / "bonjour.txt").write_text("salut", encoding="utf-8")
    (folder / "sous-dossier" / "vide.bin").write_bytes(b"")
    archive = tmp_path / "backup.7z"

    result = engine.compress([folder], "7z", output=archive)
    entries = engine.inspect_archive(archive)
    assert {entry.name for entry in entries} >= {"un dossier", "un dossier/bonjour.txt", "un dossier/sous-dossier/vide.bin"}
    destination = tmp_path / "extrait"
    progress_events: list[engine.Progress] = []
    extracted = engine.extract_archive(archive, output=destination, progress=progress_events.append)
    assert (destination / "un dossier" / "bonjour.txt").read_text(encoding="utf-8") == "salut"
    assert (destination / "un dossier" / "sous-dossier" / "vide.bin").read_bytes() == b""
    assert extracted.integrity_checked
    assert result.output_paths == (archive,)
    assert progress_events


def test_archive_can_extract_selected_files(tmp_path: Path) -> None:
    folder = tmp_path / "input"
    folder.mkdir()
    (folder / "keep.txt").write_text("keep", encoding="utf-8")
    (folder / "skip.txt").write_text("skip", encoding="utf-8")
    archive = engine.compress([folder], "7z", output=tmp_path / "selected.7z").output_paths[0]
    destination = tmp_path / "selected-out"

    engine.extract_archive(archive, output=destination, selected=["input/keep.txt"])

    assert (destination / "input" / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert not (destination / "input" / "skip.txt").exists()


def test_selecting_directory_extracts_its_children_and_counts_them(tmp_path: Path) -> None:
    folder = tmp_path / "input"
    (folder / "part").mkdir(parents=True)
    (folder / "part" / "one.txt").write_text("one", encoding="utf-8")
    (folder / "part" / "two.txt").write_text("two", encoding="utf-8")
    archive = engine.compress([folder], "7z", output=tmp_path / "tree.7z").output_paths[0]
    destination = tmp_path / "only-part"

    result = engine.extract_archive(archive, output=destination, selected=["input/part"])

    assert (destination / "input" / "part" / "one.txt").exists()
    assert (destination / "input" / "part" / "two.txt").exists()
    assert result.output_bytes == 6


def test_archive_password_and_wrong_password(tmp_path: Path) -> None:
    source = tmp_path / "secret.txt"
    source.write_text("confidentiel", encoding="utf-8")
    archive = engine.compress([source], "7z", output=tmp_path / "secret.7z", password="correct").output_paths[0]

    with pytest.raises(Exception):
        engine.inspect_archive(archive, password="wrong")
    out = tmp_path / "secret-out"
    engine.extract_archive(archive, output=out, password="correct")
    assert (out / "secret.txt").read_text(encoding="utf-8") == "confidentiel"


@pytest.mark.parametrize("name", ["../outside.txt", "C:/outside.txt", "\\\\server\\share\\outside.txt"])
def test_rejects_dangerous_archive_paths(name: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="dangereux"):
        engine._safe_member_path(tmp_path, name)


def test_malicious_archive_member_is_rejected_before_extraction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    py7zr = pytest.importorskip("py7zr")
    archive = tmp_path / "malicious.7z"
    archive.write_bytes(b"archive placeholder")
    entry = SimpleNamespace(filename="../outside.txt", uncompressed=6, is_file=True,
                            is_directory=False, is_symlink=False)

    class FakeArchive:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def list(self):
            return [entry]

        def extract(self, *args, **kwargs):
            raise AssertionError("unsafe archive extraction was reached")

    monkeypatch.setattr(py7zr, "SevenZipFile", FakeArchive)
    with pytest.raises(ValueError, match="dangereux"):
        engine.extract_archive(archive, output=tmp_path / "safe")
    assert not (tmp_path / "outside.txt").exists()


def test_rejects_excessive_declared_size(tmp_path: Path) -> None:
    source = tmp_path / "large.txt"
    source.write_bytes(b"a" * 1000)
    archive = engine.compress([source], "7z", output=tmp_path / "large.7z").output_paths[0]
    with pytest.raises(ValueError, match="limite"):
        engine.inspect_archive(archive, max_uncompressed_bytes=10)


def test_corrupt_7z_is_reported(tmp_path: Path) -> None:
    corrupt = tmp_path / "broken.7z"
    corrupt.write_bytes(b"not a 7z archive")
    with pytest.raises(Exception):
        engine.inspect_archive(corrupt)


def test_missing_7z_library_reports_dependency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    source = tmp_path / "input.txt"
    source.write_text("data", encoding="utf-8")
    original_import = builtins.__import__

    def no_py7zr(name, *args, **kwargs):
        if name == "py7zr":
            raise ImportError("not installed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_py7zr)
    with pytest.raises(RuntimeError, match="py7zr"):
        engine.compress([source], "7z")


def test_extraction_collision_requires_overwrite_and_keeps_existing_data(tmp_path: Path) -> None:
    source = tmp_path / "hello.txt"
    source.write_text("from archive", encoding="utf-8")
    archive = engine.compress([source], "7z", output=tmp_path / "hello.7z").output_paths[0]
    destination = tmp_path / "restore"
    destination.mkdir()
    existing = destination / "hello.txt"
    existing.write_text("keep this", encoding="utf-8")

    with pytest.raises(FileExistsError):
        engine.extract_archive(archive, output=destination)
    assert existing.read_text(encoding="utf-8") == "keep this"
    engine.extract_archive(archive, output=destination, overwrite=True)
    assert existing.read_text(encoding="utf-8") == "from archive"


def test_corrupt_stream_fails_and_leaves_no_partial_output(tmp_path: Path) -> None:
    corrupt = tmp_path / "broken.bz2"
    corrupt.write_bytes(b"not a bzip stream")
    output = tmp_path / "restored.txt"
    with pytest.raises((OSError, EOFError)):
        engine.decompress_file(corrupt, output=output)
    assert not output.exists()


def test_existing_output_is_not_overwritten(tmp_path: Path) -> None:
    source = tmp_path / "input.txt"
    source.write_text("new", encoding="utf-8")
    output = tmp_path / "input.txt.bz2"
    output.write_bytes(b"keep me")
    with pytest.raises(FileExistsError):
        engine.compress([source], "bz2")
    assert output.read_bytes() == b"keep me"


def test_cancellation_cleans_partial_compression(tmp_path: Path) -> None:
    source = tmp_path / "large.bin"
    source.write_bytes(os.urandom(4 * 1024 * 1024))
    cancelled = False

    def progress(event: engine.Progress) -> None:
        nonlocal cancelled
        if event.done >= 1024 * 1024:
            cancelled = True

    with pytest.raises(engine.OperationCancelled):
        engine.compress([source], "bz2", progress=progress, cancel=lambda: cancelled)
    assert not source.with_name(source.name + ".bz2").exists()


def test_7z_cancellation_cleans_partial_archive(tmp_path: Path) -> None:
    first, second = tmp_path / "first.txt", tmp_path / "second.txt"
    first.write_bytes(os.urandom(128 * 1024))
    second.write_bytes(os.urandom(128 * 1024))
    cancelled = False

    def progress(event: engine.Progress) -> None:
        nonlocal cancelled
        if event.done > 0:
            cancelled = True

    target = tmp_path / "partial.7z"
    with pytest.raises(engine.OperationCancelled):
        engine.compress([first, second], "7z", output=target, progress=progress, cancel=lambda: cancelled)
    assert not target.exists()


def test_permission_error_is_reported_and_partial_output_removed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "denied.txt"
    source.write_text("data", encoding="utf-8")
    original_open = Path.open

    def denied(path: Path, *args, **kwargs):
        if path == source:
            raise PermissionError("permission denied by test")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied)
    with pytest.raises(PermissionError):
        engine.compress([source], "bz2")
    assert not source.with_name(source.name + ".bz2").exists()


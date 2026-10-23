"""Compression et extraction des fichiers, sans dépendance à l’interface."""

from __future__ import annotations

import bz2
import lzma
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable, Iterable


CHUNK_SIZE = 1024 * 1024
FORMATS = {"bz2", "xz", "lzma", "7z"}
DEFAULT_MAX_FILES = 10_000
DEFAULT_MAX_UNCOMPRESSED_BYTES = 10 * 1024**3


class OperationCancelled(Exception):
    """Signale l’annulation d’une opération à un point sûr."""


@dataclass(frozen=True)
class Progress:
    phase: str
    current: str
    done: int
    total: int | None
    rate: float


@dataclass(frozen=True)
class ArchiveEntry:
    name: str
    extension: str
    size: int
    compressed_size: int | None
    timestamp: str
    is_directory: bool
    is_symlink: bool = False


@dataclass(frozen=True)
class OperationResult:
    action: str
    format: str
    source_names: tuple[str, ...]
    output_paths: tuple[Path, ...]
    input_bytes: int
    output_bytes: int
    duration_seconds: float
    integrity_checked: bool

    @property
    def reduction_percent(self) -> float | None:
        if self.action != "compress" or self.input_bytes == 0:
            return None
        return (1 - self.output_bytes / self.input_bytes) * 100


ProgressCallback = Callable[[Progress], None]
CancelCheck = Callable[[], bool]


def infer_format(path: Path) -> str:
    name = path.name.lower()
    for suffix, kind in ((".bz2", "bz2"), (".xz", "xz"), (".lzma", "lzma"), (".7z", "7z")):
        if name.endswith(suffix):
            return kind
    raise ValueError(f"Format non reconnu pour « {path.name} ».")


def _check_cancel(cancel: CancelCheck | None) -> None:
    if cancel and cancel():
        raise OperationCancelled("Opération annulée.")


def _report(
    callback: ProgressCallback | None,
    phase: str,
    current: str,
    done: int,
    total: int | None,
    started: float,
) -> None:
    if callback:
        elapsed = max(time.monotonic() - started, 0.001)
        callback(Progress(phase, current, done, total, done / elapsed))


def _reserve_target(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
    except FileExistsError:
        raise FileExistsError(f"La destination existe déjà : {path}") from None
    os.close(descriptor)


def _atomic_file(target: Path, writer: Callable[[Path], None], *, overwrite: bool = False) -> None:
    """Prépare une sortie temporaire avant de la déplacer vers son nom final."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".part", dir=target.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    reserved = False
    try:
        writer(temporary)
        if overwrite:
            if target.is_dir():
                raise IsADirectoryError(f"La destination est un dossier : {target}")
            os.replace(temporary, target)
        else:
            _reserve_target(target)
            reserved = True
            os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        if reserved:
            target.unlink(missing_ok=True)
        raise


def _stream_compress(source: Path, target: Path, kind: str, level: int, dictionary_kib: int,
                     callback: ProgressCallback | None, cancel: CancelCheck | None,
                     started: float, all_total: int, completed_before: int) -> int:
    # Le traitement par blocs évite de charger tout le fichier en mémoire.
    def write(temp_path: Path) -> None:
        if kind == "bz2":
            compressor = bz2.BZ2Compressor(level)
        else:
            filter_id = lzma.FILTER_LZMA2 if kind == "xz" else lzma.FILTER_LZMA1
            filter_options = {"id": filter_id, "preset": level, "dict_size": dictionary_kib * 1024}
            format_id = lzma.FORMAT_XZ if kind == "xz" else lzma.FORMAT_ALONE
            compressor = lzma.LZMACompressor(format=format_id, filters=[filter_options])
        processed = 0
        with source.open("rb") as reader, temp_path.open("wb") as writer:
            while True:
                _check_cancel(cancel)
                block = reader.read(CHUNK_SIZE)
                if not block:
                    break
                writer.write(compressor.compress(block))
                processed += len(block)
                _report(callback, "compress", source.name, completed_before + processed, all_total, started)
            writer.write(compressor.flush())

    _atomic_file(target, write)
    return target.stat().st_size


def _archive_items(sources: list[Path]) -> list[tuple[Path, str]]:
    items: list[tuple[Path, str]] = []
    seen: set[str] = set()
    for source in sources:
        if source.is_symlink():
            raise ValueError(f"Les liens symboliques ne sont pas pris en charge : {source}")
        if source.is_file():
            candidates = [(source, source.name)]
        elif source.is_dir():
            candidates = [(source, source.name)]
            candidates.extend((p, str(Path(source.name) / p.relative_to(source)))
                              for p in sorted(source.rglob("*")) if not p.is_symlink())
            symlinks = [p for p in source.rglob("*") if p.is_symlink()]
            if symlinks:
                raise ValueError(f"Le dossier contient des liens symboliques non pris en charge : {symlinks[0]}")
        else:
            raise ValueError(f"Élément non pris en charge : {source}")
        for path, name in candidates:
            key = name.casefold()
            if key in seen:
                raise ValueError(f"Deux éléments portent le même chemin dans l’archive : {name}")
            seen.add(key)
            items.append((path, name))
    return items


def compress(
    sources: Iterable[Path], kind: str, *, output: Path | None = None, level: int = 6,
    dictionary_kib: int = 8 * 1024, password: str | None = None,
    progress: ProgressCallback | None = None, cancel: CancelCheck | None = None,
) -> OperationResult:
    if kind not in FORMATS:
        raise ValueError(f"Format non pris en charge : {kind}")
    if not 1 <= level <= 9:
        raise ValueError("Le niveau de compression doit être compris entre 1 et 9.")
    candidates: list[Path] = []
    seen_sources: set[str] = set()
    for candidate in sources:
        original = candidate.expanduser()
        if original.is_symlink():
            raise ValueError(f"Les liens symboliques ne sont pas pris en charge : {original}")
        source = original.resolve()
        if not source.exists():
            raise FileNotFoundError(f"Source introuvable : {candidate}")
        if not source.is_file() and not (kind == "7z" and source.is_dir()):
            raise ValueError(f"Source non prise en charge pour le format {kind} : {source}")
        key = os.path.normcase(str(source))
        if key not in seen_sources:
            seen_sources.add(key)
            candidates.append(source)
    if not candidates:
        raise ValueError("Sélectionnez au moins un fichier ou dossier.")
    files = candidates
    total_input = sum(p.stat().st_size for p in files if p.is_file())
    if kind == "7z":
        for source in files:
            if source.is_dir():
                total_input += sum(p.stat().st_size for p in source.rglob("*") if p.is_file())
    if kind != "7z" and password:
        raise ValueError("Le chiffrement n’est disponible que pour les archives 7z.")
    started = time.monotonic()
    output_paths: list[Path] = []
    output_bytes = 0
    if kind == "7z":
        try:
            import py7zr
        except ImportError as exc:
            raise RuntimeError("La prise en charge 7z nécessite py7zr.") from exc
        items = _archive_items(files)
        destination = output or files[0].with_name(files[0].name + ".7z")
        destination = destination.expanduser().absolute()

        def write_archive(temp_path: Path) -> None:
            nonlocal output_bytes
            options = {"id": py7zr.FILTER_LZMA2, "preset": level, "dict_size": dictionary_kib * 1024}
            with py7zr.SevenZipFile(temp_path, mode="w", filters=[options], password=password,
                                    header_encryption=bool(password)) as archive:
                completed = 0
                if progress:
                    progress(Progress("compress", "Préparation de l’archive", 0, total_input, 0.0))
                for path, archive_name in items:
                    _check_cancel(cancel)
                    archive.write(path, arcname=archive_name)
                    if path.is_file():
                        completed += path.stat().st_size
                    if progress:
                        progress(Progress("compress", path.name, completed, total_input, 0.0))
            _check_cancel(cancel)
            output_bytes = temp_path.stat().st_size

        _atomic_file(destination, write_archive)
        output_paths.append(destination)
    else:
        if any(not p.is_file() for p in files):
            raise ValueError("BZIP2 et LZMA compressent des fichiers individuels ; utilisez 7z pour les dossiers.")
        out_dir = output.expanduser().absolute() if output else None
        suffix = {"bz2": ".bz2", "xz": ".xz", "lzma": ".lzma"}[kind]
        targets: list[Path] = []
        seen_targets: set[str] = set()
        for source in files:
            if out_dir and len(files) == 1 and out_dir.suffix.lower() == suffix and not out_dir.is_dir():
                target = out_dir
            else:
                target = (out_dir / (source.name + suffix)) if out_dir else source.with_name(source.name + suffix)
            key = os.path.normcase(str(target.absolute()))
            if key in seen_targets:
                raise ValueError(f"Plusieurs sources produiraient le même fichier : {target.name}")
            seen_targets.add(key)
            if target.exists():
                raise FileExistsError(f"La destination existe déjà : {target}")
            targets.append(target)
        completed = 0
        try:
            for source, target in zip(files, targets):
                _check_cancel(cancel)
                output_bytes += _stream_compress(source, target, kind, level, dictionary_kib,
                                                 progress, cancel, started, total_input, completed)
                completed += source.stat().st_size
                output_paths.append(target)
        except BaseException:
            for path in output_paths:
                path.unlink(missing_ok=True)
            raise
    return OperationResult("compress", kind, tuple(str(p) for p in files), tuple(output_paths),
                           total_input, output_bytes, time.monotonic() - started, False)


def _open_stream_reader(source: Path, kind: str):
    if kind == "bz2":
        return bz2.open(source, "rb")
    return lzma.open(source, "rb", format=lzma.FORMAT_XZ if kind == "xz" else lzma.FORMAT_ALONE)


def _stream_decompress(source: Path, target: Path, kind: str, *, max_bytes: int, overwrite: bool,
                       progress: ProgressCallback | None, cancel: CancelCheck | None,
                       started: float) -> int:
    # La limite est vérifiée sur les octets décompressés, avant leur écriture.
    output_size = 0

    def write(temp_path: Path) -> None:
        nonlocal output_size
        with _open_stream_reader(source, kind) as reader, temp_path.open("wb") as writer:
            while True:
                _check_cancel(cancel)
                block = reader.read(CHUNK_SIZE)
                if not block:
                    break
                output_size += len(block)
                if output_size > max_bytes:
                    raise ValueError(f"Le fichier décompressé dépasse la limite de {max_bytes:,} octets.")
                writer.write(block)
                # The reader API exposes uncompressed bytes; the bar is an honest byte count,
                # not a fabricated percentage of the compressed stream.
                _report(progress, "decompress", source.name, output_size, None, started)

    _atomic_file(target, write, overwrite=overwrite)
    return output_size


def decompress_file(source: Path, *, kind: str | None = None, output: Path | None = None,
                    overwrite: bool = False, password: str | None = None,
                    max_files: int = DEFAULT_MAX_FILES,
                    max_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
                    progress: ProgressCallback | None = None, cancel: CancelCheck | None = None) -> OperationResult:
    source = source.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Fichier introuvable : {source}")
    kind = kind or infer_format(source)
    if kind == "7z":
        return extract_archive(source, output=output, password=password, overwrite=overwrite,
                               max_files=max_files, max_uncompressed_bytes=max_bytes,
                               progress=progress, cancel=cancel)
    if kind not in ("bz2", "xz", "lzma"):
        raise ValueError(f"Format non pris en charge : {kind}")
    suffix = {"bz2": ".bz2", "xz": ".xz", "lzma": ".lzma"}[kind]
    target = output or source.with_name(source.name[:-len(suffix)] if source.name.lower().endswith(suffix) else source.stem)
    started = time.monotonic()
    output_size = _stream_decompress(source, target.expanduser().absolute(), kind, max_bytes=max_bytes, overwrite=overwrite,
                                     progress=progress, cancel=cancel, started=started)
    return OperationResult("decompress", kind, (str(source),), (target,), source.stat().st_size,
                           output_size, time.monotonic() - started, True)


def _safe_member_path(root: Path, member_name: str) -> Path:
    """Vérifie qu’un chemin d’archive reste dans le dossier d’extraction."""
    if not member_name or "\x00" in member_name:
        raise ValueError("L’archive contient un nom de fichier invalide.")
    normalized = member_name.replace("\\", "/")
    posix = PurePosixPath(normalized)
    windows = PureWindowsPath(member_name)
    if posix.is_absolute() or windows.is_absolute() or windows.drive:
        raise ValueError(f"Chemin absolu dangereux dans l’archive : {member_name}")
    if any(part == ".." for part in posix.parts):
        raise ValueError(f"Chemin de traversée dangereux dans l’archive : {member_name}")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    for part in posix.parts:
        if any(ord(char) < 32 or char in '<>:"|?*' for char in part) or part.endswith((".", " ")):
            raise ValueError(f"Nom de fichier Windows dangereux dans l’archive : {member_name}")
        if part.split(".", 1)[0].upper() in reserved:
            raise ValueError(f"Nom de périphérique Windows interdit dans l’archive : {member_name}")
    candidate = (root / Path(*posix.parts)).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        raise ValueError(f"Chemin hors destination dans l’archive : {member_name}") from None
    return candidate


def inspect_archive(path: Path, *, password: str | None = None,
                    max_files: int = DEFAULT_MAX_FILES,
                    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES) -> tuple[ArchiveEntry, ...]:
    if max_files < 1 or max_uncompressed_bytes < 1:
        raise ValueError("Les limites d’extraction doivent être positives.")
    try:
        import py7zr
    except ImportError as exc:
        raise RuntimeError("La prise en charge 7z nécessite py7zr.") from exc
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Archive introuvable : {path}")
    with py7zr.SevenZipFile(path, mode="r", password=password,
                            max_extract_size=max_uncompressed_bytes) as archive:
        raw_entries = archive.list()
    if len(raw_entries) > max_files:
        raise ValueError(f"L’archive contient plus de {max_files:,} éléments (limite configurée).")
    total = sum(max(0, int(item.uncompressed or 0)) for item in raw_entries)
    if total > max_uncompressed_bytes:
        raise ValueError(f"Taille décompressée annoncée supérieure à la limite de {max_uncompressed_bytes:,} octets.")
    entries: list[ArchiveEntry] = []
    normalized_names: set[str] = set()
    for item in raw_entries:
        name = str(item.filename)
        _safe_member_path(Path.cwd(), name)
        normalized = PurePosixPath(name.replace("\\", "/")).as_posix().casefold()
        if normalized in normalized_names:
            raise ValueError(f"Chemin dupliqué dans l’archive : {name}")
        normalized_names.add(normalized)
        if item.is_symlink or (not item.is_directory and not item.is_file):
            raise ValueError(f"Type spécial refusé dans l’archive : {name}")
        timestamp = item.creationtime.isoformat(sep=" ", timespec="seconds") if item.creationtime else ""
        entries.append(ArchiveEntry(name, PurePosixPath(name.replace("\\", "/")).suffix, int(item.uncompressed or 0),
                                    int(item.compressed) if item.compressed is not None else None,
                                    timestamp, bool(item.is_directory), bool(item.is_symlink)))
    return tuple(entries)


def _py7zr_progress(base_class, callback: ProgressCallback | None,
                    phase: str, total: int | None, started: float,
                    warnings: list[str]):
    class ProgressCallbackAdapter(base_class):
        def __init__(self) -> None:
            self.current = "Préparation"
            self.done = 0

        def report_start_preparation(self) -> None:
            return None

        def report_start(self, processing_file_path: str, processing_bytes: str) -> None:
            self.current = processing_file_path

        def report_update(self, decompressed_bytes: str) -> None:
            try:
                self.done += int(decompressed_bytes)
            except (TypeError, ValueError):
                pass
            _report(callback, phase, self.current, self.done, total, started)

        def report_end(self, processing_file_path: str, wrote_bytes: str) -> None:
            self.current = processing_file_path

        def report_warning(self, message: str) -> None:
            warnings.append(str(message))

        def report_postprocess(self) -> None:
            return None

    return ProgressCallbackAdapter()


def _select_archive_items(entries, destination: Path, selected: Iterable[str] | None,
                          max_files: int, max_uncompressed_bytes: int):
    """Valide l’archive et renvoie les éléments demandés, dossiers inclus."""
    if len(entries) > max_files:
        raise ValueError(f"L’archive contient plus de {max_files:,} éléments (limite configurée).")

    total_bytes = sum(
        max(0, int(item.uncompressed or 0))
        for item in entries
        if item.is_file
    )
    if total_bytes > max_uncompressed_bytes:
        raise ValueError(
            "Taille décompressée annoncée supérieure à la limite de "
            f"{max_uncompressed_bytes:,} octets."
        )

    items_by_name = {str(item.filename): item for item in entries}
    if len(items_by_name) != len(entries):
        raise ValueError("L’archive contient des noms d’éléments dupliqués.")

    # Une sélection de dossier doit aussi inclure tous ses fichiers enfants.
    requested_names = list(selected) if selected else list(items_by_name)
    unknown_names = set(requested_names) - set(items_by_name)
    if unknown_names:
        raise ValueError(f"Élément absent de l’archive : {next(iter(unknown_names))}")

    selected_paths = {
        PurePosixPath(items_by_name[name].filename.replace("\\", "/"))
        .as_posix().rstrip("/").casefold()
        for name in requested_names
    }
    selected_directories = {
        PurePosixPath(items_by_name[name].filename.replace("\\", "/"))
        .as_posix().rstrip("/").casefold()
        for name in requested_names
        if items_by_name[name].is_directory
    }

    selected_items = []
    seen_paths: set[str] = set()
    for item in entries:
        name = str(item.filename)
        _safe_member_path(destination, name)
        normalized_name = PurePosixPath(name.replace("\\", "/")).as_posix()
        if normalized_name in seen_paths:
            raise ValueError(f"Chemin dupliqué dans l’archive : {name}")
        seen_paths.add(normalized_name.casefold())

        if item.is_symlink or (not item.is_directory and not item.is_file):
            raise ValueError(f"Type spécial refusé dans l’archive : {name}")

        normalized_path = normalized_name.rstrip("/").casefold()
        matches_directory = any(
            normalized_path.startswith(directory + "/")
            for directory in selected_directories
        )
        if not selected or normalized_path in selected_paths or matches_directory:
            selected_items.append(item)

    return selected_items


def _check_extraction_collisions(items, destination: Path, overwrite: bool) -> None:
    """Refuse les conflits fichier/dossier et protège les fichiers existants."""
    collisions = []
    for item in items:
        path = _safe_member_path(destination, str(item.filename))
        if not path.exists() or (item.is_directory and path.is_dir()):
            continue
        if item.is_directory or path.is_dir():
            raise IsADirectoryError(f"Conflit entre fichier et dossier : {path}")
        collisions.append(path)

    if collisions and not overwrite:
        raise FileExistsError(f"La destination contient déjà : {collisions[0]}")


def _install_staged_items(items, staging: Path, destination: Path,
                          overwrite: bool) -> list[Path]:
    """Déplace les sorties validées depuis le dossier temporaire vers la destination."""
    output_paths = []
    for item in items:
        staged_path = _safe_member_path(staging, str(item.filename))
        final_path = _safe_member_path(destination, str(item.filename))
        if staged_path.is_dir():
            final_path.mkdir(parents=True, exist_ok=True)
        else:
            final_path.parent.mkdir(parents=True, exist_ok=True)
            if overwrite:
                os.replace(staged_path, final_path)
            else:
                # Réserver le nom avant le déplacement évite d’écraser un fichier concurrent.
                _reserve_target(final_path)
                try:
                    os.replace(staged_path, final_path)
                except BaseException:
                    final_path.unlink(missing_ok=True)
                    raise
        output_paths.append(final_path)
    return output_paths


def extract_archive(
    source: Path, *, output: Path | None = None, selected: Iterable[str] | None = None,
    password: str | None = None, overwrite: bool = False,
    max_files: int = DEFAULT_MAX_FILES,
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
    progress: ProgressCallback | None = None, cancel: CancelCheck | None = None,
) -> OperationResult:
    try:
        import py7zr
    except ImportError as exc:
        raise RuntimeError("La prise en charge 7z nécessite py7zr.") from exc
    source = source.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Archive introuvable : {source}")
    destination = (output or source.with_name(source.stem)).expanduser().absolute()
    if max_files < 1 or max_uncompressed_bytes < 1:
        raise ValueError("Les limites d’extraction doivent être positives.")
    started = time.monotonic()
    with py7zr.SevenZipFile(
        source,
        mode="r",
        password=password,
        max_extract_size=max_uncompressed_bytes,
    ) as archive:
        entries = archive.list()
        selected_items = _select_archive_items(
            entries, destination, selected, max_files, max_uncompressed_bytes
        )
        selected_names = [str(item.filename) for item in selected_items]
        total_selected = sum(
            max(0, int(item.uncompressed or 0))
            for item in selected_items
            if item.is_file
        )
        _check_extraction_collisions(selected_items, destination, overwrite)

        destination.mkdir(parents=True, exist_ok=True)
        warnings: list[str] = []
        with tempfile.TemporaryDirectory(prefix=".compress-clone-stage-", dir=destination) as staging_name:
            staging = Path(staging_name)
            callback = _py7zr_progress(
                py7zr.callbacks.ExtractCallback,
                progress,
                "extract",
                total_selected,
                started,
                warnings,
            )
            archive.extract(
                path=staging,
                targets=selected_names,
                recursive=True,
                callback=callback,
            )
            _check_cancel(cancel)
            if warnings:
                raise RuntimeError(
                    "Le moteur 7z a signalé un avertissement ; extraction non "
                    f"validée : {warnings[0]}"
                )
            output_paths = _install_staged_items(
                selected_items, staging, destination, overwrite
            )
    output_bytes = sum(p.stat().st_size for p in output_paths if p.is_file())
    input_bytes = source.stat().st_size
    return OperationResult("extract", "7z", (str(source),), tuple(output_paths), input_bytes,
                           output_bytes, time.monotonic() - started, True)


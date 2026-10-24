"""Optional command-line entry point; the desktop UI is the primary interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import engine


FORMATS = ("bz2", "xz", "lzma", "7z")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="compress-clone", description="Compresser et extraire des fichiers bzip2, LZMA et 7z.")
    commands = parser.add_subparsers(dest="command", required=True)
    compress = commands.add_parser("compress", aliases=["c"], help="compresser un ou plusieurs fichiers")
    compress.add_argument("inputs", nargs="+", type=Path)
    compress.add_argument("-f", "--format", choices=FORMATS, default="xz")
    compress.add_argument("-o", "--output", type=Path, help="destination (fichier 7z ou dossier de sortie)")
    compress.add_argument("-l", "--level", type=int, choices=range(1, 10), default=9)
    compress.add_argument("--dictionary-mib", type=int, default=32, help="taille du dictionnaire LZMA en MiB")

    decompress = commands.add_parser("decompress", aliases=["d"], help="extraire un ou plusieurs fichiers")
    decompress.add_argument("inputs", nargs="+", type=Path)
    decompress.add_argument("-f", "--format", choices=FORMATS, help="forcer le format")
    decompress.add_argument("-o", "--output", type=Path, help="fichier ou dossier de destination")

    listing = commands.add_parser("list", aliases=["t"], help="afficher le contenu d’une archive 7z")
    listing.add_argument("input", type=Path)
    commands.add_parser("gui", aliases=["app"], help="ouvrir l’application graphique")
    return parser


def _print_result(result: engine.OperationResult) -> None:
    print(
        f"{result.action.capitalize()} {result.format} : "
        f"{result.input_bytes} octets → {result.output_bytes} octets "
        f"en {result.duration_seconds:.2f} s"
    )
    if result.reduction_percent is not None:
        print(f"Réduction mesurée : {result.reduction_percent:.1f} %")
    for path in result.output_paths:
        print(f"Sortie : {path}")
    if result.action == "decompress" and result.integrity_checked:
        print("Contrôle d’intégrité du flux effectué pendant la décompression.")


def _decompression_output(
    source: Path,
    kind: str,
    requested_output: Path | None,
    input_count: int,
) -> Path | None:
    """Choisit un fichier ou dossier de sortie selon la commande demandée."""
    if requested_output is None:
        return None
    if kind == "7z":
        return requested_output / source.stem
    if input_count == 1 and requested_output.suffix:
        return requested_output

    suffix = {"bz2": ".bz2", "xz": ".xz", "lzma": ".lzma"}[kind]
    base_name = (
        source.name[:-len(suffix)]
        if source.name.lower().endswith(suffix)
        else source.stem
    )
    return requested_output / base_name


def _decompress_inputs(args: argparse.Namespace) -> list[engine.OperationResult]:
    """Décompresse les entrées en calculant chaque destination séparément."""
    results: list[engine.OperationResult] = []
    for source in args.inputs:
        kind = args.format or engine.infer_format(source)
        output = _decompression_output(
            source, kind, args.output, len(args.inputs)
        )
        results.append(engine.decompress_file(source, kind=kind, output=output))
    return results


def _list_archive(path: Path) -> None:
    """Affiche les éléments d’une archive 7z avec leur taille."""
    if engine.infer_format(path) != "7z":
        raise ValueError("La commande list prend en charge les archives .7z.")
    entries = engine.inspect_archive(path)
    print(f"Contenu de {path} :")
    for entry in entries:
        size = "dossier" if entry.is_directory else f"{entry.size:>10} octets"
        print(f"{size:>18}  {entry.name}")


def main(argv: list[str] | None = None) -> int:
    """Analyse la commande, délègue l’opération et convertit les erreurs en code retour."""
    args = _parser().parse_args(argv)
    try:
        if args.command in ("gui", "app"):
            from .gui import main as launch_gui

            launch_gui()
            return 0

        if args.command in ("compress", "c"):
            result = engine.compress(
                args.inputs,
                args.format,
                output=args.output,
                level=args.level,
                dictionary_kib=args.dictionary_mib * 1024,
            )
            _print_result(result)
            return 0

        if args.command in ("decompress", "d"):
            for result in _decompress_inputs(args):
                _print_result(result)
            return 0

        _list_archive(args.input)
        return 0
    except Exception as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

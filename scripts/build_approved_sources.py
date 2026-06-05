from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence


DEFAULT_CORPUS_DIR = Path("5e PHB") / "chapters"
DEFAULT_OUTPUT_PATH = Path("settings") / "approved_sources.5e_phb.local.json"
DEFAULT_MAX_SOURCE_BYTES = 32 * 1024 * 1024


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build an approved_sources.json file from a local PDF corpus."
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=DEFAULT_CORPUS_DIR,
        help=f"Directory to scan for PDFs. Defaults to {DEFAULT_CORPUS_DIR}.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Output JSON path. Defaults to {DEFAULT_OUTPUT_PATH}.",
    )
    parser.add_argument(
        "--max-source-bytes",
        type=int,
        default=DEFAULT_MAX_SOURCE_BYTES,
        help="Fail if any discovered PDF exceeds this size. Defaults to 32 MiB.",
    )
    args = parser.parse_args(argv)

    repo_root = Path.cwd().resolve()
    corpus_dir = _resolve_path(args.corpus, repo_root)
    output_path = _resolve_path(args.output, repo_root)
    sources = discover_pdf_sources(repo_root, corpus_dir, args.max_source_bytes)
    write_approved_sources(output_path, sources)
    print(f"Wrote {len(sources)} approved source(s) to {output_path}")
    return 0


def discover_pdf_sources(repo_root: Path, corpus_dir: Path, max_source_bytes: int) -> list[dict[str, str]]:
    repo_root = repo_root.resolve()
    corpus_dir = corpus_dir.resolve()
    if max_source_bytes <= 0:
        raise SystemExit("--max-source-bytes must be greater than zero")
    if not corpus_dir.is_dir():
        raise SystemExit(f"Corpus directory does not exist: {corpus_dir}")

    oversized: list[str] = []
    sources: list[dict[str, str]] = []
    for pdf_path in sorted(corpus_dir.rglob("*.pdf")):
        size_bytes = pdf_path.stat().st_size
        relative_path = _repo_relative(pdf_path, repo_root)
        if size_bytes > max_source_bytes:
            oversized.append(f"{relative_path} ({_format_bytes(size_bytes)})")
            continue
        sources.append(
            {
                "path": relative_path,
                "label": _label_from_pdf_path(pdf_path),
                "description": "Chapter PDF from the local 5e PHB corpus.",
            }
        )

    if oversized:
        joined = "\n".join(f"- {entry}" for entry in oversized)
        raise SystemExit(
            "One or more PDFs exceed --max-source-bytes. Use chapter-level PDFs or raise the limit explicitly.\n"
            f"{joined}"
        )
    if not sources:
        raise SystemExit(f"No PDFs found under {corpus_dir}")
    return sources


def write_approved_sources(output_path: Path, sources: list[dict[str, str]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"sources": sources}
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _resolve_path(path: Path, repo_root: Path) -> Path:
    if path.is_absolute():
        return path
    return repo_root / path


def _repo_relative(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root).as_posix()
    except ValueError as exc:
        raise SystemExit(f"PDF path is outside repo root: {path}") from exc


def _label_from_pdf_path(path: Path) -> str:
    stem = path.stem
    prefix, separator, rest = stem.partition(" - ")
    if separator and prefix.isdigit():
        return rest
    return stem


def _format_bytes(size_bytes: int) -> str:
    mib = size_bytes / (1024 * 1024)
    if mib >= 1:
        return f"{mib:.1f} MiB"
    kib = size_bytes / 1024
    if kib >= 1:
        return f"{kib:.1f} KiB"
    return f"{size_bytes} bytes"


if __name__ == "__main__":
    raise SystemExit(main())

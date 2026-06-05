from __future__ import annotations

import pytest

from scripts.build_approved_sources import discover_pdf_sources


def test_discover_pdf_sources_returns_repo_relative_entries(tmp_path) -> None:
    corpus_dir = tmp_path / "5e PHB" / "chapters"
    corpus_dir.mkdir(parents=True)
    pdf_path = corpus_dir / "01 - Chapter 1 - Step-By-Step Characters.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\n")

    sources = discover_pdf_sources(tmp_path, corpus_dir, max_source_bytes=1024)

    assert sources == [
        {
            "path": "5e PHB/chapters/01 - Chapter 1 - Step-By-Step Characters.pdf",
            "label": "Chapter 1 - Step-By-Step Characters",
            "description": "Chapter PDF from the local 5e PHB corpus.",
        }
    ]


def test_discover_pdf_sources_rejects_oversized_pdf(tmp_path) -> None:
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    (corpus_dir / "huge.pdf").write_bytes(b"123456")

    with pytest.raises(SystemExit, match="exceed --max-source-bytes"):
        discover_pdf_sources(tmp_path, corpus_dir, max_source_bytes=5)

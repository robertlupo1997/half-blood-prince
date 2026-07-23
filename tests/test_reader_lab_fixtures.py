"""Offline integrity checks for the advisory EPUB reader-lab artifacts."""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from lxml import etree

pytestmark = pytest.mark.filterwarnings("ignore::bs4.XMLParsedAsHTMLWarning")

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "tests" / "fixtures" / "make_reader_lab_epubs.py"
COMMITTED_DIR = ROOT / "tests" / "fixtures" / "reader_lab"
ARTIFACTS = ("reader_lab_epub3.epub", "reader_lab_epub2.epub")
CHAPTERS = tuple(f"chapter-{index}.xhtml" for index in range(1, 5))
MARK_CLASSES = {
    "hbp-mark-underline",
    "hbp-mark-circle",
    "hbp-mark-strike",
    "hbp-mark-highlight",
    "hbp-mark-caret",
}


def _generate(output_dir: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--output-dir", str(output_dir)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"reader-lab generator failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    for artifact in ARTIFACTS:
        assert f"{artifact} sha256 " in result.stdout


def _chapter_name(zf: zipfile.ZipFile, basename: str) -> str:
    matches = [name for name in zf.namelist() if name.endswith(basename)]
    assert len(matches) == 1, f"expected one {basename} entry, found {matches!r}"
    return matches[0]


def _all_chapter_bytes(zf: zipfile.ZipFile) -> bytes:
    return b"\n".join(zf.read(_chapter_name(zf, chapter)) for chapter in CHAPTERS)


def test_generator_is_byte_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _generate(first)
    _generate(second)

    for artifact in ARTIFACTS:
        assert (first / artifact).read_bytes() == (second / artifact).read_bytes(), (
            f"{artifact} differs across two generator runs; ZIP timestamps and content "
            "must be deterministic"
        )


def test_committed_artifacts_match_fresh_generation(tmp_path: Path) -> None:
    fresh = tmp_path / "fresh"
    _generate(fresh)

    for artifact in ARTIFACTS:
        assert (COMMITTED_DIR / artifact).read_bytes() == (fresh / artifact).read_bytes(), (
            f"{artifact} is stale or was edited by hand; re-run make_reader_lab_epubs.py"
        )


@pytest.mark.parametrize(("artifact", "epub3"), ((ARTIFACTS[0], True), (ARTIFACTS[1], False)))
def test_reader_lab_artifact_structure(artifact: str, epub3: bool) -> None:
    path = COMMITTED_DIR / artifact
    assert zipfile.is_zipfile(path), f"{artifact} must be a valid ZIP container"

    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        assert infos[0].filename == "mimetype", "EPUB mimetype must be the first ZIP entry"
        assert infos[0].compress_type == zipfile.ZIP_STORED
        assert zf.read("mimetype") == b"application/epub+zip"
        chapters = _all_chapter_bytes(zf)
        chapter_1 = zf.read(_chapter_name(zf, CHAPTERS[0]))
        chapter_2 = zf.read(_chapter_name(zf, CHAPTERS[1]))
        chapter_3 = zf.read(_chapter_name(zf, CHAPTERS[2]))
        package = next(zf.read(name) for name in zf.namelist() if name.endswith(".opf"))

        assert (b'version="3.0"' in package) is epub3
        assert (b'version="2.0"' in package) is not epub3
        if epub3:
            assert b'epub:type="footnote"' in chapters
            assert b"<aside" in chapters
        else:
            assert b"epub:type" not in chapters
            assert b"<aside" not in chapters
            assert b'<div class="hbp-note ' in chapters

        assert "‸".encode() in chapters, "caret must be real DOM text, not ::after-only"
        assert b"hbp-caret-glyph" in chapters
        assert b".hbp-mark-caret::after" not in chapters

        soup = BeautifulSoup(chapters, "lxml")
        classes = {
            class_name
            for tag in soup.find_all(True)
            for class_name in (tag.get("class") or [])
        }
        assert classes >= MARK_CLASSES
        assert "hbp-mark-none" not in classes
        assert "hbp-note-invention" in classes
        assert "hbp-note-warning" in classes

        none_ref = BeautifulSoup(chapter_1, "lxml").find(id="hbp-ref-lab-none-note-only")
        assert none_ref is not None
        assert none_ref.find_previous("span", class_="hbp-target") is not None
        assert "pewter ladle beside the cooling rack" in none_ref.parent.get_text()
        assert none_ref.previous_sibling is not None
        assert "hbp-target" not in getattr(none_ref.previous_sibling, "attrs", {}).get(
            "class", []
        )

        mark_only_ref = BeautifulSoup(chapter_1, "lxml").find(
            id="hbp-ref-lab-mark-only-caret"
        )
        assert mark_only_ref is not None
        mark_only_span = mark_only_ref.find_previous_sibling("span")
        assert mark_only_span is not None
        assert "hbp-mark-caret" in (mark_only_span.get("class") or [])
        mark_only_note = BeautifulSoup(chapter_1, "lxml").find(
            id="hbp-note-lab-mark-only-caret"
        )
        assert mark_only_note is not None
        backlink = mark_only_note.find("a", class_="hbp-note-backlink")
        assert backlink is not None
        backlink.extract()
        assert mark_only_note.get_text() == "\u2060"

        cluster_notes = BeautifulSoup(chapter_2, "lxml").select(
            ".hbp-note-cluster .hbp-note"
        )
        assert [note["id"] for note in cluster_notes] == [
            "hbp-note-lab-cluster-1",
            "hbp-note-lab-cluster-2",
            "hbp-note-lab-cluster-3",
        ]

        dense_soup = BeautifulSoup(chapter_3, "lxml")
        dense = dense_soup.select_one(".hbp-note-cluster-dense")
        assert dense is not None, "eight-note chapter must carry the NL3 dense fallback class"
        assert "hbp-note-cluster-floatable" not in (dense.get("class") or [])
        assert len(dense.select(".hbp-note")) == 8


@pytest.mark.parametrize("artifact", ARTIFACTS)
def test_every_reader_lab_chapter_is_parseable_xhtml(artifact: str) -> None:
    with zipfile.ZipFile(COMMITTED_DIR / artifact) as zf:
        for chapter in CHAPTERS:
            etree.fromstring(zf.read(_chapter_name(zf, chapter)))

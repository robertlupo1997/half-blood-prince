"""Read-only verification of the documented offline Alice runs."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import fitz
from bs4 import BeautifulSoup
from ebooklib import epub


def main() -> None:
    for kind in ("pdf", "epub"):
        output = Path(f"/tmp/hbp-final-alice.{kind}")
        report = json.loads(Path(str(output) + ".report.json").read_text())
        render = report["render"]
        summary = {
            "format": kind,
            "pages_total": report["pages_total"],
            "pages_annotated": report["pages_annotated"],
            "failed_pages": report["failed_pages"],
            "skipped_pages": report["skipped_pages"],
            "placement_statuses": dict(Counter(p["result"]["status"] for p in render["placements"])),
            "rendered": len(render["rendered"]),
            "render_skips": len(render["skipped"]),
        }
        if kind == "pdf":
            with fitz.open("examples/src/alice.pdf") as source, fitz.open(output) as result:
                assert source.page_count == result.page_count
                assert all(a.get_text().strip() in b.get_text()
                           for a, b in zip(source, result, strict=True))
                summary["source_page_text_retained"] = True
                summary["vector_drawings"] = sum(len(p.get_drawings()) for p in result)
                summary["native_annotations"] = sum(len(list(p.annots() or [])) for p in result)
        else:
            book = epub.read_epub(str(output))
            target_count = sum(
                len(BeautifulSoup(item.get_content(), "html.parser").select(".hbp-target"))
                for item in book.get_items_of_type(9)
            )
            assert target_count == len(render["rendered"])
            assert all(not p["result"]["quads"] for p in render["placements"])
            summary["target_spans"] = target_count
            summary["pdf_quads"] = 0
        print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()

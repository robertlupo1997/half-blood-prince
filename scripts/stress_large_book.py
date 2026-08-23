"""Build a large (~400-page) deterministic PDF from a Project Gutenberg text
to stress-test the pipeline at real book scale, offline and for $0.

Reuses the committed example builder's boilerplate stripping + typesetting,
with typography scaled up so the same public-domain text fills ~400 pages.

Usage:
  python scripts/stress_large_book.py --out /tmp/hbp-stress/big.pdf [--pages 400]

Deterministic given the same PyMuPDF version and source text: anyone can
reproduce the stress input from examples/src/pg11.txt.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from build_example_book import paragraphs, strip_gutenberg_boilerplate  # noqa: E402


def build_pdf_sized(txt_path: Path, out_pdf: Path, target_pages: int) -> tuple[int, float]:
    """Typeset the text, growing font size until page count >= target_pages."""
    import fitz

    raw = txt_path.read_text(encoding="utf-8-sig", errors="replace")
    paras = paragraphs(strip_gutenberg_boilerplate(raw))

    def render(font_pt: float, out: Path) -> int:
        body_style = (
            f"body {{ font-family: serif; font-size: {font_pt:.1f}pt; "
            f"line-height: 1.7; }}"
            "p { margin: 0 0 9pt; }"
        )
        html_parts = [f"<html><head><style>{body_style}</style></head><body>"]
        import html as _html

        html_parts.extend(f"<p>{_html.escape(p)}</p>" for p in paras)
        html_parts.append("</body></html>")
        story = fitz.Story(html="\n".join(html_parts))
        writer = fitz.DocumentWriter(str(out))
        mediabox = fitz.paper_rect("letter")
        margin = 54
        where = mediabox + (margin, margin, -margin, -margin)
        n = 0
        more = True
        while more:
            device = writer.begin_page(mediabox)
            more, _ = story.place(where)
            story.draw(device)
            writer.end_page()
            n += 1
        writer.close()
        return n

    # 13pt gave 78 pages for this text; page count scales ~ font^2.
    font = 13.0 * (float(target_pages) / 78.0) ** 0.5
    for _ in range(12):
        n = render(font, out_pdf)
        if n >= target_pages or font > 60:
            return n, font
        font *= 1.05
    return n, font


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--txt", type=Path, default=REPO / "examples" / "src" / "pg11.txt",
                    help="Gutenberg txt source (default: cached example source)")
    ap.add_argument("--out", type=Path, required=True, help="output PDF path")
    ap.add_argument("--pages", type=int, default=400, help="target page count")
    args = ap.parse_args(argv)

    if not args.txt.exists():
        raise SystemExit(f"source text missing: {args.txt} (run scripts/build_example_book.py once)")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    n_pages, font = build_pdf_sized(args.txt, args.out, args.pages)
    size_kb = args.out.stat().st_size // 1024
    print(f"wrote {args.out} ({n_pages} pages, {size_kb} KB, font {font:.1f}pt)")
    if n_pages < args.pages:
        print(f"WARNING: only {n_pages} pages (< target {args.pages})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

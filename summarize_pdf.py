#!/usr/bin/env python3
"""
Summarize a PDF's methods, data, and results in three paragraphs using TAMU AI.

Usage:
    python3 summarize_pdf.py "Lamp and Samano 2022.pdf"
    python3 summarize_pdf.py paper.pdf -o summary.txt -m "protected.Claude Opus 4.8"

The API key is never stored here. It is resolved by the tamu-ai client from
$TAMU_AI_API_KEY, then ~/.config/tamu-ai/api-key.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# The TAMU AI client. A copy bundled next to this script wins, so the repo can be
# self-contained; otherwise fall back to the Claude skill install.
for _dir in (Path(__file__).resolve().parent,
             Path.home() / ".claude" / "skills" / "tamu-ai" / "scripts"):
    if (_dir / "tamu_ai.py").is_file():
        sys.path.insert(0, str(_dir))
        break
from tamu_ai import chat, TamuAIError  # noqa: E402

# An academic paper needs comprehension, not throughput -- one judgment-grade call.
DEFAULT_MODEL = "protected.Claude Sonnet 4.6"

# Generous enough for a long paper, small enough to stay well inside context.
MAX_CHARS = 300_000

PROMPT = """\
You are summarizing an academic paper for a researcher who wants to know quickly \
what was done and what was found.

Write EXACTLY three paragraphs, in this order, with no headings, no bullet \
points, no bold text, and no preamble:

1. METHODS -- the research design, models, estimation strategy, or experimental \
approach, and the key identifying assumptions.
2. DATA -- the sources, variables, units of observation, time period, geographic \
coverage, and sample size.
3. RESULTS -- the main quantitative findings with specific numbers, their \
direction and magnitude, and the authors' stated caveats.

Be concrete and specific: name the actual methods, datasets, and numbers used in \
this paper. If the paper does not report something, say so rather than guessing. \
Separate the three paragraphs with a blank line. Do not label them.

Here is the full text of the paper:

<paper>
{text}
</paper>
"""


def extract_text(pdf_path: Path) -> str:
    """Pull the text layer out of a PDF, preferring PyMuPDF."""
    try:
        import fitz  # PyMuPDF

        with fitz.open(pdf_path) as doc:
            return "\n".join(page.get_text() for page in doc)
    except ImportError:
        pass

    try:
        import pdfplumber
    except ImportError:
        raise SystemExit(
            "Need a PDF library. Install one:  pip install pymupdf"
        )

    with pdfplumber.open(pdf_path) as pdf:
        return "\n".join((page.extract_text() or "") for page in pdf.pages)


def clean(summary: str) -> str:
    """Undo markdown-isms the model slips into what should be plain text."""
    summary = summary.replace(r"\$", "$").replace(r"\%", "%").replace(r"\_", "_")
    summary = re.sub(r"\*\*(.+?)\*\*", r"\1", summary)   # stray bold
    summary = re.sub(r"\n{3,}", "\n\n", summary)         # collapse blank runs
    return summary.strip()


def open_in_textedit(path: Path) -> None:
    """Show the finished summary. Never fatal -- the file is already written."""
    try:
        # Absolute path so this works whatever PATH the caller hands us.
        subprocess.run(["/usr/bin/open", "-a", "TextEdit", str(path)],
                       check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Warning: could not open TextEdit ({exc}).", file=sys.stderr)


def summarize(pdf_path: Path, model: str) -> str:
    text = extract_text(pdf_path).strip()

    if len(text) < 500:
        raise SystemExit(
            f"Only {len(text)} characters of text in {pdf_path.name}. "
            "It is probably a scanned image and needs OCR first."
        )

    truncated = len(text) > MAX_CHARS
    if truncated:
        # Keep the front (abstract, methods, data) and the back (results,
        # conclusions); the middle of a long paper is the safest thing to drop.
        head, tail = int(MAX_CHARS * 0.6), int(MAX_CHARS * 0.4)
        text = text[:head] + "\n\n[... middle of document omitted ...]\n\n" + text[-tail:]
        print(f"Note: text truncated to {MAX_CHARS:,} characters.", file=sys.stderr)

    print(f"Extracted {len(text):,} characters. Calling {model}...", file=sys.stderr)
    summary = clean(chat(PROMPT.format(text=text), model=model))

    paras = [p for p in summary.split("\n\n") if p.strip()]
    if len(paras) != 3:
        print(f"Warning: model returned {len(paras)} paragraphs, expected 3.",
              file=sys.stderr)
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", type=Path, help="path to the PDF to summarize")
    ap.add_argument("-o", "--output", type=Path,
                    help="output .txt path (default: <pdf name>_summary.txt)")
    ap.add_argument("-m", "--model", default=DEFAULT_MODEL,
                    help=f"TAMU AI model id (default: {DEFAULT_MODEL})")
    ap.add_argument("--no-open", dest="open_after", action="store_false",
                    help="don't open the summary in TextEdit when done")
    args = ap.parse_args()

    if not args.pdf.is_file():
        raise SystemExit(f"No such file: {args.pdf}")

    out_path = args.output or args.pdf.with_name(args.pdf.stem + "_summary.txt")

    try:
        summary = summarize(args.pdf, args.model)
    except TamuAIError as exc:
        raise SystemExit(f"TAMU AI call failed: {exc}")

    header = f"Summary of: {args.pdf.name}\nGenerated with TAMU AI ({args.model})\n"
    out_path.write_text(header + "\n" + summary + "\n", encoding="utf-8")

    print(f"Wrote {out_path}", file=sys.stderr)

    if args.open_after:
        open_in_textedit(out_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())

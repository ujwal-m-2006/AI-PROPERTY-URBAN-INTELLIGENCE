"""OCR the zoning notification so its clauses can be read at all.

The Zonal Regulations to RMP-2015 — notification UDD 235 MNJ 2025 dated
05.01.2026 — is the instrument that governs FAR, height, setbacks, coverage and
parking for Bengaluru. It is published as a **7-page scan with no text layer**,
which is why the rules engine has never been able to transcribe a single clause
and why every regulatory output was UNAVAILABLE.

This renders each page and runs OCR on it, producing a text layer the project
can actually read.

WHAT THIS DOES NOT DO
---------------------
It does not make the numbers authoritative. OCR on a scanned government gazette
misreads digits — 1 and 7, 5 and 6, decimal points, and table cell boundaries
are all routine failures. A FAR of 1.75 misread as 1.25 would be worse than no
FAR at all, because it would look right.

So the output here is **candidate text with per-line confidence**, saved
verbatim. Nothing is encoded into the rules engine by this script. A human reads
the extraction next to the page image and confirms each clause, and only
confirmed clauses become rules.

    python etl/flows/ocr_zoning_notification.py
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "regulations"
OUT = ROOT / "data" / "processed"

SOURCE_PAGE = ("https://data.opencity.in/dataset/"
               "greater-bengaluru-amendment-regulations-2025")
PDF_URL = ("https://data.opencity.in/dataset/31a482fe-4ffd-4929-a61d-2fdcca90be91/"
           "resource/36f1c5e6-5f5d-4356-bfba-00c5fe1020e2/download/"
           "udd-235-mnj-2025e-05.01.2026.pdf")
REFERENCE = "UDD 235 MNJ 2025"
NOTIFIED_ON = "2026-01-05"

USER_AGENT = ("GBA-Property-Intelligence/0.1 (academic research prototype; "
              "contact via project README)")

RENDER_SCALE = 3          # ~300 dpi; below this the table digits smear
MIN_CONFIDENCE = 0.60     # lines below this are kept but flagged

# Terms whose surrounding lines are worth surfacing for a human to check first.
TERMS = ("far", "f.a.r", "floor area ratio", "setback", "set back", "height",
         "coverage", "parking", "plot", "road width", "dwelling", "tenement")


def download() -> Path | None:
    RAW.mkdir(parents=True, exist_ok=True)
    dest = RAW / "udd-235-mnj-2025e-05.01.2026.pdf"
    if dest.exists() and dest.stat().st_size > 50_000:
        print(f"  cached: {dest.name} ({dest.stat().st_size:,} B)")
        return dest
    try:
        r = httpx.get(PDF_URL, headers={"User-Agent": USER_AGENT},
                      timeout=180.0, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"  download failed: {type(exc).__name__}")
        return None
    dest.write_bytes(r.content)
    print(f"  downloaded {len(r.content):,} B")
    return dest


def has_text_layer(path: Path) -> bool:
    try:
        import pypdf
    except ImportError:
        return False
    reader = pypdf.PdfReader(str(path))
    return sum(len((p.extract_text() or "").strip()) for p in reader.pages) > 200


def ocr(path: Path) -> list[dict[str, Any]]:
    import pypdfium2 as pdfium
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR()
    doc = pdfium.PdfDocument(str(path))
    pages: list[dict[str, Any]] = []

    images_dir = RAW / "pages"
    images_dir.mkdir(parents=True, exist_ok=True)

    for i in range(len(doc)):
        img = doc[i].render(scale=RENDER_SCALE).to_pil()
        img_path = images_dir / f"page_{i + 1:02d}.png"
        img.save(img_path)

        result, _elapse = engine(str(img_path))
        lines: list[dict[str, Any]] = []
        if result:
            for entry in result:
                # (box, text, confidence)
                text = str(entry[1]).strip()
                conf = float(entry[2]) if len(entry) > 2 else 0.0
                if text:
                    lines.append({"text": text, "confidence": round(conf, 3)})

        low = sum(1 for ln in lines if ln["confidence"] < MIN_CONFIDENCE)
        pages.append({
            "page": i + 1,
            "image": str(img_path.relative_to(ROOT)).replace("\\", "/"),
            "lines": lines,
            "line_count": len(lines),
            "low_confidence_lines": low,
            "mean_confidence": (round(sum(ln["confidence"] for ln in lines)
                                      / len(lines), 3) if lines else 0.0),
        })
        print(f"    page {i + 1}: {len(lines):>3} lines, "
              f"mean confidence {pages[-1]['mean_confidence']:.3f}, "
              f"{low} below {MIN_CONFIDENCE}")
    return pages


def candidates(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Lines mentioning a regulated quantity AND carrying a number.

    A shortlist for a human to check, not an extraction. A clause is only useful
    if it survives being read next to the page image.
    """
    out = []
    number = re.compile(r"\d")
    for page in pages:
        for idx, line in enumerate(page["lines"]):
            low = line["text"].lower()
            if not number.search(line["text"]):
                continue
            if not any(t in low for t in TERMS):
                continue
            out.append({
                "page": page["page"],
                "line_index": idx,
                "text": line["text"],
                "confidence": line["confidence"],
                "reliable": line["confidence"] >= MIN_CONFIDENCE,
            })
    return out


def main() -> int:
    print("OCR — Zonal Regulations to RMP-2015 (UDD 235 MNJ 2025)\n")

    print("fetching the notification ...")
    pdf = download()
    if pdf is None:
        return 2

    if has_text_layer(pdf):
        print("  this PDF has a text layer after all — OCR not needed")
        return 0
    print("  no text layer confirmed; OCR required\n")

    print("rendering and reading pages ...")
    pages = ocr(pdf)
    shortlist = candidates(pages)

    total_lines = sum(p["line_count"] for p in pages)
    low = sum(p["low_confidence_lines"] for p in pages)
    reliable = sum(1 for c in shortlist if c["reliable"])

    print(f"\n  {total_lines:,} lines across {len(pages)} pages "
          f"({low} below {MIN_CONFIDENCE} confidence)")
    print(f"  {len(shortlist)} lines mention a regulated quantity and a number")
    print(f"  {reliable} of those are above the confidence floor")

    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "instrument": "Zonal Regulations to RMP-2015",
        "reference": REFERENCE,
        "notified_on": NOTIFIED_ON,
        "source_url": SOURCE_PAGE,
        "download_url": PDF_URL,
        "extracted_at": datetime.now(UTC).isoformat(),
        "method": f"pypdfium2 render at scale {RENDER_SCALE} + RapidOCR (ONNX)",
        "status": "OCR CANDIDATE TEXT — NOT VERIFIED, NOT ENCODED",
        "pages": pages,
        "candidate_clauses": shortlist,
        "caveats": [
            "OCR ON A SCANNED GAZETTE MISREADS DIGITS. 1/7, 5/6 and decimal "
            "points are routine failures, and table cell boundaries are lost. A "
            "FAR of 1.75 misread as 1.25 would be worse than no FAR, because it "
            "would look right.",
            "NOTHING HERE IS ENCODED INTO THE RULES ENGINE. These are candidate "
            "lines for a human to confirm against the page images in "
            "data/raw/regulations/pages/.",
            "A confidence score is the OCR engine's own, and a confidently "
            "misread digit still scores high. It filters noise, not error.",
            "Only clauses a person has confirmed against the image may become "
            "rules, and each must cite its page.",
        ],
    }
    (OUT / "zoning_notification_ocr.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    print(f"\n  wrote {OUT / 'zoning_notification_ocr.json'}")
    print(f"  page images in {RAW / 'pages'}")
    print("\n  NEXT: a human confirms each candidate against its page image.")
    print("  Nothing becomes a rule until then.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

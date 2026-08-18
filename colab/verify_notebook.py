"""Execute every code cell of the notebook, in order, in one namespace.

A notebook nobody has run is a liability — it will fail in front of an examiner
on a cell nobody checked. This runs the real cells against the real data and
reports the first failure with its cell number.

It reads CSVs from the local `colab/data/` rather than the GitHub raw URL, so it
verifies the code and the data without depending on the push having landed. The
only rewrite is that one BASE line.

    python colab/verify_notebook.py
"""

from __future__ import annotations

import io
import json
import sys
import traceback
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
NB = HERE / "GBA_Property_Intelligence.ipynb"
LOCAL_DATA = HERE / "data"


def main() -> int:
    nb = json.loads(NB.read_text(encoding="utf-8"))
    cells = [c for c in nb["cells"] if c["cell_type"] == "code"]
    print(f"Executing {len(cells)} code cells from {NB.name}\n")

    # `display` is a Colab/IPython builtin; give it a plain-text stand-in.
    def display(obj):
        print(obj)

    ns: dict = {"display": display, "__name__": "__main__"}
    transcript: list[str] = []

    for i, cell in enumerate(cells, 1):
        src = "".join(cell["source"])
        # Point BASE at the local export instead of the raw GitHub URL.
        if "BASE = " in src:
            src = src.replace(
                f'BASE = "https://raw.githubusercontent.com/ujwal-m-2006/'
                f'AI-PROPERTY-URBAN-INTELLIGENCE/main/colab/data"',
                f'BASE = r"{LOCAL_DATA}"')
        first = next((ln for ln in src.splitlines() if ln.strip()), "")[:58]
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                exec(compile(src, f"cell_{i}", "exec"), ns)  # noqa: S102
        except Exception:
            print(f"  [{i:>2}/{len(cells)}] FAILED  {first}")
            print("\n" + buf.getvalue())
            traceback.print_exc()
            return 1
        out = buf.getvalue()
        transcript.append(f"### cell {i}\n{out}")
        lines = [ln for ln in out.splitlines() if ln.strip()]
        preview = lines[-1][:70] if lines else "(no output)"
        print(f"  [{i:>2}/{len(cells)}] ok      {first}")
        if lines:
            print(f"            -> {preview}")

    (HERE / "verified_output.txt").write_text(
        "Local execution transcript — every code cell, in order.\n"
        "Produced by colab/verify_notebook.py against colab/data/.\n"
        "Colab output will match except for figures.\n\n"
        + "\n".join(transcript), encoding="utf-8")

    print(f"\n  all {len(cells)} cells executed")
    print(f"  transcript: {HERE / 'verified_output.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

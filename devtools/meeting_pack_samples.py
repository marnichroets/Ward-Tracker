"""Generate sample Leadership Meeting Packs from SYNTHETIC data — LOCAL ONLY.

    python devtools/meeting_pack_samples.py OUT_DIR [scenario ...]

For each scenario writes <scenario>.pdf, <scenario>.pptx and <scenario>.json
(the pack data both formats were drawn from), renders every PDF page to PNG
with PyMuPDF (if installed) and, on Windows with PowerPoint installed, every
PowerPoint slide to PNG through PowerPoint itself. Same isolation and frozen
clock (Thursday 12 November 2026) as devtools/golden_reports.py.
"""
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import golden_reports as g  # noqa: E402  (isolation + frozen clock)
import meeting_pack  # noqa: E402

SCENARIOS = {
    "default_last_completed_week": {},                                    # 2-8 Nov 2026
    "current_week_in_progress": {"date_from": "2026-11-09", "date_to": "2026-11-15"},
    "next_week_not_started": {"date_from": "2026-11-16", "date_to": "2026-11-22"},
    "four_weeks": {"date_from": "2026-10-19", "date_to": "2026-11-15"},
    "twelve_weeks": {"date_from": "2026-08-24", "date_to": "2026-11-15"},
    "twenty_six_weeks": {"date_from": "2026-05-18", "date_to": "2026-11-15"},
    "empty_period": {"date_from": "2025-01-06", "date_to": "2025-01-12"},
}


def render_pptx(pptx: Path, out_dir: Path) -> int:
    """Export each slide to PNG through PowerPoint (Windows only)."""
    if os.name != "nt":
        return 0
    script = (
        "$ErrorActionPreference='Stop'; $pp = New-Object -ComObject PowerPoint.Application; "
        f"$p = $pp.Presentations.Open('{pptx}', $true, $false, $false); "
        "$i = 0; foreach ($s in $p.Slides) { $i++; "
        f"$s.Export(('{out_dir}' + '\\' + '{pptx.stem}_slide' + $i + '.png'), 'PNG', 1600, 900) }}; "
        "$p.Close(); $pp.Quit(); $i"
    )
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, timeout=180)
        return int(result.stdout.strip().splitlines()[-1]) if result.returncode == 0 else 0
    except Exception:
        return 0


def render_pdf(pdf: Path, out_dir: Path) -> int:
    try:
        import pymupdf
    except ImportError:
        return 0
    doc = pymupdf.open(pdf)
    for i, page in enumerate(doc, 1):
        page.get_pixmap(dpi=120).save(str(out_dir / f"{pdf.stem}_page{i}.png"))
    return len(doc)


async def build(name: str, args: dict, out: Path) -> None:
    entries, roster, campaigns = await g.main.leadership_dataset()
    pack = meeting_pack.build_meeting_pack(entries, roster, campaigns, args.get("date_from"), args.get("date_to"))
    (out / f"{name}.json").write_text(json.dumps(pack, indent=1), encoding="utf-8")
    (out / f"{name}.pdf").write_bytes(meeting_pack.meeting_pack_pdf_bytes(pack))
    (out / f"{name}.pptx").write_bytes(meeting_pack.meeting_pack_pptx_bytes(pack))


def main(out: Path, names: list[str]) -> None:
    out = out.resolve()
    images = out / "rendered"
    images.mkdir(parents=True, exist_ok=True)
    g.install_store()
    for name in names:
        asyncio.run(build(name, SCENARIOS[name], out))
        pages = render_pdf(out / f"{name}.pdf", images)
        slides = render_pptx(out / f"{name}.pptx", images)
        print(f"{name}: PDF {pages} pages rendered, PowerPoint {slides} slides rendered")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    main(Path(sys.argv[1]), sys.argv[2:] or list(SCENARIOS))

"""Wrap each dashboard's heading-led sections in one milesight-dynamic-layout card, so the page flows into a
space-filling masonry with a Packed ⇄ Rows toggle (instead of every section taking a full-width row). Run once:

    python3 tools/pack_dashboards.py

Rules, per view of type `sections`:
  * The leading sections that have no heading (the page header, onboarding, and any summary bands) stay on top,
    full width, outside the wrapper.
  * Every section from the first heading-led one onward becomes a block {heading, icon, cards} inside a single
    dynamic-layout card. The widgets are unchanged; only the layout container changes.
  * A view with fewer than two blocks to pack, or one already wrapped, is left as-is.

Idempotent: running it again changes nothing. Comments inside the section list are not preserved (the file is
re-emitted from its parsed structure); the top-of-file comment block is kept.
"""
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
DASH = ROOT / "dashboards"
SKIP_FILES = {"building_overview.example.yaml"}


def _leading_comment(text: str) -> str:
    out = []
    for line in text.splitlines():
        if line.strip() == "" or line.lstrip().startswith("#"):
            out.append(line)
        else:
            break
    block = "\n".join(out).rstrip()
    return block + "\n" if block else ""


def _is_heading_led(section: dict) -> bool:
    cards = section.get("cards") or []
    return bool(cards) and isinstance(cards[0], dict) and cards[0].get("type") == "heading"


def _already_wrapped(section: dict) -> bool:
    return any(isinstance(c, dict) and c.get("type") == "custom:milesight-dynamic-layout"
               for c in (section.get("cards") or []))


def _wrap_view(view: dict, wrap_id: str) -> bool:
    if view.get("type") != "sections":
        return False
    secs = view.get("sections") or []
    if any(_already_wrapped(s) for s in secs):
        return False
    split = 0
    while split < len(secs) and not _is_heading_led(secs[split]):
        split += 1
    lead, rest = secs[:split], secs[split:]
    if len(rest) < 2:
        return False
    blocks = []
    for s in rest:
        cards = list(s.get("cards") or [])
        heading = icon = None
        if cards and isinstance(cards[0], dict) and cards[0].get("type") == "heading":
            hc = cards.pop(0)
            heading, icon = hc.get("heading"), hc.get("icon")
        for c in cards:                                   # the wrapper controls width; drop per-card full-span hints
            if isinstance(c, dict):
                c.pop("grid_options", None)
        block = {}
        if heading:
            block["heading"] = heading
        if icon:
            block["icon"] = icon
        block["cards"] = cards
        blocks.append(block)
    wrapper = {"type": "grid", "column_span": 3, "cards": [{
        "type": "custom:milesight-dynamic-layout",
        "id": wrap_id,
        "default": "packed",
        "grid_options": {"columns": "full"},
        "sections": blocks,
    }]}
    view["sections"] = lead + [wrapper]
    return True


def main() -> int:
    changed = []
    for f in sorted(DASH.glob("*.yaml")):
        if f.name in SKIP_FILES:
            continue
        text = f.read_text(encoding="utf-8")
        cfg = yaml.safe_load(text)
        header = _leading_comment(text)
        did = False
        for i, view in enumerate(cfg.get("views", [])):
            wid = f"{f.stem}-{view.get('path') or view.get('title') or i}".lower().replace(" ", "-")
            if _wrap_view(view, wid):
                did = True
        if did:
            body = yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, default_flow_style=False, width=1000)
            f.write_text(header + body, encoding="utf-8")
            changed.append(f.name)
    print("wrapped:", ", ".join(changed) if changed else "(none — all already wrapped)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

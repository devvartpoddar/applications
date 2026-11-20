"""Bars as rows: a label, a bar, its value. The same row height, radius and
label style as the heat map and the lists, so a chart reads as part of the
same page. A click on a row sends its payload as one Shiny input, as every
other clickable thing does (see kit.heat, kit.cards)."""
from __future__ import annotations

import json

from shiny import ui

CSS = """
.kb { display: flex; flex-direction: column; gap: 2px; }
.kb-row { display: grid; grid-template-columns: var(--kb-l, 220px) minmax(60px, 1fr); gap: 12px; align-items: center; width: 100%;
  min-height: var(--k-row-h); padding: 2px 4px; border: 0; background: none; border-radius: var(--k-radius); text-align: left; font: inherit; color: inherit; }
.kb-l { font-size: var(--k-size-s); line-height: 1.25; text-align: right; overflow-wrap: normal; }
.kb-t { display: flex; align-items: center; gap: 8px; height: 18px; min-width: 0; }
.kb-f { display: block; flex: none; height: 100%; min-width: 2px; background: var(--k-bar); border-radius: var(--k-radius); }
.kb-v { font-size: 13px; font-variant-numeric: tabular-nums; white-space: nowrap; }
.kb-note { font-size: var(--k-size-s); color: var(--k-muted); margin: 6px 0 0; }
@media (max-width: 576px) { .kb-row { grid-template-columns: 110px 1fr; gap: 8px; } }
"""


def bar_rows(rows, *, label_w: int = 220, value_w: int = 96, input_id: str = "card"):
    """rows: dicts label, value, text (what is written at the end), tip (the tooltip: what it is, a line break,
    the count), payload (what a click sends; none: not clickable) and color (a bar's own colour)."""
    top = max([r["value"] for r in rows] or [0]) or 1
    out = []
    for r in rows:
        attrs = {"type": "button", "class": "kb-row", "data-tip": r.get("tip") or f"{r['label']}\n{r['text']}"}
        if r.get("payload") is not None:
            attrs["onclick"] = f"Shiny.setInputValue({json.dumps(input_id)}, {json.dumps(r['payload'], default=str)}, {{priority: 'event'}})"
        else:
            attrs["style"] = "cursor:default"
        fill = {"style": f"width:calc((100% - {value_w}px) * {r['value'] / top:.4f})" + (f";background:{r['color']}" if r.get("color") else "")}
        out.append(ui.tags.button(attrs, ui.span(r["label"], class_="kb-l"),
                                  ui.span(ui.span(fill, class_="kb-f"), ui.span(r["text"], class_="kb-v"), class_="kb-t")))
    return ui.div(*out, class_="kb", style=f"--kb-l:{label_w}px;--kb-v:{value_w}px")

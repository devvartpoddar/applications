"""A heat map drawn as an HTML table: one tile per cell with its number, an
empty cell left blank (not zero), names wrapped on the axes (never cut or
turned), and optional totals along the right and the bottom. Crisper than the
plotly grid and it can total. A click on a tile, a total or a name sends its
payload to the server as one Shiny input, as kit.card does.

It takes the width of its box: the row names get a fixed width, the columns
share the rest up to max_cell each, and below min width (a column's longest
word) the box scrolls rather than squeeze. A grid that cannot fill its box
(few columns) belongs beside another block, not alone in a wide card."""
from __future__ import annotations

import html
import json

from shiny import ui

from kit.look import ramp, ramp_ink

CSS = """
.kit-heat-wrap { overflow-x: auto; padding-bottom: 4px; }
.kit-heat { width: 100%; border-collapse: separate; border-spacing: 3px; table-layout: fixed; font-size: 13px; margin-left: -3px; }
.kit-heat th, .kit-heat td { padding: 0; font-weight: 400; vertical-align: middle; }
.kit-heat thead th { vertical-align: bottom; text-align: center; font-size: 11.5px; line-height: 1.25; color: var(--k-ink2); padding: 0 2px 4px; }
.kit-heat thead th .n, .kit-heat tbody th .n { display: block; overflow-wrap: normal; word-break: normal; }
.kit-heat tbody th { text-align: right; font-size: 12.5px; line-height: 1.25; color: var(--k-ink); padding-right: 8px; }
.kit-heat .lnk { cursor: pointer; background: none; border: 0; padding: 0; font: inherit; color: inherit; text-align: inherit; width: 100%; }
.kit-heat .lnk:hover { color: var(--k-blue); text-decoration: underline; }
.kit-heat td .h { display: flex; align-items: center; justify-content: center; width: 100%; height: var(--kh, 40px); border: 0; border-radius: var(--k-radius);
  font: inherit; font-variant-numeric: tabular-nums; color: var(--k-ink); padding: 0; }
.kit-heat td .h.e { background: var(--k-mist); cursor: default; }
.kit-heat td .h.e:hover { outline: 0; }
.kit-heat td.tot .h { background: transparent; font-weight: 600; border: 1px solid var(--k-line); }
.kit-heat td.tot .h:hover { outline-offset: -3px; }
.kit-heat .sep { width: 6px; }
.kit-heat-note { font-size: 12.5px; color: #4b5563; margin: 6px 0 0; }
"""


def _t(v: float, top: float) -> float:
    return 0.0 if not top or top <= 1 else (v - 1) / (top - 1)


def _js(input_id: str, payload) -> str:
    return f"Shiny.setInputValue({json.dumps(input_id)}, {json.dumps(payload)}, {{priority: 'event'}})"


def heat_table(rows, cols, z, *, row_tot=None, col_tot=None, grand=None, keys=None, row_keys=None, col_keys=None,
               grand_key=None, row_nav=None, col_nav=None, col_hover=None, row_hover=None, hover=None, text=None,
               cell_w: int = 56, cell_h: int = 40, label_w: int = 250, max_cell: int = 150, tot_label: str = "All",
               input_id: str = "card"):
    """rows, cols: the names on the axes. z[i][j]: the count of a cell (None for none).
    row_tot / col_tot / grand: totals, shown when given (a total counts each thing once,
    so it need not equal the sum of its cells). keys[i][j], row_keys[i], col_keys[j],
    grand_key: what a click on the cell / total sends as input[input_id]; row_nav[i] and
    col_nav[j]: what a click on the name sends. hover[i][j], row_hover, col_hover: titles.
    text[i][j]: what a cell shows instead of its number. cell_w: the least a column gets (more when a word
    of its name needs it); max_cell: the most."""
    top = max([v for r in z for v in r if v] or [0])
    # a column is wide enough for the longest word of its name: names wrap at spaces, never inside a word
    word = max([len(w) for c in cols for w in str(c).split()] or [0])
    cell_w = max(cell_w, int(word * 5.7) + 6)
    ths = [ui.tags.th(class_="c0")]
    for j, c in enumerate(cols):
        label = ui.span(c, class_="n")
        inner = ui.tags.button(label, {"type": "button", "class": "lnk", "onclick": _js(input_id, col_nav[j])}) \
            if col_nav and col_nav[j] else label
        ths.append(ui.tags.th(inner, **{"data-tip": col_hover[j] if col_hover else c}))
    if row_tot is not None:
        ths += [ui.tags.th(class_="sep"), ui.tags.th(tot_label)]

    def tile(v, payload, title, *, shown=None, t=None):
        if v in (None, 0) and shown is None:
            return ui.tags.td(ui.span(class_="h e"))
        attrs = {"type": "button", "class": "h"}
        if title:
            attrs["data-tip"] = title
        if payload:
            attrs["onclick"] = _js(input_id, payload)
        if t is not None:
            attrs["style"] = f"background:{ramp(t)};color:{ramp_ink(t)}"
        return ui.tags.td(ui.tags.button(attrs, shown if shown is not None else f"{int(v):,}"))

    body = []
    for i, r in enumerate(rows):
        label = ui.span(r, class_="n")
        head = ui.tags.button(label, {"type": "button", "class": "lnk", "onclick": _js(input_id, row_nav[i])}) \
            if row_nav and row_nav[i] else label
        tds = [ui.tags.th(head, **{"data-tip": row_hover[i] if row_hover else r}, scope="row")]
        for j in range(len(cols)):
            v = z[i][j]
            tds.append(tile(v, keys[i][j] if keys else None, hover[i][j] if hover else None,
                            shown=(text[i][j] if text and v else None), t=_t(v, top) if v else None))
        if row_tot is not None:
            tds += [ui.tags.td(class_="sep"),
                    ui.tags.td({"class": "tot"}, ui.tags.button(
                        {"type": "button", "class": "h", "onclick": _js(input_id, row_keys[i]) if row_keys else None,
                         "data-tip": f"{r}\n{row_tot[i]:,} in all"}, f"{int(row_tot[i]):,}"))]
        body.append(ui.tags.tr(*tds))
    foot = []
    if col_tot is not None:
        tds = [ui.tags.th(tot_label, scope="row")]
        for j in range(len(cols)):
            tds.append(ui.tags.td({"class": "tot"}, ui.tags.button(
                {"type": "button", "class": "h", "onclick": _js(input_id, col_keys[j]) if col_keys else None,
                 "data-tip": f"{cols[j]}\n{col_tot[j]:,} in all"}, f"{int(col_tot[j]):,}")))
        if row_tot is not None:
            tds += [ui.tags.td(class_="sep"),
                    ui.tags.td({"class": "tot"}, ui.tags.button(
                        {"type": "button", "class": "h", "onclick": _js(input_id, grand_key) if grand_key else None,
                         "data-tip": f"All\n{grand:,}"}, f"{int(grand):,}"))]
        foot.append(ui.tags.tr(ui.tags.td(class_="sep", colspan=len(tds)), class_="sepr", style="height:3px"))
        foot.append(ui.tags.tr(*tds))
    # the total column is as wide as its numbers need; the grid's columns share the rest
    tot_w = 64 if row_tot is not None else 0
    extra = (tot_w + 3 + 9) if row_tot is not None else 0
    lo = label_w + len(cols) * (cell_w + 3) + extra + 3
    hi = label_w + len(cols) * (max(max_cell, cell_w) + 3) + extra + 3
    table = ui.tags.table(ui.tags.colgroup(ui.tags.col(style=f"width:{label_w}px"),
                                           *[ui.tags.col() for _ in cols],
                                           *([ui.tags.col(style="width:6px"), ui.tags.col(style=f"width:{tot_w}px")]
                                             if row_tot is not None else [])),
                          ui.tags.thead(ui.tags.tr(*ths)), ui.tags.tbody(*body), ui.tags.tfoot(*foot) if foot else None,
                          class_="kit-heat", style=f"--kh:{cell_h}px;min-width:{lo}px;max-width:{hi}px")
    return ui.div(table, class_="kit-heat-wrap")

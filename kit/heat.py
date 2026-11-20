"""A heat map drawn as an HTML table: one tile per cell with its number, an
empty cell left blank (not zero), names wrapped on the axes (never cut or
turned), and optional totals along the right and the bottom. Crisper than the
plotly grid and it can total. A click on a tile, a total or a name sends its
payload to the server as one Shiny input, as kit.card does."""
from __future__ import annotations

import html
import json

from shiny import ui

CSS = """
.kit-heat-wrap { overflow-x: auto; padding-bottom: 4px; }
.kit-heat { width: max-content; border-collapse: separate; border-spacing: 3px; table-layout: fixed; font-size: 13px; }
.kit-heat th, .kit-heat td { padding: 0; font-weight: 400; vertical-align: middle; }
.kit-heat thead th { vertical-align: bottom; text-align: center; font-size: 11.5px; line-height: 1.25; color: #4b5563; padding: 0 2px 4px; }
.kit-heat thead th .n, .kit-heat tbody th .n { display: block; overflow-wrap: normal; word-break: normal; }
.kit-heat tbody th { text-align: right; font-size: 12.5px; line-height: 1.25; color: var(--bs-body-color, #1b1f24); padding-right: 8px; }
.kit-heat .lnk { cursor: pointer; background: none; border: 0; padding: 0; font: inherit; color: inherit; text-align: inherit; width: 100%; }
.kit-heat .lnk:hover { color: var(--bs-primary, #2458b3); text-decoration: underline; }
.kit-heat td .h { display: flex; align-items: center; justify-content: center; width: 100%; height: var(--kh, 40px); border: 0; border-radius: 4px;
  font: inherit; font-variant-numeric: tabular-nums; color: var(--bs-body-color, #1b1f24); cursor: pointer; padding: 0; }
.kit-heat td .h:hover { outline: 2px solid var(--bs-primary, #2458b3); outline-offset: -2px; }
.kit-heat td .h.e { background: #f4f5f7; cursor: default; }
.kit-heat td .h.e:hover { outline: 0; }
.kit-heat td.tot .h { background: transparent; font-weight: 600; border: 1px solid var(--bs-border-color, #d9dde3); }
.kit-heat td.tot .h:hover { outline-offset: -3px; }
.kit-heat .sep { width: 6px; }
.kit-heat-note { font-size: 12.5px; color: #4b5563; margin: 6px 0 0; }
"""


def _shade(v: float, top: float) -> str:
    """Mist at nothing to the house's light blue at the largest count, dark numbers readable on all of it."""
    t = 0 if not top else min(1.0, v / top)
    t = t ** 0.8
    lo, hi = (231, 236, 245), (143, 176, 230)
    return "rgb(" + ",".join(str(round(a + (b - a) * t)) for a, b in zip(lo, hi)) + ")"


def _js(input_id: str, payload) -> str:
    return f"Shiny.setInputValue({json.dumps(input_id)}, {json.dumps(payload)}, {{priority: 'event'}})"


def heat_table(rows, cols, z, *, row_tot=None, col_tot=None, grand=None, keys=None, row_keys=None, col_keys=None,
               grand_key=None, row_nav=None, col_nav=None, col_hover=None, row_hover=None, hover=None, text=None,
               cell_w: int = 68, cell_h: int = 40, label_w: int = 250, tot_label: str = "All", input_id: str = "card"):
    """rows, cols: the names on the axes. z[i][j]: the count of a cell (None for none).
    row_tot / col_tot / grand: totals, shown when given (a total counts each thing once,
    so it need not equal the sum of its cells). keys[i][j], row_keys[i], col_keys[j],
    grand_key: what a click on the cell / total sends as input[input_id]; row_nav[i] and
    col_nav[j]: what a click on the name sends. hover[i][j], row_hover, col_hover: titles.
    text[i][j]: what a cell shows instead of its number."""
    top = max([v for r in z for v in r if v] or [0])
    # a column is wide enough for the longest word of its name: names wrap at spaces, never inside a word
    word = max([len(w) for c in cols for w in str(c).split()] or [0])
    cell_w = max(cell_w, int(word * 6.4) + 12)
    ths = [ui.tags.th(class_="c0")]
    for j, c in enumerate(cols):
        label = ui.span(c, class_="n")
        inner = ui.tags.button(label, {"type": "button", "class": "lnk", "onclick": _js(input_id, col_nav[j])}) \
            if col_nav and col_nav[j] else label
        ths.append(ui.tags.th(inner, title=(col_hover[j] if col_hover else c), style=f"width:{cell_w}px"))
    if row_tot is not None:
        ths += [ui.tags.th(class_="sep"), ui.tags.th(tot_label, style=f"width:{cell_w}px")]

    def tile(v, payload, title, *, shown=None, bg=None):
        if v in (None, 0) and shown is None:
            return ui.tags.td(ui.span(class_="h e"))
        attrs = {"type": "button", "class": "h", "title": title or ""}
        if payload:
            attrs["onclick"] = _js(input_id, payload)
        if bg:
            attrs["style"] = f"background:{bg}"
        return ui.tags.td(ui.tags.button(attrs, shown if shown is not None else f"{int(v):,}"))

    body = []
    for i, r in enumerate(rows):
        label = ui.span(r, class_="n")
        head = ui.tags.button(label, {"type": "button", "class": "lnk", "onclick": _js(input_id, row_nav[i])}) \
            if row_nav and row_nav[i] else label
        tds = [ui.tags.th(head, title=(row_hover[i] if row_hover else r), scope="row")]
        for j in range(len(cols)):
            v = z[i][j]
            tds.append(tile(v, keys[i][j] if keys else None, hover[i][j] if hover else None,
                            shown=(text[i][j] if text and v else None), bg=_shade(v, top) if v else None))
        if row_tot is not None:
            tds += [ui.tags.td(class_="sep"),
                    ui.tags.td({"class": "tot"}, ui.tags.button(
                        {"type": "button", "class": "h", "onclick": _js(input_id, row_keys[i]) if row_keys else None,
                         "title": f"{r}: {row_tot[i]:,}"}, f"{int(row_tot[i]):,}"))]
        body.append(ui.tags.tr(*tds))
    foot = []
    if col_tot is not None:
        tds = [ui.tags.th(tot_label, scope="row")]
        for j in range(len(cols)):
            tds.append(ui.tags.td({"class": "tot"}, ui.tags.button(
                {"type": "button", "class": "h", "onclick": _js(input_id, col_keys[j]) if col_keys else None,
                 "title": f"{cols[j]}: {col_tot[j]:,}"}, f"{int(col_tot[j]):,}")))
        if row_tot is not None:
            tds += [ui.tags.td(class_="sep"),
                    ui.tags.td({"class": "tot"}, ui.tags.button(
                        {"type": "button", "class": "h", "onclick": _js(input_id, grand_key) if grand_key else None,
                         "title": f"All: {grand:,}"}, f"{int(grand):,}"))]
        foot.append(ui.tags.tr(ui.tags.td(class_="sep", colspan=len(tds)), class_="sepr", style="height:3px"))
        foot.append(ui.tags.tr(*tds))
    table = ui.tags.table(ui.tags.colgroup(ui.tags.col(style=f"width:{label_w}px"),
                                           *[ui.tags.col(style=f"width:{cell_w}px") for _ in cols],
                                           *([ui.tags.col(style="width:6px"), ui.tags.col(style=f"width:{cell_w}px")]
                                             if row_tot is not None else [])),
                          ui.tags.thead(ui.tags.tr(*ths)), ui.tags.tbody(*body), ui.tags.tfoot(*foot) if foot else None,
                          class_="kit-heat", style=f"--kh:{cell_h}px")
    return ui.div(table, class_="kit-heat-wrap")

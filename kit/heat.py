"""A heat map drawn as an HTML table: one tile per cell with its number, an
empty cell left blank (not zero), names wrapped on the axes (never cut or
turned), and optional totals along the right and the bottom. Crisper than the
plotly grid and it can total. A click on a tile, a total or a name sends its
payload to the server as one Shiny input, as kit.card does.

It takes the whole width of its box: the row names get a fixed width, the
columns share the rest, and below a least width (a column's longest word) the
box scrolls rather than squeeze. Columns can come in groups (say, by asset,
then by instrument): each group gets a small label above it, a thin divider
before it, and its own shading, since its counts are of a different split.
The total stays apart at the far right."""
from __future__ import annotations

import json

from shiny import ui

from kit.look import ramp, ramp_ink

CSS = """
.kit-heat-wrap { overflow-x: auto; padding-bottom: 2px; }
.kit-heat { width: 100%; border-collapse: separate; border-spacing: 3px; table-layout: fixed; font-size: var(--k-fs-b); margin-left: -3px; }
.kit-heat th, .kit-heat td { padding: 0; font-weight: 400; vertical-align: middle; }
.kit-heat thead th { vertical-align: bottom; text-align: center; font-size: var(--k-fs-s); line-height: var(--k-lh-s); color: var(--k-ink2); padding: 0 2px 4px; }
.kit-heat thead tr.grp th { padding: 0 2px 2px; font-weight: 600; color: var(--k-muted); text-align: left; }
.kit-heat thead tr.grp th.g span { display: block; border-bottom: 1px solid var(--k-line); padding-bottom: 2px; }
.kit-heat thead th .n, .kit-heat tbody th .n { display: block; overflow-wrap: normal; word-break: normal; }
.kit-heat tbody th, .kit-heat tfoot th { text-align: right; font-size: var(--k-fs-s); line-height: var(--k-lh-s); color: var(--k-ink); padding-right: 8px; }
.kit-heat tfoot th { font-weight: 600; }
.kit-heat .lnk { cursor: pointer; background: none; border: 0; padding: 0; font: inherit; color: inherit; text-align: inherit; width: 100%; }
.kit-heat .lnk:hover { color: var(--k-blue); text-decoration: underline; }
.kit-heat td .h { display: flex; align-items: center; justify-content: center; width: 100%; height: var(--kh, 38px); border: 0; border-radius: var(--k-radius);
  font: inherit; font-variant-numeric: tabular-nums; color: var(--k-ink); padding: 0; }
.kit-heat td .h.e { background: var(--k-mist); cursor: default; }
.kit-heat td .h.e:hover { outline: 0; }
.kit-heat td.tot .h { background: transparent; font-weight: 600; border: 1px solid var(--k-line); }
.kit-heat td.tot .h:hover { outline-offset: -3px; }
.kit-heat .sep { width: 6px; }
.kit-heat .div { width: 9px; position: relative; }
.kit-heat td.div::after, .kit-heat th.div::after { content: ""; position: absolute; left: 4px; top: -2px; bottom: -2px; border-left: 1px solid var(--k-line); }
.kit-heat tbody th, .kit-heat tfoot th, .kit-heat thead th.c0 { position: sticky; left: 0; z-index: 1; background: var(--bs-body-bg, #fff); }
.kit-heat-note { font-size: var(--k-fs-s); color: var(--k-muted); margin: 6px 0 0; }
"""


def _t(v: float, top: float) -> float:
    return 0.0 if not top or top <= 1 else (v - 1) / (top - 1)


def _js(input_id: str, payload) -> str:
    return f"Shiny.setInputValue({json.dumps(input_id)}, {json.dumps(payload)}, {{priority: 'event'}})"


def heat_table(rows, cols, z, *, row_tot=None, col_tot=None, grand=None, keys=None, row_keys=None, col_keys=None,
               grand_key=None, row_nav=None, col_nav=None, col_hover=None, row_hover=None, hover=None, text=None,
               groups=None, cell_w: int = 56, cell_h: int = 38, label_w: int = 250, tot_label: str = "All",
               input_id: str = "card", **_):
    """rows, cols: the names on the axes. z[i][j]: the count of a cell (None for none).
    row_tot / col_tot / grand: totals, shown when given (a total counts each thing once,
    so it need not equal the sum of its cells). keys[i][j], row_keys[i], col_keys[j],
    grand_key: what a click on the cell / total sends as input[input_id]; row_nav[i] and
    col_nav[j]: what a click on the name sends. hover[i][j], row_hover, col_hover: titles.
    text[i][j]: what a cell shows instead of its number. groups: [(label, number of columns)]
    in order, covering cols; each group is shaded on its own and set off by a divider.
    cell_w: the least a column gets (more when a word of its name needs it)."""
    groups = groups or [(None, len(cols))]
    starts, at = [], 0
    for _, n in groups:
        starts.append(at)
        at += n
    group_of = [gi for gi, (_, n) in enumerate(groups) for _ in range(n)]
    tops = [max([v for r in z for j, v in enumerate(r) if v and group_of[j] == gi] or [0]) for gi in range(len(groups))]
    word = max([len(w) for c in cols for w in str(c).split()] or [0])
    cell_w = max(cell_w, int(word * 6.0) + 6)
    divs = set(starts[1:])          # a divider before each group but the first
    tot_w = 64 if row_tot is not None else 0

    def div_cell(tag="td"):
        return getattr(ui.tags, tag)(class_="div")

    head = [ui.tags.th(class_="c0")]
    for j, c in enumerate(cols):
        if j in divs:
            head.append(div_cell("th"))
        label = ui.span(c, class_="n")
        inner = ui.tags.button(label, {"type": "button", "class": "lnk", "onclick": _js(input_id, col_nav[j])}) \
            if col_nav and col_nav[j] else label
        head.append(ui.tags.th(inner, **{"data-tip": col_hover[j] if col_hover else c}))
    if row_tot is not None:
        head += [ui.tags.th(class_="sep"), ui.tags.th(tot_label)]
    thead = [ui.tags.tr(*head)]
    if any(g for g, _ in groups):
        grp = [ui.tags.th(class_="c0")]
        for gi, (g, n) in enumerate(groups):
            if gi:
                grp.append(div_cell("th"))
            grp.append(ui.tags.th(ui.span(g or ""), colspan=n, class_="g" if g else None))
        if row_tot is not None:
            grp += [ui.tags.th(), ui.tags.th()]
        thead.insert(0, ui.tags.tr(*grp, class_="grp"))

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

    def total(v, payload, tip):
        return ui.tags.td({"class": "tot"}, ui.tags.button(
            {"type": "button", "class": "h", "onclick": _js(input_id, payload) if payload else None, "data-tip": tip}, f"{int(v):,}"))

    body = []
    for i, r in enumerate(rows):
        label = ui.span(r, class_="n")
        rh = ui.tags.button(label, {"type": "button", "class": "lnk", "onclick": _js(input_id, row_nav[i])}) \
            if row_nav and row_nav[i] else label
        tds = [ui.tags.th(rh, **{"data-tip": row_hover[i] if row_hover else r}, scope="row")]
        for j in range(len(cols)):
            if j in divs:
                tds.append(div_cell())
            v = z[i][j]
            tds.append(tile(v, keys[i][j] if keys else None, hover[i][j] if hover else None,
                            shown=(text[i][j] if text and v else None), t=_t(v, tops[group_of[j]]) if v else None))
        if row_tot is not None:
            tds += [ui.tags.td(class_="sep"), total(row_tot[i], row_keys[i] if row_keys else None, f"{r}\n{row_tot[i]:,} in all")]
        body.append(ui.tags.tr(*tds))
    foot = []
    if col_tot is not None:
        tds = [ui.tags.th(tot_label, scope="row")]
        for j in range(len(cols)):
            if j in divs:
                tds.append(div_cell())
            tds.append(total(col_tot[j], col_keys[j] if col_keys else None, f"{cols[j]}\n{col_tot[j]:,} in all"))
        if row_tot is not None:
            tds += [ui.tags.td(class_="sep"), total(grand, grand_key, f"All\n{grand:,}")]
        foot.append(ui.tags.tr(ui.tags.td(class_="sep", colspan=len(tds)), style="height:3px"))
        foot.append(ui.tags.tr(*tds))
    extra = (tot_w + 3 + 17) if row_tot is not None else 0
    lo = label_w + len(cols) * (cell_w + 3) + 12 * len(divs) + extra + 3
    colgroup = [ui.tags.col(style=f"width:{label_w}px")]
    for j in range(len(cols)):
        if j in divs:
            colgroup.append(ui.tags.col(style="width:9px"))
        colgroup.append(ui.tags.col())
    if row_tot is not None:
        colgroup += [ui.tags.col(style="width:14px"), ui.tags.col(style=f"width:{tot_w}px")]
    table = ui.tags.table(ui.tags.colgroup(*colgroup), ui.tags.thead(*thead), ui.tags.tbody(*body),
                          ui.tags.tfoot(*foot) if foot else None, class_="kit-heat", style=f"--kh:{cell_h}px;min-width:{lo}px")
    return ui.div(table, class_="kit-heat-wrap")

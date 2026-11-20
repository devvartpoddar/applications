"""One look, in one place. Every visual constant of an app built on the kit
(the font and its sizes, the blue ramp that says how much, the status colours,
the investment and policy colours, the lines and labels, the corner radius, how
a thing that can be clicked behaves) is set here once. The HTML components
read it as CSS variables (css()), the plotly figures read it as Python
(LOOK, ramp()), so a chart and a table drawn by different tools cannot drift
apart. The house palette in _brand.yml wins where it names a colour."""
from __future__ import annotations

from kit.theme import palette

_DEFAULT = {
    "font": "Inter, system-ui, sans-serif",
    # the one type scale: a page title and a big number, a subtitle, body text, small text (notes, labels, axes); two
    # weights (400, 600) and three greys (ink for text, ink2 for labels, muted for notes)
    "type": {"t": (22, 1.2), "h": (16, 1.3), "b": (14, 1.45), "s": (12.5, 1.45)},
    "size": 14, "size_s": 12.5,
    # one card: its padding, its title bar, the gap between cards
    "pad": 16, "head_h": 44, "gap": 16,
    "ink": "#1b1f24", "ink2": "#4b5563", "muted": "#6b7280", "line": "#d9dde3", "rule": "#eceef1", "mist": "#f4f5f7",
    "blue": "#2458b3", "hover": "#f4f7fc", "selected": "#dde8f9",
    # the one blue ramp that says how much (map, heat map, bars): its first step is clearly apart from the
    # no-data grey, its last a deep blue; numbers on the darker half are written in white
    "ramp": ((185, 208, 239), (141, 179, 230), (90, 143, 214), (47, 104, 189), (19, 63, 140)), "ramp_light_text": 0.5,
    "bar_t": 0.62,
    # one colour per status of a procurement package, as the plan names it: still to come in warm colours, signed and
    # under way in blues, done in green, cancelled or no longer in the plan muted
    "status": {"Planned": "#c77d00", "Tendered": "#8a4fbf", "Contract signed": "#5f8fd8", "Under implementation": "#1f4a9e",
               "Contract completed": "#1f8a70", "Cancelled": "#8d939c", "Not in latest plan": "#c2c7cf",
               "No package linked": "#9aa1ac"},
    "investment": ("#e1f1ed", "#17695a"), "policy": ("#fbefd9", "#8a5a00"),
    "radius": 4, "radius_lg": 6, "row_h": 30,
}


def look() -> dict:
    """The look: the defaults, with the brand's palette over them."""
    p = palette()
    out = dict(_DEFAULT)
    for k in ("ink", "mist", "line", "blue"):
        if p.get(k):
            out[k] = p[k]
    out["bar"] = ramp(out["bar_t"], out)
    return out


def ramp(t: float, L: dict | None = None) -> str:
    """The blue that says how much: 0 is the lightest step with data (clearly apart from the no-data grey), 1 a deep
    blue. Every map, heat map and bar takes its colour from here."""
    stops = (L or _DEFAULT)["ramp"]
    t = max(0.0, min(1.0, float(t))) * (len(stops) - 1)
    i = min(int(t), len(stops) - 2)
    f = t - i
    return "rgb(" + ",".join(str(round(a + (b - a) * f)) for a, b in zip(stops[i], stops[i + 1])) + ")"


def ramp_ink(t: float) -> str:
    """The colour a number is written in on ramp(t): dark on the light half, white on the dark half."""
    return "#ffffff" if t > _DEFAULT["ramp_light_text"] else _DEFAULT["ink"]


def css() -> str:
    """The variables every component reads, and the rules that make everything clickable behave the same way."""
    L = look()
    st = "".join(f"--k-st-{k.lower().replace(' ', '-')}: {v}; " for k, v in L["status"].items())
    ty = L["type"]
    fs = "".join(f"--k-fs-{k}: {v[0]}px; " for k, v in ty.items())
    return f"""
:root {{ {fs}--k-lh-t: {ty['t'][1]}; --k-lh: {ty['b'][1]}; --k-lh-s: {ty['s'][1]}; --k-pad: {L['pad']}px; --k-gap: {L['gap']}px;
  --bs-body-font-size: {ty['b'][0]}px; --bs-body-line-height: {ty['b'][1]}; --bs-card-spacer-y: {L['pad']}px; --bs-card-spacer-x: {L['pad']}px;
  --k-font: {L['font']}; --k-size: {L['size']}px; --k-size-s: {L['size_s']}px; --k-ink: {L['ink']}; --k-ink2: {L['ink2']};
  --k-muted: {L['muted']}; --k-line: {L['line']}; --k-rule: {L['rule']}; --k-mist: {L['mist']}; --k-blue: {L['blue']};
  --k-bar: {L['bar']}; --k-hover: {L['hover']}; --k-selected: {L['selected']}; --k-radius: {L['radius']}px;
  --k-radius-lg: {L['radius_lg']}px; --k-row-h: {L['row_h']}px; --k-inv-bg: {L['investment'][0]}; --k-inv: {L['investment'][1]};
  --k-pol-bg: {L['policy'][0]}; --k-pol: {L['policy'][1]}; {st} }}
/* the type scale everywhere: body, inputs, cards */
body {{ font-size: var(--k-fs-b); line-height: var(--k-lh); color: var(--k-ink); }}
.form-control, .form-select, .selectize-input, .selectize-input input, .selectize-dropdown, .form-check-label, .control-label,
.shiny-input-container > label, .btn, .navbar .nav-link {{ font-size: var(--k-fs-b); }}
.selectize-input, .selectize-input input {{ color: var(--k-ink); }}
.shiny-input-container > label, .control-label {{ font-weight: 600; color: var(--k-ink2); font-size: var(--k-fs-s); margin-bottom: 4px; }}
.btn-sm {{ font-size: var(--k-fs-s); }}
h1, h2, h3, .h3, .h4 {{ font-size: var(--k-fs-t); line-height: var(--k-lh-t); font-weight: 600; }}
h4, h5, h6, .h5 {{ font-size: var(--k-fs-h); line-height: var(--k-lh-t); font-weight: 600; }}
.card {{ margin-bottom: var(--k-gap); }}
.card > .card-header {{ font-size: var(--k-fs-b); font-weight: 600; line-height: var(--k-lh); padding: 0 var(--k-pad); min-height: {L['head_h']}px;
  display: flex; align-items: center; justify-content: space-between; gap: 8px; }}
.card > .card-body {{ padding: var(--k-pad); }}
.bslib-grid {{ gap: var(--k-gap); }}
.bslib-grid > .card, .bslib-grid > div > .card {{ margin-bottom: 0; }}
.bslib-grid {{ margin-bottom: var(--k-gap); }}
/* anything that can be clicked: the same pointer, the same hover, the same focus ring */
.kit-heat .h, .kb-row, tr.go, .pc-q, .pc-tab, .wbg-trow, .wbg-pkgline, .kit-card, .wbg-seg button, .pc-qchip {{ cursor: pointer; }}
.kb-row:hover, tr.go:hover td, .wbg-trow:not(.head):hover, .wbg-pkgline:hover, .pc-q:hover {{ background: var(--k-hover); }}
.kit-heat .h:hover {{ outline: 2px solid var(--k-blue); outline-offset: -2px; }}
button:focus-visible, tr.go:focus-visible, .wbg-trow:focus-visible {{ outline: 2px solid var(--k-blue); outline-offset: 1px; }}
/* one tooltip: what it is, then the count */
.kit-tip {{ position: fixed; z-index: 3000; display: none; pointer-events: none; max-width: 320px; padding: 6px 10px; border-radius: var(--k-radius);
  background: var(--k-ink); color: #fff; font: 400 var(--k-fs-s)/var(--k-lh-s) var(--k-font); box-shadow: 0 2px 8px rgba(0,0,0,.25); }}
.kit-tip b {{ display: block; font-weight: 600; }}
"""


def js() -> str:
    return """
(function () {
  var tip = document.createElement('div'); tip.className = 'kit-tip'; document.addEventListener('DOMContentLoaded', function () { document.body.appendChild(tip); });
  function place(e) {
    var w = tip.offsetWidth, h = tip.offsetHeight, x = e.clientX + 14, y = e.clientY + 16;
    if (x + w > window.innerWidth - 8) x = e.clientX - w - 14;
    if (y + h > window.innerHeight - 8) y = e.clientY - h - 12;
    tip.style.left = Math.max(4, x) + 'px'; tip.style.top = Math.max(4, y) + 'px';
  }
  document.addEventListener('mouseover', function (e) {
    var t = e.target.closest && e.target.closest('[data-tip]');
    if (!t) { tip.style.display = 'none'; return; }
    var lines = t.getAttribute('data-tip').split('\\n');
    tip.innerHTML = ''; var b = document.createElement('b'); b.textContent = lines[0]; tip.appendChild(b);
    lines.slice(1).forEach(function (l) { var d = document.createElement('div'); d.textContent = l; tip.appendChild(d); });
    tip.style.display = 'block'; place(e);
  });
  document.addEventListener('mousemove', function (e) { if (tip.style.display === 'block') place(e); });
  document.addEventListener('mouseleave', function () { tip.style.display = 'none'; });
})();
"""

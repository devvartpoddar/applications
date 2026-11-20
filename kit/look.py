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
    "size": 13.5, "size_s": 12.5, "size_xs": 11.5, "size_label": 12.5, "size_num": 13,
    "ink": "#1b1f24", "ink2": "#4b5563", "muted": "#6b7280", "line": "#d9dde3", "rule": "#eceef1", "mist": "#f4f5f7",
    "blue": "#2458b3", "ramp_lo": (231, 236, 245), "ramp_hi": (143, 176, 230), "bar": "#8fb0e6", "hover": "#f4f7fc",
    "selected": "#dde8f9",
    # one colour per stage of procurement; the dropped and the late ones are muted on purpose
    "status": {"Coming up": "#c77d00", "Planned date passed": "#d9b36f", "Under way": "#2458b3", "Completed": "#1f8a70",
               "Dropped": "#9aa1ac", "No package linked": "#9aa1ac"},
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
    return out


def ramp(t: float) -> str:
    """The blue that says how much: 0 is the faintest wash, 1 the strongest that dark numbers still read on."""
    L = look()
    t = max(0.0, min(1.0, t)) ** 0.8
    return "rgb(" + ",".join(str(round(a + (b - a) * t)) for a, b in zip(L["ramp_lo"], L["ramp_hi"])) + ")"


def css() -> str:
    """The variables every component reads, and the rules that make everything clickable behave the same way."""
    L = look()
    st = "".join(f"--k-st-{k.lower().replace(' ', '-')}: {v}; " for k, v in L["status"].items())
    return f"""
:root {{ --k-font: {L['font']}; --k-size: {L['size']}px; --k-size-s: {L['size_s']}px; --k-ink: {L['ink']}; --k-ink2: {L['ink2']};
  --k-muted: {L['muted']}; --k-line: {L['line']}; --k-rule: {L['rule']}; --k-mist: {L['mist']}; --k-blue: {L['blue']};
  --k-bar: {L['bar']}; --k-hover: {L['hover']}; --k-selected: {L['selected']}; --k-radius: {L['radius']}px;
  --k-radius-lg: {L['radius_lg']}px; --k-row-h: {L['row_h']}px; --k-inv-bg: {L['investment'][0]}; --k-inv: {L['investment'][1]};
  --k-pol-bg: {L['policy'][0]}; --k-pol: {L['policy'][1]}; {st} }}
/* anything that can be clicked: the same pointer, the same hover, the same focus ring */
.kit-heat .h, .kb-row, tr.go, .pc-q, .pc-tab, .wbg-trow, .wbg-pkgline, .kit-card, .wbg-seg button, .pc-qchip {{ cursor: pointer; }}
.kb-row:hover, tr.go:hover td, .wbg-trow:not(.head):hover, .wbg-pkgline:hover, .pc-q:hover {{ background: var(--k-hover); }}
.kit-heat .h:hover {{ outline: 2px solid var(--k-blue); outline-offset: -2px; }}
button:focus-visible, tr.go:focus-visible, .wbg-trow:focus-visible {{ outline: 2px solid var(--k-blue); outline-offset: 1px; }}
/* one tooltip: what it is, then the count */
.kit-tip {{ position: fixed; z-index: 3000; display: none; pointer-events: none; max-width: 320px; padding: 6px 10px; border-radius: var(--k-radius);
  background: var(--k-ink); color: #fff; font: 400 var(--k-size-s)/1.35 var(--k-font); box-shadow: 0 2px 8px rgba(0,0,0,.25); }}
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

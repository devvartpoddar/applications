"""What the wbg app lays out with, apart from its reactive wiring: how a frame
of activities and one of packages are prepared, the words and the small HTML
pieces (chips, strength marker, sentences, activity cards, the procurement
calendar and list, the package sheet). Nothing in this file reads the
database or an input: every function takes frames and returns tags."""
from __future__ import annotations

import html
import json
import math
import re

import pandas as pd
from shiny import ui as cui

import kit
from wbg_portfolio import app as W

# ---------------------------------------------------------------- words

NO_ASSET = "No single asset"         # an activity whose documents name no one asset (policy is an instrument, never an asset)
ASSET_SHORT = {"Connectivity networks": "Connectivity", "Digital platforms and systems": "Digital platforms",
               "Monitoring, warning and control systems": "Monitoring and control"}
DOC_KIND = {"pad": "Appraisal document", "additional_financing": "Additional financing paper",
            "restructuring": "Restructuring paper", "project_paper_other": "Project paper"}
# How far above its threshold a sentence's probability is, shown as one to three bars and never as a number.
STRENGTH = ((0.95, 3, "Well above the threshold"), (0.88, 2, "Above the threshold"), (0.0, 1, "Near the threshold"))
# The status of a procurement package, by the names the procurement plan itself uses (the reader's package_status),
# in the order a package moves through them, then the two ways it leaves the plan. The reader also says Overdue: a
# package still Planned whose planned date is behind us with no notice or signing recorded. It is the same status,
# so it is shown as Planned, drawn hollow and noted "date passed".
STATUSES = ("Planned", "Tendered", "Contract signed", "Under implementation", "Contract completed", "Cancelled",
            "Not in latest plan")
SAME_STATUS = {"Overdue": "Planned"}
TO_COME = ("Planned", "Tendered")
STATUS_COLOR = kit.look()["status"]
TABS = (*STATUSES, "All")
LATE_NOTE = "date passed"
REGION_SHORT = {"Eastern and Southern Africa": "AFE", "Western and Central Africa": "AFW",
                "East Asia and Pacific": "EAP", "Europe and Central Asia": "ECA",
                "Latin America and Caribbean": "LAC", "South Asia": "SAR",
                "Middle East, North Africa, Afghanistan, and Pakistan": "MENAAP", "Middle East and North Africa": "MENA"}


def short_asset(a):
    return ASSET_SHORT.get(a, a)


def short_region(r):
    return REGION_SHORT.get(r, r)


def short_type(t):
    return "No type stated" if t == W.NO_TYPE else str(t).removeprefix("OTH. ")


def plural(n, word):
    return f"{int(n):,} {word}{'' if n == 1 else 's'}"


def no_kind(s):
    """The word 'kind' is not used on the dashboard: a type is a type."""
    if not isinstance(s, str):
        return s
    return re.sub(r"\bKinds\b", "Types", re.sub(r"\bkinds\b", "types", re.sub(r"\bKind\b", "Type", re.sub(r"\bkind\b", "type", s))))


def short_def(text, n=2):
    """(the first n sentences, the rest) of a definition written for the model."""
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return " ".join(parts[:n]), " ".join(parts[n:])


def definition_block(text, n=2, **kw):
    """A definition as a reader wants it: its first sentences, the rest behind 'more'."""
    first, rest = short_def(text, n)
    if not first:
        return None
    return cui.div(cui.span(first), cui.tags.details(cui.tags.summary("more"), cui.span(rest), class_="wbg-more") if rest else None,
                   class_="wbg-def", **kw)


def n_acts(n):
    return f"{int(n):,} {'activity' if n == 1 else 'activities'}"


def money(usd):
    """One way of writing an amount: US$1.2 million, or US$340,000 under a million."""
    if usd is None or pd.isna(usd):
        return "no estimate"
    return f"US${usd / 1e6:,.1f} million" if abs(usd) >= 1e6 else f"US${usd:,.0f}"


def day(d, fmt="%d %b %Y"):
    return "" if d is None or pd.isna(d) else f"{pd.Timestamp(d):{fmt}}"


def ago(d):
    return day(d) or "no date"


def split(v):
    return [x for x in str(v).split(W.SEPARATOR) if x] if isinstance(v, str) and v else []


def js(input_id, payload):
    return f"Shiny.setInputValue({json.dumps(input_id)}, {json.dumps(payload, default=str)}, {{priority: 'event'}})"


def clicker(payload, input_id="card"):
    return {"onclick": js(input_id, payload)}


def source(kind, date):
    name = DOC_KIND.get(kind, "Project document")
    return f"{name}, {pd.Timestamp(date):%d %b %Y}" if date is not None and pd.notna(date) else name


# ---------------------------------------------------------------- frames

def axis_values(assets_df):
    """The asset axis, in the order the dashboard shows it: the assets, then no single asset."""
    names = list(dict.fromkeys(assets_df["asset_name"])) if len(assets_df) else []
    return names + [NO_ASSET]


def prep_acts(df, stages=None):
    """The activities frame with what the pages need beside the reader's columns: the asset axis
    values (one per asset, or No single asset), the asset types, the
    types as lists, the procurement summary and the instrument as a word."""
    df = df.copy()
    if df.empty:
        for c in ("assets", "asset_types", "types", "type_id_list"):
            df[c] = pd.Series(dtype=object)
        for c in ("stage", "chip", "pk_stage", "pk_date", "pk_id", "pk_n", "pk_late"):
            df[c] = pd.Series(dtype=object)
        return df

    def assets(r):
        a = [x for x in (r["asset_name"], r["asset2_name"]) if isinstance(x, str) and x]
        return a or [NO_ASSET]

    df["assets"] = [assets(r) for _, r in df.iterrows()]
    df["asset_types"] = [[no_kind(x) for x in (a, b) if isinstance(x, str) and x]
                         for a, b in zip(df["subtype_name"], df["subtype2_name"])]
    df["types"] = df["type_names"].map(split)
    df["type_id_list"] = df["type_ids"].map(split)
    df["chip"] = df["instrument"].map({"investment": "Investment", "policy": "Policy"}).fillna("")
    df["place"] = df["place"].fillna("")
    df["component"] = [(f"{n} {m}".strip() if isinstance(m, str) else "No component stated")
                       if True else "" for n, m in zip(df["component_number"].fillna(""), df["component_name"])]
    return df


def prep_pkgs(pk):
    """Packages with the date that matters (the next one while still to come, else the signing date,
    else the date it was due), its quarter, the activities it serves as a list, and its status as a
    tab."""
    pk = pk.copy()
    if pk.empty:
        for c in ("date", "q", "acts", "tab", "late"):
            pk[c] = pd.Series(dtype=object)
        return pk
    pk["date"] = pd.to_datetime(pk["next_date"].fillna(pk["signed_date"]).fillna(pk["due_date"]))
    pk["q"] = [f"{d.year}Q{(d.month - 1) // 3 + 1}" if pd.notna(d) else None for d in pk["date"]]
    pk["acts"] = pk["activity_ids"].map(split)
    today = pd.Timestamp.today().normalize()
    # The status as the plan names it; Overdue is Planned with its date behind us, kept as a flag (late).
    pk["tab"] = pk["package_status"].map(lambda v: SAME_STATUS.get(v, v))
    pk["late"] = [st == "Overdue" or (t == "Planned" and pd.notna(d) and d < today)
                  for st, t, d in zip(pk["package_status"], pk["tab"], pk["date"])]
    return pk


def link_procurement(acts, pk):
    """Adds to each activity where its procurement stands: the status of its least advanced linked
    package, and the next (else latest) package with its status and date."""
    acts = acts.copy()
    cols = ["stage", "pk_stage", "pk_date", "pk_id", "pk_n", "pk_late"]
    if acts.empty:
        for c in cols:
            acts[c] = pd.Series(dtype=object)
        return acts
    best: dict = {}
    order = {s: i for i, s in enumerate(STATUSES)}
    for r in pk.itertuples():
        for a in r.acts:
            cur = best.setdefault(a, {"stage": None, "n": 0, "next": None, "last": None})
            cur["n"] += 1
            if cur["stage"] is None or order.get(r.tab, 99) < order.get(cur["stage"], 99):
                cur["stage"] = r.tab
            if r.tab in TO_COME and pd.notna(r.date) and (cur["next"] is None or r.date < cur["next"][0]):
                cur["next"] = (r.date, r.package_id, r.tab, bool(r.late))
            if pd.notna(r.date) and (cur["last"] is None or r.date > cur["last"][0]):
                cur["last"] = (r.date, r.package_id, r.tab, bool(r.late))
    st, pst, pdt, pid, pn, pl = [], [], [], [], [], []
    for a in acts["activity_id"]:
        b = best.get(a)
        if not b:
            st.append("No package linked"); pst.append(None); pdt.append(pd.NaT); pid.append(None); pn.append(0); pl.append(False)
            continue
        pick = b["next"] or b["last"]
        st.append(b["stage"]); pn.append(b["n"])
        pst.append(pick[2] if pick else b["stage"]); pdt.append(pick[0] if pick else pd.NaT)
        pid.append(pick[1] if pick else None); pl.append(pick[3] if pick else False)
    acts["stage"], acts["pk_stage"], acts["pk_date"], acts["pk_id"], acts["pk_n"], acts["pk_late"] = st, pst, pdt, pid, pn, pl
    return acts


def filter_acts(df, where):
    """The activities that meet a click's `where`: a column equal to a value, or one of the few
    keys that mean more (an asset the activity applies to, a type, a procurement stage, a list of
    activities)."""
    for k, v in (where or {}).items():
        if k == "asset":
            df = df[df["assets"].map(lambda a: v in a)]
        elif k == "asset_type":
            df = df[df["asset_types"].map(lambda a: v in a)]
        elif k == "type":
            df = df[df["n_types"] == 0] if v == W.NO_TYPE else df[df["type_id_list"].map(lambda a: v in a)]
        elif k == "activity_ids":
            df = df[df["activity_id"].isin(v)]
        elif k == "instrument":
            df = df[df["instrument"] == v]
        elif k == "approval_fiscal_year":
            df = df[df[k] == v]
        else:
            df = df[df[k] == v]
    return df


# ---------------------------------------------------------------- small pieces

def chip(instrument):
    if not instrument:
        return None
    return cui.span("Investment" if instrument in ("investment", "Investment") else "Policy",
                    class_="wbg-chip " + ("inv" if str(instrument).lower() == "investment" else "pol"))


def strength(p):
    """Three small bars for how far above the threshold a sentence sits."""
    if p is None or pd.isna(p):
        return None
    level, label = next((lv, lb) for at, lv, lb in STRENGTH if p >= at)
    bars = [cui.span(style=f"display:inline-block;width:4px;height:{6 + 3 * i}px;margin-right:2px;border-radius:1px;"
                           f"background:{'var(--k-blue)' if i < level else 'var(--k-line)'}") for i in range(3)]
    return cui.span(*bars, style="display:inline-flex;align-items:flex-end;margin-right:8px",
                    **{"aria-label": label, "data-tip": label})


def status_mark(status, late=False, **attrs):
    """The small square of a status, as the calendar draws it: filled, or hollow for a Planned package whose date
    has passed."""
    c = STATUS_COLOR.get(status, STATUS_COLOR["No package linked"])
    style = f"box-shadow: inset 0 0 0 1.5px {c}; background: #fff" if late else f"background:{c}"
    return cui.span(class_="sq", style=style, **attrs)


def status_dot(status, late=False, text=None):
    """A package's status in words beside its square; 'date passed' after a Planned package's date has gone by."""
    return cui.span(status_mark(status, late), cui.span(text or status),
                    cui.span(f" · {LATE_NOTE}", class_="late") if late else None, class_="wbg-st")


def sentence(s):
    """One sentence in full, with the strength marker, the document kind and date, the section and the
    page link; 'kept on second look' small beneath when that is how it was decided."""
    page = cui.a(f"page {int(s['page_number'])}", href=s["pdf_url"], target="_blank") \
        if s.get("pdf_url") and pd.notna(s.get("page_number")) else None
    where = source(s.get("document_kind"), s.get("document_date"))
    sec = s.get("section_title")
    foot = [strength(s.get("posterior_probability")), where,
            f" · {sec}" if isinstance(sec, str) and sec else "", " · " if page else "", page]
    out = [kit.quote(s["text"], *foot, limit=100000)]
    if s.get("decided_by") == "second_look":
        out.append(cui.div("kept on second look", class_="wbg-muted-s", style="margin:-2px 0 6px 13px"))
    return cui.div(*out, class_="wbg-sentence")


def applied_to(r):
    """'Data hosting · Cloud hosting and computing services', or the policy axis name."""
    parts = []
    for i, a in enumerate(r["assets"]):
        t = r["asset_types"][i] if i < len(r["asset_types"]) else None
        parts.append(f"{short_asset(a)} · {t}" if t and a != NO_ASSET else short_asset(a))
    return parts


def type_tags(r, limit=2):
    ts = r["types"]
    shown = [kit.tag(short_type(t), "outline", title="Type") for t in ts[:limit]]
    if len(ts) > limit:
        shown.append(cui.span(f"+{len(ts) - limit}", class_="wbg-muted-s", **{"data-tip": "; ".join(short_type(t) for t in ts[limit:])}))
    if not ts:
        shown = [cui.span("No type stated", class_="wbg-muted-s")]
    return shown


def package_line(p):
    """One linked package as a row inside an activity card or the package sheet: status, date, number and
    description; a click opens the package."""
    return cui.tags.button(
        {"type": "button", "class": "wbg-pkgline", **clicker({"pkg": p["package_id"]})},
        cui.span(status_dot(p["tab"], p["late"]), class_="s"),
        cui.span(day(p["date"]) or "no date", class_="d"),
        cui.span(p["package_number"] or p["package_id"], class_="n"),
        cui.span(p["description"] or "", class_="x"))


def activity_card(a, sents, pkgs, *, open=False, show_project=False):
    """One activity in the side panel: label, Investment/Policy chip, type, asset and asset type,
    component, sentence count; opened it shows its sentences in full and then its linked packages."""
    meta = [chip(a["instrument"])] + type_tags(a)
    for t in applied_to(a):
        meta.append(kit.tag(t, "tint", title="Applied to"))
    n = int(a["n_sentences"])
    body = [sentence(s) for _, s in sents.iterrows()] or [cui.p("No sentences in this view.", class_="wbg-muted-s")]
    if len(pkgs):
        body.append(cui.div(cui.div("Linked procurement", class_="wbg-sub"),
                            *[package_line(p) for _, p in pkgs.iterrows()], class_="mt-2"))
    return cui.tags.details(
        cui.tags.summary(
            cui.div(cui.span(a["activity_label"], class_="lbl"),
                    cui.span(plural(n, "sentence"), class_="cnt")),
            cui.div(*meta, class_="tags"),
            cui.div(a["component"] + (f" · {a['project_name']}" if show_project else ""), class_="wbg-muted-s")),
        cui.div(*body, class_="inner"), class_="wbg-act", open="" if open else None)


# ---------------------------------------------------------------- procurement

def proc_quarters(pk, today):
    d = pk.dropna(subset=["date"])
    tq = pd.Period(today, "Q")
    lo = min(d["date"].min().to_period("Q"), tq) if len(d) else tq
    hi = max(d["date"].max().to_period("Q"), tq) if len(d) else tq
    qs = list(pd.period_range(lo, hi, freq="Q"))
    while len(qs) < 8:
        qs.append(qs[-1] + 1)
    return qs


def first_tab(pk, tab):
    """The status tab to show: the one chosen, unless it has no package here; then the first status that has one."""
    if tab == "All" or (pk["tab"] == tab).any():
        return tab
    return next((t for t in STATUSES if (pk["tab"] == t).any()), "All")


def proc_legend(pk, key, tab=None):
    """The statuses present, each with its square and count, listed once. With tab, the legend is also the tabs of the
    list under the calendar: a click on a status lists its packages, All lists every one. A status with no package
    here is left out. The hollow square for a Planned package whose date has passed gets one short note."""
    items = []
    several = pk["tab"].nunique() > 1
    for t in (*STATUSES, "All") if tab is not None and several else STATUSES:
        n = len(pk) if t == "All" else int((pk["tab"] == t).sum())
        if not n:
            continue
        inner = (status_mark(t) if t != "All" else None, t, cui.span(f"{n:,}", class_="c"))
        if tab is None:
            items.append(cui.span(*inner, class_="lg"))
        else:
            items.append(cui.tags.button({"type": "button", "class": "lg pc-tab" + (" on" if t == tab else ""),
                                          **clicker({"key": key, "tab": t}, "pc")}, *inner))
    late = int(pk["late"].sum())
    if late:
        items.append(cui.span(status_mark("Planned", True), f"{LATE_NOTE} {late:,}", class_="lg note",
                              **{"data-tip": "Planned, date passed\nStill planned, but the planned date is behind us and no notice "
                                             "or signing is recorded. A past date is what the plan records, not evidence of delay."}))
    return cui.div(*items, class_="pc-legend" + (" tabs" if tab is not None else ""))


def proc_calendar(pk, key, sel_q, today, tab=None):
    """One small square per linked package, stacked by quarter on a time axis, coloured by status, a line
    for today. A click on a quarter filters the list under it. tab: the status listed under it, when the legend is
    also the list's tabs."""
    d = pk.dropna(subset=["date"])
    legend = proc_legend(pk, key, tab)
    undated = len(pk) - len(d)
    if d.empty:
        return cui.div(legend, cui.p("No linked package has a date.", class_="wbg-muted-s"))
    qs = proc_quarters(pk, today)
    nq = len(qs)
    per_row = 5 if nq <= 14 else 4 if nq <= 24 else 3 if nq <= 36 else 2
    counts = d.groupby("q").size()
    rows = max(1, math.ceil(counts.max() / per_row))
    height = rows * 11 + 6
    order = {t: i for i, t in enumerate(TABS)}
    cols = []
    for q in qs:
        name = f"{q.year}Q{q.quarter}"
        mine = d[d["q"] == name].assign(o=lambda x: x["tab"].map(order)).sort_values(["o", "late", "date"])
        sq = [status_mark(r.tab, r.late,
                       **{"data-tip": f"{r.package_number or r.package_id} · {(r.description or '')[:70]}\n{r.tab}"
                                      + (f", {LATE_NOTE}" if r.late else "")})
              for r in mine.itertuples()]
        tip = f"{q.year} Q{q.quarter}\n" + (", ".join(f"{int((mine['tab'] == t).sum())} {t.lower()}" for t in STATUSES
                                                       if (mine["tab"] == t).any()) or "no packages")
        cols.append(cui.tags.button(*sq, {"type": "button", "class": "pc-q" + (" sel" if sel_q == name else "")
                                          + (" y" if q.quarter == 1 else ""), "data-tip": tip,
                                          **clicker({"key": key, "q": name}, "pc")}))
    axis = []
    for q in qs:
        axis.append(cui.span(cui.span(f"Q{q.quarter}", class_="q"),
                             cui.span(str(q.year), class_="yr") if q.quarter == 1 or q == qs[0] else None,
                             class_="pc-ax" + (" y" if q.quarter == 1 else "")))
    t = pd.Timestamp(today)
    idx = qs.index(pd.Period(t, "Q"))
    qstart = pd.Period(t, "Q").start_time
    frac = (t - qstart) / (pd.Period(t, "Q").end_time - qstart)
    left = (idx + min(frac, 1)) / nq * 100
    chart = cui.div(
        cui.div(*cols, cui.div(cui.span("today"), class_="pc-today" + (" r" if left > 90 else ""), style=f"left:{left:.2f}%"),
                class_="pc-cols", style=f"height:{height}px"),
        cui.div(*axis, class_="pc-axis"), class_="pc-chart", style=f"min-width:{nq * per_row * 11}px")
    note = cui.p(cui.span("One square per package, by quarter. Click a quarter to list it.",
                          **{"data-tip": "One square per package\nIn the quarter of its planned date, its signing date once signed, "
                                         "or the date it was due."}),
                 f" {plural(undated, 'package')} with no date not shown." if undated else None, class_="wbg-muted-s mt-1 mb-0")
    return cui.div(legend, cui.div(chart, class_="pc-scroll"), note)


SORTS = {"date": ("Date", ["date", "package_number"]), "country": ("Country", ["place", "date"]),
         "project": ("Project", ["project_name", "date"]), "amount": ("Estimate", ["estimated_amount_usd", "date"])}


def proc_for(r, names):
    """What a package is for: the measures its strong links name, else the asset it shares with the activities."""
    if r["measure_names"]:
        return cui.span(r["measure_names"], **{"data-tip": r["measure_names"]})
    shared = [names.get(a, a) for a in split(r["shared_asset_ids"])] or split(r["asset_names"])
    return cui.span("Same asset: " + "; ".join(short_asset(x) for x in shared) if shared else "", class_="wbg-muted-s")


def proc_list(pk, key, tab, sort, desc, limit, sel_q, asset_names, *, tabs=True, hide=(), page=None):
    """The list under the calendar: status tabs, then one row per package. A click opens the package."""
    head = []
    if sel_q:
        y, q = sel_q.split("Q")
        head.append(cui.tags.button({"type": "button", "class": "pc-qchip", "data-tip": "Show every quarter",
                                     **clicker({"key": key, "q": sel_q}, "pc")}, f"{y} Q{q}  ×"))
    view = pk if tab == "All" else pk[pk["tab"] == tab]
    if sel_q:
        view = view[view["q"] == sel_q]
    col, sec = SORTS[sort][1][0], SORTS[sort][1][1:]
    # what is still to come before what is late: on the Planned tab by date, the packages whose date has passed go last
    first = ["late"] if sort == "date" and tab == "Planned" else []
    view = view.sort_values([*first, col, *sec], ascending=[*[True] * len(first), not desc, *[True] * len(sec)], na_position="last", kind="stable")
    total = len(view)
    view = view.head(limit) if page is None else view.iloc[page * limit:(page + 1) * limit]

    def th(name, label, cls=""):
        if name not in SORTS:
            return cui.tags.th(label, class_=cls)
        on = sort == name
        return cui.tags.th(cui.tags.button({"type": "button", "class": "srt" + (" on" if on else ""),
                                            **clicker({"key": key, "sort": name}, "pc")},
                                           label, cui.span(("▾" if desc else "▴") if on else "", class_="ar")), class_=cls)

    cols = [("date", "Date", "w-date"), ("pkg", "Package", "w-pkg"), ("desc", "Description", ""),
            ("project", "Project", "w-proj"), ("country", "Country", "w-ctry"), ("cat", "Category", "w-cat"),
            ("method", "Method", "w-meth"), ("amount", "Estimate", "w-amt r"), ("for", "What it is for", "w-for")]
    if pk["project_id"].nunique() == 1:
        hide = (*hide, "project", "country")      # every row is the same project: say it once, not on each row
    cols = [c for c in cols if c[0] not in hide]
    thead = cui.tags.tr(*[th(n if n in SORTS else "", l, c) for n, l, c in cols])
    body = []
    for _, r in view.iterrows():
        cells = {"date": cui.tags.td(day(r["date"]) or "no date", cui.div(LATE_NOTE, class_="late") if r["late"] else None, class_="w-date"),
                 "pkg": cui.tags.td(r["package_number"] or r["package_id"], class_="w-pkg"),
                 "desc": cui.tags.td(cui.div(r["description"] or "", class_="clamp"), status_dot(r["tab"])
                                     if tab == "All" else None),
                 "project": cui.tags.td(cui.div(r["project_name"], class_="clamp"), class_="w-proj"),
                 "country": cui.tags.td(r["place"], class_="w-ctry"),
                 "cat": cui.tags.td((r["category"] or "").replace("_", " ").capitalize(), class_="w-cat"),
                 "method": cui.tags.td(cui.div(r["method_name"] or r["method_code"] or "", class_="clamp"), class_="w-meth"),
                 "amount": cui.tags.td(money(r["estimated_amount_usd"]) if pd.notna(r["estimated_amount_usd"]) else "—", class_="w-amt r"),
                 "for": cui.tags.td(cui.div(proc_for(r, asset_names), class_="clamp"), class_="w-for")}
        body.append(cui.tags.tr(*[cells[n] for n, _, _ in cols], {"class": "go", **clicker({"pkg": r["package_id"]})}))
    if not body:
        body = [cui.tags.tr(cui.tags.td("No linked packages here.", colspan=len(cols), class_="wbg-muted", style="padding:18px 8px"))]
    more = None
    if page is not None and total > limit:
        last = (total - 1) // limit
        btn = lambda label, to, off: cui.tags.button({"type": "button", "class": "btn btn-sm btn-outline-primary", "disabled": "" if off else None,
                                                     **clicker({"key": key, "page": to}, "pc")}, label)  # noqa: E731
        more = cui.div(btn("‹ Previous", page - 1, page == 0), cui.span(f"{page * limit + 1:,}–{min(total, (page + 1) * limit):,} of {total:,}", class_="wbg-muted-s mx-2"),
                       btn("Next ›", page + 1, page == last), class_="mt-2 d-flex align-items-center")
    elif page is None and total > limit:
        more = cui.div(cui.tags.button({"type": "button", "class": "btn btn-sm btn-outline-primary", **clicker({"key": key, "more": True}, "pc")},
                                       f"Show all {total:,}"), class_="mt-2")
    elif page is None and limit > 8 and total > 8:
        more = cui.div(cui.tags.button({"type": "button", "class": "btn btn-sm btn-outline-secondary", **clicker({"key": key, "fewer": True}, "pc")},
                                       "Show fewer"), class_="mt-2")
    return cui.div(cui.div(*head, class_="pc-tabs") if head else None,
                   cui.div(cui.tags.table(cui.tags.thead(thead), cui.tags.tbody(*body), class_="wbg-table pc-table"), class_="wbg-scroll"),
                   more)


# ---------------------------------------------------------------- the package sheet

def _dl(rows):
    out = []
    for k, v in rows:
        if v is None or (isinstance(v, float) and pd.isna(v)) or v == "" or (v is pd.NaT):
            v = cui.span("—", class_="wbg-muted-s")
        out += [cui.tags.dt(k), cui.tags.dd(v)]
    return cui.tags.dl(*out, class_="wbg-dl")


STEPS = STATUSES[:5]     # the way through the plan; Cancelled and Not in latest plan leave it


def stage_strip(p):
    """Where a package stands, by the plan's own statuses: Planned, Tendered, Contract signed, Under implementation,
    Contract completed, each reached step in its own colour with its date, and the date planned for the next one.
    A package cancelled or no longer in the plan shows the steps it reached and none after."""
    status = p["tab"]
    at = STEPS.index(status) if status in STEPS else None
    reached = [i <= at if at is not None else False for i in range(len(STEPS))]
    if at is None:      # left the plan: what it had reached by its dates
        reached = [True, pd.notna(p["notice_date"]), pd.notna(p["signed_date"]), False, False]
    reached[1] = reached[1] or pd.notna(p["notice_date"])
    dates = [p["planned_date"], p["notice_date"], p["signed_date"], pd.NaT, pd.NaT]
    nxt = next((i for i, r in enumerate(reached) if not r), None)
    out = []
    for i, name in enumerate(STEPS):
        c = STATUS_COLOR[name]
        if reached[i]:
            under = day(dates[i], "%d %b %Y") if pd.notna(dates[i]) else ""
            if i == 0 and p["late"]:
                under = (under + " · " if under else "") + LATE_NOTE
            cls, style = "done", f"--st:{c}"
        elif i == nxt and at is not None:
            plan = p["next_date"] if pd.notna(p["next_date"]) else p["due_date"] if pd.notna(p["due_date"]) else dates[i]
            under = ("planned " + day(plan, "%d %b %Y")) if pd.notna(plan) and not (pd.notna(dates[0]) and plan == dates[0]) else ""
            cls, style = "next", f"--st:{c}"
        else:
            under, cls, style = "", "todo", None
        out.append(cui.div(cui.span(class_="dot"), cui.div(name, class_="nm"), cui.div(under, class_="dt"),
                           class_="wbg-step " + cls, style=style))
    return cui.div(*out, class_="wbg-steps")


def package_sheet(parts, acts_cards, project_btn, names=None):
    """A package at a glance: what it is, where it stands (a status line and a strip of the stages), the amount, who
    has it, what it is for and the activities it serves. The rest of what the reader has is behind one 'More
    details'."""
    p = parts["package"].iloc[0]
    n, aw = parts["notices"], parts["awards"]
    fnum = lambda v: money(v) if pd.notna(v) else None  # noqa: E731
    names = names or {}
    estimate = [cui.span("Estimate ", class_="wbg-muted-s"), cui.span(fnum(p["estimated_amount_usd"]) or "not stated", class_="fw-semibold")]
    if pd.notna(p["contract_amount_usd"]):
        estimate += [cui.span("  ·  Contract ", class_="wbg-muted-s"), cui.span(fnum(p["contract_amount_usd"]), class_="fw-semibold")]
    muted = " · ".join(x for x in [(p["category"] or "").replace("_", " ").capitalize(),
                                   p["method_name"] or p["method_code"]] if x)
    if p["measure_names"]:
        for_ = cui.div(cui.span("For ", class_="wbg-muted-s"), cui.span(p["measure_names"]),
                       cui.div("names this measure", class_="wbg-muted-s"))
    else:
        shared = [names.get(a, a) for a in split(p["shared_asset_ids"])] or split(p["asset_names"])
        for_ = cui.div("for the same asset: " + "; ".join(short_asset(x) for x in shared), class_="wbg-muted-s") if shared else None
    comp = f"{p['component_number']} {p['component_name']}".strip() if isinstance(p["component_name"], str) or pd.notna(p["component_number"]) else None
    more = [("Component", comp), ("Market approach", p["market_approach"]), ("The plan's own status", p["plan_status"]),
            ("In the latest plan", None if pd.isna(p["in_latest_plan"]) else ("Yes" if p["in_latest_plan"] else "No")),
            ("Planned", day(p["planned_date"])), ("Revised", day(p["revised_date"])), ("Due", day(p["due_date"])),
            ("Notice", day(p["notice_date"])), ("Bid deadline", day(p["notice_deadline"])), ("Signed", day(p["signed_date"])),
            ("Actual amount", fnum(p["actual_amount_usd"])), ("Plan document", p["plan_document_id"]),
            ("Plan published", day(p["plan_disclosure_date"]))]
    detail = [_dl(more), cui.div(f"Notices ({len(n)})", class_="wbg-sub")]
    detail.append(cui.div(cui.tags.table(
        cui.tags.thead(cui.tags.tr(*[cui.tags.th(h) for h in ("Published", "Type", "Status", "Deadline", "Description")])),
        cui.tags.tbody(*[cui.tags.tr(cui.tags.td(day(r.publication_date)), cui.tags.td(r.notice_type or ""), cui.tags.td(r.notice_status or ""),
                                     cui.tags.td(day(r.deadline_date)), cui.tags.td(r.description or "")) for r in n.itertuples()]),
        class_="wbg-table mini"), class_="wbg-scroll") if len(n) else cui.p("None linked.", class_="wbg-muted-s"))
    detail.append(cui.div(f"Awards ({len(aw)})", class_="wbg-sub"))
    detail.append(cui.div(cui.tags.table(
        cui.tags.thead(cui.tags.tr(*[cui.tags.th(h) for h in ("Signed", "Supplier", "Country", "Amount", "Review")])),
        cui.tags.tbody(*[cui.tags.tr(cui.tags.td(day(r.signed_date)), cui.tags.td(r.supplier_name or ""), cui.tags.td(r.supplier_country or ""),
                                     cui.tags.td(fnum(r.total_amount_usd) or ""), cui.tags.td(r.review_type or "")) for r in aw.itertuples()]),
        class_="wbg-table mini"), class_="wbg-scroll") if len(aw) else cui.p("None linked.", class_="wbg-muted-s"))
    supplier = cui.div(cui.span("Supplier ", class_="wbg-muted-s"), cui.span(p["supplier"]),
                       cui.span(f" ({p['supplier_country']})", class_="wbg-muted-s") if p["supplier_country"] else None) if p["supplier"] else None
    return cui.div(
        cui.p(p["description"] or "", class_="mb-1 fw-semibold"),
        cui.p(cui.span(p["project_name"], " · ", p["place"]), project_btn, class_="mb-2 small"),
        cui.div(status_dot(p["tab"], p["late"]), class_="mb-1"),
        stage_strip(p),
        cui.div(*estimate, class_="mt-3"),
        cui.div(muted, class_="wbg-muted-s"),
        supplier, cui.div(for_, class_="mt-2") if for_ else None,
        cui.tags.details(cui.tags.summary("More details"), cui.div(*detail), class_="wbg-moredetails"),
        cui.div(f"Activities it serves ({len(acts_cards)})", class_="wbg-sub"),
        *(acts_cards or [cui.p("None.", class_="wbg-muted-s")]))


# ---------------------------------------------------------------- the app's own css and script

CSS = """
:root { --wbg-muted: var(--k-muted); --wbg-ink2: var(--k-ink2); --wbg-line: var(--k-line); }
.tab-pane:has(.wbg-notice) .card, .tab-pane:has(.wbg-notice) .wbg-filters, .tab-pane:has(.wbg-notice) > .d-flex, .tab-pane:has(.wbg-notice) .alert-light:not(.wbg-notice) { display: none; }
.wbg-muted { color: var(--wbg-muted); }
p.wbg-muted { font-size: var(--k-fs-s); }
.card-header .wbg-muted-s, .card-header .wbg-muted { font-weight: 400; }
.wbg-tbar.head .v { font-size: inherit; font-weight: 600; }
.pc-tab, .wbg-seg button { color: var(--k-ink); }
.btn-link, .selectize-input { line-height: var(--k-lh); }
.wbg-proc-empty .wbg-muted { font-size: var(--k-fs-s); }
.wbg-head .df .lead-in { color: var(--k-ink2); }
.wbg-muted-s { color: var(--wbg-muted); font-size: var(--k-fs-s); }
.wbg-sub { font-size: var(--k-fs-s); font-weight: 600; letter-spacing: .04em; text-transform: uppercase; color: var(--wbg-ink2); margin: 16px 0 6px; padding-bottom: 3px; border-bottom: 1px solid var(--wbg-line); }
/* the page before a group is chosen shows the start page and nothing of the app */
a.nav-link[data-value="Start"], li:has(> a.nav-link[data-value="Start"]) { display: none !important; }
.no-family .navbar-nav .nav-item, .no-family .wbg-top { display: none !important; }
.navbar .navbar-brand { font-size: var(--k-fs-h); }
.navbar .nav-link { padding-left: .6rem; padding-right: .6rem; }
.navbar-brand { display: flex; align-items: baseline; gap: 10px; white-space: nowrap; margin-right: 8px; }
.navbar .navbar-nav { flex-wrap: nowrap; align-items: center; }
.no-family .sidebar-collapse-toggle, .no-family .collapse-toggle { display: none !important; }
.wbg-fam { font-size: var(--k-fs-b); font-weight: 400; color: #c9d0da; display: inline-flex; align-items: baseline; gap: 8px; }
.wbg-fam b { color: #fff; font-weight: 600; }
.wbg-fam .sl { color: #6f7885; }
.wbg-fam a { font-size: var(--k-fs-s); color: #9bb8ea; text-decoration: underline; text-underline-offset: 2px; cursor: pointer; }
.wbg-fam a:hover { color: #fff; }
.navbar .wbg-top { display: flex; gap: 8px; align-items: center; }
.wbg-find { position: relative; }
.wbg-find-btn { color: #fff; border: 1px solid rgba(255,255,255,.45); width: 36px; height: 34px; padding: 0; display: inline-flex; align-items: center; justify-content: center; }
.wbg-find-btn:hover, .wbg-find.open .wbg-find-btn { background: rgba(255,255,255,.12); color: #fff; border-color: #fff; }
.wbg-find .box { display: none; position: absolute; right: 0; top: calc(100% + 10px); z-index: 1050; background: #fff; border-radius: var(--k-radius-lg);
  box-shadow: 0 6px 24px rgba(0,0,0,.18); padding: 8px; }
.wbg-find.open .box { display: block; }
.wbg-find .box .shiny-input-container { margin: 0; }
/* the row a page opens with: its title or intro on the left, the Count switch on the right, the same on every page */
.wbg-titlerow { display: flex; justify-content: space-between; align-items: flex-end; gap: 12px 32px; margin: 18px 0 16px; }
.wbg-titlerow > p { max-width: 110ch; }
.wbg-titlerow.ex .shiny-input-container { margin-bottom: 0; }
.wbg-titlerow > .shiny-html-output { flex: none; }
@media (max-width: 900px) { .wbg-titlerow { flex-wrap: wrap; } .wbg-titlerow > p { flex-basis: 100%; } }
.wbg-unit { display: inline-flex; align-items: center; gap: 8px; flex: none; }
.wbg-unit .lb { font-size: var(--k-fs-s); color: var(--wbg-muted); }
.navbar .wbg-top .shiny-input-container { margin-bottom: 0; }
.navbar .wbg-top .form-select, .navbar .wbg-top .selectize-input, .navbar .wbg-top .btn { font-size: var(--k-fs-b); min-height: 34px; }
/* start page */
.wbg-start { max-width: 1060px; margin: 0 auto; padding-top: 28px; }
.wbg-start h1 { font-size: var(--k-fs-t); margin-bottom: 4px; }
.wbg-start .lead { color: var(--wbg-ink2); font-size: var(--k-fs-b); margin-bottom: 22px; }
.wbg-fgrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; align-items: stretch; }
.wbg-fcard { display: flex; flex-direction: column; background: #fff; border: 1px solid var(--wbg-line); border-radius: 8px; padding: 22px 24px 20px; min-width: 0; }
.wbg-fcard h2 { font-size: var(--k-fs-t); margin: 0 0 6px; }
.wbg-fcard .desc { color: var(--wbg-ink2); font-size: var(--k-fs-b); line-height: var(--k-lh); min-height: 4.2em; margin: 0 0 14px; }
.wbg-fcard .nums { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; padding: 12px 0; border-top: 1px solid var(--wbg-line); border-bottom: 1px solid var(--wbg-line); margin-bottom: 12px; }
.wbg-fcard .nums div { min-width: 0; }
.wbg-fcard .nums b { display: block; font-size: var(--k-fs-t); font-weight: 600; line-height: var(--k-lh-t); font-variant-numeric: tabular-nums; }
.wbg-fcard .nums span { font-size: var(--k-fs-s); color: var(--wbg-muted); }
.wbg-fcard .ms-h { font-size: var(--k-fs-s); font-weight: 600; letter-spacing: .04em; text-transform: uppercase; color: var(--wbg-ink2); margin-bottom: 4px; }
.wbg-fcard ul { list-style: none; padding: 0; margin: 0 0 18px; min-height: calc(5 * 1.65em); }
.wbg-fcard li { font-size: var(--k-fs-b); line-height: var(--k-lh); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.wbg-fcard li.more { color: var(--wbg-muted); }
.wbg-fcard .btn { margin-top: auto; align-self: stretch; font-weight: 600; padding: 9px 14px; }
/* figures */
.wbg-figs { display: flex; flex-direction: column; height: 100%; }
.wbg-fig { flex: 1; display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--k-rule); }
.wbg-fig:last-child { border-bottom: 0; }
.wbg-fig .l { font-size: var(--k-fs-b); color: var(--wbg-ink2); }
.wbg-fig .l small { display: block; font-size: var(--k-fs-s); color: var(--wbg-muted); }
.wbg-fig .v { font-size: var(--k-fs-t); font-weight: 600; font-variant-numeric: tabular-nums; line-height: var(--k-lh-t); }
.wbg-fig.sub { padding-left: 14px; }
.wbg-fig.sub .v { font-size: var(--k-fs-h); font-weight: 600; }
/* tables */
.wbg-scroll { overflow-x: auto; }
.wbg-table { width: 100%; border-collapse: collapse; font-size: var(--k-fs-b); }
.wbg-table th { text-align: left; font-size: var(--k-fs-s); font-weight: 600; color: var(--wbg-ink2); padding: 6px 10px 6px 0; border-bottom: 1px solid var(--wbg-line); white-space: nowrap; vertical-align: bottom; }
.wbg-table td { padding: 8px 10px 8px 0; border-bottom: 1px solid var(--k-rule); vertical-align: top; }
.wbg-table td.r + td, .wbg-table th.r + th { padding-left: 16px; }
.wbg-table th.r, .wbg-table td.r { text-align: right; font-variant-numeric: tabular-nums; }
.wbg-table tr.go { cursor: pointer; }
.wbg-table tr.go:hover td { background: var(--k-hover); }
.wbg-table .clamp { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; line-height: var(--k-lh-s); }
.wbg-ctable { width: 100%; min-width: 900px; }
.wbg-ctable td.pn { min-width: 260px; }
.wbg-ctable th, .wbg-ctable td { white-space: nowrap; }
.wbg-ctable td.pn { white-space: normal; }
.wbg-table .id { display: block; font-size: var(--k-fs-s); color: var(--wbg-muted); }
.wbg-table.mini { font-size: var(--k-fs-s); }
.wbg-table.mini td, .wbg-table.mini th { padding: 4px 8px 4px 0; }
.wbg-chip { display: inline-block; font-size: var(--k-fs-s); font-weight: 600; padding: 1px 8px; border-radius: 99px; white-space: nowrap; }
.wbg-chip.inv { background: var(--k-inv-bg); color: var(--k-inv); }
.wbg-chip.pol { background: var(--k-pol-bg); color: var(--k-pol); }
/* procurement */
.sq { display: inline-block; width: 9px; height: 9px; border-radius: 2px; flex: none; }
.wbg-st { display: inline-flex; align-items: center; gap: 6px; font-size: var(--k-fs-b); }
.wbg-st .late, .pc-table .late { color: #8a5a00; font-size: var(--k-fs-s); }
.wbg-st .late { margin-left: -4px; }
.pc-legend { display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: var(--k-fs-b); margin-bottom: 8px; align-items: center; }
.pc-legend .lg { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
.pc-legend .lg .c { color: var(--wbg-muted); font-variant-numeric: tabular-nums; }
.pc-legend .lg { font-size: var(--k-fs-s); }
.pc-legend .lg.note { color: var(--k-muted); padding-left: 4px; }
.pc-legend.tabs { gap: 6px; margin-bottom: 10px; }
.pc-legend.tabs .pc-tab { padding: 2px 10px; gap: 6px; font-size: var(--k-fs-s); }
.pc-legend.tabs .lg.note { gap: 5px; }
.pc-scroll { overflow-x: auto; padding-bottom: 2px; }
.pc-chart { width: 100%; }
.pc-cols { position: relative; display: flex; align-items: stretch; border-bottom: 1px solid var(--wbg-line); }
.pc-q { flex: 1 1 0; min-width: 0; display: flex; flex-wrap: wrap-reverse; align-content: flex-start; gap: 2px; padding: 0 3px 2px; background: none; border: 0; border-radius: 3px; cursor: pointer; }
.pc-q:hover { background: #eef3fb; }
.pc-q.sel { background: var(--k-selected); box-shadow: inset 0 0 0 1px var(--k-blue); }
.pc-q.y { border-left: 1px solid var(--k-rule); }
.pc-today { position: absolute; top: 0; bottom: 0; width: 0; border-left: 1.5px dashed var(--k-ink2); pointer-events: none; }
.pc-today.r span { left: auto; right: 4px; }
.pc-today span { position: absolute; top: -1px; left: 4px; font-size: var(--k-fs-s); color: var(--k-ink2); background: #fff; padding: 0 2px; }
.pc-axis { display: flex; margin-top: 3px; }
.pc-ax { flex: 1 1 0; min-width: 0; display: flex; flex-direction: column; align-items: flex-start; font-size: var(--k-fs-s); color: var(--wbg-muted); padding-left: 3px; min-height: 36px; }
.pc-ax.y { border-left: 1px solid var(--k-rule); }
.pc-ax .yr { font-size: var(--k-fs-s); font-weight: 600; color: var(--wbg-ink2); white-space: nowrap; }
.pc-tabs { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin: 14px 0 8px; }
.pc-tab { border: 1px solid var(--wbg-line); background: #fff; border-radius: 99px; padding: 3px 12px; font-size: var(--k-fs-b); cursor: pointer; display: inline-flex; gap: 7px; align-items: center; white-space: nowrap; }
.pc-tab.zero { color: var(--wbg-muted); }
.pc-tab .c { color: var(--wbg-muted); font-variant-numeric: tabular-nums; }
.pc-tab.on { background: var(--k-ink); border-color: var(--k-ink); color: #fff; }
.pc-tab.on .c { color: #c9d0da; }
.pc-qchip { border: 1px solid var(--k-blue); background: var(--k-selected); color: #1a4287; border-radius: 99px; padding: 3px 12px; font-size: var(--k-fs-b); cursor: pointer; }
.pc-table { table-layout: fixed; min-width: 1100px; }
.pc-table .w-date { width: 104px; } .pc-table .w-pkg { width: 96px; } .pc-table .w-proj { width: 170px; } .pc-table .w-ctry { width: 100px; }
.pc-table .w-cat { width: 92px; } .pc-table .w-meth { width: 112px; } .pc-table .w-amt { width: 124px; } .pc-table .w-for { width: 160px; }
.pc-table td.w-pkg { overflow-wrap: anywhere; }
.pc-table .srt { background: none; border: 0; padding: 0; font: inherit; color: inherit; cursor: pointer; }
.pc-table .srt:hover, .pc-table .srt.on { color: var(--bs-primary, var(--k-blue)); }
.pc-table .srt .ar { display: inline-block; width: 12px; }
/* side panel */
.wbg-ph { margin-bottom: 10px; }
.wbg-ph h5 { margin: 0 0 4px; font-size: var(--k-fs-h); line-height: var(--k-lh-s); }
.wbg-ph .tot { font-size: var(--k-fs-b); color: var(--wbg-ink2); }
.wbg-seg { display: inline-flex; border: 1px solid var(--wbg-line); border-radius: 6px; overflow: hidden; background: #fff; }
.wbg-seg button { border: 0; background: none; padding: 4px 12px; font-size: var(--k-fs-b); cursor: pointer; border-right: 1px solid var(--wbg-line); display: inline-flex; gap: 6px; align-items: baseline; }
.wbg-seg button:last-child { border-right: 0; }
.wbg-seg button .c { color: var(--wbg-muted); font-variant-numeric: tabular-nums; font-size: var(--k-fs-s); }
.wbg-seg button.on { background: var(--k-ink); color: #fff; }
.wbg-seg button.on .c { color: #c9d0da; }
.wbg-bar { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; margin: 8px 0 12px; }
.wbg-pgroup { margin-top: 14px; }
.wbg-pgroup > header { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; padding-bottom: 4px; border-bottom: 1px solid var(--wbg-line); margin-bottom: 6px; }
.wbg-pgroup > header .t { font-weight: 600; font-size: var(--k-fs-b); }
.wbg-pgroup > header .s { font-size: var(--k-fs-s); color: var(--wbg-muted); }
.wbg-pgroup > header .btn { font-size: var(--k-fs-s); padding: 0; white-space: nowrap; }
.wbg-act { border: 1px solid var(--wbg-line); border-radius: 6px; margin-bottom: 8px; background: #fff; }
.wbg-act > summary { list-style: none; cursor: pointer; padding: 8px 10px 8px 26px; position: relative; display: flex; flex-direction: column; gap: 4px; }
.wbg-act > summary::-webkit-details-marker { display: none; }
.wbg-act > summary::before { content: "▸"; position: absolute; left: 10px; top: 8px; color: var(--wbg-ink2); }
.wbg-act[open] > summary::before { content: "▾"; }
.wbg-act[open] > summary { border-bottom: 1px solid var(--wbg-line); }
.wbg-act .lbl { font-weight: 600; font-size: var(--k-fs-b); line-height: var(--k-lh); }
.wbg-act .cnt { font-size: var(--k-fs-s); color: var(--wbg-muted); white-space: nowrap; margin-left: auto; }
.wbg-act summary > div:first-child { display: flex; gap: 10px; align-items: baseline; justify-content: space-between; }
.wbg-act .tags { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.wbg-act .tags .kit-tag { margin: 0; }
.wbg-act .inner { padding: 8px 12px 10px; }
.wbg-sentence .kit-quote { margin: 4px 0 8px; }
.wbg-pkgline { display: grid; grid-template-columns: 150px 84px 84px 1fr; gap: 8px; align-items: start; width: 100%; text-align: left; background: none; border: 0; border-top: 1px solid var(--k-rule); padding: 5px 0; font-size: var(--k-fs-s); cursor: pointer; color: inherit; }
.wbg-pkgline:hover { background: var(--k-hover); }
.wbg-pkgline .wbg-st { flex-wrap: wrap; font-size: var(--k-fs-s); }
.wbg-pkgline .x { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; color: var(--wbg-ink2); line-height: var(--k-lh-s); }
.wbg-pkgline .n { color: var(--wbg-ink2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wbg-steps { display: grid; grid-template-columns: repeat(5, 1fr); margin: 6px 0 0; }
.wbg-step { position: relative; text-align: center; padding-top: 18px; font-size: var(--k-fs-s); }
.wbg-step::before { content: ""; position: absolute; top: 5px; left: -50%; right: 50%; height: 2px; background: var(--k-line); }
.wbg-step:first-child::before { display: none; }
.wbg-step .dot { position: absolute; top: 0; left: calc(50% - 6px); width: 12px; height: 12px; border-radius: 50%; border: 2px solid var(--k-line); background: #fff; }
.wbg-step.done .dot { background: var(--st); border-color: var(--st); }
.wbg-step.done::before { background: var(--st); }
.wbg-step.next .dot { border-color: var(--st); border-style: dashed; }
.wbg-step .nm { font-weight: 600; line-height: var(--k-lh-s); } .wbg-step.todo .nm, .wbg-step.todo { color: var(--k-muted); } .wbg-step .dt { color: var(--k-muted); min-height: 1.3em; }
.wbg-moredetails { margin-top: 14px; border-top: 1px solid var(--k-line); padding-top: 8px; }
.wbg-moredetails > summary { cursor: pointer; color: var(--k-blue); font-size: var(--k-fs-b); font-weight: 600; }
.wbg-dl { display: grid; grid-template-columns: 150px 1fr; gap: 3px 12px; margin: 0; font-size: var(--k-fs-b); }
.wbg-dl dt { font-weight: 400; color: var(--wbg-muted); }
.wbg-dl dd { margin: 0; overflow-wrap: anywhere; }
/* the head of an Explore page: what it is on the left, its figures as tiles on the right */
.wbg-head { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 16px 40px; align-items: start; background: #fff; border: 1px solid var(--wbg-line);
  border-radius: var(--k-radius-lg); padding: 18px 22px; margin-bottom: 16px; box-shadow: var(--bs-box-shadow-sm, none); }
.wbg-head .kd { font-size: var(--k-fs-s); font-weight: 600; letter-spacing: .04em; text-transform: uppercase; color: var(--wbg-ink2); }
.wbg-head h3 { font-size: var(--k-fs-t); margin: 2px 0 8px; }
.wbg-head .df { color: var(--wbg-ink2); font-size: var(--k-fs-b); }
.wbg-head .nt { font-size: var(--k-fs-s); color: var(--wbg-muted); margin: 10px 0 0; max-width: 80ch; }
.wbg-head .inst { display: flex; align-items: center; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
.wbg-head .tiles { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(104px, auto); gap: 10px; }
.wbg-head .tiles > div { border: 1px solid var(--k-rule); background: var(--k-mist); border-radius: var(--k-radius-lg); padding: 10px 14px; min-width: 104px; }
.wbg-head .tiles b { display: block; font-size: var(--k-fs-t); font-weight: 600; line-height: var(--k-lh-t); font-variant-numeric: tabular-nums; }
.wbg-head .tiles span { display: block; font-size: var(--k-fs-b); color: var(--wbg-ink2); white-space: nowrap; }
.wbg-head .tiles small { display: block; font-size: var(--k-fs-s); color: var(--wbg-muted); white-space: nowrap; }
@media (max-width: 1100px) { .wbg-head { grid-template-columns: 1fr; } .wbg-head .tiles { grid-auto-flow: row; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); } }
.wbg-head.one { grid-template-columns: minmax(240px, 1fr) minmax(0, 2.2fr); align-items: center; }
.wbg-head.one h3 { margin-bottom: 4px; }
.wbg-head .facts, .wbg-pfacts .facts { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 10px 28px; }
.wbg-head .facts .k, .wbg-pfacts .facts .k { display: block; font-size: var(--k-fs-s); color: var(--k-muted); }
.wbg-head .facts .v, .wbg-pfacts .facts .v { display: block; font-size: var(--k-fs-b); font-weight: 600; white-space: nowrap; font-variant-numeric: tabular-nums; }
@media (max-width: 1360px) { .wbg-head.one { grid-template-columns: 1fr; gap: 12px; } }
/* a quiet filter as text links */
.wbg-tlinks { display: inline-flex; align-items: baseline; gap: 6px; font-size: var(--k-fs-s); }
.wbg-tlinks button { border: 0; background: none; padding: 0; color: var(--k-blue); font: inherit; cursor: pointer; }
.wbg-tlinks button:hover { text-decoration: underline; }
.wbg-tlinks button.on { color: var(--k-ink); font-weight: 600; cursor: default; text-decoration: none; }
.wbg-tlinks .c { color: var(--k-muted); font-weight: 400; }
.wbg-tlinks .dot { color: var(--k-muted); }
/* types as bars: name and one line of definition, a bar, the count */
.wbg-tbars { display: flex; flex-direction: column; }
.wbg-tbar { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(80px, 1fr) 72px; gap: 14px; align-items: center; width: 100%; text-align: left;
  background: none; border: 0; border-bottom: 1px solid var(--k-rule); padding: 7px 6px; font: inherit; color: inherit; border-radius: 0; cursor: pointer; }
.wbg-tbar:hover { background: var(--k-hover); }
.wbg-tbar.head { cursor: default; padding: 0 6px 5px; font-size: var(--k-fs-s); font-weight: 600; color: var(--wbg-ink2); border-bottom: 1px solid var(--wbg-line); }
.wbg-tbar.head:hover { background: none; }
.wbg-tbar .tx { min-width: 0; display: flex; flex-wrap: wrap; align-items: baseline; gap: 0 8px; }
.wbg-tbar .nm { font-weight: 600; font-size: var(--k-fs-b); color: var(--bs-primary, var(--k-blue)); }
.wbg-tbar .sg { font-size: var(--k-fs-s); color: var(--wbg-muted); border: 1px solid var(--wbg-line); border-radius: 99px; padding: 0 6px; }
.wbg-tbar .df { flex-basis: 100%; font-size: var(--k-fs-s); color: var(--wbg-ink2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.wbg-tbar .tr { display: block; height: 16px; }
.wbg-tbar .f { display: block; height: 100%; min-width: 2px; background: var(--k-bar); border-radius: var(--k-radius); }
.wbg-tbar .v { white-space: nowrap; text-align: right; font-variant-numeric: tabular-nums; font-size: var(--k-fs-b); }
/* a project's facts in one band */
.wbg-pfacts { display: grid; grid-template-columns: minmax(220px, 1.1fr) 3fr; gap: 12px 32px; align-items: start; }
.wbg-pfacts .nm { font-weight: 600; font-size: var(--k-fs-h); line-height: var(--k-lh-s); }
.wbg-pfacts .id { font-size: var(--k-fs-s); color: var(--wbg-muted); margin-top: 2px; }
.wbg-pfacts { grid-template-columns: minmax(200px, 300px) 1fr; }
.wbg-pfacts .facts { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 10px 28px; }
.wbg-pfacts .facts .v { white-space: nowrap; }
.wbg-pfacts .facts .k { display: block; font-size: var(--k-fs-s); color: var(--wbg-muted); }
.wbg-pfacts .facts .v { display: block; font-size: var(--k-fs-b); font-weight: 600; font-variant-numeric: tabular-nums; line-height: var(--k-lh-s); }
@media (max-width: 900px) { .wbg-pfacts { grid-template-columns: 1fr; } }
.wbg-actgrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(480px, 1fr)); gap: 0 12px; align-items: start; }
@media (max-width: 576px) { .wbg-actgrid { grid-template-columns: 1fr; } }
/* procurement with nothing linked: one line, not an empty card */
.card:has(.wbg-proc-empty) > .card-header { display: none; }
.card:has(.wbg-proc-empty) > .card-body { padding-top: 12px; padding-bottom: 12px; gap: 0; }
.card:has(.wbg-proc-empty) .shiny-html-output:empty { display: none; }
.wbg-pair { align-items: start; }
.modebar-container { display: none !important; }
#pick + .selectize-control .selectize-input > .item { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
.wbg-stack { display: flex; flex-direction: column; gap: var(--bslib-spacer, 1rem); }
.wbg-stack > .card { margin-bottom: 0; }
.wbg-proc-empty { display: flex; gap: 12px; align-items: baseline; font-size: var(--k-fs-b); }
/* lists of types, activities */
.wbg-types .wbg-trow { display: grid; grid-template-columns: 1fr 96px 80px; gap: 14px; padding: 10px 6px; border-bottom: 1px solid var(--k-rule); cursor: pointer; align-items: baseline; }
.wbg-types .wbg-trow:hover { background: var(--k-hover); }
.wbg-types .wbg-trow.head { cursor: default; padding: 4px 6px; font-size: var(--k-fs-s); font-weight: 600; color: var(--wbg-ink2); border-bottom: 1px solid var(--wbg-line); }
.wbg-types .wbg-trow.head:hover { background: none; }
.wbg-types .nm { font-weight: 600; color: var(--bs-primary, var(--k-blue)); }
.wbg-types .df { font-size: var(--k-fs-b); color: var(--wbg-ink2); margin-top: 2px; max-width: 95ch; }
.wbg-types .sg { font-size: var(--k-fs-s); color: var(--wbg-muted); margin-top: 2px; }
.wbg-types .num { text-align: right; font-variant-numeric: tabular-nums; }
.wbg-grp { border: 1px solid var(--wbg-line); border-radius: 6px; margin-bottom: 8px; background: #fff; }
.wbg-grp > summary { cursor: pointer; padding: 8px 12px; list-style: none; display: flex; gap: 10px; align-items: baseline; }
.wbg-grp > summary::-webkit-details-marker { display: none; }
.wbg-grp > summary::before { content: "▸"; color: var(--wbg-ink2); }
.wbg-grp[open] > summary::before { content: "▾"; }
.wbg-grp > summary .t { font-weight: 600; }
.wbg-grp > summary .s { color: var(--wbg-muted); font-size: var(--k-fs-s); margin-left: auto; }
.wbg-grp[open] > summary { border-bottom: 1px solid var(--wbg-line); }
.wbg-grp .wbg-table { margin: 0; } .wbg-grp .wbg-table td, .wbg-grp .wbg-table th { padding-left: 12px; } .wbg-grp .wbg-table tr:last-child td { border-bottom: 0; }
.wbg-acts { table-layout: fixed; min-width: 960px; }
.wbg-acts .a-act { width: 36%; } .wbg-acts .a-typ { width: 17%; } .wbg-acts .a-app { width: 21%; } .wbg-acts .a-chip { width: 100px; } .wbg-acts .a-pro { width: 17%; }
.wbg-acts td .tg { display: flex; flex-wrap: wrap; gap: 3px; } .wbg-acts td .kit-tag { margin: 0; }
.wbg-radios { display: flex; gap: 14px; align-items: center; font-size: var(--k-fs-b); }
.wbg-radios .shiny-input-container { margin: 0; width: auto; }
.wbg-radios .shiny-options-group { display: flex; gap: 14px; }
.wbg-radios .form-check { margin: 0; }
.wbg-filters { display: flex; flex-wrap: wrap; gap: 16px; align-items: end; margin: 14px 0; }
.wbg-filters .shiny-input-container { margin: 0; }
.wbg-filters label { font-size: var(--k-fs-s); font-weight: 600; color: var(--wbg-ink2); margin-bottom: 2px; }
.wbg-def { max-width: 80ch; line-height: var(--k-lh); }
.wbg-more > summary { display: inline; color: var(--bs-primary, var(--k-blue)); cursor: pointer; margin-left: 4px; list-style: none; }
.wbg-more > summary::-webkit-details-marker { display: none; }
.wbg-more[open] > summary { display: none; }
.wbg-more { display: inline; }
.wbg-facts { font-weight: 600; margin: 0; }
/* download */
.dl-levels .shiny-options-group { display: flex; flex-direction: column; gap: 8px; }
.dl-levels .radio, .dl-levels .form-check { margin: 0; padding: 8px 12px; border: 1px solid var(--wbg-line); border-radius: 6px; }
.dl-levels .radio:has(input:checked), .dl-levels .form-check:has(input:checked) { border-color: var(--k-blue); background: var(--k-hover); }
.dl-levels label { width: 100%; margin: 0; display: flex; align-items: flex-start; gap: 12px; cursor: pointer; }
.dl-levels label input { position: static; margin: 3px 0 0; flex: none; }
.dl-levels label > span { display: block; padding: 0; }
.dl-levels label b { display: block; font-size: var(--k-fs-b); }
.dl-levels label small { display: block; font-size: var(--k-fs-s); color: var(--wbg-ink2); font-weight: 400; }
.dl-chip { display: inline-flex; gap: 6px; align-items: center; background: #e3ebf8; color: #1a4287; border: 1px solid #c5d5f0; border-radius: 99px; padding: 2px 4px 2px 10px; font-size: var(--k-fs-b); margin: 0 6px 6px 0; }
.dl-chip button { border: 0; background: none; color: #1a4287; font-size: var(--k-fs-b); line-height: var(--k-lh-t); padding: 0 5px; cursor: pointer; border-radius: 50%; }
.dl-chip button:hover { background: #c5d5f0; }
.dl-prev { overflow: auto; max-height: 300px; border: 1px solid var(--wbg-line); border-radius: 6px; }
.dl-prev table { border-collapse: collapse; font-size: var(--k-fs-s); white-space: nowrap; }
.dl-prev th { position: sticky; top: 0; background: #f4f5f7; text-align: left; padding: 5px 10px; border-bottom: 1px solid var(--wbg-line); font-weight: 600; }
.dl-prev td { padding: 4px 10px; border-bottom: 1px solid var(--k-rule); max-width: 260px; overflow: hidden; text-overflow: ellipsis; }
.modal-xl-wbg .modal-dialog { max-width: 1040px; }
/* between 992 and 1200 wide the bar keeps the family and drops the app's name, so nothing in it is cut */
@media (min-width: 992px) and (max-width: 1199.98px) { .navbar .navbar-brand { font-size: 0; } .navbar .wbg-fam .sl { display: none; } .navbar .nav-link { padding-left: .45rem; padding-right: .45rem; } }
@media (max-width: 576px) { .navbar-brand { flex-wrap: wrap; white-space: normal; gap: 0 10px; } .navbar .wbg-top { flex-wrap: wrap; padding: 8px 0; } .wbg-fgrid { grid-template-columns: 1fr; } .wbg-dl { grid-template-columns: 1fr; } .wbg-dl dt { margin-top: 6px; } .wbg-pkgline { grid-template-columns: 1fr; gap: 0; } }
"""

SCRIPT = """
(function () {
  if (!new URLSearchParams(window.location.search).get('family')) document.documentElement.classList.add('no-family');
  function reg() {
    if (!window.Shiny || !Shiny.addCustomMessageHandler) return setTimeout(reg, 50);
    Shiny.addCustomMessageHandler('wbg_family', function (m) {
      document.documentElement.classList.toggle('no-family', !m.family);
      history.replaceState(null, '', m.family ? '?family=' + m.family : window.location.pathname);
    });
  }
  reg();
  // the search icon in the bar opens the search box under it; a pick, Escape or a click elsewhere closes it
  window.wbgFind = function (open) {
    var f = document.getElementById('wbg_find'); if (!f) return;
    var on = open === undefined ? !f.classList.contains('open') : open;
    f.classList.toggle('open', on);
    var s = document.getElementById('find'); s = s && s.selectize;
    if (s) { if (on) { s.clear(true); setTimeout(function () { s.focus(); }, 30); } else { s.blur(); } }
  };
  document.addEventListener('click', function (e) { var f = document.getElementById('wbg_find'); if (f && f.classList.contains('open') && !f.contains(e.target)) wbgFind(false); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') wbgFind(false); });
  if (window.jQuery) jQuery(document).on('change', '#find', function () { if (this.value) setTimeout(function () { wbgFind(false); }, 50); });
  // plotly charts measure their box once: tell them when the side panel has moved the page
  var t; document.addEventListener('transitionend', function () { clearTimeout(t); t = setTimeout(function () { window.dispatchEvent(new Event('resize')); }, 80); });
})();
"""

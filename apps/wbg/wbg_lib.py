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

POLICY = "Policy and regulation"     # an activity about policy, not about one asset
NO_ASSET = "No single asset"
ASSET_SHORT = {"Connectivity networks": "Connectivity", "Digital platforms and systems": "Digital platforms",
               "Monitoring, warning and control systems": "Monitoring and control"}
DOC_KIND = {"pad": "Appraisal document", "additional_financing": "Additional financing paper",
            "restructuring": "Restructuring paper", "project_paper_other": "Project paper"}
# How far above its threshold a sentence's probability is, shown as one to three bars and never as a number.
STRENGTH = ((0.95, 3, "Well above the threshold"), (0.88, 2, "Above the threshold"), (0.0, 1, "Near the threshold"))
# One colour per stage of procurement, wherever one is shown (the dropped one is muted on purpose).
_ST = kit.look()["status"]
STAGE_COLOR = {**_ST, W.DROPPED: _ST["Dropped"]}
STAGE_TAB = {"Coming up": "Coming up", "Under way": "Under way", "Completed": "Completed", W.DROPPED: "Dropped"}
LATE = "Planned date passed"     # to come by the plan, but its planned date is behind us with no notice or signing recorded
TAB_COLOR = _ST
TABS = ("Coming up", LATE, "Under way", "Completed", "Dropped", "All")
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
    """The asset axis, in the order the dashboard shows it: the assets, policy, no single asset."""
    names = list(dict.fromkeys(assets_df["asset_name"])) if len(assets_df) else []
    return names + [POLICY, NO_ASSET]


def prep_acts(df, stages=None):
    """The activities frame with what the pages need beside the reader's columns: the asset axis
    values (one per asset, or Policy and regulation, or No single asset), the asset types, the
    types as lists, the procurement summary and the instrument as a word."""
    df = df.copy()
    if df.empty:
        for c in ("assets", "asset_types", "types", "type_id_list"):
            df[c] = pd.Series(dtype=object)
        for c in ("stage", "chip", "pk_stage", "pk_date", "pk_id", "pk_n"):
            df[c] = pd.Series(dtype=object)
        return df

    def assets(r):
        a = [x for x in (r["asset_name"], r["asset2_name"]) if isinstance(x, str) and x]
        return a or [POLICY if r["asset_column"] == "policy" else NO_ASSET]

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
        for c in ("date", "q", "acts", "tab"):
            pk[c] = pd.Series(dtype=object)
        return pk
    pk["date"] = pd.to_datetime(pk["next_date"].fillna(pk["signed_date"]).fillna(pk["due_date"]))
    pk["q"] = [f"{d.year}Q{(d.month - 1) // 3 + 1}" if pd.notna(d) else None for d in pk["date"]]
    pk["acts"] = pk["activity_ids"].map(split)
    today = pd.Timestamp.today().normalize()
    # Coming up: planned for today or later. Planned date passed: the date is behind us with no notice or signing
    # recorded. A tender already out (Tendered) has started, so it counts as under way, as the plan's own words do.
    pk["tab"] = [("Under way" if st == "Tendered" else LATE if pd.notna(d) and d < today else "Coming up") if s == "Coming up" else STAGE_TAB[s]
                 for s, st, d in zip(pk["stage"], pk["package_status"], pk["date"])]
    return pk


def link_procurement(acts, pk):
    """Adds to each activity where its procurement stands: the stage of its most pressing linked
    package, and the next (else latest) package with its date."""
    acts = acts.copy()
    cols = ["stage", "pk_stage", "pk_date", "pk_id", "pk_n"]
    if acts.empty:
        for c in cols:
            acts[c] = pd.Series(dtype=object)
        return acts
    best: dict = {}
    order = {s: i for i, s in enumerate(W.STAGE_URGENCY)}
    for r in pk.itertuples():
        for a in r.acts:
            cur = best.setdefault(a, {"stage": None, "n": 0, "next": None, "last": None})
            cur["n"] += 1
            if cur["stage"] is None or order[r.stage] < order[cur["stage"]]:
                cur["stage"] = r.stage
            if r.stage == "Coming up" and pd.notna(r.date) and (cur["next"] is None or r.date < cur["next"][0]):
                cur["next"] = (r.date, r.package_id, r.stage)
            if pd.notna(r.date) and (cur["last"] is None or r.date > cur["last"][0]):
                cur["last"] = (r.date, r.package_id, r.stage)
    st, pst, pdt, pid, pn = [], [], [], [], []
    for a in acts["activity_id"]:
        b = best.get(a)
        if not b:
            st.append("No package linked"); pst.append(None); pdt.append(pd.NaT); pid.append(None); pn.append(0)
            continue
        pick = b["next"] or b["last"]
        st.append(b["stage"]); pn.append(b["n"])
        pst.append(pick[2] if pick else b["stage"]); pdt.append(pick[0] if pick else pd.NaT)
        pid.append(pick[1] if pick else None)
    acts["stage"], acts["pk_stage"], acts["pk_date"], acts["pk_id"], acts["pk_n"] = st, pst, pdt, pid, pn
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


def status_dot(stage, text=None):
    return kit.dot(text or stage, TAB_COLOR.get(stage) or STAGE_COLOR.get(stage), hollow=stage == "No package linked")


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
        parts.append(f"{short_asset(a)} · {t}" if t and a not in (POLICY, NO_ASSET) else short_asset(a))
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
        cui.span(status_dot(p["tab"], p["package_status"]), class_="s"),
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


def proc_calendar(pk, key, sel_q, today):
    """One small square per linked package, stacked by quarter on a time axis, coloured by status, a line
    for today. A click on a quarter filters the list under it."""
    d = pk.dropna(subset=["date"])
    legend = [cui.span(cui.span(class_="sq", style=f"background:{TAB_COLOR[t]}"), f"{t} {int((d['tab'] == t).sum()):,}",
                       class_="lg") for t in TABS[:-1]]
    undated = len(pk) - len(d)
    if d.empty:
        return cui.div(cui.div(*legend, class_="pc-legend"), cui.p("No linked package has a date.", class_="wbg-muted"))
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
        mine = d[d["q"] == name].assign(o=lambda x: x["tab"].map(order)).sort_values(["o", "date"])
        sq = [cui.span(class_="sq", style=f"background:{TAB_COLOR[r.tab]}",
                       **{"data-tip": f"{r.package_number or r.package_id} · {(r.description or '')[:70]}\n{r.package_status}"})
              for r in mine.itertuples()]
        tip = f"{q.year} Q{q.quarter}\n" + (", ".join(f"{int((mine['tab'] == t).sum())} {t.lower()}" for t in TABS[:-1]
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
        cui.div(*cols, cui.div(cui.span("today"), class_="pc-today", style=f"left:{left:.2f}%"),
                class_="pc-cols", style=f"height:{height}px"),
        cui.div(*axis, class_="pc-axis"), class_="pc-chart", style=f"min-width:{nq * (per_row * 11 + 6)}px")
    note = (f"One square is one linked package, in the quarter of its planned date, its signing date once signed, or the date it "
            f"was due. Click a quarter to list only its packages." + (f" Not shown: {plural(undated, 'package')} with no date." if undated else ""))
    return cui.div(cui.div(*legend, class_="pc-legend"), cui.div(chart, class_="pc-scroll"), cui.p(note, class_="wbg-muted-s mt-1 mb-0"))


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
    counts = {t: int((pk["tab"] == t).sum()) for t in TABS[:-1]}
    counts["All"] = len(pk)
    head = []
    if tabs:
        head = [cui.tags.button({"type": "button", "class": "pc-tab" + (" on" if t == tab else ""),
                                 **clicker({"key": key, "tab": t}, "pc")},
                                t, cui.span(f"{counts[t]:,}", class_="c")) for t in TABS]
    if sel_q:
        y, q = sel_q.split("Q")
        head.append(cui.tags.button({"type": "button", "class": "pc-qchip", "data-tip": "Show every quarter",
                                     **clicker({"key": key, "q": sel_q}, "pc")}, f"{y} Q{q}  ×"))
    view = pk if tab == "All" else pk[pk["tab"] == tab]
    if sel_q:
        view = view[view["q"] == sel_q]
    col, sec = SORTS[sort][1][0], SORTS[sort][1][1:]
    view = view.sort_values([col, *sec], ascending=[not desc, *[True] * len(sec)], na_position="last", kind="stable")
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
    cols = [c for c in cols if c[0] not in hide]
    thead = cui.tags.tr(*[th(n if n in SORTS else "", l, c) for n, l, c in cols])
    body = []
    for _, r in view.iterrows():
        cells = {"date": cui.tags.td(day(r["date"]) or "no date", class_="w-date"),
                 "pkg": cui.tags.td(r["package_number"] or r["package_id"], class_="w-pkg"),
                 "desc": cui.tags.td(cui.div(r["description"] or "", class_="clamp"), status_dot(r["tab"], r["package_status"])
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
                                       f"Show all {total:,}"), cui.span(f"Showing the first {limit:,}", class_="wbg-muted-s ms-2"), class_="mt-2")
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


STEPS = ("Planned", "Notice", "Signed", "Completed")


def stage_strip(p):
    """Where a package stands: Planned, Notice, Signed, Completed, with the date under each step that has happened
    and the date planned for the next one."""
    status = p["package_status"]
    signed_on = status in ("Contract signed", "Under implementation", "Contract completed")
    reached = [True, pd.notna(p["notice_date"]) or status == "Tendered" or signed_on, pd.notna(p["signed_date"]) or signed_on,
               status == "Contract completed"]
    dates = [p["planned_date"], p["notice_date"], p["signed_date"], pd.NaT]
    nxt = next((i for i, r in enumerate(reached) if not r), None)
    dropped = p["tab"] == "Dropped"
    out = []
    for i, name in enumerate(STEPS):
        if reached[i]:
            under = day(dates[i], "%d %b %Y") if pd.notna(dates[i]) else ""
            cls = "done"
        elif i == nxt and not dropped:
            plan = p["next_date"] if pd.notna(p["next_date"]) else p["due_date"] if pd.notna(p["due_date"]) else dates[i]
            under = ("planned " + day(plan, "%d %b %Y")) if pd.notna(plan) else ""
            cls = "next"
        else:
            under, cls = "", "todo"
        out.append(cui.div(cui.span(class_="dot"), cui.div(name, class_="nm"), cui.div(under, class_="dt"), class_="wbg-step " + cls))
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
        cui.div(status_dot(p["tab"], p["package_status"]), class_="mb-1"),
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
.wbg-muted-s { color: var(--wbg-muted); font-size: 12.5px; }
.wbg-sub { font-size: 12px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; color: var(--wbg-ink2); margin: 16px 0 6px; padding-bottom: 3px; border-bottom: 1px solid var(--wbg-line); }
/* the page before a group is chosen shows the start page and nothing of the app */
a.nav-link[data-value="Start"], li:has(> a.nav-link[data-value="Start"]) { display: none !important; }
.no-family .navbar-nav .nav-item, .no-family .wbg-top { display: none !important; }
.navbar .navbar-brand { font-size: 1.12rem; }
.navbar .nav-link { padding-left: .6rem; padding-right: .6rem; }
.navbar-brand { display: flex; align-items: baseline; gap: 10px; white-space: nowrap; margin-right: 8px; }
.navbar .navbar-nav { flex-wrap: nowrap; align-items: center; }
.no-family .sidebar-collapse-toggle, .no-family .collapse-toggle { display: none !important; }
.wbg-fam { font-size: 14px; font-weight: 400; color: #c9d0da; display: inline-flex; align-items: baseline; gap: 8px; }
.wbg-fam b { color: #fff; font-weight: 600; }
.wbg-fam .sl { color: #6f7885; }
.wbg-fam a { font-size: 12.5px; color: #9bb8ea; text-decoration: underline; text-underline-offset: 2px; cursor: pointer; }
.wbg-fam a:hover { color: #fff; }
.navbar .wbg-top { display: flex; gap: 8px; align-items: center; }
.navbar .wbg-top .shiny-input-container { margin-bottom: 0; }
.navbar .wbg-top .form-select, .navbar .wbg-top .selectize-input, .navbar .wbg-top .btn { font-size: 14px; min-height: 34px; }
/* start page */
.wbg-start { max-width: 1060px; margin: 0 auto; padding-top: 28px; }
.wbg-start h1 { font-size: 1.7rem; margin-bottom: 4px; }
.wbg-start .lead { color: var(--wbg-ink2); font-size: 15px; margin-bottom: 22px; }
.wbg-fgrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; align-items: stretch; }
.wbg-fcard { display: flex; flex-direction: column; background: #fff; border: 1px solid var(--wbg-line); border-radius: 8px; padding: 22px 24px 20px; min-width: 0; }
.wbg-fcard h2 { font-size: 1.3rem; margin: 0 0 6px; }
.wbg-fcard .desc { color: var(--wbg-ink2); font-size: 14.5px; line-height: 1.4; min-height: 4.2em; margin: 0 0 14px; }
.wbg-fcard .nums { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; padding: 12px 0; border-top: 1px solid var(--wbg-line); border-bottom: 1px solid var(--wbg-line); margin-bottom: 12px; }
.wbg-fcard .nums div { min-width: 0; }
.wbg-fcard .nums b { display: block; font-size: 1.5rem; font-weight: 600; line-height: 1.15; font-variant-numeric: tabular-nums; }
.wbg-fcard .nums span { font-size: 12.5px; color: var(--wbg-muted); }
.wbg-fcard .ms-h { font-size: 12px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; color: var(--wbg-ink2); margin-bottom: 4px; }
.wbg-fcard ul { list-style: none; padding: 0; margin: 0 0 18px; min-height: calc(5 * 1.65em); }
.wbg-fcard li { font-size: 14px; line-height: 1.65; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.wbg-fcard li.more { color: var(--wbg-muted); }
.wbg-fcard .btn { margin-top: auto; align-self: stretch; font-weight: 600; padding: 9px 14px; }
/* figures */
.wbg-figs { display: flex; flex-direction: column; height: 100%; }
.wbg-fig { flex: 1; display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--k-rule); }
.wbg-fig:last-child { border-bottom: 0; }
.wbg-fig .l { font-size: 14px; color: var(--wbg-ink2); }
.wbg-fig .l small { display: block; font-size: 12px; color: var(--wbg-muted); }
.wbg-fig .v { font-size: 1.55rem; font-weight: 600; font-variant-numeric: tabular-nums; line-height: 1.1; }
.wbg-fig.sub { padding-left: 14px; }
.wbg-fig.sub .v { font-size: 1.25rem; font-weight: 500; }
/* tables */
.wbg-scroll { overflow-x: auto; }
.wbg-table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
.wbg-table th { text-align: left; font-size: 12px; font-weight: 600; color: var(--wbg-ink2); padding: 6px 10px 6px 0; border-bottom: 1px solid var(--wbg-line); white-space: nowrap; vertical-align: bottom; }
.wbg-table td { padding: 8px 10px 8px 0; border-bottom: 1px solid var(--k-rule); vertical-align: top; }
.wbg-table td.r + td, .wbg-table th.r + th { padding-left: 16px; }
.wbg-table th.r, .wbg-table td.r { text-align: right; font-variant-numeric: tabular-nums; }
.wbg-table tr.go { cursor: pointer; }
.wbg-table tr.go:hover td { background: var(--k-hover); }
.wbg-table .clamp { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; line-height: 1.35; }
.wbg-ctable { width: 100%; min-width: 900px; }
.wbg-ctable td.pn { min-width: 260px; }
.wbg-ctable th, .wbg-ctable td { white-space: nowrap; }
.wbg-ctable td.pn { white-space: normal; }
.wbg-table .id { display: block; font-size: 12px; color: var(--wbg-muted); }
.wbg-table.mini { font-size: 12.5px; }
.wbg-table.mini td, .wbg-table.mini th { padding: 4px 8px 4px 0; }
.wbg-chip { display: inline-block; font-size: 12px; font-weight: 600; padding: 1px 8px; border-radius: 99px; white-space: nowrap; }
.wbg-chip.inv { background: var(--k-inv-bg); color: var(--k-inv); }
.wbg-chip.pol { background: var(--k-pol-bg); color: var(--k-pol); }
/* procurement */
.pc-legend { display: flex; flex-wrap: wrap; gap: 16px; font-size: 13px; margin-bottom: 8px; }
.pc-legend .sq, .pc-cols .sq { display: inline-block; width: 9px; height: 9px; border-radius: 2px; }
.pc-legend .lg { display: inline-flex; align-items: center; gap: 6px; }
.pc-scroll { overflow-x: auto; padding-bottom: 2px; }
.pc-chart { width: 100%; }
.pc-cols { position: relative; display: flex; align-items: stretch; border-bottom: 1px solid var(--wbg-line); }
.pc-q { flex: 1 1 0; min-width: 0; display: flex; flex-wrap: wrap-reverse; align-content: flex-start; gap: 2px; padding: 0 3px 2px; background: none; border: 0; border-radius: 3px; cursor: pointer; }
.pc-q:hover { background: #eef3fb; }
.pc-q.sel { background: var(--k-selected); box-shadow: inset 0 0 0 1px var(--k-blue); }
.pc-q.y { border-left: 1px solid var(--k-rule); }
.pc-today { position: absolute; top: 0; bottom: 0; width: 0; border-left: 1.5px dashed var(--k-ink2); pointer-events: none; }
.pc-today span { position: absolute; top: -1px; left: 4px; font-size: 11px; color: var(--k-ink2); background: #fff; padding: 0 2px; }
.pc-axis { display: flex; margin-top: 3px; }
.pc-ax { flex: 1 1 0; min-width: 0; display: flex; flex-direction: column; align-items: flex-start; font-size: 10px; color: var(--wbg-muted); padding-left: 3px; height: 28px; }
.pc-ax.y { border-left: 1px solid var(--k-rule); }
.pc-ax .yr { font-size: 11.5px; font-weight: 600; color: var(--wbg-ink2); white-space: nowrap; }
.pc-tabs { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin: 14px 0 8px; }
.pc-tab { border: 1px solid var(--wbg-line); background: #fff; border-radius: 99px; padding: 3px 12px; font-size: 13px; cursor: pointer; display: inline-flex; gap: 7px; }
.pc-tab .c { color: var(--wbg-muted); font-variant-numeric: tabular-nums; }
.pc-tab.on { background: var(--k-ink); border-color: var(--k-ink); color: #fff; }
.pc-tab.on .c { color: #c9d0da; }
.pc-qchip { border: 1px solid var(--k-blue); background: var(--k-selected); color: #1a4287; border-radius: 99px; padding: 3px 12px; font-size: 13px; cursor: pointer; }
.pc-table { table-layout: fixed; min-width: 1240px; }
.pc-table .w-date { width: 104px; } .pc-table .w-pkg { width: 100px; } .pc-table .w-proj { width: 190px; } .pc-table .w-ctry { width: 110px; }
.pc-table .w-cat { width: 96px; } .pc-table .w-meth { width: 120px; } .pc-table .w-amt { width: 112px; } .pc-table .w-for { width: 180px; }
.pc-table td.w-pkg { overflow-wrap: anywhere; font-size: 12.5px; }
.pc-table .srt { background: none; border: 0; padding: 0; font: inherit; color: inherit; cursor: pointer; }
.pc-table .srt:hover, .pc-table .srt.on { color: var(--bs-primary, var(--k-blue)); }
.pc-table .srt .ar { display: inline-block; width: 12px; }
/* side panel */
.wbg-ph { margin-bottom: 10px; }
.wbg-ph h5 { margin: 0 0 4px; font-size: 1.08rem; line-height: 1.3; }
.wbg-ph .tot { font-size: 13px; color: var(--wbg-ink2); }
.wbg-seg { display: inline-flex; border: 1px solid var(--wbg-line); border-radius: 6px; overflow: hidden; background: #fff; }
.wbg-seg button { border: 0; background: none; padding: 4px 12px; font-size: 13px; cursor: pointer; border-right: 1px solid var(--wbg-line); display: inline-flex; gap: 6px; align-items: baseline; }
.wbg-seg button:last-child { border-right: 0; }
.wbg-seg button .c { color: var(--wbg-muted); font-variant-numeric: tabular-nums; font-size: 12px; }
.wbg-seg button.on { background: var(--k-ink); color: #fff; }
.wbg-seg button.on .c { color: #c9d0da; }
.wbg-bar { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; margin: 8px 0 12px; }
.wbg-pgroup { margin-top: 14px; }
.wbg-pgroup > header { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; padding-bottom: 4px; border-bottom: 1px solid var(--wbg-line); margin-bottom: 6px; }
.wbg-pgroup > header .t { font-weight: 600; font-size: 14.5px; }
.wbg-pgroup > header .s { font-size: 12.5px; color: var(--wbg-muted); }
.wbg-pgroup > header .btn { font-size: 12.5px; padding: 0; white-space: nowrap; }
.wbg-act { border: 1px solid var(--wbg-line); border-radius: 6px; margin-bottom: 8px; background: #fff; }
.wbg-act > summary { list-style: none; cursor: pointer; padding: 8px 10px 8px 26px; position: relative; display: flex; flex-direction: column; gap: 4px; }
.wbg-act > summary::-webkit-details-marker { display: none; }
.wbg-act > summary::before { content: "▸"; position: absolute; left: 10px; top: 8px; color: var(--wbg-ink2); }
.wbg-act[open] > summary::before { content: "▾"; }
.wbg-act[open] > summary { border-bottom: 1px solid var(--wbg-line); }
.wbg-act .lbl { font-weight: 600; font-size: 13.5px; line-height: 1.35; }
.wbg-act .cnt { font-size: 12px; color: var(--wbg-muted); white-space: nowrap; margin-left: auto; }
.wbg-act summary > div:first-child { display: flex; gap: 10px; align-items: baseline; justify-content: space-between; }
.wbg-act .tags { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.wbg-act .tags .kit-tag { margin: 0; }
.wbg-act .inner { padding: 8px 12px 10px; }
.wbg-sentence .kit-quote { margin: 4px 0 8px; }
.wbg-pkgline { display: grid; grid-template-columns: 112px 84px 92px 1fr; gap: 8px; align-items: start; width: 100%; text-align: left; background: none; border: 0; border-top: 1px solid var(--k-rule); padding: 5px 0; font-size: 12.5px; cursor: pointer; color: inherit; }
.wbg-pkgline:hover { background: var(--k-hover); }
.wbg-pkgline .x { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; color: var(--wbg-ink2); line-height: 1.35; }
.wbg-pkgline .n { color: var(--wbg-ink2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wbg-steps { display: grid; grid-template-columns: repeat(4, 1fr); margin: 6px 0 0; }
.wbg-step { position: relative; text-align: center; padding-top: 18px; font-size: 12px; }
.wbg-step::before { content: ""; position: absolute; top: 5px; left: -50%; right: 50%; height: 2px; background: var(--k-line); }
.wbg-step:first-child::before { display: none; }
.wbg-step .dot { position: absolute; top: 0; left: calc(50% - 6px); width: 12px; height: 12px; border-radius: 50%; border: 2px solid var(--k-line); background: #fff; }
.wbg-step.done .dot { background: var(--k-st-completed); border-color: var(--k-st-completed); }
.wbg-step.done::before { background: var(--k-st-completed); }
.wbg-step.next .dot { border-color: var(--k-st-coming-up); }
.wbg-step .nm { font-weight: 600; } .wbg-step.todo .nm, .wbg-step.todo { color: var(--k-muted); } .wbg-step .dt { color: var(--k-muted); min-height: 1.3em; }
.wbg-moredetails { margin-top: 14px; border-top: 1px solid var(--k-line); padding-top: 8px; }
.wbg-moredetails > summary { cursor: pointer; color: var(--k-blue); font-size: 13.5px; font-weight: 500; }
.wbg-dl { display: grid; grid-template-columns: 150px 1fr; gap: 3px 12px; margin: 0; font-size: 13.5px; }
.wbg-dl dt { font-weight: 400; color: var(--wbg-muted); }
.wbg-dl dd { margin: 0; overflow-wrap: anywhere; }
/* lists of types, activities */
.wbg-types .wbg-trow { display: grid; grid-template-columns: 1fr 96px 80px; gap: 14px; padding: 10px 6px; border-bottom: 1px solid var(--k-rule); cursor: pointer; align-items: baseline; }
.wbg-types .wbg-trow:hover { background: var(--k-hover); }
.wbg-types .wbg-trow.head { cursor: default; padding: 4px 6px; font-size: 12px; font-weight: 600; color: var(--wbg-ink2); border-bottom: 1px solid var(--wbg-line); }
.wbg-types .wbg-trow.head:hover { background: none; }
.wbg-types .nm { font-weight: 600; color: var(--bs-primary, var(--k-blue)); }
.wbg-types .df { font-size: 13px; color: var(--wbg-ink2); margin-top: 2px; max-width: 95ch; }
.wbg-types .sg { font-size: 12.5px; color: var(--wbg-muted); margin-top: 2px; }
.wbg-types .num { text-align: right; font-variant-numeric: tabular-nums; }
.wbg-grp { border: 1px solid var(--wbg-line); border-radius: 6px; margin-bottom: 8px; background: #fff; }
.wbg-grp > summary { cursor: pointer; padding: 8px 12px; list-style: none; display: flex; gap: 10px; align-items: baseline; }
.wbg-grp > summary::-webkit-details-marker { display: none; }
.wbg-grp > summary::before { content: "▸"; color: var(--wbg-ink2); }
.wbg-grp[open] > summary::before { content: "▾"; }
.wbg-grp > summary .t { font-weight: 600; }
.wbg-grp > summary .s { color: var(--wbg-muted); font-size: 12.5px; margin-left: auto; }
.wbg-grp[open] > summary { border-bottom: 1px solid var(--wbg-line); }
.wbg-grp .wbg-table { margin: 0; } .wbg-grp .wbg-table td, .wbg-grp .wbg-table th { padding-left: 12px; } .wbg-grp .wbg-table tr:last-child td { border-bottom: 0; }
.wbg-acts { table-layout: fixed; min-width: 960px; }
.wbg-acts .a-act { width: 36%; } .wbg-acts .a-typ { width: 17%; } .wbg-acts .a-app { width: 21%; } .wbg-acts .a-chip { width: 100px; } .wbg-acts .a-pro { width: 17%; }
.wbg-acts td .tg { display: flex; flex-wrap: wrap; gap: 3px; } .wbg-acts td .kit-tag { margin: 0; }
.wbg-radios { display: flex; gap: 14px; align-items: center; font-size: 13.5px; }
.wbg-radios .shiny-input-container { margin: 0; width: auto; }
.wbg-radios .shiny-options-group { display: flex; gap: 14px; }
.wbg-radios .form-check { margin: 0; }
.wbg-filters { display: flex; flex-wrap: wrap; gap: 16px; align-items: end; margin: 14px 0; }
.wbg-filters .shiny-input-container { margin: 0; }
.wbg-filters label { font-size: 12px; font-weight: 600; color: var(--wbg-ink2); margin-bottom: 2px; }
.wbg-def { max-width: 80ch; line-height: 1.45; }
.wbg-more > summary { display: inline; color: var(--bs-primary, var(--k-blue)); cursor: pointer; margin-left: 4px; list-style: none; font-weight: 500; }
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
.dl-levels label b { display: block; font-size: 14px; }
.dl-levels label small { display: block; font-size: 12.5px; color: var(--wbg-ink2); font-weight: 400; }
.dl-chip { display: inline-flex; gap: 6px; align-items: center; background: #e3ebf8; color: #1a4287; border: 1px solid #c5d5f0; border-radius: 99px; padding: 2px 4px 2px 10px; font-size: 13px; margin: 0 6px 6px 0; }
.dl-chip button { border: 0; background: none; color: #1a4287; font-size: 15px; line-height: 1; padding: 0 5px; cursor: pointer; border-radius: 50%; }
.dl-chip button:hover { background: #c5d5f0; }
.dl-prev { overflow: auto; max-height: 300px; border: 1px solid var(--wbg-line); border-radius: 6px; }
.dl-prev table { border-collapse: collapse; font-size: 12.5px; white-space: nowrap; }
.dl-prev th { position: sticky; top: 0; background: #f4f5f7; text-align: left; padding: 5px 10px; border-bottom: 1px solid var(--wbg-line); font-weight: 600; }
.dl-prev td { padding: 4px 10px; border-bottom: 1px solid var(--k-rule); max-width: 260px; overflow: hidden; text-overflow: ellipsis; }
.modal-xl-wbg .modal-dialog { max-width: 1040px; }
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
  // plotly charts measure their box once: tell them when the side panel has moved the page
  var t; document.addEventListener('transitionend', function () { clearTimeout(t); t = setTimeout(function () { window.dispatchEvent(new Event('resize')); }, 80); });
})();
"""

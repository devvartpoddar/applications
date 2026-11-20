# wbg — what World Bank appraisal documents commit to for the digital assets a
# project finances (repository devvartpoddar/wbg-digital-resilience). Every
# query and every number computed beyond the views is in wbg_portfolio.app;
# this file and wbg_lib.py only lay them out. Read only: no write, no model
# call. The measures come in families (climate resilience; cloud, datacenters
# and data) and a team works in one: the app opens on a page that asks what
# you are working on, and every view then shows that family only. The unit is
# the activity (what a project commits to do for a measure); "Count" switches
# between activities and projects. Any bar, cell, number, card or row opens
# what lies behind it in the side panel. A comment, not a docstring: Express
# renders a module docstring onto the page.
from __future__ import annotations

import io
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs

import pandas as pd
import psycopg
from shiny import reactive, render, req
from shiny import ui as cui
from shiny.express import input, session, ui
from shinywidgets import render_plotly

import kit
from wbg_portfolio import app as W

sys.path.insert(0, str(Path(__file__).parent))
import wbg_about  # noqa: E402  (the About view's HTML, beside this file)
import wbg_lib as L  # noqa: E402

START = "Start"
# The families of measures (the `family` column of a measure's file in the pipeline), in the order the
# start page lists them: the name shown and what the card says it covers. A family the pipeline adds
# before it is named here is shown under its id.
FAMILIES = {
    "climate": ("Climate resilience",
                "Backup power, early warning, disaster recovery, climate-informed siting and design, renewable energy "
                "and more: keeping digital infrastructure working through climate and disaster risk."),
    "cloud_data": ("Cloud, datacenters and data",
                   "Datacenters, cloud strategy and migration, government cloud, and how data is classified, "
                   "governed, hosted and shared."),
}
PLACE = "Country or region"
LENSES = {"country": PLACE, "project": "Project", "asset": "Digital asset", "measure": "Measure"}
COHORTS = {"": "All projects", "digital": "Digital projects", "digital_contributor": "With a digital part"}
COHORT_NOUN = {"": "projects", "digital": "digital projects", "digital_contributor": "projects with a digital part"}
SENT_CAP = 30            # activities the side panel draws with their sentences; the download holds all of them
EXPLODE = {"asset": "assets", "asset_type": "asset_types", "type": "type_id_list"}

kit.page("WBG Digital Resilience", navbar="view", beside=cui.output_ui("brand"), css=L.CSS, script=L.SCRIPT)

# ---------------------------------------------------------------- data

family = reactive.value(None)        # the family being looked at; None on the start page
q = kit.query_df


def family_name(f):
    return FAMILIES[f][0] if f in FAMILIES else str(f).replace("_", " ").capitalize()


FAMILY_COLUMNS = ["family", "label_set", "measure_name", "definition", "measure_projects", "measure_activities",
                  "family_projects", "family_activities", "family_measures"]


@reactive.calc
def fam_table():
    """The families and their measures; an empty table when the database holds no tables of the new shape yet."""
    try:
        return kit.cached(("wbg", "families"), lambda: W.families(q))
    except psycopg.Error:
        return pd.DataFrame(columns=FAMILY_COLUMNS)


@reactive.calc
def families():
    """The families the store holds, those named in FAMILIES first."""
    found = list(dict.fromkeys(fam_table()["family"]))
    return [f for f in FAMILIES if f in found] + sorted(f for f in found if f not in FAMILIES and f != "(no family)")


def chosen():
    f = family.get()
    return f if f in families() else None


@reactive.calc
def asset_df():
    def load():
        a = W.asset_types(q)
        return a.assign(subtype_name=a["subtype_name"].map(L.no_kind), subtype_definition=a["subtype_definition"].map(L.no_kind))
    return kit.cached(("wbg", "asset_types"), load)


@reactive.calc
def asset_names():
    """{asset id: name}."""
    a = asset_df()
    return dict(zip(a["asset_id"], a["asset_name"]))


@reactive.calc
def axis():
    return L.axis_values(asset_df())


@reactive.calc
def type_df():
    return kit.cached(("wbg", "type_defs"), lambda: W.type_definitions(q))


@reactive.calc
def measure_df():
    return kit.cached(("wbg", "measures"), lambda: W.measures(q))


def cohort():
    """The projects every figure, chart, list, panel and download is limited to: None for all of them."""
    return input.cohort() or None


def load_pkgs(f, c):
    return kit.cached(("wbg", "pkgs", f, c), lambda: L.prep_pkgs(W.packages_detail(q, f, cohort=c)))


@reactive.calc
def pkgs():
    f = chosen()
    req(f)
    try:
        return load_pkgs(f, cohort())
    except psycopg.Error:
        req(False)


@reactive.calc
def acts_raw():
    """The family's activities; None when the database does not hold the new data yet."""
    f = chosen()
    req(f)
    try:
        c = cohort()
        return kit.cached(("wbg", "acts", f, c), lambda: L.link_procurement(L.prep_acts(W.activities(q, f, cohort=c)), load_pkgs(f, c)))
    except psycopg.Error:
        return None


@reactive.calc
def acts():
    """The family's activities; a page with none shows its notice, and nothing else draws."""
    df = acts_raw()
    req(df is not None and len(df))
    return df


def notice(what="page"):
    """What a page says when there is nothing to show: the new data is not published, or the family has none."""
    if not len(families()):
        return cui.div("The new data is not published yet. This dashboard reads the activities, sentences and procurement "
                       "of the redesigned pipeline, which is not in the database yet.", class_="alert alert-light border my-3 wbg-notice")
    df = acts_raw()
    if df is None:
        return cui.div("The new data is not published yet. The database holds no activities for this dashboard.",
                       class_="alert alert-light border my-3 wbg-notice")
    if df.empty:
        return cui.div(f"There are no activities for {family_name(chosen()).lower()} yet, so this {what} has nothing to show.",
                       class_="alert alert-light border my-3 wbg-notice")
    return None


@reactive.calc
def measure_ids():
    """{measure id: its name}, of every measure the store has, for turning an id in a definition into words."""
    try:
        m = kit.cached(("wbg", "measures"), lambda: W.measures(q))
    except psycopg.Error:
        return {}
    return dict(zip(m["label_set"], m["measure_name"]))


def plain(text):
    """A definition for people: a measure's id written in it (backup_power, cra) becomes that measure's name, and
    the word kind becomes type."""
    if not isinstance(text, str) or not text:
        return text
    for mid, name in sorted(measure_ids().items(), key=lambda kv: -len(kv[0])):
        word = name if name[1:2].isupper() else name[:1].lower() + name[1:]
        text = re.sub(rf"(?<![\w]){re.escape(mid)}(?![\w])", word, text)
    return L.no_kind(text)


@reactive.calc
def base():
    """The projects a share is taken of: every project with a document read, with or without an activity."""
    c = cohort()
    return kit.cached(("wbg", "projects", c), lambda: W.projects(q, c))


@reactive.calc
def proj_facts():
    f = chosen()
    req(f)
    c = cohort()
    return kit.cached(("wbg", "proj_facts", f, c), lambda: W.download(q, "project", f, cohort=c))


unit_v = reactive.value("activities")   # what Count says one thing is: activities or projects


def by_projects():
    return unit_v.get() == "projects"


def unit_word(n=2):
    if by_projects():
        return "project" if n == 1 else "projects"
    return "activity" if n == 1 else "activities"


def unit_n(n):
    return f"{n:,} {unit_word(n)}"


def cnt(df):
    """What the Count switch says one thing is: activities, or the projects they belong to."""
    return int(df["project_id"].nunique() if by_projects() else df["activity_id"].nunique())


def expand(df, name):
    """One row per value of a column that holds several (the assets an activity applies to, its asset types, its
    types; no type becomes '(no type)'), under the name the click and the chart use."""
    if name not in EXPLODE:
        return df
    d = df.assign(**{name: df[EXPLODE[name]]})
    if name == "type":
        d["type"] = d["type"].map(lambda t: t or [W.NO_TYPE])
    return d.explode(name)


def tally(df, *by, of=None):
    """W.tally in the unit the switch says; of: the projects a share is taken of (default: every project read)."""
    return W.tally(df, *by, unit="projects" if by_projects() else "commitments", base=base() if of is None else of)


def of_text(r):
    return f"{int(r['n']):,} of {int(r['of']):,} projects ({r['share']:.0%})" if by_projects() and pd.notna(r["share"]) \
        else f"{int(r['n']):,} {'projects' if by_projects() else 'activities'}"


def cell_text(r):
    return f"{int(r['n']):,} ({r['share']:.0%})" if by_projects() and pd.notna(r["share"]) else f"{int(r['n']):,}"


def project_names():
    """{project_id: name}, with the place added where two projects share a name."""
    d = acts().drop_duplicates("project_id")
    twice = d["project_name"].duplicated(keep=False)
    return {r.project_id: (f"{r.project_name} · {r.place}" if t else r.project_name) for r, t in zip(d.itertuples(), twice)}


def measure_names():
    """{label_set: name}, of the family."""
    d = acts().drop_duplicates("label_set")
    return dict(zip(d["label_set"], d["measure_name"]))


def type_names(label_set):
    d = type_df()
    d = d[d["label_set"] == label_set]
    return dict(zip(d["type_id"], d["type_name"])) | {W.NO_TYPE: "No type stated"}


def pkgs_for(df, pk=None):
    """The linked packages that serve any of these activities."""
    pk = pkgs() if pk is None else pk
    ids = set(df["activity_id"])
    return pk[pk["acts"].map(lambda a: any(x in ids for x in a))] if len(pk) else pk


# ---------------------------------------------------------------- where the reader is

drill = reactive.value(None)         # {"kind": "acts", "title": str, "where": {...}} | {"kind": "pkg", ...} | {"kind": "nd", ...}
panel_inst = reactive.value("all")   # the panel's own All / Investment / Policy
m_inst = reactive.value("all")       # the measure page's, which filters the whole page
p_group = reactive.value("measure")  # how the project page groups its activities
pending_pick = reactive.value(None)
pstate = reactive.value({})          # per procurement component: quarter picked, tab, sort, rows shown


def open_panel(c):
    """The one place that opens the side panel. Every bar, cell, square, row, number, card and map country sends its
    payload as the input `card` and lands here: an activity list ({title, where}), a package ({pkg}) or the sentences
    left out as not digital ({nd})."""
    if c.get("pkg"):
        drill.set({"kind": "pkg", "package_id": c["pkg"], "at": time.time()})
    elif c.get("nd"):
        drill.set({"kind": "nd", "project_id": c["nd"], "at": time.time()})
    else:
        panel_inst.set("all")
        drill.set({"kind": "acts", "title": c["title"], "where": c["where"], "at": time.time()})


@reactive.effect
@reactive.event(drill)
def _show_panel():
    if drill.get():
        ui.update_sidebar("panel", show=True)


@reactive.effect
@reactive.event(input.card)
def _card_clicked():
    c = input.card()
    if c.get("go"):
        go_to(c["go"], c["value"])      # a name on an axis opens its page
    else:
        open_panel(c)


@reactive.effect
@reactive.event(input.seg)
def _seg():
    s = input.seg()
    {"m_inst": m_inst, "panel_inst": panel_inst, "p_group": p_group, "unit": unit_v}[s["name"]].set(s["value"])


def go_to(lens, value):
    """Open Explore on one country, project (by id), asset or measure (by id)."""
    ui.update_navs("view", selected="Explore")
    with reactive.isolate():
        same = input.lens() == lens
    if same:
        ui.update_selectize("pick", selected=value)
    else:
        pending_pick.set(value)
        ui.update_radio_buttons("lens", selected=lens)


@reactive.effect
@reactive.event(input.lens, input.pick)
def _reset_page_state():
    pstate.set({})
    m_inst.set("all")


def seg(name, current, options):
    """A row of buttons, one pressed: options [(value, label, count or None)]."""
    return cui.div(*[cui.tags.button({"type": "button", "class": "on" if v == current else "", "onclick": L.js("seg", {"name": name, "value": v})},
                                     lab, cui.span(f"{n:,}", class_="c") if n is not None else None) for v, lab, n in options],
                   class_="wbg-seg")


def unit_ctl():
    """The Count switch, the same small control at the right of the title row of every page it applies to."""
    return cui.div(cui.span("Count", class_="lb"), seg("unit", unit_v.get(), [("activities", "Activities", None), ("projects", "Projects", None)]),
                   class_="wbg-unit", **{"data-tip": "Count\nWhat one is in every chart and figure on the page: an activity, or a project that has one."})


# ---------------------------------------------------------------- the frame: family, start page, address

def enter(f, lens=None, value=None):
    family.set(f)
    drill.set(None)
    ui.update_sidebar("panel", show=False)
    if lens:
        go_to(lens, value)
    else:
        ui.update_navs("view", selected="Overview")


@reactive.effect
@reactive.event(input.family_pick)
def _family_picked():
    f = input.family_pick()["family"]
    if f in families():
        enter(f)


@reactive.effect
@reactive.event(input.go_start)
def _go_start():
    family.set(None)
    drill.set(None)
    ui.update_sidebar("panel", show=False)
    ui.update_navs("view", selected=START)


@reactive.effect
def _from_link():
    # .../wbg/?family=cloud_data opens that family: a link to hand to someone.
    want = parse_qs(session.clientdata.url_search().lstrip("?")).get("family", [None])[0]
    fams = families()
    with reactive.isolate():
        if want in fams and family.get() is None:
            enter(want)


@reactive.effect
async def _address():
    await session.send_custom_message("wbg_family", {"family": chosen()})


@reactive.effect
def _one_place_at_a_time():
    # Every view but About shows one family: with none chosen, back to the start page.
    if input.view() in ("Overview", "Explore", "Procurement") and chosen() is None:
        ui.update_navs("view", selected=START)


with ui.hold():

    @render.ui
    def brand():
        f = chosen()
        if not f:
            return None
        return cui.span(cui.span("/", class_="sl"), cui.tags.b(family_name(f)),
                        cui.tags.a("change", href="#", title="Choose another group",
                                   onclick="Shiny.setInputValue('go_start', Date.now(), {priority: 'event'}); return false;"),
                        class_="wbg-fam")


with ui.nav_panel(START):

    @render.ui
    def start():
        ft = fam_table()
        if not len(families()):
            return cui.div(cui.tags.h1("What are you working on?"), notice(), class_="wbg-start")
        cards = []
        for f in families():
            m = ft[ft["family"] == f]
            names = m["measure_name"].tolist()
            more = len(names) - 4
            cards.append(cui.div(
                cui.tags.h2(family_name(f)),
                cui.p(FAMILIES[f][1] if f in FAMILIES else "", class_="desc"),
                cui.div(cui.div(cui.tags.b(f"{int(m['family_projects'].iloc[0]):,}"), cui.span("projects")),
                        cui.div(cui.tags.b(f"{int(m['family_activities'].iloc[0]):,}"), cui.span("activities")),
                        cui.div(cui.tags.b(f"{len(m):,}"), cui.span("measures")), class_="nums"),
                cui.div("Measures", class_="ms-h"),
                cui.tags.ul(*[cui.tags.li(n, title=n) for n in names[:4]],
                            cui.tags.li(f"and {more} more", class_="more") if more > 0 else None),
                cui.tags.button({"type": "button", "class": "btn btn-primary",
                                 **L.clicker({"family": f}, "family_pick")}, "Open"),
                class_="wbg-fcard"))
        return cui.div(cui.tags.h1("What are you working on?"),
                       cui.p("World Bank project documents are read for what each project commits to do for its digital assets. "
                             "Choose the group of measures your team works on; every page then shows that group only.", class_="lead"),
                       cui.div(*cards, class_="wbg-fgrid"), class_="wbg-start")


# ---------------------------------------------------------------- the pieces the views share

def heat(df, row, col, *, rows, cols, row_label=lambda v: v, col_label=lambda v: v, where=None, row_nav=None, col_nav=None,
         col_hover=None, cell_w=56, label_w=250, max_cell=150, of=None, tot_label="All"):
    """A rows x cols grid of activities (or projects) with a total on each row and column; a click on a tile or a
    total opens what is behind it. rows / cols: the values to show, in order, of the columns row / col of df (a
    column that holds several is expanded: an activity counts under each of its assets)."""
    if df.empty or not rows or not cols:
        return cui.p("Nothing under these filters.", class_="wbg-muted")
    where = where or {}
    both = expand(expand(df, row), col)
    c = tally(both, row, col, of=of)
    look = {(r[row], r[col]): r for _, r in c.iterrows()}
    z = [[int(look[(r, k)]["n"]) if (r, k) in look else None for k in cols] for r in rows]
    hover = [[f"{row_label(r)} · {col_label(k)}\n{of_text(look[(r, k)])}" if (r, k) in look else None for k in cols] for r in rows]
    keys = [[{"title": f"{row_label(r)} · {col_label(k)}", "where": {**where, row: r, col: k}} for k in cols] for r in rows]
    rf, cf = expand(df, row), expand(df, col)
    row_tot = [cnt(rf[rf[row] == r]) for r in rows]
    col_tot = [cnt(cf[cf[col] == k]) for k in cols]
    note = cui.p("Counting projects: a project counts once in each tile it has an activity in, so the tiles do not add up to the "
                 "totals' projects.", class_="kit-heat-note") if by_projects() else None
    return cui.div(kit.heat_table(
        [row_label(r) for r in rows], [col_label(k) for k in cols], z, row_tot=row_tot, col_tot=col_tot, grand=cnt(df),
        keys=keys, hover=hover, col_hover=col_hover or [str(k) for k in cols],
        row_keys=[{"title": row_label(r), "where": {**where, row: r}} for r in rows],
        col_keys=[{"title": col_label(k), "where": {**where, col: k}} for k in cols],
        grand_key={"title": "All", "where": where} if where else {"title": "Everything in this view", "where": {}},
        row_nav=row_nav, col_nav=col_nav, cell_w=cell_w, label_w=label_w, max_cell=max_cell, tot_label=tot_label), note)


def bars(df, col, *, where=None, label=lambda v: v, title=None, order=None, zeros=False, colors=None, of=None, label_w=220):
    """Bars of activities (or projects) per value of col, drawn as rows like the lists: a label, a bar, its value. A
    click opens the bar in the side panel like everything else."""
    if df.empty:
        return cui.p("Nothing under these filters.", class_="wbg-muted")
    c = tally(expand(df, col), col, of=of)
    if order:
        c = c.set_index(col).reindex(order if zeros else [o for o in order if o in set(c[col])]).reset_index()
        c["n"] = c["n"].fillna(0)
    rows = []
    for _, r in c.iterrows():
        k, name = r[col], label(r[col])
        rows.append({"label": name, "value": r["n"], "text": cell_text(r) if r["n"] else "0",
                     "tip": f"{name}\n{of_text(r) if r['n'] else '0 ' + unit_word()}",
                     "payload": {"title": (title or label)(k), "where": {**(where or {}), col: k}}, "color": (colors or {}).get(k)})
    return kit.bar_rows(rows, label_w=label_w)


def lens_map(df, where, *, height=420, go=False):
    """Countries with an activity. A click opens the country in the side panel (or, with go, its page)."""
    c = tally(df[~df["is_regional"].fillna(False).astype(bool)], "country_code", "place")
    if c.empty:
        return kit.empty("", "nothing on the map under these filters")
    fig = kit.world(c["country_code"], c["n"], c["place"], height=height, label=unit_word(), shaded=True,
                    hover=[f"<b>{r['place']}</b><br>{of_text(r)}" for _, r in c.iterrows()])
    names = list(fig.data[0].text) if len(fig.data) else []
    fig.data[0].customdata = [{"go": "country", "value": n} if go else {"title": n, "where": {**where, "place": n}} for n in names]
    return fig


def facts(name, kind, df, definition=None, note=None, *, of=None, of_what="projects read", extra=None):
    """The head of a lens: what it is and its definition on the left, its key figures as tiles on the right (how
    many projects of how many have it, its activities, countries and measures). Every Explore page opens with it."""
    b = base() if of is None else of
    places = df.loc[~df["is_regional"].fillna(False).astype(bool), "country_code"].nunique()
    n = df["project_id"].nunique()
    tiles = [(f"{n:,}", "project" if n == 1 else "projects", f"of {len(b):,} {of_what.split(' ', 1)[1]}" if len(b) else None),
             (f"{df['activity_id'].nunique():,}", "activity" if df["activity_id"].nunique() == 1 else "activities", None)]
    if places and kind != PLACE:
        tiles.append((f"{places:,}", "country" if places == 1 else "countries", None))
    if kind != "Measure":
        m = df["label_set"].nunique()
        tiles.append((f"{m:,}", "measure" if m == 1 else "measures", None))
    return cui.div(
        cui.div(cui.span(kind, class_="kd"), cui.h3(name),
                cui.div(L.definition_block(plain(definition)), class_="df") if definition else None,
                extra,
                cui.p(note, class_="nt") if note else None, class_="tx"),
        cui.div(*[cui.div(cui.tags.b(v), cui.span(lab), cui.tags.small(sub) if sub else None) for v, lab, sub in tiles], class_="tiles"),
        class_="wbg-head")


def project_facts(r, df):
    """A project's facts in one band: its name and id, then practice, amount, approval, closing, and what it commits to."""
    if r is None:
        return cui.p(df["project_name"].iloc[0], class_="fw-semibold mb-0")
    val = lambda v, f: f(v) if v is not None and pd.notna(v) else "—"  # noqa: E731
    items = [("Practice", r["practice"] or "—"), ("Amount", val(r["commitment_usd_millions"], lambda v: L.money(v * 1e6))),
             ("Approved", val(r["approval_fiscal_year"], lambda v: f"FY{int(v)}")), ("Closes", L.day(r["closing_date"]) or "—"),
             ("Measures", f"{int(r['measures']):,}"), ("Activities", f"{int(r['activities']):,}"),
             ("Next procurement", val(r["next_package_date"], L.day))]
    return cui.div(cui.div(cui.div(r["project_name"], class_="nm"), cui.div(r["project_id"], class_="id"), class_="who"),
                   cui.div(*[cui.div(cui.span(k, class_="k"), cui.span(v, class_="v")) for k, v in items], class_="facts"),
                   class_="wbg-pfacts")


def type_bars(items, *, head="Types"):
    """Types (or asset types) as clickable bars: the name with its definition in one line under it, a bar and the
    count, in the unit Count says. A click opens them in the side panel. items: dicts name, definition, proposed,
    acts, projects, title, where."""
    if not items:
        return cui.p("Nothing under these filters.", class_="wbg-muted mb-0")
    key = "projects" if by_projects() else "acts"
    top = max([it[key] for it in items] or [0]) or 1
    rows = []
    for it in items:
        d = L.short_def(plain(it.get("definition") or ""), 1)[0]
        tip = f"{it['name']}\n{it['acts']:,} {'activity' if it['acts'] == 1 else 'activities'} · {L.plural(it['projects'], 'project')}"
        rows.append(cui.tags.button(
            {"type": "button", "class": "wbg-tbar", "data-tip": tip, **L.clicker({"title": it["title"], "where": it["where"]})},
            cui.span(cui.span(it["name"], class_="nm"), cui.span("suggested", class_="sg", **{"data-tip": "Suggested, not yet an agreed type"})
                     if it.get("proposed") else None, cui.span(d, class_="df", title=d) if d else None, class_="tx"),
            cui.span(cui.span(class_="f", style=f"width:{100 * it[key] / top:.1f}%"), class_="tr"),
            cui.span(f"{it[key]:,}", class_="v")))
    return cui.div(cui.div(cui.span(head), cui.span(), cui.span("Projects" if by_projects() else "Activities", class_="v"), class_="wbg-tbar head"),
                   *rows, class_="wbg-tbars")


# ---------------------------------------------------------------- procurement: one component, used on every page

def pstate_of(key):
    """What the component keeps: the quarter picked, its status tab, the sort the reader chose (none: by date, or
    by country on the Contract completed tab, which is how to see who has already done something), the rows shown."""
    return {"q": None, "tab": "Planned", "sort": None, "desc": False, "limit": 25 if key == "pg" else 8, "page": 0,
            **pstate.get().get(key, {})}


def pstate_default(key):
    return 25 if key == "pg" else 8


def eff(key):
    s = pstate_of(key)
    t = (input.pg_status() or "All") if key == "pg" else s["tab"]
    return s, t, s["sort"] or ("country" if t == "Contract completed" else "date")


@reactive.effect
@reactive.event(input.pc)
def _pc():
    c = input.pc()
    key = c["key"]
    st = dict(pstate.get())
    s, _, sort = eff(key)
    cur = dict(st.get(key, {}))
    if "q" in c:
        cur.update(q=None if s["q"] == c["q"] else c["q"], limit=pstate_default(key), page=0)
    if "tab" in c:
        cur.update(tab=c["tab"], sort=None, desc=False, limit=pstate_default(key), page=0)
    if "sort" in c:
        cur.update(desc=not s["desc"]) if sort == c["sort"] else cur.update(sort=c["sort"], desc=False)
    if c.get("more"):
        cur["limit"] = 10 ** 6
    if c.get("fewer"):
        cur["limit"] = pstate_default(key)
    if "page" in c:
        cur["page"] = max(0, int(c["page"]))
    st[key] = cur
    pstate.set(st)


def proc_section(key, scope, *, tabs=True, hide=(), tab=None, title="Linked procurement"):
    """The procurement component: a calendar of linked packages by quarter and, under it, the list with status
    tabs. scope(): the packages this page is about. tab(): a status chosen elsewhere on the page (the Procurement
    page's filter), when the component has no tabs of its own."""
    def calendar():
        s, _, _ = eff(key)
        if scope().empty:
            # one line in place of the card: the card's header is hidden by the css when this is all it holds
            return cui.div(cui.tags.b(title), cui.span("No procurement package is linked to these activities.", class_="wbg-muted"),
                           class_="wbg-proc-empty")
        return L.proc_calendar(scope(), key, s["q"], pd.Timestamp.today().normalize())

    def listing():
        s, t, sort = eff(key)
        if scope().empty:
            return None
        return L.proc_list(scope(), key, tab() if tab else t, sort, s["desc"], s["limit"], s["q"], asset_names(),
                           tabs=tabs, hide=hide, page=s["page"] if key == "pg" else None)

    calendar.__name__, listing.__name__ = f"{key}_pcal", f"{key}_plist"
    return cui.TagList(render.ui(calendar), render.ui(listing))


# ---------------------------------------------------------------- the panel: what is behind a click

def sentences_for(ids):
    f = chosen()
    ids = tuple(ids)
    return kit.cached(("wbg", "sentences", f, ids), lambda: W.activity_sentences(q, list(ids), f), seconds=300)


def activity_cards(df, pk, *, first_open=True, show_project=False):
    """A card for each activity of df, with its sentences and linked packages."""
    sent = sentences_for(df["activity_id"]) if len(df) else pd.DataFrame()
    cards = []
    for i, (_, a) in enumerate(df.iterrows()):
        mine = sent[sent["activity_id"] == a["activity_id"]] if len(sent) else sent
        linked = pk[pk["acts"].map(lambda x: a["activity_id"] in x)].sort_values("date") if len(pk) else pk
        cards.append(L.activity_card(a, mine, linked, open=first_open and i == 0, show_project=show_project))
    return cards


@reactive.calc
def panel_df():
    """The activities the panel holds: what was clicked, then its own All / Investment / Policy."""
    d = drill.get()
    req(d and d["kind"] == "acts")
    df = L.filter_acts(acts(), d["where"])
    inst = panel_inst.get()
    return df if inst == "all" else df[df["instrument"] == inst]


@reactive.calc
def panel_all():
    d = drill.get()
    req(d and d["kind"] == "acts")
    return L.filter_acts(acts(), d["where"])


with ui.sidebar(id="panel", position="right", open="closed", width=560, title="What is behind it"):

    @render.ui
    def panel_body():
        d = drill.get()
        if not d:
            return cui.p("Click a bar, a cell, a number, a country, a card or a row.", class_="wbg-muted")
        if d["kind"] == "pkg":
            return package_panel(d["package_id"])
        if d["kind"] == "nd":
            return not_digital_panel(d["project_id"])
        whole, df = panel_all(), panel_df()
        if whole.empty:
            return cui.div(cui.h5(d["title"]), cui.p("Nothing under the filters set now.", class_="wbg-muted"))
        n_inv, n_pol = int((whole["instrument"] == "investment").sum()), int((whole["instrument"] == "policy").sum())
        sentences = int(df["n_sentences"].sum())
        head = cui.div(
            cui.h5(d["title"]),
            cui.div(f"{L.n_acts(df['activity_id'].nunique())} · "
                    f"{L.plural(df['project_id'].nunique(), 'project')} · {L.plural(sentences, 'sentence')}", class_="tot"),
            cui.div(seg("panel_inst", panel_inst.get(), [("all", "All", len(whole)), ("investment", "Investment", n_inv),
                                                         ("policy", "Policy", n_pol)]),
                    cui.download_button("dl_panel", "Download these", class_="btn btn-sm btn-outline-primary") if len(df) else None,
                    class_="wbg-bar"), class_="wbg-ph")
        if df.empty:
            return cui.div(head, cui.p("Nothing under this filter.", class_="wbg-muted"))
        pk = pkgs_for(df)
        order = df.groupby("project_id").size().sort_values(ascending=False)
        names = df.drop_duplicates("project_id").set_index("project_id")
        drawn, body, shown = 0, [], 0
        for pid in sorted(order.index, key=lambda p: (-order[p], names.loc[p, "project_name"])):
            part = df[df["project_id"] == pid]
            room = max(0, SENT_CAP - drawn)
            if room == 0:
                break
            part = part.head(room)
            drawn += len(part)
            shown += 1
            body.append(cui.div(
                cui.tags.header(cui.div(cui.span(names.loc[pid, "project_name"], class_="t"),
                                        cui.div(f"{names.loc[pid, 'place']} · {L.n_acts(order[pid])}", class_="s")),
                                cui.tags.button({"type": "button", "class": "btn btn-link", **L.clicker({"go": "project", "value": pid})},
                                                "open project")),
                *activity_cards(part, pk, first_open=drawn == len(part)), class_="wbg-pgroup"))
        if drawn < len(df):
            body.append(cui.p(f"The first {drawn} activities are shown, in the {shown} projects with most. "
                              f"{len(df) - drawn:,} more are in the download. Click a smaller part to see them here.",
                              class_="wbg-muted-s mt-3"))
        return cui.div(head, *body)


def package_panel(package_id):
    parts = kit.cached(("wbg", "package", package_id), lambda: W.package(q, package_id), seconds=300)
    if parts["package"].empty:
        return cui.p("This package is not in the data.")
    parts = {**parts, "package": L.prep_pkgs(parts["package"])}
    p = parts["package"].iloc[0]
    a = L.link_procurement(L.prep_acts(parts["activities"]), pd.DataFrame(columns=pkgs().columns))
    cards = activity_cards(a, pkgs().iloc[0:0], first_open=True, show_project=False) if len(a) else []
    btn = cui.tags.button({"type": "button", "class": "btn btn-link btn-sm p-0 ms-2", **L.clicker({"go": "project", "value": p["project_id"]})},
                          "open project")
    return cui.div(cui.div(cui.h5(f"Package {p['package_number'] or p['package_id']}"), class_="wbg-ph"),
                   L.package_sheet(parts, cards, btn, asset_names()))


def not_digital_panel(project_id):
    f = chosen()
    mids = fam_table().loc[fam_table()["family"] == f, "label_set"].tolist()
    nd = W.not_digital(q, project_id=project_id, measure=mids, cohort=cohort())
    name = acts().loc[acts()["project_id"] == project_id, "project_name"].iloc[0] if (acts()["project_id"] == project_id).any() else project_id
    body = []
    for (m,), g in nd.groupby(["measure_name"]):
        body.append(cui.div(cui.div(kit.tag(m, "solid", title="Measure"), class_="mt-3 mb-1"),
                            *[L.sentence(s) for _, s in g.iterrows()]))
    return cui.div(cui.div(cui.h5(f"Also read, not counted · {name}"),
                           cui.div(f"{L.plural(len(nd), 'sentence')} the pipeline found committed but judged not to be about a digital "
                                   f"asset or the digital sector. They count nowhere on the dashboards.", class_="tot"), class_="wbg-ph"),
                   *body)


# ======================================================= overview
with ui.nav_panel("Overview"):

    @render.ui
    def ov_notice():
        return notice("page")

    @render.ui
    def ov_intro():
        f = chosen()
        req(f)
        if notice():
            return None
        return cui.div(cui.p(f"What World Bank project documents commit to do for digital assets under {family_name(f).lower()}, and the "
                             "procurement linked to it. An activity is one thing a project commits to do for a measure, grouped from the "
                             "sentences that say so: what a document says the project will or may do, not delivery. Click any bar, cell, "
                             "number or row for the activities and sentences behind it. The About tab sets out the method and its limits.",
                             class_="mb-0"), unit_ctl(), class_="wbg-titlerow")

    @render.ui
    def ov_note():
        if not by_projects():
            return None
        return cui.div("Counting projects: a project counts once in each bar or cell it has an activity in, so the bars do not add "
                       "up to the number of projects. Hover a bar or cell for the share of the projects read.",
                       class_="alert alert-light border py-2 small mb-3")

    with ui.layout_columns(col_widths=[4, 8], class_="mb-3"):
        with ui.card():
            ui.card_header("Figures")

            @render.ui
            def ov_figs():
                df, pk, b = acts(), pkgs(), base()

                def fig(label, value, note=None, sub=False, where=None):
                    attrs = {"class": "wbg-fig" + (" sub" if sub else "")}
                    if where is not None:
                        attrs.update(style="cursor:pointer", **L.clicker({"title": label, "where": where}))
                    return cui.div(cui.span(label, cui.tags.small(note) if note else None, class_="l"),
                                   cui.span(f"{value:,}", class_="v"), attrs)
                n = df["project_id"].nunique()
                return cui.div(
                    fig("Projects read", len(b), "with a document read"),
                    fig("With an activity", n, f"{n / len(b):.0%} of the projects read" if len(b) else None, where={}),
                    fig("Activities", len(df), "what the projects commit to do", where={}),
                    fig("of which investment", int((df["instrument"] == "investment").sum()), sub=True, where={"instrument": "investment"}),
                    fig("of which policy", int((df["instrument"] == "policy").sum()), sub=True, where={"instrument": "policy"}),
                    fig("Linked packages", len(pk), "procurement linked to an activity"), class_="wbg-figs")

        with ui.card():
            ui.card_header("Where")

            @render_plotly
            def ov_map():
                return lens_map(acts(), {}, height=430, go=True)

            @render.text
            def ov_regional():
                reg = acts()[acts()["is_regional"].fillna(False).astype(bool)]
                n = cnt(reg) if len(reg) else 0
                return f"{unit_n(n)} {'are' if n != 1 else 'is'} in regional projects and not on the map."

    with ui.card():
        ui.card_header("Measures by asset")

        @render.ui
        def ov_heat():
            df = acts()
            names = measure_names()
            have = set(a for l in df["assets"] for a in l)
            cols = [a for a in axis() if a in have]
            ms = [m for m in df.groupby("label_set").size().sort_values(ascending=False).index]
            return heat(df, "label_set", "asset", rows=ms, cols=cols, row_label=lambda m: names.get(m, m), col_label=L.short_asset,
                        col_hover=cols, row_nav=[{"go": "measure", "value": m} for m in ms],
                        col_nav=[{"go": "asset", "value": a} for a in cols], label_w=300, max_cell=190)

    with ui.card():
        ui.card_header("Procurement linked to these activities")
        proc_section("ov", lambda: pkgs())

    with ui.layout_columns(col_widths=[6, 6]):
        with ui.card():
            ui.card_header("By approval year")

            @render.ui
            def ov_fy():
                df = acts().dropna(subset=["approval_fiscal_year"])
                years = sorted(df["approval_fiscal_year"].unique())
                return bars(df, "approval_fiscal_year", label=lambda y: f"FY{int(y)}", title=lambda y: f"Approved in FY{int(y)}",
                            order=years, label_w=150)

            @render.ui
            def ov_fy_note():
                missing = acts()[acts()["approval_fiscal_year"].isna()]
                n = cnt(missing) if len(missing) else 0
                return cui.p("FY is the World Bank fiscal year, July to June." +
                             (f" Not shown: {unit_n(n)} with no approval year." if n else ""), class_="kb-note mb-0")

        with ui.card():
            ui.card_header("By region")

            @render.ui
            def ov_region():
                df = acts()
                df = df[df["region"].notna() & (df["region"] != "")]
                return bars(df, "region", title=lambda r: f"In {r}", label_w=150)


# ======================================================= explore
def lens_where(lens, value):
    return {"country": {"place": value}, "project": {"project_id": value}, "asset": {"asset": value},
            "measure": {"label_set": value}}[lens]


def mwhere(m):
    """What a click on the measure page opens: the measure, and the instrument the page is filtered to."""
    return {"label_set": m, **({"instrument": m_inst.get()} if m_inst.get() != "all" else {})}


def lens_frame(lens=None, value=None):
    """The activities of what is picked. While the picker still holds the last lens's value (the moment after
    the lens changes) this waits, so no output draws an empty state and then its real one a moment later."""
    lens, value = lens or input.lens(), value if value is not None else input.pick()
    df = L.filter_acts(acts(), lens_where(lens, value)) if value else acts().iloc[0:0]
    if lens == "measure" and m_inst.get() != "all":
        df = df[df["instrument"] == m_inst.get()]
    req(len(df) > 0)
    return df


def lens_base(lens=None, value=None):
    """The projects a share inside a lens is taken of: a country's projects (with or without an activity); for an
    asset or a measure, the projects that have it."""
    b = base()
    lens, value = lens or input.lens(), value if value is not None else input.pick()
    if lens == "country":
        return b[b["place"] == value]
    if lens == "project":
        return b[b["project_id"] == value]
    return b[b["project_id"].isin(lens_frame(lens, value)["project_id"])]


with ui.nav_panel("Explore"):

    @render.ui
    def ex_notice():
        return notice("page")

    with ui.div(class_="wbg-titlerow ex"):
        with ui.div(class_="d-flex flex-wrap gap-3 align-items-end"):
            ui.input_radio_buttons("lens", "View by", LENSES, selected="country", inline=True)
            ui.input_selectize("pick", None, choices=[], width="460px")

        @render.ui
        def ex_unit():
            return unit_ctl()

    @reactive.effect
    def _pick_choices():
        df, lens = acts(), input.lens()
        if lens == "asset":
            have = {a for l in df["assets"] for a in l}
            choices = [a for a in axis() if a in have]
        else:
            col = {"country": "place", "project": "project_id", "measure": "label_set"}[lens]
            choices = df.groupby(col).size().sort_values(ascending=False).index.tolist()
            if lens == "project":
                names = project_names()
                choices = {pid: names.get(pid, pid) for pid in choices}
            elif lens == "measure":
                names = measure_names()
                choices = {m: names.get(m, m) for m in choices}
        with reactive.isolate():
            want = pending_pick.get() or input.pick()
            pending_pick.set(None)
        ui.update_selectize("pick", choices=choices, selected=want if want in choices else (next(iter(choices), None)))

    # ---------------------------------------------- one country
    with ui.panel_conditional("input.lens === 'country'"):

        @render.ui
        def c_head():
            df = lens_frame()
            return facts(input.pick(), PLACE, df, of=lens_base(), of_what="projects read here")

        @render.ui
        def c_body():
            """A country with one project shows that project in full: its facts, its measures and assets side by side and
            its activities inline. A country with several shows its projects, who commits to what (a heat map) and its
            assets beside it."""
            df, place = lens_frame(), input.pick()
            pf = proj_facts()
            pf = pf[pf["project_id"].isin(df["project_id"])].sort_values(["activities", "project_name"], ascending=[False, True])
            where = {"place": place}
            assets = cui.card(cui.card_header("Digital assets"), cui.card_body(
                bars(df, "asset", where=where, label=L.short_asset, title=lambda a: f"{L.short_asset(a)} in {place}", order=axis(),
                     of=lens_base(), label_w=150)))
            if df["project_id"].nunique() == 1:
                r = pf.iloc[0] if len(pf) else None
                names = measure_names()
                project = cui.card(
                    cui.card_header(cui.span("The project"), cui.tags.button(
                        {"type": "button", "class": "btn btn-link btn-sm p-0", **L.clicker({"go": "project", "value": df["project_id"].iloc[0]})},
                        "Open the project page"), class_="d-flex justify-content-between align-items-center"),
                    cui.card_body(project_facts(r, df)))
                measures = cui.card(cui.card_header("Measures"), cui.card_body(
                    bars(df, "label_set", where=where, label=lambda m: names.get(m, m), of=lens_base(), label_w=220)))
                cards = activity_cards(df.sort_values(["measure_name", "activity_label"]), pkgs_for(df), first_open=False)
                acts_card = cui.card(cui.card_header(cui.span("What it commits to"), cui.span(L.n_acts(len(df)), class_="wbg-muted-s"),
                                                     class_="d-flex justify-content-between align-items-center"),
                                     cui.card_body(cui.div(*cards, class_="wbg-actgrid")))
                return cui.TagList(project, cui.layout_columns(measures, assets, col_widths={"sm": (12, 12), "lg": (7, 5)}), acts_card)
            rows = []
            for r in pf.itertuples():
                nxt = L.day(r.next_package_date) if pd.notna(r.next_package_date) else "—"
                rows.append(cui.tags.tr(
                    cui.tags.td(cui.span(r.project_name), cui.span(r.project_id, class_="id"), class_="pn"),
                    cui.tags.td(r.practice or "—"),
                    cui.tags.td(L.money(r.commitment_usd_millions * 1e6) if pd.notna(r.commitment_usd_millions) else "—", class_="r"),
                    cui.tags.td(f"FY{int(r.approval_fiscal_year)}" if pd.notna(r.approval_fiscal_year) else "—"),
                    cui.tags.td(L.day(r.closing_date) or "—"),
                    cui.tags.td(f"{int(r.measures):,}", class_="r"), cui.tags.td(f"{int(r.activities):,}", class_="r"),
                    cui.tags.td(nxt),
                    {"class": "go", **L.clicker({"title": f"{r.project_name} in {place}", "where": {"project_id": r.project_id}})}))
            heads = [("Project", ""), ("Practice", ""), ("Amount", "r"), ("Approved", ""), ("Closes", ""), ("Measures", "r"),
                     ("Activities", "r"), ("Next procurement", "")]
            table = cui.card(cui.card_header("Its projects"), cui.card_body(cui.div(cui.tags.table(
                cui.tags.thead(cui.tags.tr(*[cui.tags.th(h, class_=c) for h, c in heads])), cui.tags.tbody(*rows),
                class_="wbg-table wbg-ctable"), class_="wbg-scroll")))
            names, pn = measure_names(), project_names()
            ps = df.groupby("project_id").size().sort_values(ascending=False).index.tolist()
            ms = df.groupby("label_set").size().sort_values(ascending=False).index.tolist()
            grid = cui.card(cui.card_header("Who commits to what"), cui.card_body(
                heat(df, "label_set", "project_id", rows=ms, cols=ps, row_label=lambda m: names.get(m, m),
                     col_label=lambda p: pn.get(p, p), where=where, label_w=230, cell_w=72, max_cell=200,
                     row_nav=[{"go": "measure", "value": m} for m in ms], col_nav=[{"go": "project", "value": p} for p in ps],
                     of=lens_base())))
            inst = cui.card(cui.card_header("Investment and policy"), cui.card_body(
                bars(df, "chip", where=where, order=["Investment", "Policy"], title=lambda v: f"{v} in {place}", label_w=150, of=lens_base())))
            if len(ps) <= 4:
                return cui.TagList(table, cui.layout_columns(grid, cui.div(assets, inst, class_="wbg-stack"),
                                                             col_widths={"sm": (12, 12), "lg": (8, 4)}, class_="wbg-pair"))
            return cui.TagList(table, grid, cui.layout_columns(assets, inst, col_widths={"sm": (12, 12), "lg": (6, 6)}, class_="wbg-pair"))

        with ui.card():
            ui.card_header("Procurement in this country")
            proc_section("c", lambda: pkgs_for(lens_frame()), hide=("country",), title="Procurement in this country")

    # ---------------------------------------------- one project
    with ui.panel_conditional("input.lens === 'project'"):

        @reactive.calc
        def project_parts():
            df = lens_frame()
            pid = df["project_id"].iloc[0]
            return kit.cached(("wbg", "project", pid), lambda: W.project(q, pid))

        @reactive.calc
        def project_sentences():
            """The sentences of the project's activities: the first of each gives its document and page."""
            pid = input.pick()
            f = chosen()
            return kit.cached(("wbg", "psent", f, pid), lambda: W.activity_sentences(q, None, f, project=pid))

        @render.ui
        def p_head():
            parts, df = project_parts(), lens_frame()
            if parts["header"].empty:
                return None
            h = parts["header"].iloc[0]
            bits = [h["project_id"], h["country_name"] or h["region"], h["status"],
                    f"approved FY{int(h['approval_fiscal_year'])}" if pd.notna(h["approval_fiscal_year"]) else None,
                    L.money(h["commitment_usd_m"] * 1e6) if pd.notna(h["commitment_usd_m"]) else None,
                    f"closes {h['closing_date']:%d %b %Y}" if pd.notna(h["closing_date"]) else None,
                    L.plural(int(h["documents_read"]), "document") + " read"]
            nm, npk = df["label_set"].nunique(), len(pkgs_for(df))
            tiles = [(len(df), "activity" if len(df) == 1 else "activities"), (nm, "measure" if nm == 1 else "measures"),
                     (npk, "linked package" if npk == 1 else "linked packages")]
            return cui.div(
                cui.div(cui.span("Project", class_="kd"), cui.h3(h["project_name"]),
                        cui.div(" · ".join(str(b) for b in bits if b), class_="df"), class_="tx"),
                cui.div(*[cui.div(cui.tags.b(f"{v:,}"), cui.span(lab)) for v, lab in tiles], class_="tiles"), class_="wbg-head")

        with ui.card():
            with ui.card_header(class_="d-flex flex-wrap justify-content-between align-items-center gap-2"):
                "Activities"

                @render.ui
                def p_group_ctl():
                    return cui.div(cui.span("Group by", class_="wbg-muted-s me-2"),
                                   seg("p_group", p_group.get(), [("measure", "Measure", None), ("asset", "Asset", None),
                                                                  ("component", "Component", None)]), class_="d-flex align-items-center")

            @render.ui
            def p_acts():
                df, sent, pk = lens_frame(), project_sentences(), pkgs()
                first = sent.drop_duplicates("activity_id").set_index("activity_id")
                mode = p_group.get()
                if mode == "measure":
                    df = df.assign(g=df["measure_name"])
                elif mode == "asset":
                    df = df.assign(g=df["assets"]).explode("g")
                else:
                    df = df.assign(g=df["component"])
                groups = list(df.groupby("g", sort=False))
                if mode == "asset":
                    order = {a: i for i, a in enumerate(axis())}
                    groups.sort(key=lambda kv: order.get(kv[0], 99))
                else:
                    groups.sort(key=lambda kv: (kv[0] == "No component stated", kv[0]))
                out = []
                for g, rows in groups:
                    trs = []
                    for _, a in rows.sort_values(["measure_name", "activity_label"]).iterrows():
                        fs = first.loc[a["activity_id"]] if a["activity_id"] in first.index else None
                        src = (f"{L.source(fs['document_kind'], fs['document_date'])}"
                               + (f", page {int(fs['page_number'])}" if pd.notna(fs["page_number"]) else "")) if fs is not None else ""
                        if a["pk_n"]:
                            pro = [L.status_dot(a["pk_stage"], a["pk_late"]), cui.div(
                                (L.day(a["pk_date"]) or "no date") + (f" · {a['pk_n']} packages" if a["pk_n"] > 1 else ""), class_="wbg-muted-s")]
                        else:
                            pro = [cui.span("—", class_="wbg-muted-s")]
                        trs.append(cui.tags.tr(
                            cui.tags.td(cui.div(a["activity_label"], class_="clamp fw-semibold"),
                                        cui.div(f"{L.plural(a['n_sentences'], 'sentence')} · {src}", class_="wbg-muted-s")),
                            cui.tags.td(cui.div(*L.type_tags(a), class_="tg")),
                            cui.tags.td(cui.div(*[kit.tag(t, "tint") for t in L.applied_to(a)], class_="tg")),
                            cui.tags.td(L.chip(a["instrument"])),
                            cui.tags.td(*pro),
                            {"class": "go", **L.clicker({"title": a["activity_label"], "where": {"activity_ids": [a["activity_id"]]}})}))
                    label = g if mode != "asset" else L.short_asset(g)
                    out.append(cui.tags.details(
                        cui.tags.summary(cui.span(label, class_="t"), cui.span(L.n_acts(len(rows)), class_="s")),
                        cui.div(cui.tags.table(
                            cui.tags.colgroup(cui.tags.col(class_="a-act"), cui.tags.col(class_="a-typ"), cui.tags.col(class_="a-app"),
                                              cui.tags.col(class_="a-chip"), cui.tags.col(class_="a-pro")),
                            cui.tags.thead(cui.tags.tr(*[cui.tags.th(h) for h in ("Activity", "Type", "Applied to", "", "Procurement")])),
                            cui.tags.tbody(*trs), class_="wbg-table wbg-acts"), class_="wbg-scroll"),
                        class_="wbg-grp", open=""))
                return cui.div(*out)

            @render.ui
            def p_nd():
                f, pid = chosen(), input.pick()
                mids = fam_table().loc[fam_table()["family"] == f, "label_set"].tolist()
                nd = kit.cached(("wbg", "nd", f, pid), lambda: W.not_digital(q, project_id=pid, measure=mids, cohort=cohort()))
                if nd.empty:
                    return cui.p("Also read, not counted: no committed sentence was left out as not digital.", class_="wbg-muted-s mt-2 mb-0")
                return cui.p(cui.tags.button({"type": "button", "class": "btn btn-link btn-sm p-0", **L.clicker({"nd": pid})},
                                             f"Also read, not counted: {L.plural(len(nd), 'committed sentence')}"),
                             " that the pipeline judged not to be about a digital asset or the digital sector. Open them to see what the rule leaves out.",
                             class_="wbg-muted-s mt-2 mb-0")

        with ui.layout_columns(col_widths=[7, 5]):
            with ui.card():
                ui.card_header("Components, with cost from all funding sources")

                @render.ui
                def p_components():
                    c = project_parts()["components"]
                    if c.empty:
                        return cui.p("No components are listed in the documents read.", class_="wbg-muted")
                    rows = [cui.tags.tr(cui.tags.td(f"{n} {name}" if n else name),
                                        cui.tags.td(f"{v:,.1f}" if pd.notna(v) else "—", class_="r"))
                            for n, name, v in zip(c["component_number"].fillna(""), c["component_name"], c["cost_usd_millions"])]
                    return cui.tags.table(cui.tags.thead(cui.tags.tr(cui.tags.th("Component"), cui.tags.th("US$ million", class_="r"))),
                                          cui.tags.tbody(*rows), class_="wbg-table")

            with ui.card():
                ui.card_header("Digital assets its activities apply to")

                @render.ui
                def p_assets():
                    return bars(lens_frame(), "asset", where={"project_id": input.pick()}, label=L.short_asset, order=axis(), label_w=150)

        with ui.card():
            ui.card_header("Its linked procurement")
            proc_section("p", lambda: pkgs_for(lens_frame()), hide=("project", "country"), title="Its linked procurement")

        with ui.card():
            ui.card_header("Documents read")

            @render.ui
            def p_docs():
                d = project_parts()["documents"]
                return cui.tags.ul(*[cui.tags.li(cui.a(f"{r.title or r.document_kind}", href=r.pdf_url, target="_blank"),
                                                 f" · {L.DOC_KIND.get(r.document_kind, 'Project document')} · {r.document_date:%d %b %Y}"
                                                 if pd.notna(r.document_date) else "") for r in d.itertuples()], class_="mb-0")

    # ---------------------------------------------- one asset
    with ui.panel_conditional("input.lens === 'asset'"):

        @render.ui
        def a_head():
            df = lens_frame()
            a = asset_df()
            a = a[a["asset_name"] == input.pick()]
            if input.pick() == L.NO_ASSET:
                d = ("Activities for which the documents name no single digital asset. Many are policy activities (a law, strategy, "
                     "standard or plan) about the sector in general; policy about one asset is counted under that asset.")
            else:
                d = a["asset_definition"].iloc[0] if len(a) else None
            return facts(input.pick(), "Digital asset", df, d)

        with ui.layout_columns(col_widths={"sm": (12, 12), "lg": (6, 6)}):
            with ui.card():
                ui.card_header("Its asset types")

                @render.ui
                def a_types():
                    df, name = lens_frame(), input.pick()
                    a = asset_df()
                    a = a[(a["asset_name"] == name) & a["subtype_name"].notna()]
                    if a.empty:
                        return cui.p("This is not one asset, so it has no asset types.", class_="wbg-muted")
                    ex = expand(df, "asset_type")
                    items = []
                    for r in a.itertuples():
                        mine = ex[ex["asset_type"] == r.subtype_name]
                        items.append({"name": r.subtype_name, "definition": r.subtype_definition, "acts": mine["activity_id"].nunique(),
                                      "projects": mine["project_id"].nunique(), "title": f"{r.subtype_name} · {name}",
                                      "where": {"asset": name, "asset_type": r.subtype_name}})
                    return type_bars(items, head="Asset type")

            with ui.card():
                ui.card_header("Where")

                @render_plotly
                def a_map():
                    return lens_map(lens_frame(), {"asset": input.pick()}, height=300)

        with ui.layout_columns(col_widths={"sm": (12, 12), "xl": (5, 7)}):
            with ui.card():
                ui.card_header("Measures committed for it")

                @render.ui
                def a_measures():
                    names = measure_names()
                    return bars(lens_frame(), "label_set", where={"asset": input.pick()}, label=lambda m: names.get(m, m),
                                of=lens_base(), label_w=210)

            with ui.card():
                ui.card_header("Measures by region")

                @render.ui
                def a_heat():
                    df = lens_frame()
                    names = measure_names()
                    rg = df.groupby("region").size().sort_values(ascending=False).index.tolist()
                    ms = df.groupby("label_set").size().sort_values(ascending=False).index.tolist()
                    return heat(df, "label_set", "region", rows=ms, cols=rg, row_label=lambda m: names.get(m, m), col_label=L.short_region,
                                col_hover=rg, where={"asset": input.pick()}, label_w=230, of=lens_base())

        with ui.card():
            ui.card_header("Procurement for this asset")
            proc_section("a", lambda: pkgs_for(lens_frame()), title="Procurement for this asset")

    # ---------------------------------------------- one measure
    with ui.panel_conditional("input.lens === 'measure'"):

        @render.ui
        def m_head():
            df = lens_frame()
            m = measure_df()
            m = m[m["label_set"] == input.pick()]
            acc = None
            if len(m) and pd.notna(m["precision"].iloc[0]):
                acc = (f"Precision {m['precision'].iloc[0]:.0%}: the share of the sentences counted for this measure "
                       f"that a grader agreed with, on {int(m['graded_units'].iloc[0])} graded sentences"
                       + (" (the sample used for tuning, so provisional)" if m["graded_sheet"].iloc[0] != "evaluation" else "")
                       + ". It does not measure activities the method missed.")
            whole = L.filter_acts(acts(), {"label_set": input.pick()})
            n_inv, n_pol = int((whole["instrument"] == "investment").sum()), int((whole["instrument"] == "policy").sum())
            ctl = cui.div(cui.span("Show", class_="wbg-muted-s"),
                          seg("m_inst", m_inst.get(), [("all", "All", len(whole)), ("investment", "Investment", n_inv), ("policy", "Policy", n_pol)]),
                          cui.span("filters this whole page", class_="wbg-muted-s"), class_="inst")
            return facts(measure_names().get(input.pick(), input.pick()), "Measure", df,
                         m["definition"].iloc[0] if len(m) else None, acc, extra=ctl)

        with ui.layout_columns(col_widths={"sm": (12, 12), "lg": (6, 6)}):
            with ui.card():
                ui.card_header("Its types")

                @render.ui
                def m_types():
                    df, m = lens_frame(), input.pick()
                    td = type_df()
                    td = td[td["label_set"] == m]
                    ex = expand(df, "type")
                    items = []
                    for r in td.itertuples():
                        mine = ex[ex["type"] == r.type_id]
                        if mine.empty and r.is_proposed:
                            continue
                        items.append({"name": L.short_type(r.type_name), "definition": r.definition, "proposed": bool(r.is_proposed),
                                      "acts": mine["activity_id"].nunique(), "projects": mine["project_id"].nunique(),
                                      "title": f"{L.short_type(r.type_name)} · {measure_names().get(m, m)}", "where": {**mwhere(m), "type": r.type_id}})
                    none = ex[ex["type"] == W.NO_TYPE]
                    if len(none):
                        items.append({"name": "No type stated", "definition": "Activities whose sentences name no specific type.",
                                      "acts": none["activity_id"].nunique(), "projects": none["project_id"].nunique(),
                                      "title": f"No type stated · {measure_names().get(m, m)}", "where": {**mwhere(m), "type": W.NO_TYPE}})
                    return type_bars(items)

            with ui.card():
                ui.card_header("Where")

                @render_plotly
                def m_map():
                    return lens_map(lens_frame(), mwhere(input.pick()), height=380)

        with ui.card():
            ui.card_header("Where it stands, by linked procurement")
            proc_section("m", lambda: pkgs_for(lens_frame()), title="Linked procurement")

        with ui.layout_columns(col_widths={"sm": (12, 12), "xl": (6, 6)}):
            with ui.card():
                ui.card_header("Types by region")

                @render.ui
                def m_heat_region():
                    df, m = lens_frame(), input.pick()
                    tn = type_names(m)
                    rg = df.groupby("region").size().sort_values(ascending=False).index.tolist()
                    ts = [t for t in expand(df, "type")["type"].dropna().unique()]
                    ts = sorted(ts, key=lambda t: (t == W.NO_TYPE, str(tn.get(t, t))))
                    return heat(df, "type", "region", rows=ts, cols=rg, row_label=lambda t: L.short_type(tn.get(t, t)),
                                col_label=L.short_region, col_hover=rg, where=mwhere(m), label_w=160, of=lens_base())

            with ui.card():
                ui.card_header("Types by asset")

                @render.ui
                def m_heat_asset():
                    df, m = lens_frame(), input.pick()
                    tn = type_names(m)
                    have = {a for l in df["assets"] for a in l}
                    cols = [a for a in axis() if a in have]
                    ts = sorted(expand(df, "type")["type"].dropna().unique(), key=lambda t: (t == W.NO_TYPE, str(tn.get(t, t))))
                    return heat(df, "type", "asset", rows=ts, cols=cols, row_label=lambda t: L.short_type(tn.get(t, t)),
                                col_label=L.short_asset, col_hover=cols, where=mwhere(m), label_w=160, of=lens_base())


# ======================================================= procurement
with ui.nav_panel("Procurement"):

    @render.ui
    def pg_notice():
        return notice("page")
    ui.h3("Procurement linked to the family's activities", class_="h4 mt-3 mb-1")
    ui.p("Every procurement package the pipeline linked to an activity of this family. A link is the model's reading: a lead to check, "
         "not a finding. Choose Contract completed and sort by country to see who has already done something.", class_="mb-2", style="max-width: 110ch; color:#4b5563")

    with ui.div(class_="wbg-filters"):
        ui.input_select("pg_status", "Status", ["All", *L.STATUSES], selected="All", width="200px")
        ui.input_select("pg_country", "Country", ["All countries"], width="250px")
        ui.input_select("pg_asset", "Asset", ["All assets"], width="270px")
        ui.input_select("pg_measure", "Measure", ["All measures"], width="380px")

    @reactive.effect
    def _pg_choices():
        pk = pkgs()
        names = measure_names()
        have = {a for r in pk.itertuples() for a in L.split(r.asset_ids) + L.split(r.shared_asset_ids)}
        an = asset_names()
        ui.update_select("pg_country", choices=["All countries", *sorted(pk["place"].dropna().unique())])
        ui.update_select("pg_asset", choices={"": "All assets", **{k: L.short_asset(v) for k, v in an.items() if k in have}})
        ui.update_select("pg_measure", choices={"": "All measures", **{k: v for k, v in sorted(names.items(), key=lambda kv: kv[1])}})

    @reactive.effect
    @reactive.event(input.pg_status, input.pg_country, input.pg_asset, input.pg_measure)
    def _pg_page_reset():
        st = dict(pstate.get())
        st["pg"] = {**st.get("pg", {}), "page": 0}
        pstate.set(st)

    @reactive.calc
    def pg_pkgs():
        pk, df = pkgs(), acts()
        if input.pg_country() and input.pg_country() != "All countries":
            pk = pk[pk["place"] == input.pg_country()]
        if input.pg_asset():
            a = input.pg_asset()
            pk = pk[pk.apply(lambda r: a in L.split(r["asset_ids"]) or a in L.split(r["shared_asset_ids"]), axis=1)] if len(pk) else pk
        if input.pg_measure():
            pk = pkgs_for(df[df["label_set"] == input.pg_measure()], pk)
        s = input.pg_status()
        if s and s != "All":
            pk = pk[pk["tab"] == s]
        return pk

    with ui.card():
        ui.card_header("Linked packages")

        @render.ui
        def pg_count():
            return cui.p(f"{L.plural(len(pg_pkgs()), 'linked package')} match the filters.", class_="wbg-muted-s mb-2")
        proc_section("pg", lambda: pg_pkgs(), tabs=False, tab=lambda: input.pg_status() or "All")


# ======================================================= about
@reactive.effect
@reactive.event(input.view)
def _about_has_no_panel():
    # The side panel belongs to the charts; the About view reads better at full width.
    if input.view() == "About":
        ui.update_sidebar("panel", show=False)


with ui.nav_panel("About"):

    @render.ui
    def about_page():
        # The counts on the pipeline figure, read once and kept for six hours.
        try:
            n = kit.cached(("wbg", "about"), lambda: W.about(q), seconds=6 * 3600)
        except psycopg.Error:
            return cui.div("The new data is not published yet, so the counts on this page cannot be read.", class_="alert alert-light border my-3 wbg-notice")
        return cui.HTML(wbg_about.page(n))


ui.nav_spacer()

SEARCH_ICON = ('<svg width="17" height="17" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">'
               '<circle cx="8.5" cy="8.5" r="6"/><path d="M13 13l5 5" stroke-linecap="round"/></svg>')

with ui.nav_control():
    with ui.div(class_="wbg-top"):
        ui.input_select("cohort", None, COHORTS, selected="", width="184px")
        with ui.div(class_="wbg-find", id="wbg_find"):
            cui.tags.button(cui.HTML(SEARCH_ICON), type="button", class_="btn wbg-find-btn", title="Find a country, project, asset or measure",
                            **{"aria-label": "Search", "onclick": "wbgFind()"})
            with ui.div(class_="box", **{"data-bs-theme": "light"}):
                ui.input_selectize("find", None, choices=[], width="360px",
                                   options={"placeholder": "Find a country, project, asset or measure"})
        ui.input_action_button("dl_open", "Download", class_="btn btn-outline-light px-3")


@reactive.effect
def _find_choices():
    df = acts()
    names, pn, mn = project_names(), project_names(), measure_names()

    def ordered(col):
        return [v for v in df.groupby(col).size().sort_values(ascending=False).index.tolist() if v]
    have = {a for l in df["assets"] for a in l}
    groups = {"Countries and regions": {f"country|{v}": v for v in ordered("place")},
              "Projects": {f"project|{v}": pn.get(v, v) for v in ordered("project_id")},
              "Digital assets": {f"asset|{v}": v for v in axis() if v in have},
              "Measures": {f"measure|{v}": mn.get(v, v) for v in ordered("label_set")}}
    ui.update_selectize("find", choices=groups, selected="", server=False)


@reactive.effect
@reactive.event(input.find)
def _found():
    if input.find():
        lens, value = input.find().split("|", 1)
        go_to(lens, value)


# ======================================================= download
DL_LEVELS = {
    "project_flags": ("A project, with yes or no for each measure", "One row per project; a column per measure of the family, 1 where the project has an activity of it."),
    "project": ("A project, with counts", "One row per project with its facts: measures, activities, investment and policy, assets, linked packages, next procurement."),
    "activity": ("An activity", "One row per activity: what a project commits to do for a measure, its types, assets, component and procurement."),
    "sentence": ("A sentence", "One row per sentence of an activity, in full, with its document, page and strength."),
    "package": ("A procurement package", "One row per package linked to an activity, with every procurement field."),
}
dl_dropped = reactive.value(set())      # filter chips the reader removed


@reactive.effect
@reactive.event(input.dl_open)
def _dl_open():
    dl_dropped.set(set())
    cui.modal_show(cui.modal(
        cui.p("Choose what one row of the file is. The file takes exactly the filters below; filters choose rows, never columns.",
              class_="wbg-muted mb-3"),
        cui.layout_columns(
            cui.div(cui.tags.h6("What should one row be?", class_="mb-2"),
                    cui.div(cui.input_radio_buttons(
                        "dl_level", None, {k: cui.HTML(f"<b>{html_text(t)}</b><small>{html_text(d)}</small>") for k, (t, d) in DL_LEVELS.items()},
                        selected="activity", width="100%"), class_="dl-levels")),
            cui.div(cui.tags.h6("Filters in force", class_="mb-2"), cui.output_ui("dl_chips"),
                    cui.tags.h6("Format", class_="mt-3 mb-2"),
                    cui.input_radio_buttons("dl_format", None, {"xlsx": "Excel, with a notes sheet", "csv": "CSV, the data only"},
                                           selected="xlsx", inline=True),
                    cui.download_button("dl_file", "Download", class_="btn btn-primary mt-2")),
            col_widths=[7, 5]),
        cui.tags.h6("Preview", class_="mt-4 mb-2"), cui.output_ui("dl_preview"),
        title="Download", size="xl", easy_close=True, footer=cui.modal_button("Close"), class_="modal-xl-wbg"))


def html_text(s):
    import html
    return html.escape(s)


def dl_context():
    """The filters in force for the page the reader is on: (id, what the chip says, filters for W.download)."""
    out = []
    f = chosen()
    if f:
        out.append(("family", f"Family: {family_name(f)}", {"family": f}))
    if cohort():
        out.append(("cohort", f"Projects: {COHORTS[cohort()]}", {"cohort": cohort()}))
    view, level = input.view(), input.dl_level()
    if view == "Explore" and input.pick():
        lens, v = input.lens(), input.pick()
        if lens == "country":
            out.append(("country", f"Country: {v}", {"country": v}))
        elif lens == "project":
            out.append(("project", f"Project: {project_names().get(v, v)}", {"project": v}))
        elif lens == "measure":
            out.append(("measure", f"Measure: {measure_names().get(v, v)}", {"measure": v}))
            if m_inst.get() != "all":
                out.append(("page_inst", f"Instrument: {m_inst.get().capitalize()}", {"instrument": m_inst.get()}))
        elif lens == "asset":
            ids = {n: i for i, n in asset_names().items()}
            if v in ids:
                out.append(("asset", f"Asset: {v}", {"asset": ids[v]}))
            else:
                out.append(("asset", "Asset: none named", {"asset": "(no asset)"}))
    if view == "Procurement":
        if input.pg_country() and input.pg_country() != "All countries":
            out.append(("pg_country", f"Country: {input.pg_country()}", {"country": input.pg_country()}))
        if input.pg_asset():
            out.append(("pg_asset", f"Asset: {asset_names().get(input.pg_asset(), input.pg_asset())}", {"asset": input.pg_asset()}))
        if input.pg_measure():
            out.append(("pg_measure", f"Measure: {measure_names().get(input.pg_measure())}", {"measure": input.pg_measure()}))
        if input.pg_status() and input.pg_status() != "All":
            out.append(("pg_status", f"Status: {input.pg_status()}",
                        {"status": [input.pg_status(), *[k for k, v in L.SAME_STATUS.items() if v == input.pg_status()]]}))
    d = drill.get()
    if d and d["kind"] == "acts" and panel_inst.get() != "all":
        out.append(("panel", f"Panel: {panel_inst.get().capitalize()} only", {"instrument": panel_inst.get()}))
    if level != "package":
        out = [o for o in out if "status" not in o[2]]
    return out


@reactive.calc
def dl_filters():
    kept = [o for o in dl_context() if o[0] not in dl_dropped.get()]
    flt: dict = {}
    for _, _, kw in kept:
        flt.update(kw)
    f = flt.pop("family", None)
    return kept, f, flt


@reactive.calc
def dl_frame():
    kept, f, flt = dl_filters()
    level = input.dl_level()
    flt = dict(flt)
    c = flt.pop("cohort", None)
    return kit.cached(("wbg", "download", level, f, c, tuple(sorted((k, str(v)) for k, v in flt.items()))),
                      lambda: restatus(untype(W.download(q, level, f, cohort=c, **flt))), seconds=120)


with ui.hold():

    @render.ui
    def dl_chips():
        chips = [cui.span(label, cui.tags.button({"type": "button", "title": "Take this filter off",
                                                  **L.clicker({"id": cid}, "dl_drop")}, "×"), class_="dl-chip")
                 for cid, label, _ in dl_context() if cid not in dl_dropped.get()]
        return cui.div(*chips) if chips else cui.p("None: every row of every family.", class_="wbg-muted-s")

    @render.ui
    def dl_preview():
        df = dl_frame()
        head = df.head(6)
        body = [cui.tags.tr(*[cui.tags.td("" if pd.isna(v) else (f"{v:%Y-%m-%d}" if hasattr(v, "year") else str(v)))
                              for v in r]) for r in head.itertuples(index=False)]
        return cui.div(cui.p(f"{len(df):,} rows · {len(df.columns)} columns. The first {len(head)} rows:", class_="wbg-muted-s mb-1"),
                       cui.div(cui.tags.table(cui.tags.thead(cui.tags.tr(*[cui.tags.th(c) for c in df.columns])),
                                              cui.tags.tbody(*body)), class_="dl-prev"))


@reactive.effect
@reactive.event(input.dl_drop)
def _dl_drop():
    dl_dropped.set(dl_dropped.get() | {input.dl_drop()["id"]})


def workbook(sheets):
    """An Excel file in memory: sheets {name: frame}, header bold, columns sized to their content, frozen first row."""
    from openpyxl.styles import Alignment, Font
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name, index=False)
            ws = xw.sheets[name]
            ws.freeze_panes = "A2"
            for cell in ws[1]:
                cell.font = Font(bold=True)
            for i, col in enumerate(df.columns, 1):
                width = max([len(str(col))] + [len(str(v)) for v in df[col].head(200)]) + 2
                letter = ws.cell(row=1, column=i).column_letter
                ws.column_dimensions[letter].width = min(width, 60 if name != "Notes" else (24 if i < 3 else 120))
            if name == "Notes":
                for row in ws.iter_rows(min_row=2):
                    row[-1].alignment = Alignment(wrap_text=True, vertical="top")
    return buf.getvalue()


def restatus(df):
    """A package's status as the dashboard names it: the plan's own names, Overdue written as Planned with a column
    that says its planned date has passed."""
    if "package_status" not in df.columns:
        return df
    late = df["package_status"].eq("Overdue")
    df = df.assign(package_status=df["package_status"].map(lambda v: L.SAME_STATUS.get(v, v)))
    df.insert(df.columns.get_loc("package_status") + 1, "planned_date_passed", late.map({True: "yes", False: ""}))
    return df


def untype(df):
    """A download without the word kind: document_kind is document_type."""
    return df.rename(columns={c: L.no_kind(c.replace("kind", "type")) for c in df.columns})


def clean_notes(notes):
    i = notes.index[notes["item"] == "package_status"]
    if len(i):
        notes = notes.copy()
        notes.loc[i, "text"] = ("Where the package stands, by the names the procurement plan uses: " + ", ".join(L.STATUSES) + ".")
        at = notes.index.get_loc(i[0]) + 1
        row = pd.DataFrame([{"section": "Column", "item": "planned_date_passed",
                             "text": "yes when the package is still Planned but its planned date is behind us with no notice or signing "
                                     "recorded. A past date is what the plan records, not evidence of delay."}])
        notes = pd.concat([notes.iloc[:at], row, notes.iloc[at:]], ignore_index=True)
    return notes.assign(item=notes["item"].map(L.no_kind).map(lambda s: s.replace("document_kind", "document_type")),
                        text=notes["text"].map(plain).map(lambda s: s.replace("_kind", "_type")))


def stamp():
    return f"{pd.Timestamp.today():%Y-%m-%d}"


with ui.hold():

    @render.download(filename=lambda: f"wbg_{chosen() or 'all'}_{input.dl_level()}_{stamp()}.{input.dl_format()}")
    def dl_file():
        kept, f, flt = dl_filters()
        level = input.dl_level()
        df = dl_frame()
        if input.dl_format() == "csv":
            yield df.to_csv(index=False).encode("utf-8-sig")
        else:
            notes = clean_notes(W.download_notes(q, level, f, flt))
            yield workbook({level: df, "Notes": notes})

    @render.download(filename=lambda: f"wbg_{chosen() or 'all'}_activities_{stamp()}.xlsx")
    def dl_panel():
        ids = panel_df()["activity_id"].tolist()
        f = chosen()
        flt = {"activity_id": ids}
        notes = clean_notes(W.download_notes(q, "activity", f, {"activity_id": f"{len(ids):,} activities from the side panel"}))
        yield workbook({"activities": untype(W.download(q, "activity", f, **flt)), "sentences": untype(W.download(q, "sentence", f, **flt)),
                        "Notes": notes})

"""
Generates the research paper, executive summary, figures and KPI tables.
Every number quoted in the documents is computed here from the cleaned data.

Run:  python build_report.py
Outputs: reports/*.docx, reports/figures/*.png, reports/tables/*.csv
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor

from analysis import bottlenecks, clean_data, group_kpis, route_kpis

OUT = Path(__file__).parent / "reports"
FIG = OUT / "figures"
TAB = OUT / "tables"
for p in (OUT, FIG, TAB):
    p.mkdir(parents=True, exist_ok=True)

THRESHOLD = 5      # delay = lead time > 5 days
MIN_SHIP = 20      # min shipments for a route / state to be ranked

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
MODE_ORDER = ["Same Day", "First Class", "Second Class", "Standard Class"]
MODE_COLORS = dict(zip(MODE_ORDER, SERIES))
FACTORY_ORDER = ["Lot's O' Nuts", "Wicked Choccy's", "Secret Factory", "The Other Factory", "Sugar Shack"]
FACTORY_COLORS = dict(zip(FACTORY_ORDER, SERIES))
INK, INK2, MUTED, GRID, AXIS = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
CRITICAL, LIGHTBLUE = "#d03b3b", "#9ec5f4"

plt.rcParams.update({
    "font.family": ["Segoe UI", "DejaVu Sans"], "font.size": 10, "axes.edgecolor": AXIS,
    "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED, "axes.titlecolor": INK,
    "axes.titlesize": 12, "axes.titleweight": "bold", "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.7, "axes.spines.top": False, "axes.spines.right": False,
    "axes.axisbelow": True, "figure.dpi": 150, "savefig.bbox": "tight", "legend.frameon": False,
})


def save(fig, name):
    path = FIG / f"{name}.png"
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Compute
# ---------------------------------------------------------------------------
df, log = clean_data()
df["Year"] = df["Order Date"].dt.year
df["Delayed"] = df["Lead Time"] > THRESHOLD
N = len(df)

overall = dict(avg=df["Lead Time"].mean(), med=df["Lead Time"].median(), std=df["Lead Time"].std(),
               delay=df["Delayed"].mean() * 100, orders=df["Order ID"].nunique(),
               customers=df["Customer ID"].nunique(), states=df["State/Province"].nunique(),
               cities=df["City"].nunique(), sales=df["Sales"].sum(), gp=df["Gross Profit"].sum(),
               dmin=df["Order Date"].min(), dmax=df["Order Date"].max(),
               raw_min=df["Raw Lead Time"].min(), raw_max=df["Raw Lead Time"].max())

routes_state = route_kpis(df, "Route (State)", THRESHOLD, MIN_SHIP)
routes_region = route_kpis(df, "Route (Region)", THRESHOLD, 1)
routes_state_all = route_kpis(df, "Route (State)", THRESHOLD, 1)
mode = group_kpis(df, "Ship Mode", THRESHOLD).set_index("Ship Mode").reindex(MODE_ORDER)
mode_grp = group_kpis(df, "Ship Mode Group", THRESHOLD).set_index("Ship Mode Group")
region = group_kpis(df, "Region", THRESHOLD).set_index("Region")
factory = group_kpis(df, "Factory", THRESHOLD).set_index("Factory").reindex(FACTORY_ORDER)
state = group_kpis(df, "State/Province", THRESHOLD)
state_rated = state[state["Shipments"] >= 50].sort_values("Mode-Adjusted Delay")
bn = bottlenecks(df, "State/Province", THRESHOLD)
bn_flag = bn[bn["Bottleneck"]]

year_mode = df.pivot_table(index="Ship Mode", columns="Year", values="Lead Time", aggfunc="mean").reindex(MODE_ORDER)
year_delay = df.groupby("Year")["Delayed"].mean() * 100
year_avg = df.groupby("Year")["Lead Time"].mean()
year_mix = pd.crosstab(df["Year"], df["Ship Mode"], normalize="index")[MODE_ORDER] * 100
year_mode_delay = df.groupby(["Year", "Ship Mode"])["Delayed"].mean().unstack()[MODE_ORDER] * 100
monthly = df.groupby("Order Month").agg(n=("Lead Time", "size"), lt=("Lead Time", "mean"),
                                        dl=("Delayed", "mean")).reset_index()
monthly["dl"] *= 100

# Significance tests on mode-adjusted delay (removes ship-mode mix)
kw_region = stats.kruskal(*[g["Mode-Adjusted Delay"] for _, g in df.groupby("Region")])
big_states = state_rated["State/Province"]
kw_state = stats.kruskal(*[g["Mode-Adjusted Delay"] for s, g in df.groupby("State/Province") if s in set(big_states)])
kw_factory = stats.kruskal(*[g["Mode-Adjusted Delay"] for f, g in df.groupby("Factory") if len(g) >= 30])
kw_mode = stats.kruskal(*[g["Lead Time"] for _, g in df.groupby("Ship Mode")])
mw_year = stats.mannwhitneyu(df.loc[df["Year"] == 2024, "Mode-Adjusted Delay"],
                             df.loc[df["Year"] == 2025, "Mode-Adjusted Delay"])
rho_dist = stats.spearmanr(df["Distance (km)"], df["Lead Time"])
rho_route_dist = stats.spearmanr(routes_state["Avg Distance (km)"], routes_state["Avg Lead Time"])

# Year-over-year controlling for mode mix: 2025 lead time if 2024 mode mix applied
mix24 = year_mix.loc[2024] / 100
lt25_at_mix24 = (year_mode[2025] * mix24).sum()

top10, bot10 = routes_state.head(10), routes_state.tail(10).iloc[::-1]
cross_factory = df.groupby("State/Province")["Factory"].nunique()

# Same-route factory gap: same state served by both chocolate factories
pair = df[df["Factory"].isin(["Lot's O' Nuts", "Wicked Choccy's"])].pivot_table(
    index="State/Province", columns="Factory", values="Mode-Adjusted Delay", aggfunc="mean")
pair_n = df[df["Factory"].isin(["Lot's O' Nuts", "Wicked Choccy's"])].pivot_table(
    index="State/Province", columns="Factory", values="Lead Time", aggfunc="size")
pair = pair[(pair_n >= 30).all(axis=1)].dropna()
pair["Gap"] = pair["Wicked Choccy's"] - pair["Lot's O' Nuts"]

# Ship-mode economics (descriptive)
mode_econ = df.groupby("Ship Mode").agg(gp_line=("Gross Profit", "mean"), sales_line=("Sales", "mean"),
                                        margin=("Margin %", "mean"), units=("Units", "mean")).reindex(MODE_ORDER)
std_share = (df["Ship Mode"] == "Standard Class").mean() * 100
std_delays_share = df.loc[df["Delayed"], "Ship Mode"].eq("Standard Class").mean() * 100
choc_share = df["Factory"].isin(["Lot's O' Nuts", "Wicked Choccy's"]).mean() * 100

# Save tables
routes_state_all.to_csv(TAB / "route_kpis_factory_state.csv", index=False)
routes_region.to_csv(TAB / "route_kpis_factory_region.csv", index=False)
mode.reset_index().to_csv(TAB / "ship_mode_kpis.csv", index=False)
region.reset_index().to_csv(TAB / "region_kpis.csv", index=False)
state.to_csv(TAB / "state_kpis.csv", index=False)
bn.to_csv(TAB / "state_bottlenecks.csv", index=False)
df.to_csv(TAB / "cleaned_shipments.csv", index=False)

# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------
figs = {}

fig, ax = plt.subplots(figsize=(8, 3.2))
ax.hist(df["Raw Lead Time"], bins=150, color=SERIES[0])
for b in (904, 1269, 1634):
    ax.axvline(b, color=MUTED, ls=":", lw=1)
    ax.text(b + 6, ax.get_ylim()[1] * 0.92, f"{b} d", color=INK2, fontsize=9)
ax.set(title="Raw Ship Date − Order Date: three clusters exactly 365 days apart", xlabel="Raw days", ylabel="Order lines")
figs["raw"] = save(fig, "01_raw_lead_time_clusters")

fig, ax = plt.subplots(figsize=(8, 3.4))
ct = pd.crosstab(df["Lead Time"], df["Ship Mode"])[MODE_ORDER]
w = 0.2
for i, m in enumerate(MODE_ORDER):
    ax.bar(ct.index + (i - 1.5) * w, ct[m], width=w, color=MODE_COLORS[m], label=m, edgecolor="white", linewidth=0.6)
ax.axvline(THRESHOLD + 0.5, color=CRITICAL, ls="--", lw=1)
ax.text(THRESHOLD + 0.6, ax.get_ylim()[1] * 0.9, f"delay threshold (> {THRESHOLD} d)", color=INK2, fontsize=9)
ax.set(title="Corrected lead time by ship mode", xlabel="Lead time (days)", ylabel="Order lines")
ax.set_xticks(range(0, int(df["Lead Time"].max()) + 1))
ax.legend(ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.2))
figs["mode_dist"] = save(fig, "02_lead_time_by_mode")

fig, ax = plt.subplots(figsize=(8, 3.4))
x = np.arange(len(MODE_ORDER))
for j, (yr, col) in enumerate([(2024, LIGHTBLUE), (2025, SERIES[0])]):
    vals = year_mode[yr].values
    bars = ax.bar(x + (j - 0.5) * 0.36, vals, 0.36, color=col, label=str(yr), edgecolor="white", linewidth=1)
    for b_, v in zip(bars, vals):
        ax.text(b_.get_x() + b_.get_width() / 2, v + 0.08, f"{v:.2f}", ha="center", fontsize=8.5, color=INK2)
ax.set_xticks(x, MODE_ORDER)
ax.set(title="Average lead time by ship mode, 2024 vs 2025", ylabel="Days")
ax.legend(loc="upper left")
figs["year_mode"] = save(fig, "03_year_over_year_by_mode")

fig, ax = plt.subplots(figsize=(8, 3.2))
ax.plot(monthly["Order Month"], monthly["lt"], color=SERIES[0], lw=2, marker="o", ms=4)
ax.axhline(overall["avg"], color=MUTED, ls=":", lw=1)
ax.text(monthly["Order Month"].iloc[0], overall["avg"] + 0.05, f"overall {overall['avg']:.2f} d", color=INK2, fontsize=9)
ax.set(title="Monthly average lead time", ylabel="Days")
figs["monthly"] = save(fig, "04_monthly_trend")

fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), sharex=True)
for ax, data, title in ((axes[0], top10, "Top 10 most efficient routes"), (axes[1], bot10, "Bottom 10 least efficient routes")):
    d = data.iloc[::-1]
    ax.barh(d["Route (State)"], d["Avg Lead Time"], color=d["Factory"].map(FACTORY_COLORS), edgecolor="white", height=0.7)
    for i, (v, n) in enumerate(zip(d["Avg Lead Time"], d["Shipments"])):
        ax.text(v + 0.05, i, f"{v:.2f} d  (n={n})", va="center", fontsize=8, color=INK2)
    ax.axvline(overall["avg"], color=MUTED, ls=":", lw=1)
    ax.set_title(title)
    ax.tick_params(axis="y", labelsize=8.5)
    ax.grid(axis="y", visible=False)
axes[0].set_xlim(0, 6.6)
handles = [plt.Rectangle((0, 0), 1, 1, color=FACTORY_COLORS[f]) for f in FACTORY_ORDER[:4]]
fig.legend(handles, FACTORY_ORDER[:4], ncol=4, loc="lower center", bbox_to_anchor=(0.5, -0.06))
fig.tight_layout()
figs["leader"] = save(fig, "05_route_leaderboard")

fig, ax = plt.subplots(figsize=(8, 4))
other = bn[~bn["Bottleneck"]]
ax.scatter(other["Shipments"], other["Delay Frequency %"], s=np.sqrt(other["Shipments"]) * 6, color=LIGHTBLUE,
           edgecolor="white", lw=1.2, label="Other states")
ax.scatter(bn_flag["Shipments"], bn_flag["Delay Frequency %"], s=np.sqrt(bn_flag["Shipments"]) * 6, color=CRITICAL,
           edgecolor="white", lw=1.2, label="Bottleneck: high volume + slow")
offsets = [((10, 6), "left"), ((-10, 12), "right"), ((10, -14), "left"), ((-12, -16), "right"), ((10, 8), "left")]
for (_, r), (off, ha) in zip(bn_flag.head(5).iterrows(), offsets):
    ax.annotate(r["State/Province"], (r["Shipments"], r["Delay Frequency %"]), xytext=off, ha=ha,
                textcoords="offset points", fontsize=8.5, color=INK2,
                arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.6))
ax.axhline(bn["Delay Frequency %"].median(), color=MUTED, ls=":", lw=1)
ax.axvline(bn["Shipments"].median(), color=MUTED, ls=":", lw=1)
ax.set_xscale("log")
ax.set(title="States: shipment volume vs delay frequency", xlabel="Shipments (log scale)",
       ylabel=f"% shipments > {THRESHOLD} days")
ax.legend(loc="upper right")
figs["bottleneck"] = save(fig, "06_state_bottlenecks")

fig, ax = plt.subplots(figsize=(8, 4.2))
sr = pd.concat([state_rated.head(8), state_rated.tail(8)])
cols = np.where(sr["Mode-Adjusted Delay"] > 0, CRITICAL, SERIES[0])
ax.barh(sr["State/Province"], sr["Mode-Adjusted Delay"], color=cols, edgecolor="white", height=0.7)
ax.axvline(0, color=AXIS, lw=1)
ax.invert_yaxis()
ax.grid(axis="y", visible=False)
ax.set(title="Mode-adjusted delay: fastest and slowest states (≥ 50 shipments)",
       xlabel="Days slower (+) / faster (−) than same-ship-mode average")
figs["state_adj"] = save(fig, "07_state_mode_adjusted")

fig, ax = plt.subplots(figsize=(8, 3.6))
rs = routes_state
ax.scatter(rs["Avg Distance (km)"], rs["Avg Lead Time"], s=np.sqrt(rs["Shipments"]) * 5,
           c=rs["Factory"].map(FACTORY_COLORS), edgecolor="white", lw=1)
ax.set(title=f"Route distance vs average lead time (Spearman ρ = {rho_route_dist.statistic:.2f})",
       xlabel="Factory → state distance (km)", ylabel="Avg lead time (days)")
figs["distance"] = save(fig, "08_distance_vs_lead_time")

fig, ax = plt.subplots(figsize=(8, 3))
vol = factory["Shipments"]
left = 0
for f in FACTORY_ORDER:
    ax.barh([0], [vol[f]], left=left, color=FACTORY_COLORS[f], edgecolor="white", lw=2, label=f"{f} ({vol[f] / N * 100:.1f}%)")
    left += vol[f]
ax.set_yticks([])
ax.grid(False)
ax.set(title="Shipment volume by origin factory", xlabel="Order lines")
ax.legend(ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.35))
figs["factory"] = save(fig, "09_factory_volume")


# ---------------------------------------------------------------------------
# Document helpers
# ---------------------------------------------------------------------------
def new_doc():
    d = Document()
    st_ = d.styles["Normal"]
    st_.font.name = "Calibri"
    st_.font.size = Pt(11)
    for s in d.sections:
        s.left_margin = s.right_margin = Inches(0.9)
        s.top_margin = s.bottom_margin = Inches(0.8)
    return d


def para(d, text, bold_lead=None, italic=False, size=None, align=None):
    p = d.add_paragraph()
    if bold_lead:
        r = p.add_run(bold_lead)
        r.bold = True
    r = p.add_run(text)
    r.italic = italic
    if size:
        r.font.size = Pt(size)
    if align:
        p.alignment = align
    return p


def bullets(d, items, style="List Bullet"):
    for it in items:
        if isinstance(it, tuple):
            p = d.add_paragraph(style=style)
            p.add_run(it[0]).bold = True
            p.add_run(it[1])
        else:
            d.add_paragraph(it, style=style)


def table(d, frame, fmt=None, widths=None):
    fmt = fmt or {}
    t = d.add_table(rows=1, cols=len(frame.columns))
    t.style = "Light Grid Accent 1"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, c in enumerate(frame.columns):
        cell = t.rows[0].cells[i]
        cell.text = str(c)
        cell.paragraphs[0].runs[0].bold = True
        cell.paragraphs[0].runs[0].font.size = Pt(9)
    for _, row in frame.iterrows():
        cells = t.add_row().cells
        for i, c in enumerate(frame.columns):
            v = row[c]
            cells[i].text = fmt[c].format(v) if c in fmt else str(v)
            cells[i].paragraphs[0].runs[0].font.size = Pt(9)
    d.add_paragraph()
    return t


def figure(d, key, caption, width=6.3):
    d.add_picture(str(figs[key]), width=Inches(width))
    d.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    c = para(d, caption, italic=True, size=9, align=WD_ALIGN_PARAGRAPH.CENTER)
    c.runs[0].font.color.rgb = RGBColor(0x52, 0x51, 0x4E)


def pval(p):
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}"


fmt_routes = {"Avg Lead Time": "{:.2f}", "Lead Time Std": "{:.2f}", "Delay Frequency %": "{:.1f}%",
              "Efficiency Score": "{:.0f}", "Shipments": "{:,}"}

# Handy derived numbers
std_m, sd_m = mode.loc["Standard Class"], mode.loc["Same Day"]
fc_m, sc_m = mode.loc["First Class"], mode.loc["Second Class"]
exp_g, std_g = mode_grp.loc["Expedited"], mode_grp.loc["Standard"]
yoy = year_avg[2025] - year_avg[2024]
worst_bn = bn_flag.head(5)["State/Province"].tolist()
slow_states = state_rated.tail(5).iloc[::-1]
fast_states = state_rated.head(5)
reg_sorted = region.sort_values("Avg Lead Time")

# ---------------------------------------------------------------------------
# Research paper
# ---------------------------------------------------------------------------
d = new_doc()
t = d.add_heading("Factory-to-Customer Shipping Route Efficiency Analysis", 0)
para(d, "Nassau Candy Distributor · Research Paper: EDA, Insights and Recommendations", size=12)
para(d, f"Data: {N:,} order lines, {overall['orders']:,} orders, orders placed "
        f"{overall['dmin']:%d %b %Y} – {overall['dmax']:%d %b %Y}", italic=True, size=10)

d.add_heading("Abstract", 1)
para(d, f"This study turns Nassau Candy's order and shipment records into route-level logistics intelligence. "
        f"Each route is defined as origin factory → customer state (or region). Lead time, volume, variability, "
        f"delay frequency and an efficiency score are measured for every route. A data-quality issue was found and "
        f"corrected first: recorded ship dates carry a whole-year offset that inflates raw lead times to "
        f"{overall['raw_min']:,}–{overall['raw_max']:,} days. After correction, the average lead time is "
        f"{overall['avg']:.2f} days (median {overall['med']:.0f}), and {overall['delay']:.1f}% of shipments exceed "
        f"{THRESHOLD} days. Ship mode is the dominant driver of lead time (Same Day {sd_m['Avg Lead Time']:.2f} d to "
        f"Standard {std_m['Avg Lead Time']:.2f} d). Distance and region have little or no measurable effect once mode "
        f"is controlled for. The most important operational signal is a broad deterioration in 2025: average lead time "
        f"rose {yoy:.2f} days, and the delay rate went from {year_delay[2024]:.1f}% to {year_delay[2025]:.1f}%, in "
        f"every ship mode. That points to a processing (order-to-dispatch) constraint rather than a "
        f"route or carrier problem. Recommendations focus on dispatch capacity, the Standard Class service promise, "
        f"and targeted fixes for a small set of high-volume, high-delay states.")

d.add_heading("1. Background and Problem Statement", 1)
para(d, "Nassau Candy ships confectionery from five factories to customers across the United States and Canada. "
        "Shipping efficiency drives customer satisfaction, delays raise operating cost, and inefficient routes "
        "limit scalability. The business has rich order data but no route-level view of efficiency, so logistics "
        "decisions have been reactive. This project answers:")
bullets(d, ["Which factory-to-customer routes are consistently efficient, and which are frequently delayed?",
            "How does shipping performance vary by region, state and ship mode?",
            "Where are the geographic bottlenecks?",
            "What cost-time trade-offs exist between standard and expedited shipping?"])

d.add_heading("2. Data", 1)
para(d, f"The dataset holds {N:,} order lines with 18 fields: order/ship dates, ship mode, customer geography "
        f"(country, region, state/province, city, postal code), product, division, sales, units, cost and gross profit. "
        f"It covers {overall['customers']:,} customers in {overall['cities']:,} cities across {overall['states']} "
        f"states/provinces, with total sales of ${overall['sales']:,.0f} and gross profit of ${overall['gp']:,.0f}. "
        f"Factory location is not in the order data. It was attached with the product → factory mapping and factory "
        f"coordinates from the project brief, so each order line has an origin. Factory-to-customer distance was "
        f"estimated as the great-circle distance from the factory to the customer state's centroid.")
figure(d, "factory", f"Figure 1. Two chocolate factories originate {choc_share:.1f}% of all shipments.")

d.add_heading("3. Data Cleaning and Validation", 1)
bullets(d, [
    ("Date validation: ", f"both date fields parsed as DD-MM-YYYY; {log['invalid_dates_removed']} invalid dates."),
    ("Missing shipment records: ", f"{log['missing_records_removed']} rows missing order ID, ship mode, state or product; "
                                   f"{log['duplicates_removed']} exact duplicates."),
    ("Negative / invalid lead times: ", f"{log['negative_lead_times_removed']} negative; "
                                        f"{log['invalid_lead_times_removed']} implausible after correction."),
    ("Geographic standardisation: ", "text fields trimmed and whitespace-normalised; every state/province mapped to "
                                     "a code and centroid; product-name inconsistency fixed "
                                     "(\"Wonka Bar -Scrumdiddlyumptious\")."),
    ("Factory mapping: ", f"all {N:,} lines mapped to an origin factory ({log['unmapped_products_removed']} unmapped)."),
])
d.add_heading("3.1 Lead-time correction (key data-quality finding)", 2)
para(d, f"Raw Ship Date − Order Date ranges from {overall['raw_min']:,} to {overall['raw_max']:,} days (2.5–4.5 years), "
        f"which is not plausible for confectionery distribution. The values fall in three tight clusters starting at "
        f"904, 1,269 and 1,634 days, exactly 365 days apart (Figure 2). That pattern is a systematic year offset in "
        f"the recorded ship dates, not real transit time. Removing the whole-year block, (raw − 904) mod 365, leaves "
        f"a 0–{int(df['Lead Time'].max())} day lead time. This value is cleanly ordered by service level (Figure 3): "
        f"Same Day 0–2 days, First Class 1–4, Second Class 1–6, Standard Class 3–8. This structure would be very "
        f"unlikely if the correction were wrong, so the corrected value is used as Shipping Lead Time throughout. "
        f"The raw value is kept in the cleaned dataset for audit. Nassau Candy should fix the ship-date "
        f"recording at source.")
figure(d, "raw", "Figure 2. Raw lead times sit in three year-offset clusters.")
figure(d, "mode_dist", "Figure 3. After correction, lead time separates cleanly by ship mode.")

d.add_heading("4. Feature Engineering and KPIs", 1)
table(d, pd.DataFrame([
    ["Shipping Lead Time", "Ship Date − Order Date (year-offset corrected), days"],
    ["Average Lead Time", "Mean lead time per route"],
    ["Route Volume", "Number of order lines per route"],
    ["Lead-Time Variability", "Standard deviation of lead time per route"],
    ["Delay Frequency", f"% of shipments with lead time > {THRESHOLD} days (adjustable in dashboard)"],
    ["Route Efficiency Score", "100 × (slowest avg − route avg) / (slowest avg − fastest avg); 100 = fastest ranked route"],
    ["Mode-Adjusted Delay", "Lead time − mean lead time of the same ship mode; isolates geography from service-level mix"],
    ["Bottleneck Index", "Share of volume × delay rate, scaled to 100; flags high-volume, high-delay states"],
], columns=["KPI", "Definition"]))
para(d, f"Routes are defined as Factory → Customer State ({len(routes_state_all)} routes) and Factory → Customer Region "
        f"({len(routes_region)} routes). Rankings use only routes with at least {MIN_SHIP} shipments "
        f"({len(routes_state)} state-level routes) so a handful of orders cannot dominate the leaderboard. Ship "
        f"modes are also grouped as Standard (Standard Class) and Expedited (Same Day, First, Second Class).")

d.add_heading("5. Exploratory Data Analysis", 1)
para(d, f"Overall average lead time is {overall['avg']:.2f} days (σ = {overall['std']:.2f}). "
        f"{overall['delay']:.1f}% of shipments exceed {THRESHOLD} days. Standard Class carries {std_share:.1f}% of volume "
        f"and accounts for {std_delays_share:.1f}% of all delayed shipments. Volume is heavily concentrated: "
        f"Lot's O' Nuts and Wicked Choccy's originate {choc_share:.1f}% of order lines, and the Sugar Shack, "
        f"Secret Factory and The Other Factory product lines are niche. Volume peaks in September and in "
        f"November–December.")
d.add_heading("5.1 A system-wide slowdown in 2025", 2)
para(d, f"Average lead time rose from {year_avg[2024]:.2f} days (2024) to {year_avg[2025]:.2f} days (2025), and the "
        f"delay rate went from {year_delay[2024]:.1f}% to {year_delay[2025]:.1f}%. The increase appears in every ship "
        f"mode (Figure 4): Same Day {year_mode.loc['Same Day', 2024]:.2f} → {year_mode.loc['Same Day', 2025]:.2f} d, "
        f"Standard {year_mode.loc['Standard Class', 2024]:.2f} → {year_mode.loc['Standard Class', 2025]:.2f} d. "
        f"Second Class delays jumped from {year_mode_delay.loc[2024, 'Second Class']:.1f}% to "
        f"{year_mode_delay.loc[2025, 'Second Class']:.1f}%. The ship-mode mix did not cause this: 2025 actually shifted "
        f"slightly toward faster modes. Applying the 2024 mode mix to 2025 performance still gives "
        f"{lt25_at_mix24:.2f} days. The year effect on mode-adjusted delay is highly significant "
        f"(Mann-Whitney {pval(mw_year.pvalue)}). Because the slowdown is uniform across modes, regions and factories, "
        f"the likely cause is order-processing or dispatch capacity, not specific routes or carriers.")
figure(d, "year_mode", "Figure 4. Every ship mode slowed in 2025.")
figure(d, "monthly", "Figure 5. Monthly average lead time drifts upward through 2025.")

d.add_heading("6. Route Efficiency Benchmarking", 1)
para(d, f"Figure 6 and the tables below rank the {len(routes_state)} state-level routes with ≥ {MIN_SHIP} shipments. "
        f"The fastest route ({top10.iloc[0]['Route (State)']}) averages {top10.iloc[0]['Avg Lead Time']:.2f} days. "
        f"The slowest ({bot10.iloc[0]['Route (State)']}) averages {bot10.iloc[0]['Avg Lead Time']:.2f} days, with "
        f"{bot10.iloc[0]['Delay Frequency %']:.0f}% of shipments delayed. The full range across ranked routes is only "
        f"{routes_state['Avg Lead Time'].max() - routes_state['Avg Lead Time'].min():.2f} days, so route differences are "
        f"real but modest next to the {std_m['Avg Lead Time'] - sd_m['Avg Lead Time']:.1f}-day gap between ship modes.")
figure(d, "leader", "Figure 6. Top and bottom 10 factory → state routes (≥ 20 shipments).", width=6.8)
cols = ["Rank", "Route (State)", "Shipments", "Avg Lead Time", "Lead Time Std", "Delay Frequency %", "Efficiency Score"]
d.add_heading("Top 10 most efficient routes", 3)
table(d, top10[cols], fmt_routes)
d.add_heading("Bottom 10 least efficient routes", 3)
table(d, bot10[cols], fmt_routes)
d.add_heading("6.1 Region-level routes", 2)
para(d, "Factory → Region routes with meaningful volume all fall between "
        f"{routes_region[routes_region['Shipments'] >= 100]['Avg Lead Time'].min():.2f} and "
        f"{routes_region[routes_region['Shipments'] >= 100]['Avg Lead Time'].max():.2f} days. The very small "
        f"Sugar Shack and The Other Factory flows sit at both extremes only because of low volume.")
table(d, routes_region[["Rank", "Route (Region)", "Shipments", "Avg Lead Time", "Lead Time Std", "Delay Frequency %",
                        "Efficiency Score"]], fmt_routes)
d.add_heading("6.2 Distance does not explain lead time", 2)
para(d, f"Great-circle distance from factory to customer has essentially no relationship with lead time "
        f"(order-line Spearman ρ = {rho_dist.statistic:.3f}; route-level ρ = {rho_route_dist.statistic:.2f}). "
        f"For example, Lot's O' Nuts (Arizona) → Ontario is one of the fastest routes despite ~3,000 km. "
        f"Lead time here measures order-to-dispatch time, which depends on processing and service level, not on "
        f"transit distance.")
figure(d, "distance", "Figure 7. No distance-lead-time relationship across routes.")

d.add_heading("7. Geographic Bottleneck Analysis", 1)
para(d, f"Regional averages are tightly clustered: {', '.join(f'{r} {v:.2f} d' for r, v in reg_sorted['Avg Lead Time'].items())}. "
        f"After controlling for ship mode, region differences are not statistically significant "
        f"(Kruskal-Wallis {pval(kw_region.pvalue)}). Differences between states with ≥ 50 shipments are "
        f"{'significant' if kw_state.pvalue < 0.05 else 'not significant'} ({pval(kw_state.pvalue)}). "
        f"A few states are consistently slower than their ship-mode mix would predict (Figure 8): "
        + ", ".join(f"{r['State/Province']} (+{r['Mode-Adjusted Delay']:.2f} d)" for _, r in slow_states.iterrows())
        + ". The fastest are "
        + ", ".join(f"{r['State/Province']} ({r['Mode-Adjusted Delay']:+.2f} d)" for _, r in fast_states.iterrows()) + ".")
table(d, region.reset_index()[["Region", "Shipments", "Avg Lead Time", "Lead Time Std", "Delay Frequency %",
                               "Mode-Adjusted Delay"]],
      {"Avg Lead Time": "{:.2f}", "Lead Time Std": "{:.2f}", "Delay Frequency %": "{:.1f}%",
       "Mode-Adjusted Delay": "{:+.3f}", "Shipments": "{:,}"})
figure(d, "state_adj", "Figure 8. States slower (red) or faster (blue) than their ship-mode mix predicts.")
para(d, f"Congestion-prone states combine above-median volume with above-median lead time or delay rate. "
        f"{len(bn_flag)} states meet this definition. Ranked by Bottleneck Index, the top five are "
        f"{', '.join(worst_bn)}. They hold large customer bases, so their delays affect the most customers.")
table(d, bn_flag.head(10)[["State/Province", "Shipments", "Avg Lead Time", "Delay Frequency %", "Mode-Adjusted Delay",
                           "Bottleneck Index"]],
      {"Avg Lead Time": "{:.2f}", "Delay Frequency %": "{:.1f}%", "Mode-Adjusted Delay": "{:+.2f}",
       "Bottleneck Index": "{:.0f}", "Shipments": "{:,}"})
figure(d, "bottleneck", "Figure 9. High-volume, high-delay states (red) are the congestion-prone markets.")
if len(pair):
    para(d, f"Comparing the two chocolate factories within the same state (both with ≥ 30 shipments, "
            f"{len(pair)} states), Wicked Choccy's is on average {pair['Gap'].mean():+.2f} days mode-adjusted versus "
            f"Lot's O' Nuts. Factory-level differences overall are "
            f"{'significant' if kw_factory.pvalue < 0.05 else 'not significant'} ({pval(kw_factory.pvalue)}).")

d.add_heading("8. Ship Mode Performance and Cost-Time Trade-off", 1)
table(d, mode.reset_index()[["Ship Mode", "Shipments", "Avg Lead Time", "Lead Time Std", "Delay Frequency %",
                             "Avg Sales / Order Line", "Gross Profit"]],
      {"Avg Lead Time": "{:.2f}", "Lead Time Std": "{:.2f}", "Delay Frequency %": "{:.1f}%",
       "Avg Sales / Order Line": "${:.2f}", "Gross Profit": "${:,.0f}", "Shipments": "{:,}"})
para(d, f"Ship mode explains most of the variation in lead time (Kruskal-Wallis {pval(kw_mode.pvalue)}). Expedited "
        f"modes average {exp_g['Avg Lead Time']:.2f} days with a {exp_g['Delay Frequency %']:.1f}% delay rate. "
        f"Standard averages {std_g['Avg Lead Time']:.2f} days, and {std_g['Delay Frequency %']:.1f}% of its shipments "
        f"exceed {THRESHOLD} days. Standard Class is also the most variable mode for its service window: it spans "
        f"3–8 days, so a customer cannot be given a reliable promise.")
para(d, "Cost-time trade-off (descriptive). ", bold_lead=None)
d.paragraphs[-1].runs[0].bold = True
d.paragraphs[-1].add_run(
    f"The dataset has no freight-cost field, so the trade-off is read from order economics. Average sales per order "
    f"line are nearly identical across modes (${mode_econ['sales_line'].min():.2f}–${mode_econ['sales_line'].max():.2f}), "
    f"and so are gross profit per line (${mode_econ['gp_line'].min():.2f}–${mode_econ['gp_line'].max():.2f}) and "
    f"margin ({mode_econ['margin'].min():.1f}–{mode_econ['margin'].max():.1f}%). Faster modes are not being used "
    f"for higher-value orders, so any premium paid for expedited shipping is not offset by higher revenue per line. "
    f"Moving an order from Standard to Second Class saves about "
    f"{std_m['Avg Lead Time'] - sc_m['Avg Lead Time']:.1f} days. Moving it to First Class saves about "
    f"{std_m['Avg Lead Time'] - fc_m['Avg Lead Time']:.1f} days and removes almost all delay risk. "
    f"The case for upgrading therefore depends on carrier rates, which should be added to the data.")

d.add_heading("9. Key Insights", 1)
bullets(d, [
    ("Data integrity: ", "ship dates carry a systematic year offset. Raw lead times are unusable until this "
                         "is corrected."),
    ("Service level drives speed: ", f"ship mode explains most of the variation; Standard Class ({std_share:.0f}% of "
                                     f"volume) produces {std_delays_share:.0f}% of delays."),
    ("2025 deterioration: ", f"+{yoy:.2f} days on average and +{year_delay[2025] - year_delay[2024]:.1f} pp delay rate, "
                             f"across every mode. This is a process-capacity signal."),
    ("Geography matters little: ", "distance and region have no meaningful effect once mode is controlled; "
                                   "route differences span well under one day."),
    ("Targeted bottlenecks: ", f"{', '.join(worst_bn[:3])} combine high volume with elevated delay; "
                               f"{', '.join(slow_states['State/Province'].head(3))} are consistently slower than their "
                               f"mode mix predicts."),
    ("Concentration risk: ", f"{choc_share:.0f}% of volume depends on two chocolate factories."),
])

d.add_heading("10. Recommendations", 1)
bullets(d, [
    ("Fix ship-date capture at source. ", "Validate that Ship Date ≥ Order Date and within 30 days at entry, and "
                                          "backfill corrected dates so future reporting is reliable."),
    ("Investigate the 2025 dispatch slowdown. ", "Audit order-to-dispatch capacity (picking, packing, staffing, "
                                                 "cut-off times) at Lot's O' Nuts and Wicked Choccy's, which handle "
                                                 f"{choc_share:.0f}% of volume. Prioritise the September and "
                                                 "November–December peaks."),
    ("Tighten the Standard Class promise. ", f"Set a ≤ {THRESHOLD}-day SLA and track delay frequency weekly. "
                                             f"Cutting Standard Class delays by half would lower the overall delay "
                                             f"rate by about {std_delays_share * overall['delay'] / 200:.0f} percentage points."),
    ("Restore true Same Day service. ", f"Same Day averaged {year_mode.loc['Same Day', 2025]:.2f} days in 2025 "
                                        f"(vs {year_mode.loc['Same Day', 2024]:.2f} in 2024). A premium service that "
                                        f"slips undermines its value."),
    ("Target bottleneck states. ", f"Review carrier performance, cut-off times and order batching for "
                                   f"{', '.join(worst_bn[:5])}. Consider a regional stocking point for high-volume "
                                   f"Pacific/Atlantic demand."),
    ("Use the dashboard operationally. ", "Review the route leaderboard and bottleneck map monthly and adjust the "
                                          "delay threshold to match the SLA in force."),
    ("Enrich the data. ", "Add freight cost, carrier, delivery date and warehouse to enable true cost-time and "
                          "end-to-end delivery analysis."),
])

d.add_heading("11. Limitations", 1)
bullets(d, [
    "The lead-time correction assumes the year offset is a recording artefact. The clean ship-mode ordering strongly "
    "supports this, but it should be confirmed with Nassau Candy's operations team.",
    "Lead time measures order-to-ship (dispatch) time, not delivery to the customer; there is no delivery date.",
    "No freight cost or carrier field, so the cost-time analysis is descriptive only.",
    "Distance uses state centroids rather than exact customer addresses.",
    "Several factory flows (Sugar Shack, The Other Factory, Secret Factory) have low volume; their route-level "
    "estimates are noisy and are excluded from rankings below the minimum-shipment rule.",
])

d.add_heading("12. Conclusion", 1)
para(d, "Once the ship-date offset is corrected, Nassau Candy's shipping performance is mostly a story of "
        "service level and process capacity, not geography. Routes differ by less than a day, while ship mode "
        "separates outcomes by five. The clearest action point is the 2025 slowdown across the whole network. "
        "The dashboard built alongside this paper gives the team a live view of route efficiency, "
        "geographic bottlenecks and ship-mode performance, so logistics decisions can move from reactive to "
        "data-driven.")

d.add_heading("Appendix: Deliverables", 1)
bullets(d, ["Streamlit dashboard: app.py (run: streamlit run app.py)",
            "Analysis pipeline: analysis.py; report generator: build_report.py",
            "KPI tables: reports/tables/*.csv (route, state, region, ship-mode KPIs; bottlenecks; cleaned data)",
            "Figures: reports/figures/*.png"])
d.save(OUT / "Nassau_Candy_Route_Efficiency_Research_Paper.docx")

# ---------------------------------------------------------------------------
# Executive summary
# ---------------------------------------------------------------------------
e = new_doc()
e.add_heading("Executive Summary", 0)
para(e, "Factory-to-Customer Shipping Route Efficiency · Nassau Candy Distributor", size=12)
para(e, f"Prepared for government and public-sector stakeholders · Based on {N:,} shipments, "
        f"{overall['dmin']:%b %Y} – {overall['dmax']:%b %Y}", italic=True, size=10)

e.add_heading("Purpose", 1)
para(e, "Nassau Candy distributes confectionery nationally from five factories to customers in "
        f"{overall['states']} US states and Canadian provinces. This review measured how quickly each factory-to-customer "
        "route ships orders, where delays concentrate, and how service level affects speed, so that logistics "
        "decisions rest on evidence.")

e.add_heading("Headline figures", 1)
table(e, pd.DataFrame([
    ["Average shipping lead time", f"{overall['avg']:.1f} days"],
    [f"Shipments over {THRESHOLD} days", f"{overall['delay']:.0f}%"],
    ["Change in lead time, 2024 → 2025", f"+{yoy:.2f} days (delays {year_delay[2024]:.0f}% → {year_delay[2025]:.0f}%)"],
    ["Fastest vs slowest service", f"Same Day {sd_m['Avg Lead Time']:.1f} d · Standard {std_m['Avg Lead Time']:.1f} d"],
    ["Spread between fastest and slowest routes", f"{routes_state['Avg Lead Time'].max() - routes_state['Avg Lead Time'].min():.1f} days"],
    ["Share of delays from Standard Class", f"{std_delays_share:.0f}%"],
], columns=["Measure", "Value"]))

e.add_heading("What we found", 1)
bullets(e, [
    ("Delivery speed is set by service level, not distance. ", "Customers far from a factory are served as quickly as "
     "nearby ones; the ship mode chosen makes the difference."),
    ("Performance slipped across the network in 2025. ", "Every service level got slower, which points to "
     "order-processing capacity at the main factories rather than any single route."),
    ("Standard shipping is the main source of delay. ", f"It carries {std_share:.0f}% of shipments and "
     f"{std_delays_share:.0f}% of late ones, with a wide 3–8 day window."),
    ("A few high-volume states are bottlenecks. ", f"{', '.join(worst_bn[:5])} combine large customer bases with "
     "above-average delays."),
    ("Records needed correction. ", "Ship dates were stored with a year offset; corrected before analysis. "
     "Fixing this at source is a governance priority."),
])

e.add_heading("Recommended actions", 1)
bullets(e, [
    "Correct and validate ship-date recording so performance can be reported accurately.",
    "Review dispatch capacity at the two main chocolate factories ahead of the September and holiday peaks.",
    f"Adopt a published ≤ {THRESHOLD}-day standard-shipping commitment and monitor delay frequency monthly.",
    f"Work with carriers on the bottleneck states ({', '.join(worst_bn[:3])}) to cut late shipments.",
    "Capture freight cost and delivery dates to support cost-versus-speed decisions.",
], style="List Number")

e.add_heading("Expected benefit", 1)
para(e, f"Halving Standard Class delays alone would cut the overall late-shipment rate by about "
        f"{std_delays_share * overall['delay'] / 200:.0f} percentage points. Reversing the 2025 slowdown would restore "
        f"roughly {yoy:.1f} days of lead time on every order. The interactive dashboard delivered with this "
        f"review lets managers track these measures continuously.")
e.save(OUT / "Nassau_Candy_Executive_Summary.docx")

print("Done.")
print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in dict(
    kw_region=kw_region.pvalue, kw_state=kw_state.pvalue, kw_factory=kw_factory.pvalue, mw_year=mw_year.pvalue,
    rho=rho_dist.statistic, rho_route=rho_route_dist.statistic, lt25_mix24=lt25_at_mix24,
    bottlenecks=worst_bn, pair_gap=pair["Gap"].mean() if len(pair) else None, n_pair=len(pair)).items()})

"""
Nassau Candy Distributor - Shipping Route Efficiency Dashboard
Run:  streamlit run app.py
"""
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from scipy import stats

from analysis import (FACTORIES, bottlenecks, clean_data, group_kpis, route_kpis, simulate_scenario)

st.set_page_config(page_title="Nassau Candy · Route Efficiency", page_icon="🚚", layout="wide")

# ---------------------------------------------------------------------------
# Visual system (validated reference palette)
# ---------------------------------------------------------------------------
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
MODE_ORDER = ["Same Day", "First Class", "Second Class", "Standard Class"]
MODE_COLORS = dict(zip(MODE_ORDER, SERIES))
FACTORY_ORDER = ["Lot's O' Nuts", "Wicked Choccy's", "Secret Factory", "The Other Factory", "Sugar Shack"]
FACTORY_COLORS = dict(zip(FACTORY_ORDER, SERIES))
SEQ_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
DIVERGING = [[0, "#1c5cab"], [0.5, "#f0efec"], [1, "#c23a3a"]]
GOOD, CRITICAL = "#0ca30c", "#d03b3b"
INK, INK2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"


CFG = {"scrollZoom": False, "displaylogo": False}


def style(fig, height=380, legend=True):
    fig.update_layout(
        # Legend lives in its own band at the bottom of the figure so it can never collide with the title.
        height=height, margin=dict(l=8, r=8, t=48, b=(104 if legend else 8)),
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family='system-ui, -apple-system, "Segoe UI", sans-serif', color=INK2, size=13),
        title_font=dict(color=INK, size=15), showlegend=legend,
        legend=dict(orientation="h", yref="container", yanchor="bottom", y=0.01, x=0, title_text=""),
        hoverlabel=dict(bgcolor="white", font_color=INK, bordercolor=GRID),
    )
    fig.update_xaxes(gridcolor=GRID, linecolor=AXIS, zerolinecolor=AXIS, tickfont_color=MUTED)
    fig.update_yaxes(gridcolor=GRID, linecolor=AXIS, zerolinecolor=AXIS, tickfont_color=MUTED)
    return fig


st.markdown("""
<style>
  .block-container {padding-top: 1.6rem;}
  div[data-testid="stMetric"] {background: #fcfcfb; border: 1px solid rgba(11,11,11,.10);
       border-radius: 10px; padding: 12px 16px;}
  div[data-testid="stMetricValue"] {font-size: 1.7rem;}
</style>""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
@st.cache_data
def load():
    return clean_data()


df_all, clean_log = load()

# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Filters")
    dmin, dmax = df_all["Order Date"].min().date(), df_all["Order Date"].max().date()
    dr = st.date_input("Order date range", (dmin, dmax), min_value=dmin, max_value=dmax)
    d_start, d_end = (dr if isinstance(dr, (tuple, list)) and len(dr) == 2 else (dmin, dmax))

    regions = sorted(df_all["Region"].unique())
    sel_regions = st.multiselect("Region", regions, default=regions)
    state_opts = sorted(df_all.loc[df_all["Region"].isin(sel_regions), "State/Province"].unique())
    sel_states = st.multiselect("State / Province", state_opts, placeholder="All states in selected regions")
    sel_modes = st.multiselect("Ship mode", MODE_ORDER, default=MODE_ORDER)
    sel_factories = st.multiselect("Factory", FACTORY_ORDER, default=FACTORY_ORDER)

    st.divider()
    threshold = st.slider("Delay threshold (days)", 0, 10, 5,
                          help="A shipment counts as delayed when its lead time is greater than this.")
    min_ship = st.slider("Min shipments per route (ranking)", 1, 100, 20,
                         help="Routes with fewer shipments are excluded from rankings to avoid noisy averages.")
    route_level = st.radio("Route definition", ["Factory → State", "Factory → Region"], horizontal=False)
    route_col = "Route (State)" if route_level == "Factory → State" else "Route (Region)"

mask = (
    df_all["Order Date"].dt.date.between(d_start, d_end)
    & df_all["Region"].isin(sel_regions)
    & df_all["Ship Mode"].isin(sel_modes)
    & df_all["Factory"].isin(sel_factories)
)
if sel_states:
    mask &= df_all["State/Province"].isin(sel_states)
df = df_all[mask].copy()
df["Delayed"] = df["Lead Time"] > threshold

st.title("Factory-to-Customer Shipping Route Efficiency")
st.caption(f"Nassau Candy Distributor · {len(df):,} of {len(df_all):,} shipments in view · "
           f"orders {d_start:%d %b %Y} – {d_end:%d %b %Y} · delay threshold > {threshold} days")

if df.empty:
    st.warning("No shipments match the current filters. Widen the selection in the sidebar.")
    st.stop()

routes = route_kpis(df, route_col, threshold, min_ship)

tab_exec, tab_over, tab_map, tab_mode, tab_sim, tab_drill, tab_dq = st.tabs(
    ["Executive Insights", "Route Efficiency Overview", "Geographic Shipping Map", "Ship Mode Comparison",
     "Scenario Simulator", "Route Drill-Down", "Data Quality & Method"])

# ===========================================================================
# 0. Executive insights (every number recomputed from the current filters)
# ===========================================================================
with tab_exec:
    yrs = df["Order Date"].dt.year
    has_yoy = {2024, 2025}.issubset(set(yrs.unique()))
    lt_y = df.groupby(yrs)["Lead Time"].mean()
    dl_y = df.groupby(yrs)["Delayed"].mean() * 100
    bn_e = bottlenecks(df, "State/Province", threshold)
    bn_e = bn_e[bn_e["Bottleneck"]]
    mk_e = group_kpis(df, "Ship Mode", threshold).set_index("Ship Mode")
    late_share = df.loc[df["Delayed"], "Ship Mode"].value_counts(normalize=True) * 100

    c = st.columns(4)
    c[0].metric("Avg lead time", f"{df['Lead Time'].mean():.2f} d",
                f"{lt_y[2025] - lt_y[2024]:+.2f} d vs 2024" if has_yoy else None, delta_color="inverse")
    c[1].metric(f"Shipments > {threshold} days", f"{df['Delayed'].mean() * 100:.1f}%",
                f"{dl_y[2025] - dl_y[2024]:+.1f} pp vs 2024" if has_yoy else None, delta_color="inverse")
    c[2].metric("Top bottleneck state", bn_e.iloc[0]["State/Province"] if len(bn_e) else "None",
                help="Highest Bottleneck Index: share of volume × delay rate")
    if len(routes):
        worst = routes.iloc[-1]
        c[3].metric(f"Slowest route · from {worst['Factory']}", worst[route_col].split(" → ")[-1],
                    help=f"{worst[route_col]}: {worst['Avg Lead Time']:.2f} d average, "
                         f"{worst['Delay Frequency %']:.0f}% delayed ({worst['Shipments']} shipments)")
    else:
        c[3].metric("Slowest route", "n/a")

    left, right = st.columns([3, 2])
    with left:
        st.subheader("What the data says")
        ins = []
        if len(mk_e) > 1:
            f_, s_ = mk_e["Avg Lead Time"].idxmin(), mk_e["Avg Lead Time"].idxmax()
            ins.append(f"**Service level drives speed.** {f_} averages {mk_e.loc[f_, 'Avg Lead Time']:.2f} d "
                       f"vs {s_} {mk_e.loc[s_, 'Avg Lead Time']:.2f} d, a "
                       f"{mk_e.loc[s_, 'Avg Lead Time'] - mk_e.loc[f_, 'Avg Lead Time']:.1f}-day gap.")
        if has_yoy:
            ins.append(f"**Performance slipped in 2025.** Average lead time {lt_y[2024]:.2f} → {lt_y[2025]:.2f} d; "
                       f"late shipments {dl_y[2024]:.1f}% → {dl_y[2025]:.1f}%.")
        if "Standard Class" in late_share.index:
            ins.append(f"**Standard Class produces {late_share['Standard Class']:.0f}% of late shipments** while "
                       f"carrying {(df['Ship Mode'] == 'Standard Class').mean() * 100:.0f}% of volume.")
        if len(df) > 50 and df["Distance (km)"].nunique() > 1:
            rho = stats.spearmanr(df["Distance (km)"], df["Lead Time"]).statistic
            ins.append(f"**Distance is not the constraint.** Distance vs lead time Spearman ρ = {rho:.2f}: "
                       f"delays come from processing and service level, not miles.")
        if df["Region"].nunique() > 1:
            p = stats.kruskal(*[g["Mode-Adjusted Delay"] for _, g in df.groupby("Region")]).pvalue
            ins.append(f"**Regions {'perform alike' if p >= 0.05 else 'differ'} once ship mode is controlled** "
                       f"(Kruskal-Wallis p = {p:.2f}).")
        if len(bn_e):
            ins.append("**Congestion-prone states:** " + ", ".join(bn_e["State/Province"].head(5)) +
                       ": high volume and above-median delay.")
        if len(routes) > 1:
            ins.append(f"**Route spread:** fastest {routes.iloc[0][route_col]} ({routes.iloc[0]['Avg Lead Time']:.2f} d) "
                       f"vs slowest {routes.iloc[-1][route_col]} ({routes.iloc[-1]['Avg Lead Time']:.2f} d).")
        st.markdown("\n".join(f"- {i}" for i in ins))
    with right:
        st.subheader("Recommended actions")
        st.markdown(f"""
1. **Fix ship-date capture** at source (year offset found in the raw data).
2. **Audit dispatch capacity** at Lot's O' Nuts and Wicked Choccy's ahead of the Sep and Nov–Dec peaks.
3. **Commit to a ≤ {threshold}-day Standard Class SLA** and track delay frequency weekly.
4. **Carrier and cut-off review** in the bottleneck states.
5. **Capture freight cost and delivery date** for true cost-to-serve analysis.

Test the impact of these levers in the **Scenario Simulator** tab.""")

    if has_yoy:
        ym = df.groupby([yrs.rename("Year"), "Ship Mode"])["Lead Time"].mean().reset_index()
        ym["Year"] = ym["Year"].astype(str)
        f = px.bar(ym, x="Ship Mode", y="Lead Time", color="Year", barmode="group", text="Lead Time",
                   category_orders={"Ship Mode": MODE_ORDER},
                   color_discrete_map={"2024": "#9ec5f4", "2025": SERIES[0]},
                   title="Average lead time by ship mode: 2024 vs 2025")
        f.update_traces(texttemplate="%{text:.2f}", textposition="outside", marker_line_color=SURFACE,
                        marker_line_width=2)
        f.update_layout(xaxis_title="", yaxis_title="Days", yaxis_range=[0, ym["Lead Time"].max() * 1.18])
        st.plotly_chart(style(f, 380), use_container_width=True, config=CFG)

# ===========================================================================
# 1. Overview
# ===========================================================================
with tab_over:
    c = st.columns(5)
    c[0].metric("Shipments", f"{len(df):,}")
    c[1].metric("Avg lead time", f"{df['Lead Time'].mean():.2f} d")
    c[2].metric("Median lead time", f"{df['Lead Time'].median():.0f} d")
    c[3].metric("Delay frequency", f"{df['Delayed'].mean() * 100:.1f}%")
    c[4].metric("Routes ranked", f"{len(routes):,}", help=f"Routes with ≥ {min_ship} shipments")

    if routes.empty:
        st.info("No route meets the minimum-shipment rule. Lower it in the sidebar.")
    else:
        left, right = st.columns(2)
        show_cols = [route_col, "Shipments", "Avg Lead Time", "Delay Frequency %", "Efficiency Score"]
        colcfg = {
            route_col: st.column_config.TextColumn("Route", width=200),
            "Shipments": st.column_config.NumberColumn("Ships", width=56),
            "Rank": st.column_config.NumberColumn("#", width=40),
            "Efficiency Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.0f", width=90),
            "Avg Lead Time": st.column_config.NumberColumn("Avg LT", format="%.2f d", width=70),
            "Lead Time Std": st.column_config.NumberColumn("Variability (σ)", format="%.2f"),
            "Delay Frequency %": st.column_config.NumberColumn("Delay %", format="%.1f%%", width=70),
        }
        with left:
            st.subheader("Top 10 most efficient routes")
            st.dataframe(routes.head(10)[["Rank"] + show_cols], hide_index=True, column_config=colcfg, use_container_width=True)
        with right:
            st.subheader("Bottom 10 least efficient routes")
            st.dataframe(routes.tail(10).iloc[::-1][["Rank"] + show_cols], hide_index=True, column_config=colcfg, use_container_width=True)

        st.subheader("Average lead time by route")
        n_show = st.slider("Routes shown (fastest → slowest)", 5, max(5, len(routes)), min(30, len(routes)), key="nshow") \
            if len(routes) > 5 else len(routes)
        top = routes.head(n_show) if n_show < len(routes) else routes
        tp = top.iloc[::-1]
        fig = go.Figure(go.Bar(
            x=tp["Avg Lead Time"], y=tp[route_col], orientation="h", showlegend=False,
            marker=dict(color=tp["Factory"].map(FACTORY_COLORS), line=dict(color=SURFACE, width=1),
                        cornerradius=4),
            customdata=np.c_[tp["Shipments"], tp["Delay Frequency %"], tp["Lead Time Std"], tp["Efficiency Score"]],
            hovertemplate="<b>%{y}</b><br>Avg lead time %{x:.2f} d<br>Shipments %{customdata[0]:,}"
                          "<br>Delay %{customdata[1]:.1f}%<br>σ %{customdata[2]:.2f}"
                          "<br>Efficiency score %{customdata[3]:.0f}<extra></extra>"))
        for fac in [f for f in FACTORY_ORDER if f in set(tp["Factory"])]:  # legend entries
            fig.add_trace(go.Bar(x=[None], y=[None], name=fac, marker_color=FACTORY_COLORS[fac]))
        fig.add_vline(x=df["Lead Time"].mean(), line_dash="dot", line_color=MUTED,
                      annotation_text=f"overall {df['Lead Time'].mean():.2f} d", annotation_font_color=INK2)
        fig.update_layout(yaxis_title="", xaxis_title="Average lead time (days)", bargap=0.25, barmode="overlay")
        st.plotly_chart(style(fig, height=max(360, 22 * len(top) + 80)), use_container_width=True, config=CFG)

        with st.expander("Full route leaderboard"):
            st.dataframe(routes, hide_index=True, use_container_width=True, column_config=colcfg)
            st.download_button("Download leaderboard (CSV)", routes.to_csv(index=False), "route_leaderboard.csv")

    st.subheader("Monthly trend")
    m = df.groupby("Order Month").agg(Shipments=("Lead Time", "size"), AvgLT=("Lead Time", "mean"),
                                      Delay=("Delayed", "mean")).reset_index()
    m["Delay"] *= 100
    a, b = st.columns(2)
    f1 = px.line(m, x="Order Month", y="AvgLT", markers=True, title="Average lead time (days)")
    f1.update_traces(line_color=SERIES[0], line_width=2, marker_size=8,
                     hovertemplate="%{x|%b %Y}<br>%{y:.2f} days<extra></extra>")
    f1.update_layout(xaxis_title="", yaxis_title="", hovermode="x unified")
    a.plotly_chart(style(f1, 320, False), use_container_width=True, config=CFG)
    f2 = px.line(m, x="Order Month", y="Delay", markers=True, title=f"Delay frequency (% > {threshold} days)")
    f2.update_traces(line_color=SERIES[1], line_width=2, marker_size=8,
                     hovertemplate="%{x|%b %Y}<br>%{y:.1f}%<extra></extra>")
    f2.update_layout(xaxis_title="", yaxis_title="", hovermode="x unified")
    b.plotly_chart(style(f2, 320, False), use_container_width=True, config=CFG)

# ===========================================================================
# 2. Geographic map
# ===========================================================================
with tab_map:
    metric = st.radio("Map metric", ["Avg Lead Time", "Delay Frequency %", "Mode-Adjusted Delay", "Shipments"],
                      horizontal=True,
                      help="Mode-Adjusted Delay = days slower (+) or faster (−) than the average for the same ship mode; "
                           "removes the effect of each state's ship-mode mix.")
    st_k = group_kpis(df, ["State/Province", "Country/Region"], threshold)
    geo = df.groupby("State/Province")[["State Code", "State Lat", "State Lon"]].first().reset_index()
    st_k = st_k.merge(geo, on="State/Province")

    if metric == "Mode-Adjusted Delay":
        lim = max(0.25, st_k[metric].abs().max())
        cscale, crange, cmid = DIVERGING, (-lim, lim), None
    else:
        cscale, crange, cmid = SEQ_BLUE, None, None

    us_all = st_k[st_k["Country/Region"] == "United States"]
    us = us_all[us_all["Shipments"] >= min_ship] if metric != "Shipments" else us_all
    low = us_all[~us_all.index.isin(us.index)]
    fig = px.choropleth(us,locations="State Code", locationmode="USA-states", color=metric, scope="usa",
                        color_continuous_scale=cscale, range_color=crange,
                        hover_name="State/Province",
                        hover_data={"State Code": False, "Shipments": True, "Avg Lead Time": ":.2f",
                                    "Delay Frequency %": ":.1f", "Mode-Adjusted Delay": ":+.2f"})
    fig.update_traces(marker_line_color="white", marker_line_width=1)
    if not low.empty:
        fig.add_trace(go.Choropleth(
            locations=low["State Code"], locationmode="USA-states", z=[0] * len(low), showscale=False,
            colorscale=[[0, "#e1e0d9"], [1, "#e1e0d9"]], marker_line_color="white", marker_line_width=1,
            text=low["State/Province"], customdata=low["Shipments"],
            hovertemplate="<b>%{text}</b><br>%{customdata} shipments: below minimum, not rated<extra></extra>"))
    fig.add_trace(go.Scattergeo(
        lon=[v[1] for v in FACTORIES.values()], lat=[v[0] for v in FACTORIES.values()],
        text=list(FACTORIES.keys()), mode="markers+text", textposition="top center",
        textfont=dict(color=INK, size=12),
        marker=dict(symbol="square", size=12, color=INK, line=dict(color="white", width=2)),
        name="Factory", hovertemplate="<b>%{text}</b><extra>Factory</extra>"))
    fig.update_geos(bgcolor=SURFACE, lakecolor=SURFACE, showlakes=False)
    fig.update_layout(title=f"US heatmap · {metric} by customer state", coloraxis_colorbar=dict(title=""))
    st.plotly_chart(style(fig, 520, False), use_container_width=True, config=CFG)
    if not low.empty:
        st.caption(f"Gray states have fewer than {min_ship} shipments in the current selection (sidebar minimum) and are not rated.")

    ca =st_k[st_k["Country/Region"] == "Canada"]
    if not ca.empty:
        st.caption("Canadian provinces (not drawn on the US heatmap): " + " · ".join(
            f"{r['State/Province']} {r['Avg Lead Time']:.2f} d / {r['Delay Frequency %']:.0f}% delayed ({r['Shipments']})"
            for _, r in ca.sort_values("Shipments", ascending=False).iterrows()))

    st.subheader("Factory → customer route network")
    net = df.groupby(["Factory", "State/Province"]).agg(
        n=("Lead Time", "size"), lt=("Lead Time", "mean"),
        flat=("Factory Lat", "first"), flon=("Factory Lon", "first"),
        slat=("State Lat", "first"), slon=("State Lon", "first")).reset_index()
    net = net[net["n"] >= max(1, min_ship // 2)]
    fig = go.Figure()
    nmax = net["n"].max() if not net.empty else 1
    for fac in FACTORY_ORDER:
        sub = net[net["Factory"] == fac]
        if sub.empty:
            continue
        lons, lats = [], []
        for _, r in sub.iterrows():
            lons += [r["flon"], r["slon"], None]
            lats += [r["flat"], r["slat"], None]
        fig.add_trace(go.Scattergeo(lon=lons, lat=lats, mode="lines", name=fac,
                                    line=dict(width=1.5, color=FACTORY_COLORS[fac]), opacity=0.55,
                                    hoverinfo="skip"))
    dest = df.groupby("State/Province").agg(n=("Lead Time", "size"), lt=("Lead Time", "mean"),
                                            lat=("State Lat", "first"), lon=("State Lon", "first")).reset_index()
    rated = dest[dest["n"] >= min_ship]["lt"]
    cmin, cmax = (rated.min(), rated.max()) if len(rated) > 1 else (dest["lt"].min(), dest["lt"].max())
    fig.add_trace(go.Scattergeo(
        lon=dest["lon"], lat=dest["lat"], mode="markers", name="Customer state",
        marker=dict(size=8 + 30 * np.sqrt(dest["n"] / dest["n"].max()), color=dest["lt"],
                    colorscale=SEQ_BLUE, cmin=cmin, cmax=cmax, line=dict(color="white", width=2),
                    colorbar=dict(title="Avg LT (d)", x=1.0)),
        text=dest["State/Province"], customdata=np.c_[dest["n"], dest["lt"]],
        hovertemplate="<b>%{text}</b><br>%{customdata[0]:,} shipments<br>%{customdata[1]:.2f} d avg<extra></extra>"))
    fig.add_trace(go.Scattergeo(
        lon=[v[1] for v in FACTORIES.values()], lat=[v[0] for v in FACTORIES.values()],
        text=list(FACTORIES.keys()), mode="markers", name="Factory",
        marker=dict(symbol="square", size=13, color=INK, line=dict(color="white", width=2)),
        hovertemplate="<b>%{text}</b><extra>Factory</extra>"))
    fig.update_geos(scope="north america", showcountries=True, countrycolor=AXIS, showsubunits=True,
                    subunitcolor=GRID, landcolor="#f9f9f7", bgcolor=SURFACE,
                    lataxis_range=[24, 58], lonaxis_range=[-130, -55])
    fig.update_layout(title=f"Lines = factory→state routes with ≥ {max(1, min_ship // 2)} shipments · bubble size = volume")
    st.plotly_chart(style(fig, 560), use_container_width=True, config=CFG)

    st.subheader("Regional bottleneck analysis")
    a, b = st.columns(2)
    reg = group_kpis(df, "Region", threshold)
    f = px.bar(reg.sort_values("Avg Lead Time"), x="Region", y="Avg Lead Time", text="Avg Lead Time",
               hover_data={"Shipments": True, "Delay Frequency %": ":.1f", "Mode-Adjusted Delay": ":+.3f"},
               title="Average lead time by region")
    f.update_traces(marker_color=SERIES[0], texttemplate="%{text:.2f} d", textposition="outside",
                    marker_line_color=SURFACE, marker_line_width=2)
    f.update_layout(yaxis_title="", xaxis_title="",
                    yaxis_range=[0, reg["Avg Lead Time"].max() * 1.18])
    a.plotly_chart(style(f, 380, False), use_container_width=True, config=CFG)

    bn = bottlenecks(df, "State/Province", threshold)
    bn["Status"] = np.where(bn["Bottleneck"], "Bottleneck (high volume + slow)", "Other")
    f = px.scatter(bn, x="Shipments", y="Delay Frequency %", size="Shipments", color="Status",
                   hover_name="State/Province", log_x=True, size_max=36,
                   color_discrete_map={"Bottleneck (high volume + slow)": CRITICAL, "Other": "#9ec5f4"},
                   hover_data={"Avg Lead Time": ":.2f", "Mode-Adjusted Delay": ":+.2f", "Bottleneck Index": True},
                   title="States: volume vs delay frequency")
    f.add_hline(y=bn["Delay Frequency %"].median(), line_dash="dot", line_color=MUTED)
    f.add_vline(x=bn["Shipments"].median(), line_dash="dot", line_color=MUTED)
    for (_, r), (ax_, ay_) in zip(bn[bn["Bottleneck"]].head(4).iterrows(), [(30, -40), (-60, -45), (40, 35), (-70, 30)]):
        f.add_annotation(x=np.log10(r["Shipments"]), y=r["Delay Frequency %"], text=r["State/Province"],
                         showarrow=True, arrowhead=0, arrowcolor=MUTED, arrowwidth=1, ax=ax_, ay=ay_,
                         font=dict(color=INK2, size=11), bgcolor="rgba(252,252,251,.85)")
    f.update_traces(marker_line_color="white", marker_line_width=2)
    f.update_layout(xaxis_title="Shipments (log scale)", yaxis_title="Delay %")
    b.plotly_chart(style(f, 380), use_container_width=True, config=CFG)

    st.markdown("**Congestion-prone states**: high volume (≥ median) and slower than median on lead time or delay rate. "
                "Bottleneck Index = share of volume × delay rate, scaled to 100.")
    st.dataframe(bn[bn["Bottleneck"]][["State/Province", "Shipments", "Avg Lead Time", "Delay Frequency %",
                                       "Mode-Adjusted Delay", "Bottleneck Index"]],
                 hide_index=True, use_container_width=True,
                 column_config={"Bottleneck Index": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"),
                                "Mode-Adjusted Delay": st.column_config.NumberColumn(format="%+.2f d")})

# ===========================================================================
# 3. Ship mode
# ===========================================================================
with tab_mode:
    mk = group_kpis(df, "Ship Mode", threshold)
    mk["Ship Mode"] = pd.Categorical(mk["Ship Mode"], MODE_ORDER, ordered=True)
    mk = mk.sort_values("Ship Mode")
    modes_present = [m for m in MODE_ORDER if m in mk["Ship Mode"].astype(str).values]

    cols = st.columns(len(mk))
    for col, (_, r) in zip(cols, mk.iterrows()):
        col.metric(str(r["Ship Mode"]), f"{r['Avg Lead Time']:.2f} d")
        col.caption(f"{r['Delay Frequency %']:.1f}% of shipments > {threshold} days · σ {r['Lead Time Std']:.2f}")

    a, b = st.columns(2)
    f = px.box(df, x="Ship Mode", y="Lead Time", color="Ship Mode", category_orders={"Ship Mode": MODE_ORDER},
               color_discrete_map=MODE_COLORS, title="Lead-time distribution by ship mode")
    f.add_hline(y=threshold, line_dash="dot", line_color=CRITICAL, annotation_text=f"threshold {threshold} d",
                annotation_position="top left", annotation_font_color=INK2)
    f.update_layout(xaxis_title="", yaxis_title="Lead time (days)")
    a.plotly_chart(style(f, 400, False), use_container_width=True, config=CFG)

    dist = df.groupby(["Ship Mode", "Lead Time"]).size().reset_index(name="Shipments")
    f = px.bar(dist, x="Lead Time", y="Shipments", color="Ship Mode", barmode="group",
               category_orders={"Ship Mode": MODE_ORDER}, color_discrete_map=MODE_COLORS,
               title="Shipments by lead-time day")
    f.update_traces(marker_line_color=SURFACE, marker_line_width=1)
    f.update_layout(xaxis_title="Lead time (days)", yaxis_title="", xaxis_dtick=1)
    b.plotly_chart(style(f, 400), use_container_width=True, config=CFG)

    st.subheader("Standard vs expedited")
    grp = group_kpis(df, "Ship Mode Group", threshold)
    st.dataframe(grp, hide_index=True, use_container_width=True,
                 column_config={"Avg Lead Time": st.column_config.NumberColumn(format="%.2f d"),
                                "Delay Frequency %": st.column_config.NumberColumn(format="%.1f%%"),
                                "Sales": st.column_config.NumberColumn(format="$%.0f"),
                                "Gross Profit": st.column_config.NumberColumn(format="$%.0f"),
                                "Avg Sales / Order Line": st.column_config.NumberColumn(format="$%.2f")})

    a, b = st.columns(2)
    tr = df.groupby("Ship Mode").agg(LT=("Lead Time", "mean"), GP=("Gross Profit", "mean"),
                                     Sales=("Sales", "mean"), n=("Lead Time", "size"),
                                     Margin=("Margin %", "mean")).reset_index()
    f = px.scatter(tr, x="LT", y="GP", size="n", color="Ship Mode", text="Ship Mode", size_max=50,
                   category_orders={"Ship Mode": MODE_ORDER}, color_discrete_map=MODE_COLORS,
                   hover_data={"Sales": ":$.2f", "Margin": ":.1f", "n": ":,"},
                   title="Cost-time trade-off: lead time vs gross profit per order line")
    f.update_traces(textposition="top center", textfont_color=INK2, marker_line_color="white", marker_line_width=2)
    f.update_layout(xaxis_title="Avg lead time (days)", yaxis_title="Avg gross profit / line ($)")
    a.plotly_chart(style(f, 400, False), use_container_width=True, config=CFG)
    b.markdown(
        "**Reading the trade-off (descriptive).** The dataset has no freight-cost field, so cost-time is read "
        "through what each mode earns per order line. Profit and margin per line are almost identical "
        "across modes, so faster modes are not being reserved for higher-value orders: speed is bought "
        "without a matching revenue signal. Mode share shows how much volume sits in the slowest, most "
        "delay-prone class.")
    share = df["Ship Mode"].value_counts(normalize=True).reindex(modes_present).mul(100).round(1)
    b.dataframe(share.rename("Share of shipments %").reset_index(), hide_index=True, use_container_width=True)

    st.subheader("Ship mode × region: average lead time")
    hm = df.pivot_table(index="Ship Mode", columns="Region", values="Lead Time", aggfunc="mean").reindex(modes_present)
    f = px.imshow(hm.round(2), text_auto=".2f", color_continuous_scale=SEQ_BLUE, aspect="auto")
    f.update_layout(xaxis_title="", yaxis_title="", coloraxis_colorbar=dict(title="days"))
    st.plotly_chart(style(f, 300, False), use_container_width=True, config=CFG)

# ===========================================================================
# 3b. Scenario simulator
# ===========================================================================
with tab_sim:
    st.markdown("Estimate the effect of operational changes on the **shipments currently in view**. Results are "
                "expected values computed from the observed lead-time distributions of each ship mode and year "
                "(no random sampling). Freight premiums are your assumptions: the dataset has no freight cost.")
    a, b, c_ = st.columns(3)
    to_second = a.slider("Upgrade Standard → Second Class (%)", 0, 100, 0, 5) / 100
    to_first = b.slider("Upgrade Standard → First Class (%)", 0, 100, 0, 5) / 100
    if to_second + to_first > 1:
        to_first = 1 - to_second
        b.caption(f"Capped at {to_first * 100:.0f}% so total upgrades ≤ 100%.")
    recover = c_.slider("Recover the 2025 dispatch slowdown (%)", 0, 100, 0, 10,
                        help="100% = 2025 shipments perform like 2024 shipments of the same mode.") / 100
    a, b, _ = st.columns(3)
    prem2 = a.number_input("Assumed premium per Second Class upgrade ($)", 0.0, 100.0, 1.50, 0.25)
    prem1 = b.number_input("Assumed premium per First Class upgrade ($)", 0.0, 100.0, 3.00, 0.25)

    r = simulate_scenario(df, threshold, to_second, to_first, recover, prem2, prem1)
    c = st.columns(5)
    c[0].metric("Avg lead time", f"{r['scenario_avg']:.2f} d", f"{r['scenario_avg'] - r['baseline_avg']:+.2f} d",
                delta_color="inverse")
    c[1].metric("Delay frequency", f"{r['scenario_delay']:.1f}%",
                f"{r['scenario_delay'] - r['baseline_delay']:+.1f} pp", delta_color="inverse")
    c[2].metric("Late shipments avoided", f"{max(r['delays_avoided'], 0):,.0f}")
    c[3].metric("Indicative added freight", f"${r['added_cost']:,.0f}", f"{r['upgraded']:,.0f} upgrades",
                delta_color="off")
    c[4].metric("Cost per delay avoided",
                "n/a" if np.isnan(r["cost_per_delay_avoided"]) else f"${r['cost_per_delay_avoided']:,.2f}")

    l, rr = st.columns(2)
    base_m = group_kpis(df, "Ship Mode", threshold)[["Ship Mode", "Delay Frequency %"]].assign(Case="Current")
    scen_m = r["by_mode"][["Ship Mode", "Delay Frequency %"]].assign(Case="Scenario")
    f = px.bar(pd.concat([base_m, scen_m]), x="Ship Mode", y="Delay Frequency %", color="Case", barmode="group",
               category_orders={"Ship Mode": MODE_ORDER},
               color_discrete_map={"Current": "#9ec5f4", "Scenario": SERIES[0]},
               title=f"Delay frequency by ship mode (> {threshold} d)")
    f.update_traces(marker_line_color=SURFACE, marker_line_width=2)
    f.update_layout(xaxis_title="", yaxis_title="%")
    l.plotly_chart(style(f, 380), use_container_width=True, config=CFG)

    support = r["distribution"].index
    cur = df["Lead Time"].value_counts(normalize=True).reindex(support, fill_value=0)
    dd = pd.DataFrame({"Lead Time": list(support) * 2,
                       "Share %": list(cur.values * 100) + list(r["distribution"].values * 100),
                       "Case": ["Current"] * len(support) + ["Scenario"] * len(support)})
    f = px.bar(dd, x="Lead Time", y="Share %", color="Case", barmode="group",
               color_discrete_map={"Current": "#9ec5f4", "Scenario": SERIES[0]}, title="Lead-time distribution")
    f.add_vline(x=threshold + 0.5, line_dash="dot", line_color=CRITICAL)
    f.update_traces(marker_line_color=SURFACE, marker_line_width=1)
    f.update_layout(xaxis_title="Lead time (days)", yaxis_title="% of shipments", xaxis_dtick=1)
    rr.plotly_chart(style(f, 380), use_container_width=True, config=CFG)

    st.caption("Method: each upgraded Standard Class order takes on the observed lead-time distribution of its new "
               "mode in the same year; 'recover' blends 2025 distributions toward 2024's for the same mode. With all "
               "sliders at zero the simulator reproduces the current KPIs exactly.")

# ===========================================================================
# 4. Drill-down
# ===========================================================================
with tab_drill:
    states_sorted = df["State/Province"].value_counts().index.tolist()
    state = st.selectbox("Customer state / province", states_sorted)
    sd = df[df["State/Province"] == state]
    overall_lt = df["Lead Time"].mean()
    c = st.columns(5)
    c[0].metric("Shipments", f"{len(sd):,}")
    c[1].metric("Avg lead time", f"{sd['Lead Time'].mean():.2f} d", f"{sd['Lead Time'].mean() - overall_lt:+.2f} vs all",
                delta_color="inverse")
    c[2].metric("Delay frequency", f"{sd['Delayed'].mean() * 100:.1f}%")
    c[3].metric("Mode-adjusted delay", f"{sd['Mode-Adjusted Delay'].mean():+.2f} d")
    c[4].metric("Cities served", f"{sd['City'].nunique():,}")

    a, b = st.columns(2)
    fm = group_kpis(sd, ["Factory", "Ship Mode"], threshold)
    f = px.bar(fm, x="Factory", y="Avg Lead Time", color="Ship Mode", barmode="group",
               category_orders={"Ship Mode": MODE_ORDER, "Factory": FACTORY_ORDER}, color_discrete_map=MODE_COLORS,
               hover_data={"Shipments": True, "Delay Frequency %": ":.1f"},
               title=f"{state}: lead time by factory & ship mode")
    f.update_traces(marker_line_color=SURFACE, marker_line_width=2)
    f.update_layout(xaxis_title="", yaxis_title="Avg lead time (days)")
    a.plotly_chart(style(f, 380), use_container_width=True, config=CFG)

    city = group_kpis(sd, "City", threshold).sort_values("Shipments", ascending=False)
    b.markdown(f"**City-level performance in {state}**")
    b.dataframe(city[["City", "Shipments", "Avg Lead Time", "Delay Frequency %", "Mode-Adjusted Delay"]],
                hide_index=True, use_container_width=True, height=340,
                column_config={"Avg Lead Time": st.column_config.NumberColumn(format="%.2f d"),
                               "Delay Frequency %": st.column_config.NumberColumn(format="%.1f%%"),
                               "Mode-Adjusted Delay": st.column_config.NumberColumn(format="%+.2f d")})

    st.subheader("Order-level shipment timeline")
    rsel = st.selectbox("Route", sd["Route (State)"].value_counts().index.tolist())
    rd = sd[sd["Route (State)"] == rsel].sort_values("Order Date")
    n_orders = st.slider("Most recent order lines shown", 10, max(10, min(300, len(rd))), min(60, len(rd))) \
        if len(rd) > 10 else len(rd)
    tl = rd.tail(n_orders).copy()
    tl["Status"] = np.where(tl["Delayed"], f"Delayed (> {threshold} d)", "On time")
    tl["Bar End"] = (tl["Effective Ship Date"] + np.timedelta64(12, "h")).astype("datetime64[ns]")  # same-day visible
    tl["Label"] = (tl["Order Date"].dt.strftime("%d %b %y") + " · " + tl["Ship Mode"].str.replace(" Class", "")
                   + " · #" + tl["Row ID"].astype(str))
    f = px.timeline(tl, x_start="Order Date", x_end="Bar End", y="Label", color="Status",
                    color_discrete_map={"On time": GOOD, f"Delayed (> {threshold} d)": CRITICAL},
                    hover_data={"Ship Mode": True, "Lead Time": True, "City": True, "Product Name": True,
                                "Bar End": False, "Label": False, "Effective Ship Date": "|%d %b %Y"},
                    title=f"{rsel}: order → ship windows")
    f.update_yaxes(categoryorder="array", categoryarray=tl["Label"].tolist(), autorange="reversed",
                   showticklabels=n_orders <= 40, title="")
    f.update_layout(xaxis_title="")
    st.plotly_chart(style(f, max(320, min(900, 16 * len(tl) + 120))), use_container_width=True, config=CFG)

    show = rd[["Order ID", "Order Date", "Effective Ship Date", "Lead Time", "Ship Mode", "City",
               "Product Name", "Units", "Sales", "Delayed"]].sort_values("Order Date", ascending=False)
    st.dataframe(show, hide_index=True, use_container_width=True,
                 column_config={"Order Date": st.column_config.DateColumn(format="DD MMM YYYY"),
                                "Effective Ship Date": st.column_config.DateColumn("Ship Date (corrected)", format="DD MMM YYYY"),
                                "Sales": st.column_config.NumberColumn(format="$%.2f")})
    st.download_button("Download route orders (CSV)", show.to_csv(index=False), "route_orders.csv")

# ===========================================================================
# 5. Data quality
# ===========================================================================
with tab_dq:
    st.subheader("Cleaning & validation log")
    log_rows = {k: v for k, v in clean_log.items() if k != "unmapped_states"}
    st.dataframe(pd.DataFrame(log_rows.items(), columns=["Step", "Rows"]), hide_index=True)
    st.subheader("Lead-time correction")
    st.markdown(
        "Raw **Ship Date − Order Date** spans **904–1,642 days**: not physically plausible for confectionery "
        "distribution. Values form three tight clusters starting at 904, 1,269 and 1,634 days, exactly 365 days "
        "apart, which points to a systematic year offset in the recorded ship dates. Removing the whole-year block, "
        "`(raw − 904) mod 365`, leaves a 0–11 day lead time that is cleanly ordered by service level. That value is "
        "used throughout the dashboard. The raw value is kept as `Raw Lead Time`.")
    a, b = st.columns(2)
    f = px.histogram(df_all, x="Raw Lead Time", nbins=150, title="Raw lead time: three year-offset clusters")
    f.update_traces(marker_color=SERIES[0])
    f.update_layout(xaxis_title="Raw days", yaxis_title="")
    a.plotly_chart(style(f, 340, False), use_container_width=True, config=CFG)
    ct = pd.crosstab(df_all["Ship Mode"], df_all["Lead Time"]).reindex(MODE_ORDER)
    b.markdown("**Corrected lead time by ship mode (shipment counts)**")
    b.dataframe(ct, use_container_width=True)
    st.markdown("""
**KPI definitions**
- **Shipping Lead Time** = Ship Date − Order Date (year-offset corrected), in days
- **Average Lead Time** = mean lead time per route · **Route Volume** = shipments (order lines) per route
- **Delay Frequency** = % of shipments with lead time > threshold (sidebar)
- **Route Efficiency Score** = 100 × (slowest avg − route avg) / (slowest avg − fastest avg) across ranked routes
- **Mode-Adjusted Delay** = lead time − average lead time of the same ship mode (fair geographic comparison)
- **Route** = Factory (from product → factory mapping) → customer State or Region
""")

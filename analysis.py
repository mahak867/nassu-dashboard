"""
Nassau Candy Distributor - Factory-to-Customer Shipping Route Efficiency Analysis
Core data pipeline: cleaning, validation, feature engineering, route aggregation, KPIs.

Used by both the Streamlit dashboard (app.py) and the report generator (build_report.py).
"""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

DATA_PATH = Path(__file__).parent / "data" / "nassau_candy.csv"

# ---------------------------------------------------------------------------
# Reference data (from project brief)
# ---------------------------------------------------------------------------
FACTORIES = {
    "Lot's O' Nuts":     (32.881893, -111.768036),
    "Wicked Choccy's":   (32.076176, -81.088371),
    "Sugar Shack":       (48.11914,  -96.18115),
    "Secret Factory":    (41.446333, -90.565487),
    "The Other Factory": (35.1175,   -89.971107),
}

PRODUCT_FACTORY = {
    "Wonka Bar - Nutty Crunch Surprise": "Lot's O' Nuts",
    "Wonka Bar - Fudge Mallows": "Lot's O' Nuts",
    "Wonka Bar - Scrumdiddlyumptious": "Lot's O' Nuts",
    "Wonka Bar - Milk Chocolate": "Wicked Choccy's",
    "Wonka Bar - Triple Dazzle Caramel": "Wicked Choccy's",
    "Laffy Taffy": "Sugar Shack",
    "SweeTARTS": "Sugar Shack",
    "Nerds": "Sugar Shack",
    "Fun Dip": "Sugar Shack",
    "Fizzy Lifting Drinks": "Sugar Shack",
    "Everlasting Gobstopper": "Secret Factory",
    "Hair Toffee": "The Other Factory",
    "Lickable Wallpaper": "Secret Factory",
    "Wonka Gum": "Secret Factory",
    "Kazookles": "The Other Factory",
}

# State / province code + approximate geographic centroid (lat, lon)
STATE_INFO = {
    # United States
    "Alabama": ("AL", 32.81, -86.79), "Alaska": ("AK", 61.37, -152.40),
    "Arizona": ("AZ", 33.73, -111.43), "Arkansas": ("AR", 34.97, -92.37),
    "California": ("CA", 36.12, -119.68), "Colorado": ("CO", 39.06, -105.31),
    "Connecticut": ("CT", 41.60, -72.76), "Delaware": ("DE", 39.32, -75.51),
    "District of Columbia": ("DC", 38.90, -77.03), "Florida": ("FL", 27.77, -81.69),
    "Georgia": ("GA", 33.04, -83.64), "Hawaii": ("HI", 21.09, -157.50),
    "Idaho": ("ID", 44.24, -114.48), "Illinois": ("IL", 40.35, -88.99),
    "Indiana": ("IN", 39.85, -86.26), "Iowa": ("IA", 42.01, -93.21),
    "Kansas": ("KS", 38.53, -96.73), "Kentucky": ("KY", 37.67, -84.67),
    "Louisiana": ("LA", 31.17, -91.87), "Maine": ("ME", 44.69, -69.38),
    "Maryland": ("MD", 39.06, -76.80), "Massachusetts": ("MA", 42.23, -71.53),
    "Michigan": ("MI", 43.33, -84.54), "Minnesota": ("MN", 45.69, -93.90),
    "Mississippi": ("MS", 32.74, -89.68), "Missouri": ("MO", 38.46, -92.29),
    "Montana": ("MT", 46.92, -110.45), "Nebraska": ("NE", 41.13, -98.27),
    "Nevada": ("NV", 38.31, -117.06), "New Hampshire": ("NH", 43.45, -71.56),
    "New Jersey": ("NJ", 40.30, -74.52), "New Mexico": ("NM", 34.84, -106.25),
    "New York": ("NY", 42.17, -74.95), "North Carolina": ("NC", 35.63, -79.81),
    "North Dakota": ("ND", 47.53, -99.78), "Ohio": ("OH", 40.39, -82.76),
    "Oklahoma": ("OK", 35.57, -96.93), "Oregon": ("OR", 44.57, -122.07),
    "Pennsylvania": ("PA", 40.59, -77.21), "Rhode Island": ("RI", 41.68, -71.51),
    "South Carolina": ("SC", 33.86, -80.95), "South Dakota": ("SD", 44.30, -99.44),
    "Tennessee": ("TN", 35.75, -86.69), "Texas": ("TX", 31.05, -97.56),
    "Utah": ("UT", 40.15, -111.86), "Vermont": ("VT", 44.05, -72.71),
    "Virginia": ("VA", 37.77, -78.17), "Washington": ("WA", 47.40, -121.49),
    "West Virginia": ("WV", 38.49, -80.95), "Wisconsin": ("WI", 44.27, -89.62),
    "Wyoming": ("WY", 42.76, -107.30),
    # Canada
    "Alberta": ("AB", 53.93, -116.58), "British Columbia": ("BC", 53.73, -127.65),
    "Manitoba": ("MB", 53.76, -98.81), "New Brunswick": ("NB", 46.57, -66.46),
    "Newfoundland and Labrador": ("NL", 53.14, -57.66), "Nova Scotia": ("NS", 44.68, -63.74),
    "Ontario": ("ON", 51.25, -85.32), "Prince Edward Island": ("PE", 46.51, -63.42),
    "Quebec": ("QC", 52.94, -73.55), "Saskatchewan": ("SK", 52.94, -106.45),
}

# Raw Ship Date - Order Date contains whole-year offsets (see clean_data docstring)
RAW_OFFSET_BASE = 904
RAW_OFFSET_STEP = 365


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


# ---------------------------------------------------------------------------
# Cleaning & feature engineering
# ---------------------------------------------------------------------------
def clean_data(path: Path | str = DATA_PATH) -> tuple[pd.DataFrame, dict]:
    """Load, validate and enrich the order data.

    Data-quality note on lead times
    -------------------------------
    The raw difference Ship Date - Order Date ranges 904-1642 days and falls in
    three tight clusters starting at 904, 1269 and 1634 days (exactly 365 apart).
    Removing the whole-year block, i.e. (raw - 904) mod 365, leaves a 0-11 day
    value that is cleanly ordered by ship mode (Same Day 0-2, First 1-4,
    Second 1-6, Standard 3-8). This residual is the operational lead time and is
    used as `Lead Time` throughout. The uncorrected value is kept as
    `Raw Lead Time` for transparency.
    """
    log: dict = {}
    df = pd.read_csv(path)
    log["rows_loaded"] = len(df)

    # --- standardise text / geographic fields --------------------------------
    for c in ["Ship Mode", "Country/Region", "City", "State/Province", "Region",
              "Division", "Product Name"]:
        df[c] = df[c].astype(str).str.strip().str.replace(r"\s+", " ", regex=True)
    df["Product Name"] = df["Product Name"].str.replace("Wonka Bar -Scrum", "Wonka Bar - Scrum", regex=False)
    df["Postal Code"] = df["Postal Code"].astype(str).str.strip()

    # --- validate dates --------------------------------------------------------
    df["Order Date"] = pd.to_datetime(df["Order Date"], format="%d-%m-%Y", errors="coerce")
    df["Ship Date"] = pd.to_datetime(df["Ship Date"], format="%d-%m-%Y", errors="coerce")
    bad_dates = df["Order Date"].isna() | df["Ship Date"].isna()
    log["invalid_dates_removed"] = int(bad_dates.sum())
    df = df[~bad_dates].copy()

    # --- missing shipment records ---------------------------------------------
    key_cols = ["Order ID", "Ship Mode", "State/Province", "Product Name"]
    missing = df[key_cols].isna().any(axis=1) | df[key_cols].isin(["", "nan"]).any(axis=1)
    log["missing_records_removed"] = int(missing.sum())
    df = df[~missing].copy()

    dups = df.duplicated()
    log["duplicates_removed"] = int(dups.sum())
    df = df[~dups].copy()

    # --- lead time --------------------------------------------------------------
    df["Raw Lead Time"] = (df["Ship Date"] - df["Order Date"]).dt.days
    neg = df["Raw Lead Time"] < 0
    log["negative_lead_times_removed"] = int(neg.sum())
    df = df[~neg].copy()

    df["Year Offset Block"] = ((df["Raw Lead Time"] - RAW_OFFSET_BASE) // RAW_OFFSET_STEP).astype(int)
    df["Lead Time"] = (df["Raw Lead Time"] - RAW_OFFSET_BASE) % RAW_OFFSET_STEP
    invalid_lt = (df["Raw Lead Time"] < RAW_OFFSET_BASE) | (df["Lead Time"] > 30)
    log["invalid_lead_times_removed"] = int(invalid_lt.sum())
    df = df[~invalid_lt].copy()
    # Operational ship date implied by corrected lead time
    df["Effective Ship Date"] = df["Order Date"] + pd.to_timedelta(df["Lead Time"], unit="D")

    # --- factory mapping ----------------------------------------------------------
    df["Factory"] = df["Product Name"].map(PRODUCT_FACTORY)
    unmapped = df["Factory"].isna()
    log["unmapped_products_removed"] = int(unmapped.sum())
    df = df[~unmapped].copy()
    df["Factory Lat"] = df["Factory"].map(lambda f: FACTORIES[f][0])
    df["Factory Lon"] = df["Factory"].map(lambda f: FACTORIES[f][1])

    # --- geography ------------------------------------------------------------------
    df["State Code"] = df["State/Province"].map(lambda s: STATE_INFO.get(s, (None,))[0])
    df["State Lat"] = df["State/Province"].map(lambda s: STATE_INFO.get(s, (None, np.nan))[1])
    df["State Lon"] = df["State/Province"].map(lambda s: STATE_INFO.get(s, (None, np.nan, np.nan))[2])
    log["unmapped_states"] = sorted(df.loc[df["State Code"].isna(), "State/Province"].unique().tolist())
    df["Distance (km)"] = haversine_km(df["Factory Lat"], df["Factory Lon"], df["State Lat"], df["State Lon"]).round(0)

    # --- route keys -----------------------------------------------------------------
    df["Route (Region)"] = df["Factory"] + " → " + df["Region"]
    df["Route (State)"] = df["Factory"] + " → " + df["State/Province"]
    df["Ship Mode Group"] = np.where(df["Ship Mode"] == "Standard Class", "Standard", "Expedited")
    df["Order Month"] = df["Order Date"].dt.to_period("M").dt.to_timestamp()
    # Mode-adjusted delay: days slower (+) / faster (-) than the average for the same ship mode.
    # Lets geographies be compared fairly regardless of their ship-mode mix.
    df["Mode-Adjusted Delay"] = df["Lead Time"] - df.groupby("Ship Mode")["Lead Time"].transform("mean")
    df["Margin %"] = np.where(df["Sales"] > 0, df["Gross Profit"] / df["Sales"] * 100, np.nan)

    log["rows_clean"] = len(df)
    return df.reset_index(drop=True), log


# ---------------------------------------------------------------------------
# Aggregation & KPIs
# ---------------------------------------------------------------------------
def route_kpis(df: pd.DataFrame, route_col: str = "Route (State)", threshold: float = 5,
               min_shipments: int = 1) -> pd.DataFrame:
    """Per-route KPIs. Delay = lead time strictly greater than `threshold` days.

    Route Efficiency Score (0-100): min-max normalised average lead time,
    inverted so 100 = fastest route in the current selection, 0 = slowest.
    """
    if df.empty:
        return pd.DataFrame()
    g = df.groupby(route_col)
    out = pd.DataFrame({
        "Factory": g["Factory"].first(),
        "Shipments": g.size(),
        "Avg Lead Time": g["Lead Time"].mean(),
        "Median Lead Time": g["Lead Time"].median(),
        "Lead Time Std": g["Lead Time"].std(ddof=0),
        "Delay Frequency %": g["Lead Time"].apply(lambda s: (s > threshold).mean() * 100),
        "Mode-Adjusted Delay": g["Mode-Adjusted Delay"].mean(),
        "Avg Distance (km)": g["Distance (km)"].mean(),
        "Sales": g["Sales"].sum(),
        "Gross Profit": g["Gross Profit"].sum(),
    })
    out = out[out["Shipments"] >= min_shipments].copy()
    if out.empty:
        return out
    lo, hi = out["Avg Lead Time"].min(), out["Avg Lead Time"].max()
    out["Efficiency Score"] = 100.0 if hi == lo else (100 * (hi - out["Avg Lead Time"]) / (hi - lo))
    out = out.sort_values(["Avg Lead Time", "Shipments"], ascending=[True, False])
    out["Rank"] = np.arange(1, len(out) + 1)
    return out.reset_index().round(2)


def group_kpis(df: pd.DataFrame, by, threshold: float = 5) -> pd.DataFrame:
    g = df.groupby(by)
    out = pd.DataFrame({
        "Shipments": g.size(),
        "Avg Lead Time": g["Lead Time"].mean(),
        "Lead Time Std": g["Lead Time"].std(ddof=0),
        "Delay Frequency %": g["Lead Time"].apply(lambda s: (s > threshold).mean() * 100),
        "Mode-Adjusted Delay": g["Mode-Adjusted Delay"].mean(),
        "Sales": g["Sales"].sum(),
        "Gross Profit": g["Gross Profit"].sum(),
        "Avg Sales / Order Line": g["Sales"].mean(),
    })
    return out.reset_index().round(2)


def bottlenecks(df: pd.DataFrame, by: str = "State/Province", threshold: float = 5) -> pd.DataFrame:
    """Flag geographies that combine above-median volume with above-median lead time
    (or delay rate). Bottleneck Index = volume share x delay rate, normalised to 100."""
    k = group_kpis(df, by, threshold)
    if k.empty:
        return k
    vmed, lmed, dmed = k["Shipments"].median(), k["Avg Lead Time"].median(), k["Delay Frequency %"].median()
    k["High Volume"] = k["Shipments"] >= vmed
    k["Slow"] = (k["Avg Lead Time"] > lmed) | (k["Delay Frequency %"] > dmed)
    k["Bottleneck"] = k["High Volume"] & k["Slow"]
    raw = (k["Shipments"] / k["Shipments"].sum()) * k["Delay Frequency %"]
    k["Bottleneck Index"] = (100 * raw / raw.max()).round(1) if raw.max() > 0 else 0.0
    return k.sort_values("Bottleneck Index", ascending=False).reset_index(drop=True)


if __name__ == "__main__":
    d, lg = clean_data()
    print(lg)
    print(route_kpis(d, "Route (Region)").to_string())


# ---------------------------------------------------------------------------
# What-if scenario simulation
# ---------------------------------------------------------------------------
MODES = ["Same Day", "First Class", "Second Class", "Standard Class"]


def _dist(s: pd.Series, support: np.ndarray) -> np.ndarray:
    """Empirical probability distribution of integer lead times over `support`."""
    if len(s) == 0:
        return np.zeros(len(support))
    return s.value_counts(normalize=True).reindex(support, fill_value=0).to_numpy()


def simulate_scenario(df: pd.DataFrame, threshold: float = 5, to_second: float = 0.0, to_first: float = 0.0,
                      recover_2025: float = 0.0, premium_second: float = 0.0, premium_first: float = 0.0) -> dict:
    """Expected KPIs if operations changed. Analytical (no random sampling), based on empirical distributions.

    to_second / to_first : share (0-1) of Standard Class shipments upgraded to Second / First Class.
                           An upgraded order takes on the empirical lead-time distribution of its new mode
                           (same order year).
    recover_2025         : share (0-1) of the 2025 slowdown recovered, i.e. 2025 shipments follow a mix of
                           (1-r) x 2025 and r x 2024 lead-time distributions for the same mode.
    premium_*            : assumed extra freight cost ($) per upgraded shipment (user assumption; the dataset
                           has no freight cost).
    """
    if to_second + to_first > 1:
        raise ValueError("to_second + to_first cannot exceed 1")
    if df.empty:
        raise ValueError("no shipments to simulate")
    support = np.arange(0, int(df["Lead Time"].max()) + 1)
    years = df["Order Date"].dt.year
    y_min = years.min()

    def mode_year_dist(mode, year):
        cur = _dist(df.loc[(df["Ship Mode"] == mode) & (years == year), "Lead Time"], support)
        if cur.sum() == 0:  # mode not seen this year: fall back to all years
            cur = _dist(df.loc[df["Ship Mode"] == mode, "Lead Time"], support)
        if recover_2025 > 0 and year == 2025 and y_min < 2025:
            base = _dist(df.loc[(df["Ship Mode"] == mode) & (years == 2024), "Lead Time"], support)
            if base.sum() > 0:
                cur = (1 - recover_2025) * cur + recover_2025 * base
        return cur

    total = np.zeros(len(support))
    per_mode = {m: np.zeros(len(support)) for m in MODES}
    moved = {"Second Class": 0.0, "First Class": 0.0}
    for (mode, year), g in df.groupby([df["Ship Mode"], years]):
        n = len(g)
        if mode == "Standard Class":
            parts = {"Standard Class": n * (1 - to_second - to_first),
                     "Second Class": n * to_second, "First Class": n * to_first}
            moved["Second Class"] += n * to_second
            moved["First Class"] += n * to_first
        else:
            parts = {mode: n}
        for m, w in parts.items():
            if w > 0:
                contrib = w * mode_year_dist(m, year)
                total += contrib
                per_mode[m] += contrib

    n_total = total.sum()
    late = support > threshold
    exp_avg = float((total * support).sum() / n_total)
    exp_delay = float(total[late].sum() / n_total * 100)
    base_avg = float(df["Lead Time"].mean())
    base_delay = float((df["Lead Time"] > threshold).mean() * 100)
    cost = moved["Second Class"] * premium_second + moved["First Class"] * premium_first
    delays_avoided = (base_delay - exp_delay) / 100 * n_total
    mode_rows = []
    for m in MODES:
        w = per_mode[m].sum()
        if w > 0:
            mode_rows.append({"Ship Mode": m, "Shipments": w, "Avg Lead Time": (per_mode[m] * support).sum() / w,
                              "Delay Frequency %": per_mode[m][late].sum() / w * 100})
    return {
        "baseline_avg": base_avg, "scenario_avg": exp_avg,
        "baseline_delay": base_delay, "scenario_delay": exp_delay,
        "shipments": n_total, "upgraded": moved["Second Class"] + moved["First Class"],
        "delays_avoided": delays_avoided, "days_saved": (base_avg - exp_avg) * n_total,
        "added_cost": cost, "cost_per_delay_avoided": cost / delays_avoided if delays_avoided > 0 else np.nan,
        "by_mode": pd.DataFrame(mode_rows), "distribution": pd.Series(total / n_total, index=support),
    }

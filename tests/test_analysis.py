"""Tests for the cleaning pipeline, KPI functions, scenario simulator and the dashboard itself."""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis import (PRODUCT_FACTORY, bottlenecks, clean_data, group_kpis,  # noqa: E402
                      route_kpis, simulate_scenario)


@pytest.fixture(scope="module")
def data():
    df, log = clean_data()
    return df, log


# --- cleaning & validation ---------------------------------------------------
def test_no_rows_lost_and_log_consistent(data):
    df, log = data
    assert log["rows_loaded"] == 10194
    assert log["rows_clean"] == len(df) == 10194
    assert log["unmapped_states"] == []


def test_lead_time_corrected_into_realistic_range(data):
    df, _ = data
    assert df["Raw Lead Time"].min() >= 904
    assert df["Lead Time"].between(0, 30).all()
    # correction only removes whole 365-day blocks
    assert ((df["Raw Lead Time"] - df["Lead Time"] - 904) % 365 == 0).all()


def test_corrected_lead_time_is_ordered_by_service_level(data):
    df, _ = data
    m = df.groupby("Ship Mode")["Lead Time"].mean()
    assert m["Same Day"] < m["First Class"] < m["Second Class"] < m["Standard Class"]
    assert df.loc[df["Ship Mode"] == "Same Day", "Lead Time"].max() <= 2


def test_every_product_mapped_to_factory(data):
    df, _ = data
    assert df["Factory"].notna().all()
    assert set(df["Product Name"]) <= set(PRODUCT_FACTORY)


def test_mode_adjusted_delay_is_centred_per_mode(data):
    df, _ = data
    assert df.groupby("Ship Mode")["Mode-Adjusted Delay"].mean().abs().max() < 1e-9


# --- KPIs --------------------------------------------------------------------
def test_route_kpis_shape_and_score(data):
    df, _ = data
    r = route_kpis(df, "Route (State)", threshold=5, min_shipments=20)
    assert (r["Shipments"] >= 20).all()
    assert r["Efficiency Score"].max() == pytest.approx(100)
    assert r["Efficiency Score"].min() == pytest.approx(0)
    assert r["Avg Lead Time"].is_monotonic_increasing
    assert list(r["Rank"]) == list(range(1, len(r) + 1))


def test_delay_frequency_matches_definition(data):
    df, _ = data
    k = group_kpis(df, "Ship Mode", threshold=5).set_index("Ship Mode")
    expected = (df.loc[df["Ship Mode"] == "Standard Class", "Lead Time"] > 5).mean() * 100
    assert k.loc["Standard Class", "Delay Frequency %"] == pytest.approx(expected, abs=0.01)


def test_bottlenecks_are_high_volume(data):
    df, _ = data
    b = bottlenecks(df, "State/Province", threshold=5)
    flagged = b[b["Bottleneck"]]
    assert len(flagged) > 0
    assert (flagged["Shipments"] >= b["Shipments"].median()).all()
    assert b["Bottleneck Index"].max() == pytest.approx(100)


# --- scenario simulator ------------------------------------------------------
def test_simulator_reproduces_baseline(data):
    df, _ = data
    r = simulate_scenario(df, threshold=5)
    assert r["scenario_avg"] == pytest.approx(r["baseline_avg"])
    assert r["scenario_delay"] == pytest.approx(r["baseline_delay"])
    assert r["added_cost"] == 0
    assert r["distribution"].sum() == pytest.approx(1)


def test_simulator_upgrades_reduce_delays_and_cost_money(data):
    df, _ = data
    r = simulate_scenario(df, threshold=5, to_second=0.5, premium_second=2.0)
    assert r["scenario_delay"] < r["baseline_delay"]
    assert r["scenario_avg"] < r["baseline_avg"]
    n_std = (df["Ship Mode"] == "Standard Class").sum()
    assert r["upgraded"] == pytest.approx(n_std * 0.5)
    assert r["added_cost"] == pytest.approx(n_std * 0.5 * 2.0)


def test_simulator_recovery_reaches_2024_performance(data):
    df, _ = data
    r = simulate_scenario(df, threshold=5, recover_2025=1.0)
    by_mode_2024 = df[df["Order Date"].dt.year == 2024].groupby("Ship Mode")["Lead Time"].mean()
    mix = df["Ship Mode"].value_counts(normalize=True)
    assert r["scenario_avg"] == pytest.approx((by_mode_2024 * mix).sum(), abs=1e-6)


def test_simulator_rejects_invalid_shares(data):
    df, _ = data
    with pytest.raises(ValueError):
        simulate_scenario(df, to_second=0.7, to_first=0.5)


# --- dashboard smoke test ----------------------------------------------------
def test_dashboard_runs_without_exceptions():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(at.tabs) == 7
    # change the threshold and re-run every module
    at.slider[0].set_value(3).run()
    assert not at.exception

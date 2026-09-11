#!/usr/bin/env python3
"""
Vol Regime Tracker — QQQ long / TQQQ short hedge sizing tool

Determines which exposure tier you should be in based on adaptive VIX bands:
    Low vol  -> 150% long / 100% short TQQQ
    Mid vol  -> 130% long / 100% short TQQQ
    High vol -> 110% long / 100% short TQQQ

Methodology:
    - Signal = 10-day SMA of VIX close (smooths single-day noise)
    - Bands = rolling 33rd / 66th percentile of VIX close over trailing 252
      trading days, recalculated every 21 trading days (~monthly) using only
      data available at that point (no lookahead)
    - Tier only changes on a CONFIRMED signal: the smoothed VIX must sit in
      a new band for 2 consecutive trading days before you act, to avoid
      whipsawing on noise

Usage:
    python3 vol_regime_tracker.py

Requires only the Python standard library (urllib, csv, statistics).
"""

import csv
import io
import statistics
import urllib.request
from datetime import datetime

# Primary source: official CBOE feed. Fallback: GitHub mirror (updated daily).
SOURCES = [
    "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
    "https://raw.githubusercontent.com/datasets/finance-vix/main/data/vix-daily.csv",
]

LOOKBACK = 252        # trading days used to compute rolling percentile bands
RECALC_EVERY = 21     # recalc thresholds roughly monthly
SMA_WINDOW = 10        # smoothing window on VIX close
LOW_PCT = 0.33
HIGH_PCT = 0.66
CONFIRM_DAYS = 2       # consecutive days required before a tier change counts

TIERS = {
    "low":  (150, 100),
    "mid":  (130, 100),
    "high": (110, 100),
}


def fetch_vix():
    last_err = None
    for url in SOURCES:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8")
            return raw
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"Could not fetch VIX data from any source. Last error: {last_err}")


def parse_vix(raw_csv):
    rows = []
    reader = csv.DictReader(io.StringIO(raw_csv))
    # Handle both CBOE's own column naming and the GitHub mirror's naming
    fieldmap = {k.strip().upper(): k for k in reader.fieldnames}
    date_key = fieldmap.get("DATE")
    close_key = fieldmap.get("CLOSE") or fieldmap.get("VIX CLOSE")
    for r in reader:
        d_raw = r[date_key].strip()
        for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
            try:
                d = datetime.strptime(d_raw, fmt)
                break
            except ValueError:
                d = None
        if d is None:
            continue
        try:
            c = float(r[close_key])
        except (ValueError, TypeError):
            continue
        rows.append((d, c))
    rows.sort()
    return rows


def sma(vals, window):
    out = [None] * len(vals)
    for i in range(window - 1, len(vals)):
        out[i] = sum(vals[i - window + 1:i + 1]) / window
    return out


def compute_thresholds(closes):
    n = len(closes)
    thresholds = [None] * n
    last_calc_idx = None
    low_cut = high_cut = None
    for i in range(n):
        if i < LOOKBACK:
            continue
        if last_calc_idx is None or i - last_calc_idx >= RECALC_EVERY:
            window = sorted(closes[i - LOOKBACK:i])
            low_cut = window[int(len(window) * LOW_PCT)]
            high_cut = window[int(len(window) * HIGH_PCT)]
            last_calc_idx = i
        thresholds[i] = (low_cut, high_cut)
    return thresholds


def band_for(val, cuts):
    lo, hi = cuts
    if val < lo:
        return "low"
    if val <= hi:
        return "mid"
    return "high"


def main():
    print("Fetching VIX history...")
    raw = fetch_vix()
    rows = parse_vix(raw)
    dates = [d for d, c in rows]
    closes = [c for d, c in rows]

    if len(closes) < LOOKBACK + SMA_WINDOW + CONFIRM_DAYS:
        print("Not enough history returned to compute bands.")
        return

    vix_sma = sma(closes, SMA_WINDOW)
    thresholds = compute_thresholds(closes)

    # Walk backwards to find the confirmed current tier (last CONFIRM_DAYS agree)
    n = len(closes)
    daily_bands = []
    for i in range(n):
        if thresholds[i] is None or vix_sma[i] is None:
            daily_bands.append(None)
        else:
            daily_bands.append(band_for(vix_sma[i], thresholds[i]))

    # confirmed tier = tier that has held for the last CONFIRM_DAYS valid days
    valid = [(i, b) for i, b in enumerate(daily_bands) if b is not None]
    last_n = valid[-CONFIRM_DAYS:]
    confirmed = last_n[-1][1]
    is_confirmed = all(b == confirmed for _, b in last_n)

    latest_idx = valid[-1][0]
    latest_date = dates[latest_idx].date()
    latest_close = closes[latest_idx]
    latest_sma = vix_sma[latest_idx]
    latest_low_cut, latest_high_cut = thresholds[latest_idx]
    long_pct, short_pct = TIERS[confirmed]

    print()
    print("=" * 50)
    print(f"  VOL REGIME STATUS — as of {latest_date}")
    print("=" * 50)
    print(f"  VIX close:        {latest_close:.2f}")
    print(f"  VIX 10-day SMA:   {latest_sma:.2f}")
    print(f"  Current bands:    low < {latest_low_cut:.2f}  |  "
          f"mid {latest_low_cut:.2f}-{latest_high_cut:.2f}  |  "
          f"high > {latest_high_cut:.2f}")
    print()
    print(f"  TIER: {confirmed.upper()}  ->  {long_pct}% long / {short_pct}% short TQQQ")
    if not is_confirmed:
        print(f"  (NOT YET CONFIRMED — signal has not held {CONFIRM_DAYS} "
              f"consecutive days, last raw reading: {daily_bands[latest_idx]})")
    print()

    # Distance to next threshold, for a heads-up before your next rebalance
    if confirmed == "low":
        dist = latest_low_cut - latest_sma
        print(f"  {dist:.2f} pts of SMA cushion before dropping to MID tier")
    elif confirmed == "high":
        dist = latest_sma - latest_high_cut
        print(f"  {dist:.2f} pts of SMA cushion before dropping to MID tier")
    else:
        dist_low = latest_sma - latest_low_cut
        dist_high = latest_high_cut - latest_sma
        print(f"  {dist_low:.2f} pts above LOW threshold, "
              f"{dist_high:.2f} pts below HIGH threshold")
    print("=" * 50)


if __name__ == "__main__":
    main()

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from vol_regime_tracker import fetch_vix, parse_vix, sma, compute_thresholds, band_for, TIERS, LOOKBACK, SMA_WINDOW, CONFIRM_DAYS

st.set_page_config(page_title="Vol Regime Tracker", layout="wide")
st.title("Vol Regime Tracker — QQQ/TQQQ Hedge Sizing")

with st.spinner("Fetching VIX history..."):
    raw = fetch_vix()
    rows = parse_vix(raw)

dates = [d for d, c in rows]
closes = [c for d, c in rows]
vix_sma = sma(closes, SMA_WINDOW)
thresholds = compute_thresholds(closes)

daily_bands = [band_for(vix_sma[i], thresholds[i]) if thresholds[i] and vix_sma[i] else None
               for i in range(len(closes))]
valid = [(i, b) for i, b in enumerate(daily_bands) if b is not None]
last_n = valid[-CONFIRM_DAYS:]
confirmed = last_n[-1][1]
is_confirmed = all(b == confirmed for _, b in last_n)
latest_idx = valid[-1][0]
long_pct, short_pct = TIERS[confirmed]

col1, col2, col3 = st.columns(3)
col1.metric("VIX Close", f"{closes[latest_idx]:.2f}")
col2.metric("VIX 10-day SMA", f"{vix_sma[latest_idx]:.2f}")
col3.metric("Tier", confirmed.upper(), f"{long_pct}% long / {short_pct}% short")

if not is_confirmed:
    st.warning(f"Signal not yet confirmed for {CONFIRM_DAYS} consecutive days.")

low_cuts = [t[0] if t else None for t in thresholds]
high_cuts = [t[1] if t else None for t in thresholds]

fig = go.Figure()
fig.add_trace(go.Scatter(x=dates, y=closes, name="VIX Close", line=dict(color="gray", width=1)))
fig.add_trace(go.Scatter(x=dates, y=vix_sma, name="10-day SMA", line=dict(color="blue")))
fig.add_trace(go.Scatter(x=dates, y=low_cuts, name="Low/Mid Cutoff", line=dict(color="green", dash="dash")))
fig.add_trace(go.Scatter(x=dates, y=high_cuts, name="Mid/High Cutoff", line=dict(color="red", dash="dash")))
fig.update_layout(height=500, hovermode="x unified")
st.plotly_chart(fig, use_container_width=True)

if st.button("Refresh Data"):
    st.rerun()

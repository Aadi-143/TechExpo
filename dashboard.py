"""Streamlit dashboard for QueueLess Campus.

Run:  streamlit run dashboard.py
"""
from __future__ import annotations

from datetime import date, datetime, time

import pandas as pd
import plotly.express as px
import streamlit as st

from app import analytics, config, db, recommender, seed

st.set_page_config(page_title="QueueLess Campus", page_icon="🎫", layout="wide")
db.init_db()

SEVERITY_ICON = {"High": "🔴", "Medium": "🟠", "Low": "🟡"}


def flash(msg: str) -> None:
    st.session_state["flash"] = msg
    st.rerun()


# ------------------------------------------------------------------ sidebar: data + settings
with st.sidebar:
    st.title("🎫 QueueLess Campus")
    st.caption("Admin Office Waiting-Time Analyzer")

    st.subheader("Data")
    n_days = st.number_input("Sample days", 1, 30, 5)
    if st.button("Load sample data", width="stretch"):
        n = db.insert_dataframe(seed.generate_sample(days=int(n_days)), source="sample")
        flash(f"Loaded {n} sample tokens.")
    up = st.file_uploader("Import CSV (counter, issued_at, served_at)", type="csv")
    if up is not None and st.button("Import CSV", width="stretch"):
        try:
            flash(f"Imported {db.insert_dataframe(pd.read_csv(up))} tokens.")
        except ValueError as e:
            st.error(str(e))
    if st.button("Clear all data", width="stretch"):
        db.clear_tokens()
        flash("All data cleared.")

raw = db.load_tokens()
df_all = analytics.prepare(raw)

with st.sidebar:
    st.subheader("Filters")
    all_counters = sorted(df_all["counter"].unique()) if not df_all.empty else []
    chosen = st.multiselect("Counters", all_counters, default=all_counters)
    if not df_all.empty:
        dmin, dmax = df_all["date"].min(), df_all["date"].max()
        rng = st.date_input("Date range", value=(dmin, dmax), min_value=dmin, max_value=dmax)
        d_from, d_to = (rng if isinstance(rng, tuple) and len(rng) == 2 else (dmin, dmax))
    st.subheader("Analysis settings")
    target_wait = st.slider("Target average wait (min)", 2, 30, int(config.TARGET_WAIT_MIN))
    sensitivity = st.slider("Peak sensitivity (lower = more peaks)", 0.0, 2.0,
                            float(config.PEAK_SENSITIVITY), 0.05)
    appt_share = st.slider("Appointment share of capacity", 0.0, 1.0,
                           float(config.APPOINTMENT_SHARE), 0.05)
    with st.expander("Staff per counter"):
        staff = {c: int(st.number_input(c, 1, 20, int(config.COUNTERS.get(c, {}).get(
            "staff", config.DEFAULT_STAFF)), key=f"staff_{c}")) for c in
            sorted(set(all_counters) | set(config.COUNTERS))}

if "flash" in st.session_state:
    st.success(st.session_state.pop("flash"))

# ------------------------------------------------------------------ filtered data
if df_all.empty:
    df = df_all
else:
    df = df_all[df_all["counter"].isin(chosen) & (df_all["date"] >= d_from) & (df_all["date"] <= d_to)]

hourly = analytics.hourly_stats(df)
hp = analytics.detect_peaks(hourly, sensitivity)

tab_over, tab_peak, tab_rec, tab_live, tab_data = st.tabs(
    ["📊 Overview", "⏰ Peak hours", "💡 Recommendations", "🎟️ Live queue & entry", "🗂️ Data"])

NO_DATA = "No data yet. Use **Load sample data** or **Import CSV** in the sidebar."

# ------------------------------------------------------------------ overview
with tab_over:
    if df.empty:
        st.info(NO_DATA)
    else:
        within = (df["wait_min"] <= target_wait).mean() * 100
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Tokens analysed", f"{len(df):,}")
        k2.metric("Average wait", f"{df['wait_min'].mean():.1f} min")
        k3.metric("90% of people wait under", f"{df['wait_min'].quantile(0.9):.1f} min")
        k4.metric(f"Served within {target_wait} min", f"{within:.0f}%")

        summary = analytics.waiting_summary(df)
        st.subheader("Waiting time by counter")
        st.dataframe(summary, hide_index=True, width="stretch")
        per = summary[summary["counter"] != "All counters"]
        fig = px.bar(per, x="counter", y=["avg_wait", "p90_wait"], barmode="group",
                     labels={"value": "Minutes", "variable": "Metric", "counter": ""})
        fig.add_hline(y=target_wait, line_dash="dash", annotation_text="target")
        st.plotly_chart(fig, width="stretch")

# ------------------------------------------------------------------ peak hours
with tab_peak:
    if df.empty:
        st.info(NO_DATA)
    else:
        st.subheader("Tokens per hour (average working day)")
        plot = hp.copy()
        plot["status"] = plot["is_peak"].map({True: "Peak", False: "Normal"})
        fig = px.bar(plot, x="hour", y="avg_arrivals", color="status", facet_col="counter",
                     facet_col_wrap=3, color_discrete_map={"Peak": "#d62728", "Normal": "#1f77b4"},
                     labels={"avg_arrivals": "Avg tokens", "hour": "Hour of day"})
        st.plotly_chart(fig, width="stretch")

        st.subheader("Average wait by hour")
        fig = px.line(hp, x="hour", y="avg_wait", color="counter", markers=True,
                      labels={"avg_wait": "Avg wait (min)", "hour": "Hour of day"})
        fig.add_hline(y=target_wait, line_dash="dash", annotation_text="target")
        st.plotly_chart(fig, width="stretch")

        st.subheader("Busy periods")
        win = analytics.peak_windows(hp)
        if win.empty:
            st.write("No peak hours detected with the current sensitivity.")
        else:
            win["window"] = win.apply(lambda r: f"{r.start_hour:02d}:00-{r.end_hour:02d}:00", axis=1)
            st.dataframe(win[["counter", "window"]], hide_index=True)

        st.subheader("Weekday x hour heatmap")
        sel = st.selectbox("Counter", ["All counters"] + sorted(df["counter"].unique()))
        m = analytics.weekday_hour_matrix(df, sel)
        if not m.empty:
            fig = px.imshow(m, aspect="auto", color_continuous_scale="OrRd",
                            labels=dict(x="Hour", y="Weekday", color="Avg tokens"))
            st.plotly_chart(fig, width="stretch")

# ------------------------------------------------------------------ recommendations
with tab_rec:
    if df.empty:
        st.info(NO_DATA)
    else:
        recs = recommender.build_recommendations(df, hp, staff, target_wait, appt_share)
        st.subheader("Suggested actions for peak windows")
        if not recs:
            st.success("No peak windows detected: workload is evenly spread.")
        for r in recs:
            with st.container(border=True):
                st.markdown(f"### {SEVERITY_ICON[r['severity']]} {r['counter']} · {r['window']} "
                            f"· {r['severity']} priority")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Avg wait", f"{r['avg_wait_min']} min")
                c2.metric("Tokens / hour", r["arrivals_per_hr"])
                c3.metric("Staff now → needed", f"{r['current_staff']} → {r['recommended_staff']}")
                c4.metric("Appointment slots / hr", r["appointment_slots_per_hr"])
                for a in r["actions"]:
                    st.markdown(f"- {a}")
        if recs:
            st.download_button("Download recommendations (CSV)",
                               recommender.recommendations_frame(recs).to_csv(index=False),
                               "recommendations.csv", "text/csv")

        st.subheader("Appointment & token plan")
        c = st.selectbox("Counter", sorted(df["counter"].unique()), key="plan_counter")
        svc = analytics.estimate_service_min(df, c)
        plan = recommender.slot_plan(hp, c, staff[c], svc, appt_share)
        moves, plan = recommender.rebalance(plan)
        st.caption(f"Capacity at {int(config.TARGET_UTILIZATION * 100)}% utilisation with "
                   f"{staff[c]} staff and {svc:.1f} min per service.")
        st.dataframe(plan, hide_index=True, width="stretch")
        if moves.empty:
            st.write("Demand fits within capacity in every hour.")
        else:
            st.markdown("**Suggested shifts of demand (via appointment booking):**")
            st.dataframe(moves, hide_index=True)

# ------------------------------------------------------------------ live queue + manual entry
with tab_live:
    left, right = st.columns(2)
    with left:
        st.subheader("Issue a token")
        counters = sorted(set(config.COUNTERS) | set(all_counters))
        with st.form("issue"):
            counter = st.selectbox("Counter", counters)
            stype = st.text_input("Service type", "general")
            if st.form_submit_button("Issue token"):
                t = db.issue_token(counter, stype)
                flash(f"Token #{t['token_no']} issued at {counter}.")
    with right:
        st.subheader("Add a manual observation")
        st.caption("Voluntary observation: when someone arrived and how long they waited.")
        with st.form("manual"):
            mc = st.selectbox("Counter", counters, key="manual_counter")
            md = st.date_input("Date", date.today())
            mt = st.time_input("Arrival time", time(11, 0))
            mw = st.number_input("Minutes waited", 0.0, 600.0, 10.0, 1.0)
            if st.form_submit_button("Save observation"):
                arrived = datetime.combine(md, mt)
                t = db.issue_token(mc, "observed", arrived, source="manual")
                db.serve_token(t["id"], arrived + pd.Timedelta(minutes=float(mw)))
                flash("Observation saved.")

    st.subheader("Live queue (today's tokens)")
    live = raw[(raw["source"] == "token") & (raw["issued_at"].dt.date == date.today())]
    waiting = live[live["served_at"].isna()]
    serving = live[live["served_at"].notna() & live["finished_at"].isna()]
    w_col, s_col = st.columns(2)
    with w_col:
        st.markdown(f"**Waiting ({len(waiting)})**")
        for r in waiting.itertuples():
            a, b = st.columns([3, 1])
            a.write(f"{r.counter} · #{r.token_no} · since {r.issued_at:%H:%M}")
            if b.button("Serve", key=f"serve_{r.id}"):
                db.serve_token(int(r.id))
                st.rerun()
    with s_col:
        st.markdown(f"**Being served ({len(serving)})**")
        for r in serving.itertuples():
            a, b = st.columns([3, 1])
            a.write(f"{r.counter} · #{r.token_no} · since {r.served_at:%H:%M}")
            if b.button("Finish", key=f"finish_{r.id}"):
                db.finish_token(int(r.id))
                st.rerun()

# ------------------------------------------------------------------ raw data
with tab_data:
    st.subheader("All stored tokens")
    st.dataframe(raw, hide_index=True, width="stretch")
    if not raw.empty:
        st.download_button("Download CSV", raw.to_csv(index=False), "tokens.csv", "text/csv")

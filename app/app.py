"""
F1 Insights - Formula 1 analytics platform: championship standings and title chances, race predictions,
strategy analytics and circuit maps. Run from the project folder:   streamlit run app/app.py
Independent platform; not affiliated with Formula 1, the FIA or any team. No betting.
"""
import json
import os
import sys
import threading
import time
from datetime import timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import championship  # noqa: E402
import strategy as strat  # noqa: E402
import ui  # noqa: E402
import weather  # noqa: E402

PROC = Path(os.environ.get("F1_DATA_DIR", ROOT / "data" / "processed"))
IST = timezone(timedelta(hours=5, minutes=30))  # India has no daylight saving

st.set_page_config(page_title="F1 Insights", page_icon="🏁", layout="wide")
try:  # brand logo in the navigation header (needs a recent Streamlit; the page headers carry the brand either way)
    st.logo(str(ROOT / "app" / "assets" / "logo.svg"), icon_image=str(ROOT / "app" / "assets" / "logo_mark.svg"), size="large")
except Exception:
    pass
st.markdown(ui.GLOBAL_CSS, unsafe_allow_html=True)


# =============================================================== data helpers
@st.cache_data(ttl=60, show_spinner=False)
def load(name: str):
    p = PROC / name
    if not p.exists():
        return None
    if name.endswith(".parquet"):
        return pd.read_parquet(p)
    if name.endswith(".json"):
        return json.loads(p.read_text())
    return pd.read_csv(p)


@st.cache_data(ttl=1800, show_spinner=False)
def forecast_cached(location, iso, country):
    return weather.event_forecast(location, pd.Timestamp(iso), country)


def pred_sig():
    p = PROC / "next_race.parquet"
    return p.stat().st_mtime if p.exists() else 0


def md(html_str):
    st.markdown(html_str, unsafe_allow_html=True)


def show_html(html_str, height):
    """Render a self-contained HTML block. Uses st.iframe (current API); falls back for older Streamlit versions."""
    if hasattr(st, "iframe"):
        st.iframe(html_str, height=int(height))
    else:  # pragma: no cover - only for Streamlit < 1.56
        import streamlit.components.v1 as components
        components.html(html_str, height=int(height))


def fig_style(fig, h=320, title=None):
    fig.update_layout(template="plotly_dark", height=h, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      margin=dict(l=10, r=10, t=44 if title else 14, b=10), title=title,
                      font=dict(family="Titillium Web, Arial"))
    return fig


def next_race_info():
    sched = load("schedule.parquet")
    if sched is None:
        return None
    sched = sched.copy()
    sched["start"] = pd.to_datetime(sched["start_utc"], utc=True)
    now = pd.Timestamp.now(tz="UTC")
    races = sched[(sched["session"] == "Race") & (sched["start"] > now)].sort_values("start")
    if races.empty:
        return None
    nxt = races.iloc[0]
    wk = sched[(sched["season"] == nxt["season"]) & (sched["round"] == nxt["round"])].sort_values("start")
    local = wk["start"].dt.tz_convert(IST)
    upcoming = wk[wk["start"] > now].iloc[0]
    sessions = []
    for (_, r), lt in zip(wk.iterrows(), local):
        state = "done" if r["start"] <= now else ("next" if r["start"] == upcoming["start"] else "")
        sessions.append({"name": r["session"], "day": lt.strftime("%a %d %b"), "time": lt.strftime("%I:%M %p"), "state": state})
    q = wk[wk["session"] == "Qualifying"]
    return {"season": int(nxt["season"]), "round": int(nxt["round"]), "event": nxt["event"], "country": nxt["country"],
            "location": nxt["location"], "race_start": nxt["start"], "sessions": sessions,
            "quali_ready": (q["start"].iloc[0] + timedelta(minutes=75)) if len(q) else None,
            "target_iso": upcoming["start"].isoformat(), "target_label": f"Next: {upcoming['session']}"}


def current_prediction(info):
    nr, meta = load("next_race.parquet"), load("next_race_meta.json")
    if nr is None or not info or len(nr) == 0:
        return None, None
    if int(nr["season"].iloc[0]) == info["season"] and int(nr["round"].iloc[0]) == info["round"]:
        return nr, meta or {}
    return None, None


@st.fragment(run_every=45)
def watch_for_prediction(sig):
    """Checks for a freshly generated prediction and reloads the page by itself."""
    if pred_sig() != sig:
        load.clear()
        st.rerun()
    st.caption("🔄 Checking automatically every minute. No manual refresh needed.")


def source_table(status):
    """Per-source result of the last check, so a failure is explained rather than hidden."""
    rows = status.get("attempts") or []
    if not rows:
        return
    label = {"ok": "OK", "not_published": "Not published yet", "rate_limited": "Rate limited", "timeout": "Timed out",
             "network": "Cannot connect", "http_error": "HTTP error", "invalid": "Rejected: invalid data",
             "mismatch": "Wrong event", "skipped": "Skipped (backing off)", "error": "Error"}
    st.dataframe(pd.DataFrame([{"Source": r["source"], "Result": label.get(r["status"], r["status"]), "Detail": r["detail"]} for r in rows]),
                 hide_index=True, width="stretch")


def retry_button(where):
    if st.button("Retry now", key=f"retry_{where}"):
        import auto_update
        with st.spinner("Checking all data sources..."):
            msg = auto_update.update_if_needed(championship=False)
        load.clear()
        (st.success if msg.startswith("prediction") else st.warning)(msg)
        if pred_sig():
            st.rerun()


def waiting_card(info, where="home"):
    now = pd.Timestamp.now(tz="UTC")
    ready = info.get("quali_ready")
    if ready is not None and now < ready:
        t = ready.tz_convert(IST).strftime("%a %d %b, %I:%M %p IST")
        md(ui.stat_card("Prediction unlocks automatically", f"~{t}"))
        st.caption("About 75 minutes after qualifying starts, F1 Insights pulls the grid, reads the weather forecast "
                   "and publishes the prediction here by itself.")
    else:
        status = load("update_status.json") or {}
        when = pd.Timestamp(status["checked_at"]).tz_convert(IST).strftime("%I:%M %p IST") if status.get("checked_at") else None
        if status.get("state") == "error":
            md(ui.stat_card("Qualifying has finished", "Results not available from any source yet"))
            st.error(f"Last check {when}: none of the data sources returned valid qualifying results. "
                     "The prediction will be generated automatically as soon as one does (checked every 15 minutes).")
            source_table(status)
        else:
            md(ui.stat_card("Qualifying has finished", "Preparing the prediction"))
            st.caption(f"Last check {when}: {status.get('message')}" if when else "The first check runs in the background shortly after the app starts.")
        retry_button(where)
    watch_for_prediction(pred_sig())


# ---- background auto-updater (one thread per server process)
@st.cache_resource
def start_updater():
    if os.environ.get("F1_AUTO_UPDATE", "1") == "0":
        return None
    import auto_update

    def loop():
        while True:
            try:
                auto_update.update_if_needed()
            except Exception as e:  # never kill the thread
                auto_update.log(f"background loop error: {e}")
            time.sleep(15 * 60)

    t = threading.Thread(target=loop, daemon=True, name="f1-auto-update")
    t.start()
    return t


# =============================================================== pages
def champ_payload():
    return load("championship.json")


def champ_status(p):
    """Honest freshness line: says exactly which race the numbers are as of."""
    gen = pd.Timestamp(p["generated_at"]).tz_convert(IST).strftime("%d %b, %I:%M %p IST")
    derived = p.get("data_status") != "official"
    pend = p.get("pending_race")
    dot = "bad" if derived else ("warn" if pend else "")
    parts = [f'<span><span class="fi-dot {dot}"></span>Official standings after round {p["as_of_round"]} of {p["total_rounds"]} · '
             f'{p["as_of_event"]}</span>' if not derived else f'<span><span class="fi-dot bad"></span>Derived from race results (sprint points not included) after round {p["as_of_round"]}</span>',
             f"<span>Checked {gen}</span>", f'<span>Source: {p["source"]}</span>']
    if pend:
        parts.append(f'<span style="color:#F5B301">Round {pend["round"]} ({pend["name"]}) has been run; official standings are not published yet. '
                     "Figures update automatically when they are.</span>")
    if p.get("incomplete_rounds"):
        parts.append("<span>Some earlier rounds could not be fetched yet; trend history is partial.</span>")
    return '<div class="fi-status">' + "".join(parts) + "</div>"


def page_home():
    md(ui.brand_banner())
    info = next_race_info()
    if not info:
        st.warning("No race calendar yet. It is fetched automatically on first start; or run `python src/fetch_schedule.py`.")
        return
    wx = forecast_cached(info["location"], info["race_start"].isoformat(), info["country"])
    md(ui.hero_card(info))
    show_html(ui.countdown_html(info["target_iso"], info["target_label"]), height=125)

    c1, c2, c3, _ = st.columns([1.2, 1.2, 1.2, 2])
    if c1.button("Circuit map"):
        st.session_state["track_pick"] = {"event": info["event"], "season": info["season"], "round": info["round"]}
        st.switch_page(PG["tracks"])
    if c2.button("Full prediction"):
        st.switch_page(PG["predictor"])
    if c3.button("Pit strategy"):
        st.switch_page(PG["strategy"])

    st.markdown("### Drivers' Championship")
    p = champ_payload()
    if p:
        md(champ_status(p))
        md(ui.leader_card(p))
        left, right = st.columns([3, 2])
        with left:
            st.markdown("#### Who can still catch the leader?")
            md(ui.mini_contenders(championship.contenders(p, 5)))
            st.caption("Title chances are model estimates, not official F1 statistics.")
        with right:
            md(ui.tiles([("Races left", str(p["remaining_rounds"])), ("Points available", str(p["max_points_remaining"]))], "fi-g3"))
            if st.button("Open the championship battle"):
                st.switch_page(PG["championship"])
    else:
        md(ui.stat_card("Championship tracker", "Loading official standings..."))
        st.caption("The first update runs in the background after the app starts. This section fills in automatically; "
                   "if the data source is unreachable it will say so on the Championship page.")

    st.markdown("### Race-day weather")
    md(ui.weather_cards(wx))

    st.markdown("### Predicted podium")
    nr, _meta = current_prediction(info)
    if nr is not None:
        show_html(ui.podium_html(nr, show_rest=False), height=ui.podium_height(len(nr), False, False))
    else:
        waiting_card(info, "home")

    res = load("results.parquet")
    if res is not None and len(res):
        last = res.sort_values(["season", "round"]).iloc[-1]
        g = res[(res["season"] == last["season"]) & (res["round"] == last["round"])].sort_values("finish_pos").head(3)
        st.markdown("### Last race")
        md(ui.stat_card(f"{int(last['season'])} · Round {int(last['round'])} · {last['event']}",
                        "  ·  ".join(f"P{int(r.finish_pos)} {r.driver}" for r in g.itertuples())))
        if st.button("Last race circuit"):
            st.session_state["track_pick"] = {"event": last["event"], "season": int(last["season"]), "round": int(last["round"])}
            st.switch_page(PG["tracks"])


def page_championship():
    md(ui.brand("Drivers' Championship", "Official standings, the battle for P1 and each contender's estimated title chances. "
                                         "Probabilities are model estimates, not official F1 statistics."))
    c1, c2 = st.columns([4, 1.4])
    if c2.button("Check for new results"):
        with st.spinner("Contacting the official data source..."):
            res = championship.update_championship(proc=PROC)
        load.clear()
        (st.success if res["ok"] else st.warning)(res["message"])
    p = champ_payload()
    if not p:
        st.info("No championship data saved yet. It is fetched automatically in the background; you can also press "
                "'Check for new results' or run `python src/championship.py`.")
        return
    md(champ_status(p))
    md(ui.leader_card(p))
    second = p["standings"][1] if len(p["standings"]) > 1 else None
    md(ui.tiles([("Races remaining", str(p["remaining_rounds"])), ("Sprints remaining", str(p["remaining_sprints"])),
                 ("Max points available", str(p["max_points_remaining"])),
                 ("Title status", "Clinched" if p.get("clinched") else ("Open" if second else "-"))]))

    st.markdown("### Championship battle")
    st.caption("Who can still realistically win the title, and how their chances moved after the latest race. "
               "Estimated from 20,000 simulations of the remaining races.")
    cont = championship.contenders(p, 8)
    md(ui.contender_cards(p, cont))

    t1, t2, t3 = st.tabs(["Title chance trend", "Points vs. what is still possible", "Full standings"])
    with t1:
        fig = go.Figure()
        for r in cont:
            xs = [h["round"] for h in p["history"]]
            fig.add_trace(go.Scatter(x=xs, y=[h["probs"].get(r["code"], 0) * 100 for h in p["history"]], mode="lines+markers", name=r["name"],
                                     line=dict(color=ui.team_style(r["team"])["ui"], width=3), customdata=[h["event"] for h in p["history"]],
                                     hovertemplate="%{customdata}<br>%{y:.1f}%<extra>" + r["name"] + "</extra>"))
        fig.update_layout(xaxis_title="After round", yaxis_title="Estimated title chance (%)", legend=dict(orientation="h", y=-0.25))
        st.plotly_chart(fig_style(fig, 380, "How each contender's title chances evolved this season"), width="stretch")
        st.caption("Each point is a fresh simulation using only what was known after that race.")
    with t2:
        rows = list(reversed(cont))
        lead = p["standings"][0]["points"]
        fig = go.Figure()
        fig.add_trace(go.Bar(y=[r["name"] for r in rows], x=[r["points"] for r in rows], orientation="h", name="Points now",
                             marker_color=[ui.team_style(r["team"])["ui"] for r in rows]))
        fig.add_trace(go.Bar(y=[r["name"] for r in rows], x=[r["max_possible"] - r["points"] for r in rows], orientation="h",
                             name="Still available", marker_color="rgba(255,255,255,0.12)"))
        fig.add_vline(x=lead, line_dash="dot", line_color="#E10600", annotation_text="Leader's points now", annotation_position="top")
        fig.update_layout(barmode="stack", xaxis_title="Points")
        st.plotly_chart(fig_style(fig, 380, "Current points and the maximum each driver could still reach"), width="stretch")
    with t3:
        recent = p["history"][-8:]
        df = pd.DataFrame([{"Pos": r["pos"], "Driver": r["name"], "Team": r["team"], "Points": r["points"], "Gap": -r["gap_leader"],
                            "Wins": r["wins"], "Podiums": r["podiums"], "Title chance %": round(r["prob"] * 100, 1),
                            "Change (pp)": round((r["prob_change"] or 0) * 100, 1),
                            "Trend": [round(h["probs"].get(r["code"], 0) * 100, 1) for h in recent]} for r in p["standings"]])
        st.dataframe(df, hide_index=True, width="stretch", column_config={
            "Title chance %": st.column_config.ProgressColumn("Title chance %", min_value=0, max_value=100, format="%.1f%%"),
            "Trend": st.column_config.LineChartColumn("Trend (last races)", y_min=0, y_max=100)})
    with st.expander("How the title chances are calculated"):
        st.write(p["method"])
        st.markdown("- Standings and results come from the official data source listed above and refresh after every Grand Prix.\n"
                    "- Probabilities across all drivers add up to 100% (rounding aside). A driver who cannot mathematically catch the leader shows 0%.\n"
                    "- Estimates do not know about penalties, upgrades, weather or driver changes still to come.\n"
                    "- Driver photos come from Wikipedia / Wikimedia Commons when available; initials are shown otherwise.")


def page_predictor():
    md(ui.brand("Race Predictor", "Win, podium and points probabilities from 5,000 simulated races."))
    tab_up, tab_past = st.tabs(["Upcoming race", "Past races (backtest)"])
    with tab_up:
        info = next_race_info()
        if not info:
            st.info("Calendar not loaded yet.")
        else:
            nr, meta = current_prediction(info)
            st.markdown(f"### {info['event']} · Round {info['round']}")
            if nr is None:
                waiting_card(info, "predictor")
            else:
                gen = pd.Timestamp(meta.get("generated_at")).tz_convert(IST).strftime("%a %d %b, %I:%M %p IST") if meta.get("generated_at") else "-"
                rain = "wet" if meta.get("rain_assumed") else "dry"
                src, gsrc = meta.get("quali_source"), meta.get("grid_source")
                st.caption(f"Qualifying data: {src or 'n/a'} · grid: {gsrc or 'qualifying order'} · assuming a {rain} race · generated {gen}.")
                status = load("update_status.json") or {}
                if status.get("state") == "error":
                    st.warning("The latest refresh failed, so this is the last good prediction. It will update automatically when "
                               "the data sources recover.")
                    source_table(status)
                    retry_button("predictor_ok")
                show_html(ui.podium_html(nr, caption="Predicted finishing order"), height=ui.podium_height(len(nr)))
    with tab_past:
        bt = load("backtest.parquet")
        if bt is None:
            st.warning("Run `python src/backtest.py` first.")
        else:
            c1, c2 = st.columns(2)
            season = c1.selectbox("Season", sorted(bt["season"].unique(), reverse=True))
            ev = bt[bt["season"] == season][["round", "event"]].drop_duplicates().sort_values("round", ascending=False)
            labels = {f"R{int(r)} · {e}": int(r) for r, e in zip(ev["round"], ev["event"])}
            pick = c2.selectbox("Race", list(labels))
            g = bt[(bt["season"] == season) & (bt["round"] == labels[pick])]
            top = g.sort_values("exp_pos").iloc[0]
            win = g[g["finish_pos"] == 1]
            m1, m2, m3 = st.columns(3)
            m1.metric("Model's top pick", str(top["driver"]), f"{top['win_prob'] * 100:.0f}% win chance", delta_color="off")
            m2.metric("Pole sitter", str(g.sort_values("grid").iloc[0]["driver"]))
            m3.metric("Actual winner", str(win.iloc[0]["driver"]) if len(win) else "-")
            show_html(ui.podium_html(g, actual=True, caption="What the model predicted"), height=ui.podium_height(len(g)))


# ---------------------------------------------------------------- strategy
def fallback_stats(all_stats):
    vals = list(all_stats.values())
    avg = lambda k: float(np.mean([v[k] for v in vals]))
    return {"n_races": sum(v["n_races"] for v in vals), "laps": int(np.median([v["laps"] for v in vals])),
            "base_pace": float(np.median([v["base_pace"] for v in vals if v.get("base_pace")] or [92.0])),
            "pit_loss": float(np.median([v["pit_loss"] for v in vals])), "sc_prob": avg("sc_prob"), "vsc_prob": avg("vsc_prob"),
            "stops": {k: float(np.mean([v["stops"][k] for v in vals])) for k in ("0", "1", "2", "3+")},
            "pit_lap_prob": [], "first_stop": None, "second_stop": None, "strategies": [], "tyres": {}}


def race_from_stats(s) -> "strat.Race":
    r = strat.Race(laps=int(s["laps"]), base_pace=float(s.get("base_pace") or 92.0), pit_loss=float(s["pit_loss"]),
                   sc_prob=float(s["sc_prob"]))
    for c, v in (s.get("tyres") or {}).items():
        if c in r.tyres:
            r.tyres[c].update({k: v[k] for k in ("deg", "offset") if k in v})
    return r


@st.cache_data(show_spinner=False)
def run_optimiser(laps, base, pit, sc, tyres_json):
    r = strat.Race(laps=laps, base_pace=base, pit_loss=pit, sc_prob=sc)
    r.tyres = json.loads(tyres_json)
    return strat.optimise(r, n_sims=200, top=3)


def upcoming_strategy(info, all_stats):
    if not info:
        st.info("Calendar not loaded yet.")
        return
    st.markdown(f"### {info['event']} · what to expect")
    if not all_stats:
        st.info("Run `python src/build_strategy_stats.py` once to unlock real pit-stop and tyre statistics "
                "(it downloads lap data for recent races; resumable if the FastF1 limit hits).")
        return
    s, approx = all_stats.get(info["event"]), False
    if s is None:
        s, approx = fallback_stats(all_stats), True
        st.warning("No history at this circuit (new venue or layout?). Showing the average of all circuits instead.")
    md('<div class="f1-sub">Based on %d past race(s) at this circuit, 2023 onward.</div>' % s["n_races"] if not approx else "")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Race distance", f"{s['laps']} laps")
    c2.metric("Pit-stop time loss", f"{s['pit_loss']:.1f} s")
    c3.metric("Safety Car chance", f"{s['sc_prob'] * 100:.0f}%")
    c4.metric("Virtual SC chance", f"{s['vsc_prob'] * 100:.0f}%")

    left, right = st.columns([1, 2])
    with left:
        st.markdown("#### Number of pit stops")
        md("".join(ui.meter(f"{k}-stop" if k != "0" else "No stop", v * 100) for k, v in s["stops"].items() if k != "0" or v > 0.01))
        if s.get("first_stop"):
            f = s["first_stop"]
            md(ui.stat_card("Likely first stop", f"Lap {f['p25']:.0f}-{f['p75']:.0f}"))
        if s.get("second_stop"):
            f = s["second_stop"]
            md(ui.stat_card("Likely second stop", f"Lap {f['p25']:.0f}-{f['p75']:.0f}"))
    with right:
        st.markdown("#### When do drivers pit?")
        if s["pit_lap_prob"]:
            p = np.array(s["pit_lap_prob"]) * 100
            x = list(range(1, len(p) + 1))
            fig = go.Figure(go.Bar(x=x, y=p, marker_color="#e10600", opacity=0.4, name="per lap"))
            fig.add_trace(go.Scatter(x=x, y=pd.Series(p).rolling(3, center=True, min_periods=1).mean(), mode="lines",
                                     line=dict(color="#ffffff", width=3), name="smoothed"))
            if s.get("first_stop"):
                fig.add_vrect(x0=s["first_stop"]["p25"], x1=s["first_stop"]["p75"], fillcolor="#e10600", opacity=0.15, line_width=0)
            fig.update_layout(xaxis_title="Lap", yaxis_title="Drivers pitting on this lap (%)", showlegend=False)
            st.plotly_chart(fig_style(fig, 300), width="stretch")
        else:
            st.caption("Per-lap pit data is not available for the average-of-all-circuits view.")

    if s.get("strategies"):
        st.markdown("#### Most-used tyre strategies")
        tbl = pd.DataFrame([{"Strategy": " > ".join(x["seq"].split("-")), "Used by": x["pct"] * 100} for x in s["strategies"]])
        st.dataframe(tbl, hide_index=True, width="stretch",
                     column_config={"Used by": st.column_config.ProgressColumn("Used by", min_value=0, max_value=100, format="%.0f%%")})
        st.caption("S = Soft, M = Medium, H = Hard, I = Intermediate, W = Full wet.")

    st.markdown("#### What our simulator recommends")
    race = race_from_stats(s)
    best = run_optimiser(race.laps, race.base_pace, race.pit_loss, race.sc_prob, json.dumps(race.tyres))
    cols = st.columns(len(best))
    for i, (col, (_, r)) in enumerate(zip(cols, best.iterrows())):
        with col:
            md(ui.stat_card("Best plan" if i == 0 else f"Alternative {i}", r["Tyres"]))
            st.caption(f"Pit at {r['Pit laps']} · expected {strat.fmt_time(r['Expected time (s)'])} "
                       f"(+{r['Behind best (s)']:.1f}s vs best)")
    wx = forecast_cached(info["location"], info["race_start"].isoformat(), info["country"])
    if wx and wx.get("rain_prob") is not None and wx["rain_prob"] >= 50:
        st.warning(f"Rain chance is {wx['rain_prob']:.0f}% - a wet race can reshuffle all of this (intermediates, extra Safety Cars).")
    st.caption("Pit probabilities come from real race data (share of classified drivers pitting on each lap). The simulator uses "
               "tyre wear and pace gaps fitted from the same races, so treat it as guidance, not gospel.")


PRESETS = {"Bahrain (approx.)": (57, 96.0, 22.0, 0.45), "Abu Dhabi (approx.)": (58, 87.0, 21.0, 0.35),
           "Silverstone (approx.)": (52, 90.0, 21.0, 0.50), "Monza (approx.)": (53, 84.0, 24.0, 0.35),
           "Singapore (approx.)": (62, 99.0, 26.0, 0.90), "Custom": (55, 92.0, 22.0, 0.45)}


def strategy_lab(info, all_stats):
    st.caption("Build your own tyre strategy and see the race time. Starts from fitted values for the upcoming circuit when available.")
    presets = dict(PRESETS)
    fitted = None
    if info and all_stats.get(info["event"]):
        fitted = all_stats[info["event"]]
        presets = {f"{info['event']} (fitted)": (int(fitted["laps"]), float(fitted.get("base_pace") or 92.0),
                                                 float(fitted["pit_loss"]), float(fitted["sc_prob"])), **presets}
    c1, c2 = st.columns(2)
    name = c1.selectbox("Circuit preset", list(presets))
    laps0, base0, pit0, sc0 = presets[name]
    k = name.split()[0]
    laps = c1.number_input("Race laps", 30, 80, laps0, key=f"laps_{k}")
    base = c1.number_input("Base lap time (s)", 60.0, 130.0, float(base0), step=0.5, key=f"base_{k}")
    pit = c2.number_input("Pit-stop time loss (s)", 15.0, 35.0, float(pit0), step=0.5, key=f"pit_{k}")
    sc = c2.slider("Chance of a Safety Car", 0.0, 1.0, float(sc0), 0.05, key=f"sc_{k}")
    race = strat.Race(laps=int(laps), base_pace=float(base), pit_loss=float(pit), sc_prob=float(sc))
    tyre_src = (fitted or {}).get("tyres", {}) if name.endswith("(fitted)") else {}

    with st.expander("Tyre model (advanced)"):
        cols = st.columns(3)
        for col, c in zip(cols, strat.COMPOUNDS):
            d = {**strat.DEFAULTS[c], **tyre_src.get(c, {})}
            race.tyres[c]["offset"] = col.number_input(f"{c.title()}: pace offset (s)", 0.0, 3.0, float(d["offset"]), 0.05, key=f"off_{k}_{c}")
            race.tyres[c]["deg"] = col.number_input(f"{c.title()}: wear (s/lap)", 0.0, 0.5, float(d["deg"]), 0.005, format="%.3f", key=f"deg_{k}_{c}")
            race.tyres[c]["life"] = col.number_input(f"{c.title()}: useful life (laps)", 5, 70, int(d["life"]), key=f"life_{k}_{c}")

    st.markdown("#### Your strategy")
    stops = st.radio("Pit stops", [1, 2], horizontal=True)
    defaults = [1, 2, 1]
    cc = st.columns(stops + 1)
    comps = [cc[i].selectbox(f"Stint {i + 1} tyre", strat.COMPOUNDS, index=defaults[i], key=f"c_{stops}_{i}") for i in range(stops + 1)]
    pc = st.columns(stops)
    pits = [int(pc[i].number_input(f"Pit stop {i + 1} at end of lap", 5, race.laps - 5, round(race.laps * (i + 1) / (stops + 1)),
                                   key=f"p_{k}_{stops}_{race.laps}_{i}")) for i in range(stops)]
    if any(b - a < 5 for a, b in zip([0] + pits, pits + [race.laps])):
        st.error("Each stint must be at least 5 laps and pit laps must be in increasing order.")
        return
    if not strat.valid_compounds(comps):
        st.error("Dry-race rule: use at least two different tyre compounds.")
        return

    mean, std = strat.evaluate(race, comps, pits, strat.make_scenarios(race, 300))
    m1, m2, m3 = st.columns(3)
    m1.metric("Race time, no Safety Car", strat.fmt_time(strat.total_time(race, comps, pits)))
    m2.metric("Expected incl. Safety Car chance", strat.fmt_time(mean))
    m3.metric("Spread (±1σ)", f"{std:.1f} s")

    lt = strat.lap_times(race, comps, pits)
    fig = go.Figure(go.Scatter(x=list(range(1, race.laps + 1)), y=lt, mode="lines", line=dict(color="#e10600", width=3)))
    for pl in pits:
        fig.add_vline(x=pl, line_dash="dot", line_color="#aaaaaa")
    fig.update_layout(xaxis_title="Lap", yaxis_title="Lap time (s)")
    st.plotly_chart(fig_style(fig, 320, "Lap times (spikes = pit stops)"), width="stretch")

    if st.button("Find the best strategies"):
        with st.spinner("Simulating thousands of strategies..."):
            best = strat.optimise(race)
        st.write(f"Your plan is **{mean - best['Expected time (s)'].iloc[0]:+.1f} s** vs the best found "
                 f"(**{best['Tyres'].iloc[0]}**, pit {best['Pit laps'].iloc[0]}).")
        st.dataframe(best[["Tyres", "Pit laps", "Stops", "Expected time (s)", "Behind best (s)", "Spread (s)"]].round(2),
                     hide_index=True, width="stretch")


def page_strategy():
    md(ui.brand("Strategy & Pit Stops", "Tyres, pit windows and Safety Car odds for the next race."))
    all_stats = load("strategy_stats.json") or {}
    info = next_race_info()
    t1, t2 = st.tabs(["Upcoming race strategy", "Strategy Lab"])
    with t1:
        upcoming_strategy(info, all_stats)
    with t2:
        strategy_lab(info, all_stats)


# ---------------------------------------------------------------- circuits (2D maps)
@st.cache_data(ttl=3600, show_spinner=False)
def circuit_meta(event):
    """Official circuit name / locality from the season calendar cache, when available."""
    for f in sorted((PROC / "standings").glob("schedule_*.json"), reverse=True):
        try:
            for r in json.loads(f.read_text()):
                if r.get("name", "").lower() == str(event).lower():
                    return r
        except Exception:
            continue
    return {}


def page_tracks():
    md(ui.brand("Circuit Maps", "Top-down track layouts with turn numbers, start/finish line and sectors, plus race-day weather."))
    tracks = load("tracks.json") or {}
    res = load("results.parquet")
    info = next_race_info()
    opts = []
    if info:
        opts.append({"label": f"NEXT · {info['event']} ({info['season']})", "event": info["event"], "season": info["season"],
                     "round": info["round"], "upcoming": True})
    if res is not None:
        done = res[["season", "round", "event"]].drop_duplicates().sort_values(["season", "round"], ascending=False).head(80)
        for r in done.itertuples():
            opts.append({"label": f"{r.season} R{r.round} · {r.event}", "event": r.event, "season": int(r.season),
                         "round": int(r.round), "upcoming": False})
    if not opts:
        st.info("No races available yet.")
        return
    pick = st.session_state.pop("track_pick", None)
    if pick:
        for i, o in enumerate(opts):
            if o["event"] == pick["event"] and o["season"] == pick["season"] and o["round"] == pick["round"]:
                st.session_state["track_sel"] = i
                break
    sel = st.selectbox("Choose a race", range(len(opts)), key="track_sel", format_func=lambda i: opts[i]["label"])
    o = opts[sel]

    if o["upcoming"] and info:
        wx = forecast_cached(info["location"], info["race_start"].isoformat(), info["country"])
        wlabel = "Forecast for race day"
    else:
        wx = weather.recorded(res, o["season"], o["round"]) if res is not None else None
        wlabel = "Conditions during the race"
    meta = circuit_meta(o["event"])
    country = meta.get("country") or (info["country"] if o["upcoming"] and info else "")
    sub = " · ".join(x for x in (meta.get("circuit"), ", ".join(y for y in (meta.get("locality"), country) if y),
                                  f"Round {o['round']} · {o['season']}") if x)
    tr = tracks.get(o["event"])
    if tr:
        show_html(ui.track2d_html(tr, o["event"], sub), height=600)
        z = tr.get("z") or [0]
        items = []
        if tr.get("length_m"):
            items.append(("Lap length", f"{tr['length_m'] / 1000:.3f} km"))
        if tr.get("top_speed"):
            items.append(("Top speed (quali lap)", f"{tr['top_speed']:.0f} km/h"))
        if tr.get("corners"):
            items.append(("Turns", str(len(tr["corners"]))))
        items.append(("Elevation range", f"{max(z) - min(z):.0f} m"))
        md(ui.tiles(items))
        if not tr.get("sectors"):
            st.caption("Sector markers appear after running `python src/build_tracks.py --add-sectors` (re-downloads only the circuits that lack them).")
        st.caption(f"Outline from real telemetry (fastest qualifying lap, {tr.get('season', '')}).")
    else:
        st.info(f"No circuit outline for **{o['event']}** yet. Run `python src/build_tracks.py` (downloads real telemetry; "
                "resumable if the FastF1 limit hits).")

    if wx:
        st.markdown(f"### {wlabel}")
        md(ui.weather_cards(wx))
        wet = (wx.get("rain_prob") or 0) >= 50 or bool(wx.get("wet"))
        st.caption("Wet conditions mean lower grip, more Safety Cars and possible intermediates, so expect a shuffled order." if wet
                   else "Dry conditions: tyre wear and strategy decide the race.")
    elif o["upcoming"]:
        st.caption("A forecast appears once the race is within about 16 days.")


def page_accuracy():
    md(ui.brand("Accuracy", "Judged honestly against the simplest guess: everyone finishes where they started."))
    sc = load("backtest_scores.csv")
    if sc is None:
        st.warning("Run `python src/backtest.py` first.")
        return
    m = sc.mean(numeric_only=True)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Avg position error", f"{m['mae_model']:.2f}", f"{m['mae_model'] - m['mae_grid']:+.2f} vs grid", delta_color="inverse")
    c2.metric("Rank correlation", f"{m['rho_model']:.2f}", f"{m['rho_model'] - m['rho_grid']:+.2f} vs grid")
    c3.metric("Winner hit rate", f"{m['win_hit_model'] * 100:.0f}%", f"{(m['win_hit_model'] - m['win_hit_grid']) * 100:+.0f} pts vs pole")
    c4.metric("Podium overlap", f"{m['podium_model'] * 100:.0f}%", f"{(m['podium_model'] - m['podium_grid']) * 100:+.0f} pts vs grid")
    st.write(f"Tested on **{len(sc)} races**, each predicted using only earlier races. The model improves the overall finishing order "
             "but is not better than 'pole wins' at picking the winner, because qualifying already holds most of that signal.")
    by = sc.groupby("season")[["mae_model", "mae_grid", "rho_model", "rho_grid", "win_hit_model", "win_hit_grid"]].mean().round(3)
    st.dataframe(by, width="stretch")
    sc = sc.copy()
    sc["label"] = sc["season"].astype(str) + " R" + sc["round"].astype(str)
    sc["gain"] = sc["mae_grid"] - sc["mae_model"]
    fig = go.Figure(go.Bar(x=sc["label"], y=sc["gain"], marker_color=["#2ecc71" if v >= 0 else "#e74c3c" for v in sc["gain"]]))
    st.plotly_chart(fig_style(fig, 320, "Positions saved vs grid baseline, per race (green = model better)"), width="stretch")
    imp = load("feature_importance.csv")
    if imp is not None:
        imp = imp.sort_values("gain_pct").tail(12)
        fig2 = go.Figure(go.Bar(x=imp["gain_pct"], y=imp.iloc[:, 0], orientation="h", marker_color="#e10600"))
        st.plotly_chart(fig_style(fig2, 380, "What the model relies on (% of gain)"), width="stretch")


def page_about():
    md(ui.brand("About F1 Insights"))
    st.markdown("""
**F1 Insights is a Formula 1 analytics platform that brings race data, championship standings, circuit information and driver
performance insight together in one place.** It helps fans and motorsport data enthusiasts follow the evolving title fight,
compare drivers, and understand the data behind every race.
""")
    st.markdown("### What the platform offers")
    md(ui.tiles([("Championship tracker", "Official Drivers' standings, the points gap to the leader and an estimated title chance for every contender, refreshed after each Grand Prix"),
                 ("Race predictor", "Win, podium and points probabilities for every driver, generated automatically once qualifying is complete"),
                 ("Strategy analytics", "Pit-stop counts, likely pit windows, Safety Car odds and tyre-wear modelling for each circuit"),
                 ("Circuit maps", "Clean 2D track layouts with turn numbers, sectors and the start/finish line, alongside race-day weather")], "fi-g4"))
    st.markdown("### Data and methodology")
    st.markdown("""
- **Data sources:** official results and standings from the Jolpica-F1 API, timing and telemetry via the open-source FastF1 library (2018 onward), and weather forecasts from Open-Meteo.
- **Championship estimates:** thousands of simulated seasons built from each driver's results, recent form, reliability and the points still available. Probabilities across all drivers total 100%.
- **Race predictions:** gradient-boosted models use only information known before the race (grid, qualifying gaps, form, circuit history, weather); Monte Carlo simulation turns them into probabilities.
- **Measured accuracy:** every prediction is scored against the simplest baseline, "everyone finishes where they start", and the results are published on the Accuracy page.
- **Local time:** every session time is shown in Indian Standard Time (IST).
""")
    st.markdown("### Transparency")
    st.markdown("""
Probabilities are model estimates, not official Formula 1 statistics, and they cannot foresee penalties, upgrades or
incidents. When a data source is unavailable, the platform shows the last saved data and says so rather than presenting it as current.
""")
    st.caption("F1 Insights is an independent platform and is not affiliated with Formula 1, the FIA or any team. \"F1\" is a trademark of "
               "Formula One Licensing BV. The platform is for information and analysis only and is not intended for betting.")
    log = PROC / "update_log.txt"
    if log.exists():
        with st.expander("Auto-update log"):
            st.code("".join(log.read_text().splitlines(True)[-15:]))


# =============================================================== navigation
PG = {
    "home": st.Page(page_home, title="Dashboard", icon="🏠", url_path="dashboard", default=True),
    "championship": st.Page(page_championship, title="Championship", icon="🏆", url_path="championship"),
    "predictor": st.Page(page_predictor, title="Race Predictor", icon="🔮", url_path="predictor"),
    "strategy": st.Page(page_strategy, title="Strategy", icon="🛞", url_path="strategy"),
    "tracks": st.Page(page_tracks, title="Circuits", icon="🧭", url_path="circuits"),
    "accuracy": st.Page(page_accuracy, title="Accuracy", icon="📊", url_path="accuracy"),
    "about": st.Page(page_about, title="About", icon="ℹ️", url_path="about"),
}
start_updater()
st.navigation(list(PG.values()), position="top").run()

"""Enterprise Risk Assessment dashboard.  Run with:  streamlit run app.py"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from era import ModelConfig, load_inputs, run
from era import reporting as rp
from era.config import (ASSESSMENT_PERIOD, BANK_NAME, CONTROL_SCALE, IMPACT_SCALE, LEVEL_ACTIONS, LIKELIHOOD_SCALE,
                        MAX_SCORE, VELOCITY_SCALE)
from era.data import DEFAULT_INPUTS, validate

st.set_page_config(page_title="Enterprise Risk Assessment", page_icon="🛡️", layout="wide")

LEVEL_COLOR = {"Low": "#2E7D63", "Medium": "#C98A1B", "High": "#9B2F3E"}
KRI_COLOR = {"Red": "#9B2F3E", "Amber": "#C98A1B", "Green": "#2E7D63", "Not measured": "#9AA3B2"}
NAVY, GRID = "#14213D", "#D5DAE1"
ROOT = Path(__file__).resolve().parent

st.markdown("""
<style>
  .block-container {padding-top: 3.5rem; max-width: 1280px;}
  [data-testid="stMetricValue"] {font-variant-numeric: tabular-nums;}
  .level {display:inline-block;padding:2px 12px;border-radius:999px;color:#fff;font-weight:600;font-size:0.95rem}
  .muted {color:#5A6478}
</style>""", unsafe_allow_html=True)


# ---------- data ----------
@st.cache_data(show_spinner=False)
def read_inputs(data: bytes | None):
    return load_inputs(io.BytesIO(data) if data else DEFAULT_INPUTS)


def chip(level: str) -> str:
    return f'<span class="level" style="background:{LEVEL_COLOR[level]}">{level}</span>'


def fmt(df: pd.DataFrame, pct=(), dp=2):
    cols = {c: "{:.0%}" for c in pct if c in df.columns}
    num = [c for c in df.select_dtypes("number").columns if c not in cols]
    cols.update({c: f"{{:.{dp}f}}" for c in num})
    sty = df.style.format(cols, na_rep="—")
    for c in ("Level", "Level (app)", "Level (Excel)"):
        if c in df.columns:
            sty = sty.map(lambda v: f"color:{LEVEL_COLOR.get(v, NAVY)};font-weight:600", subset=[c])
    if "KRI status" in df.columns:
        sty = sty.map(lambda v: f"color:{KRI_COLOR.get(v, NAVY)};font-weight:600", subset=["KRI status"])
    return sty


def base_layout(fig, height=360, **kw):
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=30, b=10), plot_bgcolor="rgba(0,0,0,0)",
                      paper_bgcolor="rgba(0,0,0,0)", font=dict(color=NAVY), **kw)
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


# ---------- sidebar ----------
with st.sidebar:
    st.subheader("Data")
    source = st.radio("Inputs", ["Sample bank (fictional)", "Upload my workbook"], label_visibility="collapsed")
    upload = None
    if source == "Upload my workbook":
        upload = st.file_uploader("Workbook with Categories, RiskTypes and Drivers sheets", type=["xlsx"])
    st.download_button("Download the input template", DEFAULT_INPUTS.read_bytes(), "era_inputs_template.xlsx",
                       help="The sample workbook. Edit the blue columns and upload it here.")

    st.subheader("Model settings")
    agg = st.radio("Combine impact and velocity upward by", ["Worst case (max)", "Weighted average"],
                   help="The methodology uses the worst case: a risk type is as severe as its most severe driver.")
    kri_overlay = st.toggle("Adjust scores for KRI status", value=False,
                            help="Red KRIs raise a driver's likelihood by 0.5 and lower its control score by 0.5; "
                                 "green KRIs do the reverse by 0.25.")
    with st.expander("Risk level thresholds"):
        low_max = st.slider("Low up to", 1.0, 12.0, 8.0, 0.5)
        med_max = st.slider("Medium up to", low_max + 0.5, 24.0, max(15.0, low_max + 0.5), 0.5)
    with st.expander("Control effectiveness by score"):
        defaults = ModelConfig().control_effectiveness
        ce = {k: st.slider(f"{k} · {CONTROL_SCALE[k][0]}", 0, 100, int(defaults[k] * 100), 5, format="%d%%") / 100
              for k in range(1, 6)}

inputs = read_inputs(upload.getvalue() if upload else None)
if source == "Upload my workbook" and upload is None:
    st.info("Upload a workbook in the sidebar, or switch back to the sample bank. The template shows the expected layout.")
    st.stop()
if not inputs.ok:
    st.error("The workbook can't be scored yet. Fix these and upload it again:")
    for e in inputs.errors:
        st.markdown(f"- {e}")
    st.stop()
for w in inputs.warnings:
    st.warning(w)

# category weight sliders need the loaded categories, so they render after loading
with st.sidebar.expander("Category weights", expanded=False):
    st.caption("Rescaled to sum to 100%.")
    cat_w = {r.category: st.slider(r.category, 0, 50, int(round(r.weight * 100)), 1, format="%d%%",
                                   key=f"cw_{r.category}") / 100
             for r in inputs.categories.itertuples()}

# ---------- what-if edits ----------
st.session_state.setdefault("edits", {})
key = "upload" if upload else "sample"
if st.session_state.get("edits_for") != key:
    st.session_state["edits"], st.session_state["edits_for"] = {}, key


def apply_edits(base):
    x = base.copy()
    for did, changes in st.session_state["edits"].items():
        for col, val in changes.items():
            x.drivers.loc[x.drivers.driver_id == did, col] = val
    return validate(x)


cfg = ModelConfig(control_effectiveness=ce, low_max=low_max, medium_max=med_max,
                  impact_aggregation="max" if agg.startswith("Worst") else "weighted",
                  velocity_aggregation="max" if agg.startswith("Worst") else "weighted",
                  kri_overlay=kri_overlay, category_weights=cat_w if sum(cat_w.values()) > 0 else None)
try:
    cfg.validate()
except ValueError as exc:
    st.error(str(exc)); st.stop()

edited = apply_edits(inputs)
if not edited.ok:
    st.error("The what-if edits make the inputs invalid: " + " ".join(edited.errors))
    st.session_state["edits"] = {}
    edited = inputs.copy()
res = run(edited, cfg)
base_res = run(inputs.copy(), cfg) if st.session_state["edits"] else res
E = res.enterprise

try:
    st.sidebar.download_button("Download results (Excel)", rp.export_excel(res), "era_results.xlsx", type="primary")
except Exception as exc:  # keep the dashboard usable even if the export fails
    st.sidebar.warning(f"The Excel download isn't available right now ({type(exc).__name__}).")

# ---------- header ----------
name = BANK_NAME if not upload else Path(upload.name).stem
st.markdown(f"<p class='muted' style='margin:0'>{name} · {ASSESSMENT_PERIOD} · "
            f"{len(res.categories)} categories, {len(res.risk_types)} risk types, {len(res.drivers)} drivers</p>",
            unsafe_allow_html=True)
st.title("Enterprise Risk Assessment")
if st.session_state["edits"]:
    d = E["era"] - base_res.enterprise["era"]
    st.info(f"Showing what-if edits to {len(st.session_state['edits'])} driver(s): ERA {d:+.2f} against the saved inputs. "
            "Clear them on the What-if tab.")

tabs = st.tabs(["Enterprise", "Risk types", "Drivers and KRIs", "What-if", "Methodology", "Excel v1.0 reconciliation"])

# ===== Enterprise =====
with tabs[0]:
    c1, c2, c3, c4 = st.columns([1.3, 1, 1, 1])
    c1.markdown(f"**Enterprise risk score**<br><span style='font-size:3rem;font-weight:750;line-height:1.1'>{E['era']:.2f}</span>"
                f"<span class='muted'> / 25</span><br>{chip(E['level'])}", unsafe_allow_html=True)
    c2.metric("Inherent risk", f"{E['inherent']:.2f}", help="Enterprise likelihood × enterprise impact, before controls")
    c3.metric("Control effectiveness", f"{E['control_eff']:.0%}", help=f"From a weighted control score of {E['control']:.2f}")
    c4.metric("Weighted ERA (check)", f"{E['era_weighted']:.2f}", help="Σ category weight × category residual. Should sit close to the ERA.")
    st.caption(LEVEL_ACTIONS[E["level"]])

    # position on the 0-25 scale with the three bands
    fig = go.Figure()
    for lo, hi, lvl in ((0, low_max, "Low"), (low_max, med_max, "Medium"), (med_max, MAX_SCORE, "High")):
        fig.add_shape(type="rect", x0=lo, x1=hi, y0=0, y1=1, fillcolor=LEVEL_COLOR[lvl], opacity=0.22, line_width=0)
        fig.add_annotation(x=(lo + hi) / 2, y=0.5, text=lvl, showarrow=False, font=dict(color=LEVEL_COLOR[lvl], size=13))
    fig.add_trace(go.Scatter(x=[E["inherent"]], y=[0.5], mode="markers+text", text=["Inherent"], textposition="top center",
                             marker=dict(size=14, color="white", line=dict(color=NAVY, width=2)), hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=[E["era"]], y=[0.5], mode="markers+text", text=["Residual"], textposition="bottom center",
                             marker=dict(size=18, color=NAVY), hoverinfo="skip"))
    base_layout(fig, 130, showlegend=False)
    fig.update_xaxes(range=[0, 25], dtick=5, showgrid=False)
    fig.update_yaxes(visible=False, range=[0, 1])
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    left, right = st.columns([1.1, 1])
    with left:
        st.subheader("Categories")
        cats = res.categories.sort_values("residual")
        fig = go.Figure()
        fig.add_bar(y=cats.category, x=cats.inherent, orientation="h", name="Inherent", marker_color="#D5DAE1",
                    hovertemplate="%{y}<br>Inherent %{x:.2f}<extra></extra>")
        fig.add_bar(y=cats.category, x=cats.residual, orientation="h", name="Residual",
                    marker_color=[LEVEL_COLOR[l] for l in cats.level], hovertemplate="%{y}<br>Residual %{x:.2f}<extra></extra>")
        base_layout(fig, 330, barmode="overlay", legend=dict(orientation="h", y=1.08, x=0))
        fig.update_xaxes(range=[0, 25], title="Score (1–25)")
        st.plotly_chart(fig, width="stretch")
    with right:
        st.subheader("Where the residual risk sits")
        sh = res.categories.sort_values("share_of_era", ascending=False)
        fig = go.Figure(go.Bar(x=sh.share_of_era, y=sh.category, orientation="h", marker_color=NAVY,
                               text=[f"{v:.0%}" for v in sh.share_of_era], textposition="outside",
                               hovertemplate="%{y}: %{x:.1%} of weighted ERA<extra></extra>"))
        base_layout(fig, 330)
        fig.update_xaxes(tickformat=".0%", range=[0, sh.share_of_era.max() * 1.25])
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, width="stretch")
    st.dataframe(fmt(rp.category_table(res), pct=("Weight", "Control eff.", "Share of ERA")), hide_index=True,
                 width="stretch")

# ===== Risk types =====
with tabs[1]:
    t = res.risk_types.sort_values("residual", ascending=True)
    st.subheader("Risk types by residual score")
    fig = go.Figure()
    fig.add_bar(y=t.risk_type, x=t.inherent, orientation="h", name="Inherent", marker_color="#D5DAE1")
    fig.add_bar(y=t.risk_type, x=t.residual, orientation="h", name="Residual", marker_color=[LEVEL_COLOR[l] for l in t.level],
                customdata=np.stack([t.category, t.control_eff], axis=1),
                hovertemplate="%{y} (%{customdata[0]})<br>Residual %{x:.2f}<br>Control eff. %{customdata[1]:.0%}<extra></extra>")
    for x in (low_max, med_max):
        fig.add_vline(x=x, line_dash="dot", line_color="#8A93A6")
    base_layout(fig, 720, barmode="overlay", legend=dict(orientation="h", y=1.03))
    fig.update_xaxes(range=[0, 25], title="Score (1–25)")
    st.plotly_chart(fig, width="stretch")

    st.dataframe(fmt(rp.risk_type_table(res), pct=("Weight in category", "Enterprise weight", "Control eff.")),
                 hide_index=True, width="stretch", height=420)

    st.subheader("Drill into a risk type")
    opts = res.risk_types.sort_values("residual", ascending=False)
    pick = st.selectbox("Risk type", opts.risk_type_id, format_func=lambda i: f"{i} · {opts.set_index('risk_type_id').loc[i, 'risk_type']}")
    r = res.risk_types.set_index("risk_type_id").loc[pick]
    st.markdown(f"**{r.risk_type}** · {r.category} &nbsp; {chip(r.level)}", unsafe_allow_html=True)
    st.caption(r.definition)
    m = st.columns(5)
    m[0].metric("Likelihood", f"{r.likelihood:.2f}"); m[1].metric("Impact", f"{r.impact:.2f}")
    m[2].metric("Control", f"{r.control:.2f}"); m[3].metric("Inherent", f"{r.inherent:.2f}"); m[4].metric("Residual", f"{r.residual:.2f}")
    g = res.drivers[res.drivers.risk_type_id == pick]
    show = pd.DataFrame({"Driver": g.driver, "Weight": g.weight, "L": g.L, "I": g.I, "V": g.V, "C": g.C,
                         "Share of likelihood": g.weighted_likelihood / g.weighted_likelihood.sum(),
                         "Driver residual": g.residual, "KRI": g.kri_name, "KRI actual": g.kri_actual, "KRI status": g.kri_status})
    st.dataframe(fmt(show, pct=("Weight", "Share of likelihood")), hide_index=True, width="stretch")
    with st.expander("Controls in place"):
        for row in g.itertuples():
            st.markdown(f"- **{row.driver_id}** {row.control}")

# ===== Drivers and KRIs =====
with tabs[2]:
    d = res.drivers
    k = d.groupby(["category", "kri_status"]).size().unstack(fill_value=0).reindex(columns=["Red", "Amber", "Green", "Not measured"], fill_value=0)
    left, right = st.columns([1, 1.2])
    with left:
        st.subheader("KRI status")
        tot = d.kri_status.value_counts()
        cs = st.columns(3)
        for col, s in zip(cs, ("Red", "Amber", "Green")):
            col.markdown(f"<span style='color:{KRI_COLOR[s]};font-weight:700;font-size:2rem'>{tot.get(s, 0)}</span><br>{s}",
                         unsafe_allow_html=True)
        fig = go.Figure()
        for s in ("Red", "Amber", "Green", "Not measured"):
            if k[s].sum():
                fig.add_bar(y=k.index, x=k[s], name=s, orientation="h", marker_color=KRI_COLOR[s])
        base_layout(fig, 300, barmode="stack", legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(fig, width="stretch")
    with right:
        st.subheader("Driver risk matrix")
        st.caption("Number of drivers at each likelihood and impact score, coloured by L × I.")
        L, I = d.likelihood.astype(int), d.impact.astype(int)
        z = np.zeros((5, 5), int)
        for a, b in zip(L, I):
            z[a - 1, b - 1] += 1
        score = np.outer(np.arange(1, 6), np.arange(1, 6))
        col = np.where(score <= low_max, 0, np.where(score <= med_max, 1, 2))
        fig = go.Figure(go.Heatmap(z=col, x=[f"{i} {IMPACT_SCALE[i][0]}" for i in range(1, 6)],
                                   y=[f"{i} {LIKELIHOOD_SCALE[i][0]}" for i in range(1, 6)],
                                   colorscale=[[0, "#CFE6DC"], [0.5, "#F1DFB8"], [1, "#E6C2C8"]], showscale=False,
                                   text=np.where(z > 0, z, ""), texttemplate="%{text}", textfont=dict(size=16, color=NAVY),
                                   customdata=z, hovertemplate="Likelihood %{y}<br>Impact %{x}<br>%{customdata} drivers<extra></extra>"))
        base_layout(fig, 360)
        fig.update_xaxes(title="Impact", showgrid=False); fig.update_yaxes(title="Likelihood", showgrid=False)
        st.plotly_chart(fig, width="stretch")

    st.subheader("All drivers")
    f1, f2, f3 = st.columns(3)
    cat_f = f1.multiselect("Category", sorted(d.category.unique()))
    kri_f = f2.multiselect("KRI status", ["Red", "Amber", "Green", "Not measured"])
    lvl_f = f3.multiselect("Driver level", ["High", "Medium", "Low"])
    tbl = rp.driver_table(res)
    if cat_f: tbl = tbl[tbl.Category.isin(cat_f)]
    if kri_f: tbl = tbl[tbl["KRI status"].isin(kri_f)]
    if lvl_f: tbl = tbl[tbl.Level.isin(lvl_f)]
    st.caption(f"{len(tbl)} of {len(d)} drivers. Driver scores here are stand-alone (L × I), not weighted.")
    st.dataframe(fmt(tbl, pct=("Weight",)), hide_index=True, width="stretch", height=480)

# ===== What-if =====
with tabs[3]:
    st.subheader("Change driver scores and see the effect")
    st.caption("Edits apply to every tab and to the Excel download. They aren't saved to the workbook.")
    pick = st.selectbox("Risk type to edit", inputs.risk_types.risk_type_id,
                        format_func=lambda i: f"{i} · {inputs.risk_types.set_index('risk_type_id').loc[i, 'risk_type']}", key="wi")
    cur = inputs.drivers[inputs.drivers.risk_type_id == pick][["driver_id", "driver", "weight", "likelihood", "impact",
                                                               "velocity", "control_score", "kri_actual"]]
    out = st.data_editor(cur, hide_index=True, width="stretch", disabled=["driver_id", "driver"], key=f"ed_{pick}",
                         column_config={
                             "driver_id": st.column_config.TextColumn("Driver ID"),
                             "driver": st.column_config.TextColumn("Driver", width="large"),
                             "weight": st.column_config.NumberColumn("Weight", min_value=0.0, max_value=1.0, step=0.05),
                             **{c: st.column_config.NumberColumn(c.replace("_", " ").title(), min_value=1, max_value=5, step=1)
                                for c in ("likelihood", "impact", "velocity", "control_score")},
                             "kri_actual": st.column_config.NumberColumn("KRI actual")})
    base_rows = inputs.drivers.set_index("driver_id")
    changed = False
    for row in out.itertuples(index=False):
        diff = {c: getattr(row, c) for c in ("weight", "likelihood", "impact", "velocity", "control_score", "kri_actual")
                if not (pd.isna(getattr(row, c)) and pd.isna(base_rows.loc[row.driver_id, c]))
                and getattr(row, c) != base_rows.loc[row.driver_id, c]}
        prev = st.session_state["edits"].get(row.driver_id, {})
        if diff != prev:
            changed = True
            if diff: st.session_state["edits"][row.driver_id] = diff
            else: st.session_state["edits"].pop(row.driver_id, None)
    if changed:
        st.rerun()
    c1, c2 = st.columns([1, 4])
    if c1.button("Clear all edits", disabled=not st.session_state["edits"]):
        st.session_state["edits"] = {}
        for k_ in [k_ for k_ in st.session_state if k_.startswith("ed_")]:
            del st.session_state[k_]
        st.rerun()
    if st.session_state["edits"]:
        b, n = base_res, res
        rt_b = b.risk_types.set_index("risk_type_id").loc[pick]; rt_n = n.risk_types.set_index("risk_type_id").loc[pick]
        m = st.columns(3)
        m[0].metric(f"{rt_n.risk_type} residual", f"{rt_n.residual:.2f}", f"{rt_n.residual - rt_b.residual:+.2f}", delta_color="inverse")
        m[1].metric(f"{rt_n.category} residual", f"{n.categories.set_index('category').loc[rt_n.category, 'residual']:.2f}",
                    f"{n.categories.set_index('category').loc[rt_n.category, 'residual'] - b.categories.set_index('category').loc[rt_n.category, 'residual']:+.2f}",
                    delta_color="inverse")
        m[2].metric("Enterprise risk score", f"{n.enterprise['era']:.2f}", f"{n.enterprise['era'] - b.enterprise['era']:+.2f}", delta_color="inverse")
        st.write("Edited drivers:", ", ".join(sorted(st.session_state["edits"])))

# ===== Methodology =====
with tabs[4]:
    st.markdown((ROOT / "docs" / "METHODOLOGY.md").read_text(encoding="utf-8"))
    st.subheader("Scales")
    sc = st.columns(4)
    for col, (title, scale) in zip(sc, (("Likelihood", LIKELIHOOD_SCALE), ("Impact", IMPACT_SCALE),
                                        ("Velocity", VELOCITY_SCALE), ("Control", CONTROL_SCALE))):
        col.markdown(f"**{title}**")
        col.dataframe(pd.DataFrame([(k, v[0], v[1]) for k, v in scale.items()], columns=["Score", "Label", "Meaning"]),
                      hide_index=True, width="stretch")

# ===== Reconciliation =====
with tabs[5]:
    if upload:
        st.info("The reconciliation compares the sample bank with the v1.0 Excel model, so it is shown only for the sample data.")
    else:
        st.subheader("How the corrected model differs from the v1.0 workbook")
        st.markdown(
            "Version 1.0 of this model was an Excel workbook. Moving it to Python surfaced calculation errors, fixed here. "
            "The biggest: risk-type likelihoods in the workbook were typed in rather than linked to the driver scores, "
            "and every one was higher than the drivers support, which inflated the enterprise score.")
        rec = rp.reconciliation(res)
        fig = go.Figure()
        fig.add_scatter(x=rec["Residual (Excel)"], y=rec["Residual (app)"], mode="markers", text=rec["Risk type"],
                        marker=dict(size=11, color=NAVY), hovertemplate="%{text}<br>Excel %{x:.0f} → app %{y:.2f}<extra></extra>")
        fig.add_shape(type="line", x0=0, y0=0, x1=20, y1=20, line=dict(dash="dot", color="#8A93A6"))
        base_layout(fig, 360)
        fig.update_xaxes(title="Residual in Excel v1.0", range=[0, 20]); fig.update_yaxes(title="Residual in this app", range=[0, 20])
        a, b = st.columns([1, 1.3])
        a.plotly_chart(fig, width="stretch")
        b.markdown(
            f"- **Enterprise score:** 11.50 (Medium) in Excel; **{res.enterprise['era']:.2f} ({res.enterprise['level']})** here.\n"
            "- Points below the dotted line scored lower once driver likelihoods were linked through.\n"
            "- Fixes applied: likelihoods and impacts linked to drivers; stated category weights used instead of "
            "weights derived from each category's own score; worst-case impact and velocity per the methodology; "
            "one threshold set; enterprise control effectiveness calculated, not fixed at 50%; no rounding between levels; "
            "a control score of 1 now gives 0% effectiveness; KRI status respects whether higher or lower is worse.")
        st.dataframe(fmt(rec), hide_index=True, width="stretch", height=520)

st.caption(f"{BANK_NAME} is fictional and all data is synthetic. Built by Emmanuel C. Iheme · "
           "[Source on GitHub](https://github.com/emmanueliheme/enterprise-risk-assessment)")

"""
app.py — CoreWitness: Hardware Integrity Dashboard

Streamlit-based UI for Sentinel-QED. Detects Silent Data Corruption (SDC)
by auditing physical CPU cores using dual-core redundancy (EDDI-V pattern).

Run:
    streamlit run app.py
"""

import multiprocessing
import time

import streamlit as st

import fault_injector
import orchestrator as orch_module
from orchestrator import DualCoreOrchestrator
from workloads import calculate_portfolio_interest

# ── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="CoreWitness — Hardware Integrity Layer",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS — 'Cables' dark industrial aesthetic ──────────────────────────
st.markdown(
    """
    <style>
    /* ── Base ── */
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;600;700&family=Inter:wght@300;400;600;700;900&display=swap');

    html, body, [data-testid="stAppViewContainer"] {
        background: #0a0c10 !important;
        color: #c9d1d9;
        font-family: 'Inter', sans-serif;
    }

    /* kill default padding */
    [data-testid="stAppViewContainer"] > .main { padding-top: 0rem; }
    [data-testid="block-container"] { padding: 1.5rem 2.5rem 3rem; }

    /* ── Sidebar ── */
    [data-testid="stSidebar"] {
        background: #0d1117 !important;
        border-right: 1px solid #21262d;
    }
    [data-testid="stSidebar"] * { color: #8b949e !important; }
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 { color: #c9d1d9 !important; }

    /* ── Inputs ── */
    .stToggle label, .stRadio label, .stCheckbox label { color: #8b949e !important; }
    .stButton > button {
        background: linear-gradient(135deg, #238636 0%, #2ea043 100%);
        color: #ffffff;
        font-family: 'JetBrains Mono', monospace;
        font-weight: 700;
        font-size: 1rem;
        letter-spacing: 0.05em;
        border: none;
        border-radius: 8px;
        padding: 0.75rem 2rem;
        width: 100%;
        transition: all 0.2s ease;
        box-shadow: 0 0 20px rgba(46, 160, 67, 0.3);
    }
    .stButton > button:hover {
        background: linear-gradient(135deg, #2ea043 0%, #39d353 100%);
        box-shadow: 0 0 30px rgba(57, 211, 83, 0.5);
        transform: translateY(-1px);
    }
    .stButton > button:active { transform: translateY(0); }

    /* ── Data table ── */
    [data-testid="stDataFrame"] { border: 1px solid #21262d; border-radius: 8px; }
    [data-testid="stDataFrame"] th {
        background: #161b22 !important;
        color: #8b949e !important;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.78rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }
    [data-testid="stDataFrame"] td {
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.85rem;
        color: #c9d1d9 !important;
    }

    /* ── Metric tweaks ── */
    [data-testid="stMetric"] { background: transparent; }

    /* ── Dividers ── */
    hr { border-color: #21262d; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ── Helpers: reusable card HTML ──────────────────────────────────────────────

def _core_card_html(
    core_id: int,
    role: str,
    state: str,           # "idle" | "healthy" | "corrupted" | "trusted"
    value_line: str = "",
    subvalue: str = "",
    affinity_label: str = "",
) -> str:
    """Return an HTML string for one core status card."""

    palette = {
        "idle":      {"border": "#30363d", "glow": "none",                              "badge_bg": "#21262d", "badge_fg": "#8b949e",  "icon": "○", "title_fg": "#8b949e"},
        "healthy":   {"border": "#2ea043", "glow": "0 0 24px rgba(46,160,67,0.45)",    "badge_bg": "#0d4020", "badge_fg": "#39d353",  "icon": "✓", "title_fg": "#39d353"},
        "corrupted": {"border": "#da3633", "glow": "0 0 28px rgba(218,54,51,0.55)",    "badge_bg": "#4a1111", "badge_fg": "#f85149",  "icon": "✗", "title_fg": "#f85149"},
        "trusted":   {"border": "#1f6feb", "glow": "0 0 24px rgba(31,111,235,0.40)",   "badge_bg": "#0d2045", "badge_fg": "#58a6ff",  "icon": "✓", "title_fg": "#58a6ff"},
    }
    p = palette.get(state, palette["idle"])

    badge_labels = {
        "idle":      "STANDBY",
        "healthy":   "PASS — TRUSTED",
        "corrupted": "CORRUPTED — QUARANTINED",
        "trusted":   "SHADOW — TRUSTED",
    }

    return f"""
    <div style="
        background: #0d1117;
        border: 2px solid {p['border']};
        border-radius: 14px;
        padding: 1.8rem 1.6rem;
        box-shadow: {p['glow']};
        transition: box-shadow 0.4s ease;
        font-family: 'JetBrains Mono', monospace;
        height: 100%;
    ">
        <!-- Core ID row -->
        <div style="display:flex; align-items:center; gap:0.7rem; margin-bottom:1.1rem;">
            <div style="
                font-size: 1.9rem;
                font-weight: 900;
                color: {p['title_fg']};
                letter-spacing: -0.02em;
                font-family: 'Inter', sans-serif;
            ">Core {core_id}</div>
            <div style="
                font-size: 0.68rem;
                letter-spacing: 0.12em;
                font-weight: 700;
                color: #555f6e;
                margin-top: 0.3rem;
            ">{role}</div>
        </div>

        <!-- Status badge -->
        <div style="
            display: inline-block;
            background: {p['badge_bg']};
            color: {p['badge_fg']};
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.12em;
            padding: 0.28rem 0.75rem;
            border-radius: 999px;
            border: 1px solid {p['border']};
            margin-bottom: 1.4rem;
        ">{p['icon']}  {badge_labels[state]}</div>

        <!-- Value -->
        <div style="
            font-size: 1.7rem;
            font-weight: 600;
            color: {p['title_fg']};
            letter-spacing: -0.01em;
            margin-bottom: 0.3rem;
        ">{value_line}</div>

        <!-- Subvalue -->
        <div style="
            font-size: 0.8rem;
            color: #555f6e;
            margin-bottom: 1.2rem;
        ">{subvalue}</div>

        <!-- Affinity label -->
        <div style="
            font-size: 0.7rem;
            color: #30363d;
            letter-spacing: 0.08em;
            border-top: 1px solid #21262d;
            padding-top: 0.8rem;
            margin-top: auto;
        ">{affinity_label}</div>
    </div>
    """


def _sdc_alert_html(mismatch_fields: list, primary_core: int, elapsed_ms: float) -> str:
    n = len(mismatch_fields)
    return f"""
    <div style="
        background: #160b0b;
        border: 2px solid #da3633;
        border-radius: 12px;
        padding: 1.4rem 1.6rem;
        box-shadow: 0 0 40px rgba(218,54,51,0.35);
        font-family: 'JetBrains Mono', monospace;
        margin: 1.2rem 0;
    ">
        <div style="color:#f85149; font-size:1.15rem; font-weight:700; letter-spacing:0.08em; margin-bottom:0.4rem;">
            !! SENTINEL-QED: CRITICAL SDC DETECTED !!
        </div>
        <div style="color:#8b949e; font-size:0.8rem; margin-bottom:0.2rem;">
            {n} field(s) corrupted on Core {primary_core} [PRIMARY] &nbsp;·&nbsp; Detection latency: {elapsed_ms:.1f} ms
        </div>
        <div style="color:#da3633; font-size:0.78rem;">
            Core {primary_core} quarantined — shadow result returned as trusted output.
        </div>
    </div>
    """


def _silent_failure_banner_html() -> str:
    return """
    <div style="
        background: #111009;
        border: 2px solid #9e6a03;
        border-radius: 12px;
        padding: 1.2rem 1.6rem;
        font-family: 'JetBrains Mono', monospace;
        margin: 1.2rem 0;
    ">
        <div style="color:#e3b341; font-size:1.05rem; font-weight:700; letter-spacing:0.06em; margin-bottom:0.3rem;">
            ⚠  HIDDEN MENACE — SILENT FAILURE
        </div>
        <div style="color:#8b949e; font-size:0.8rem; margin-bottom:0.15rem;">System status: HEALTHY &nbsp;·&nbsp; ECC check: PASS &nbsp;·&nbsp; OS monitor: ALL CLEAR</div>
        <div style="color:#9e6a03; font-size:0.78rem;">
            The wrong answer is now in your database. The system has no idea.
        </div>
    </div>
    """


# ── Sidebar — Chaos Monkey ────────────────────────────────────────────────────

with st.sidebar:
    st.markdown(
        "<h2 style='color:#c9d1d9;font-family:Inter,sans-serif;font-weight:900;"
        "letter-spacing:-0.02em;margin-bottom:0.2rem;'>⚡ Chaos Monkey</h2>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='color:#555f6e;font-size:0.78rem;font-family:JetBrains Mono,monospace;"
        "margin-bottom:1.4rem;'>Inject silicon defects into Core 0 (Primary)</p>",
        unsafe_allow_html=True,
    )

    fault_active = st.toggle("Inject Hardware Fault", value=False, key="fault_active")
    fault_type = st.radio(
        "Fault Type",
        options=["stuck_at", "resistive"],
        captions=["Bit flip in register (stuck-at-1)", "Value drift (~$100 off)"],
        key="fault_type",
    )

    st.divider()
    st.markdown(
        "<h3 style='color:#c9d1d9;font-family:Inter,sans-serif;font-weight:700;"
        "font-size:0.9rem;letter-spacing:0.05em;margin-bottom:0.6rem;'>WORKLOAD</h3>",
        unsafe_allow_html=True,
    )

    principal = st.number_input("Principal ($)", min_value=1_000, max_value=10_000_000,
                                value=250_000, step=10_000, format="%d")
    rate_pct = st.slider("Annual Rate (%)", min_value=0.5, max_value=15.0,
                         value=6.85, step=0.05, format="%.2f")
    years = st.slider("Horizon (years)", min_value=1, max_value=30, value=10)

    st.divider()
    st.markdown(
        "<p style='color:#30363d;font-size:0.68rem;font-family:JetBrains Mono,monospace;"
        "letter-spacing:0.06em;'>CPU affinity pinning via psutil<br>Linux: real core isolation<br>macOS: logical isolation only</p>",
        unsafe_allow_html=True,
    )


# ── Main header ───────────────────────────────────────────────────────────────

st.markdown(
    """
    <div style="
        border-bottom: 1px solid #21262d;
        padding-bottom: 1.2rem;
        margin-bottom: 2rem;
    ">
        <div style="
            font-family: 'Inter', sans-serif;
            font-size: 2.1rem;
            font-weight: 900;
            letter-spacing: -0.03em;
            color: #c9d1d9;
            margin-bottom: 0.2rem;
        ">
            <span style="color:#58a6ff;">Core</span>Witness
            <span style="
                font-size: 0.65rem;
                font-family: 'JetBrains Mono', monospace;
                color: #555f6e;
                letter-spacing: 0.12em;
                font-weight: 400;
                vertical-align: middle;
                margin-left: 0.5rem;
            ">HARDWARE INTEGRITY LAYER</span>
        </div>
        <div style="color:#555f6e; font-size:0.85rem; font-family:'JetBrains Mono',monospace; letter-spacing:0.04em;">
            Silent Data Corruption · Dual-Core QED · EDDI-V pattern
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ── Controls row ──────────────────────────────────────────────────────────────

ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([2, 2, 1])

with ctrl_col1:
    disable_sentinel = st.checkbox(
        "☠ Disable Sentinel Protection",
        value=False,
        help="Run on one core only. System will report HEALTHY even when math is wrong. Simulates the Hidden Menace.",
        key="disable_sentinel",
    )

with ctrl_col3:
    run_audit = st.button("▶  Run Integrity Audit", use_container_width=True)

st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)

# ── Silicon Map heading ───────────────────────────────────────────────────────

st.markdown(
    "<div style='font-family:\"JetBrains Mono\",monospace;font-size:0.72rem;"
    "letter-spacing:0.14em;color:#555f6e;margin-bottom:0.8rem;'>SILICON MAP — PHYSICAL CORE STATUS</div>",
    unsafe_allow_html=True,
)

core_col0, spacer, core_col1 = st.columns([5, 0.3, 5])

# ── State initialisation ──────────────────────────────────────────────────────

if "last_result" not in st.session_state:
    st.session_state.last_result = None
if "last_fault_active" not in st.session_state:
    st.session_state.last_fault_active = False
if "last_silent" not in st.session_state:
    st.session_state.last_silent = None   # (corrupted_result, correct_result)

# ── Execution ─────────────────────────────────────────────────────────────────

if run_audit:
    # Sync globals that the subprocesses will inherit
    fault_injector.FAULT_ACTIVE = fault_active
    fault_injector.FAULT_TYPE = fault_type

    injector_fn = fault_injector.get_active_injector() if fault_active else None
    workload_args = (float(principal), rate_pct / 100.0, int(years))

    with st.spinner("Dispatching workloads to physical cores…"):

        if disable_sentinel:
            # ── Single-core run — simulate legacy unprotected system ──────────
            result_queue: multiprocessing.Queue = multiprocessing.Queue()
            p = multiprocessing.Process(
                target=orch_module._worker,
                args=(0, calculate_portfolio_interest, workload_args, result_queue, injector_fn),
            )
            p.start()
            p.join(timeout=15)

            try:
                status, core_id, single_result = result_queue.get(timeout=5)
            except Exception:
                single_result = None

            if p.is_alive():
                p.terminate()
                p.join()

            correct = calculate_portfolio_interest(*workload_args)
            st.session_state.last_result = None
            st.session_state.last_fault_active = fault_active
            st.session_state.last_silent = (single_result, correct)

        else:
            # ── Dual-core QED run via orchestrator ────────────────────────────
            orch = DualCoreOrchestrator(primary_core=0, shadow_core=1)
            qed = orch.run(
                func=calculate_portfolio_interest,
                args=workload_args,
                fault_injector=injector_fn,
                timeout=30.0,
            )
            st.session_state.last_result = qed
            st.session_state.last_fault_active = fault_active
            st.session_state.last_silent = None


# ── Render Silicon Map ────────────────────────────────────────────────────────

qed = st.session_state.last_result
silent_data = st.session_state.last_silent
was_fault = st.session_state.last_fault_active

if qed is None and silent_data is None:
    # ── Idle — no run yet ──────────────────────────────────────────────────
    with core_col0:
        st.markdown(
            _core_card_html(0, "PRIMARY", "idle", "—", "No audit run yet",
                            "cpu_affinity → Core 0"),
            unsafe_allow_html=True,
        )
    with core_col1:
        st.markdown(
            _core_card_html(1, "SHADOW", "idle", "—", "No audit run yet",
                            "cpu_affinity → Core 1"),
            unsafe_allow_html=True,
        )

elif silent_data is not None:
    # ── Silent / unprotected run ───────────────────────────────────────────
    corrupted_result, correct_result = silent_data

    corrupted_val = corrupted_result.total_dollars if corrupted_result else "ERROR"
    corrupted_sub = (
        f"interest: {corrupted_result.interest_dollars}" if corrupted_result else ""
    )

    with core_col0:
        st.markdown(
            _core_card_html(
                0, "PRIMARY (UNPROTECTED)",
                "corrupted" if was_fault else "healthy",
                corrupted_val,
                corrupted_sub,
                "cpu_affinity → Core 0  |  sentinel: DISABLED",
            ),
            unsafe_allow_html=True,
        )
    with core_col1:
        st.markdown(
            _core_card_html(
                1, "SHADOW",
                "idle",
                "—",
                "Sentinel disabled — not executed",
                "cpu_affinity → Core 1  |  skipped",
            ),
            unsafe_allow_html=True,
        )

    if was_fault:
        st.markdown(_silent_failure_banner_html(), unsafe_allow_html=True)

        # Reveal the truth
        diff_cents = abs(
            (corrupted_result.total_cents if corrupted_result else 0)
            - correct_result.total_cents
        )
        truth_cols = st.columns(3)
        truth_cols[0].metric(
            "Reported Value (wrong)",
            corrupted_result.total_dollars if corrupted_result else "N/A",
            delta=None,
        )
        truth_cols[1].metric("Correct Value", correct_result.total_dollars)
        truth_cols[2].metric("Error", f"${diff_cents/100:,.2f}", delta=None)

else:
    # ── QED result ──────────────────────────────────────────────────────────
    if not qed.fault_detected:
        # Healthy — both cores agree
        primary_val = qed.primary_result.total_dollars if qed.primary_result else "—"
        primary_sub = f"interest: {qed.primary_result.interest_dollars}" if qed.primary_result else ""
        shadow_val  = qed.shadow_result.total_dollars  if qed.shadow_result  else "—"
        shadow_sub  = f"interest: {qed.shadow_result.interest_dollars}"  if qed.shadow_result  else ""

        with core_col0:
            st.markdown(
                _core_card_html(0, "PRIMARY", "healthy", primary_val, primary_sub,
                                f"cpu_affinity → Core 0  |  {qed.execution_time_ms:.1f} ms"),
                unsafe_allow_html=True,
            )
        with core_col1:
            st.markdown(
                _core_card_html(1, "SHADOW", "healthy", shadow_val, shadow_sub,
                                f"cpu_affinity → Core 1  |  {qed.execution_time_ms:.1f} ms"),
                unsafe_allow_html=True,
            )

        st.markdown(
            """
            <div style="
                background:#0d200f; border:1.5px solid #2ea043; border-radius:10px;
                padding:0.9rem 1.4rem; font-family:'JetBrains Mono',monospace;
                color:#39d353; font-size:0.85rem; letter-spacing:0.06em; margin-top:1rem;
            ">✓ QED PASS — Both cores agree. Result is trusted.</div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            "<div style='height:1rem'></div>",
            unsafe_allow_html=True,
        )
        m1, m2, m3 = st.columns(3)
        m1.metric("Portfolio Value", qed.primary_result.total_dollars)
        m2.metric("Interest Earned", qed.primary_result.interest_dollars)
        m3.metric("Detection Latency", f"{qed.execution_time_ms:.1f} ms")

    else:
        # SDC detected
        primary_val = qed.primary_result.total_dollars if qed.primary_result else "—"
        primary_sub = f"interest: {qed.primary_result.interest_dollars}" if qed.primary_result else ""
        shadow_val  = qed.shadow_result.total_dollars  if qed.shadow_result  else "—"
        shadow_sub  = f"interest: {qed.shadow_result.interest_dollars}"  if qed.shadow_result  else ""

        with core_col0:
            st.markdown(
                _core_card_html(0, "PRIMARY", "corrupted", primary_val, primary_sub,
                                f"cpu_affinity → Core 0  |  QUARANTINED"),
                unsafe_allow_html=True,
            )
        with core_col1:
            st.markdown(
                _core_card_html(1, "SHADOW", "trusted", shadow_val, shadow_sub,
                                f"cpu_affinity → Core 1  |  {qed.execution_time_ms:.1f} ms"),
                unsafe_allow_html=True,
            )

        st.markdown(
            _sdc_alert_html(qed.mismatch_fields, qed.primary_core, qed.execution_time_ms),
            unsafe_allow_html=True,
        )

        m1, m2, m3 = st.columns(3)
        m1.metric("Trusted Value (Shadow)", qed.shadow_result.total_dollars)
        m2.metric("Corrupted Value (Primary)", qed.primary_result.total_dollars)
        diff_cents = abs(qed.primary_result.total_cents - qed.shadow_result.total_cents)
        m3.metric("Corruption Error", f"${diff_cents/100:,.2f}")

        # ── Diagnosis Table ────────────────────────────────────────────────
        st.markdown("<div style='height:1.4rem'></div>", unsafe_allow_html=True)
        st.markdown(
            "<div style='font-family:\"JetBrains Mono\",monospace;font-size:0.72rem;"
            "letter-spacing:0.14em;color:#555f6e;margin-bottom:0.6rem;'>"
            "MISMATCH DIAGNOSIS — FIELD-LEVEL CORRUPTION REPORT</div>",
            unsafe_allow_html=True,
        )

        import pandas as pd

        rows = []
        for field_name, v_primary, v_shadow in qed.mismatch_fields:
            delta = ""
            if isinstance(v_primary, (int, float)) and isinstance(v_shadow, (int, float)):
                delta = f"{v_primary - v_shadow:+,.0f}"
            rows.append({
                "Field": field_name,
                f"Core {qed.primary_core} — PRIMARY (corrupted)": str(v_primary),
                f"Core {qed.shadow_core} — SHADOW (trusted)":     str(v_shadow),
                "Δ (primary − shadow)":                            delta,
            })

        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.markdown(
            f"""
            <div style="font-family:'JetBrains Mono',monospace; font-size:0.72rem;
                        color:#555f6e; margin-top:0.6rem; line-spacing:1.6;">
                Fault type injected: <span style="color:#e3b341;">{fault_type}</span> &nbsp;·&nbsp;
                Quarantined core: <span style="color:#f85149;">Core {qed.quarantined_core}</span> &nbsp;·&nbsp;
                Recovery: <span style="color:#39d353;">Shadow result returned</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

# ── Footer ────────────────────────────────────────────────────────────────────

st.markdown("<div style='height:3rem'></div>", unsafe_allow_html=True)
st.markdown(
    """
    <div style="
        border-top: 1px solid #21262d;
        padding-top: 1rem;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.68rem;
        color: #30363d;
        letter-spacing: 0.08em;
        display: flex;
        justify-content: space-between;
    ">
        <span>CoreWitness · EDDI-V dual-core redundancy · psutil CPU affinity</span>
        <span>Manufacturing escapes: 5,000 DPM · Industry SDC detection: ~0%</span>
    </div>
    """,
    unsafe_allow_html=True,
)

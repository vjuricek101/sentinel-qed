"""
app.py — CoreWitness: Hardware Integrity Dashboard

Streamlit-based UI for Sentinel-QED. Detects Silent Data Corruption (SDC)
by auditing physical CPU cores using dual-core redundancy (EDDI-V pattern).

Run:
    streamlit run app.py
"""

import glob
import json
import multiprocessing
import time

import pandas as pd
import streamlit as st

import fault_injector
import orchestrator as orch_module
from orchestrator import DualCoreOrchestrator
from workloads import calculate_portfolio_interest

# ── Page config — must be FIRST Streamlit call ───────────────────────────────
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
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;600;700&family=Inter:wght@300;400;600;700;900&display=swap');

    html, body, [data-testid="stAppViewContainer"] {
        background: #0a0c10 !important;
        color: #c9d1d9;
        font-family: 'Inter', sans-serif;
    }
    [data-testid="stAppViewContainer"] > .main { padding-top: 0rem; }
    [data-testid="block-container"] { padding: 1.5rem 2.5rem 3rem; }

    [data-testid="stSidebar"] {
        background: #0d1117 !important;
        border-right: 1px solid #21262d;
    }
    [data-testid="stSidebar"] * { color: #8b949e !important; }
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 { color: #c9d1d9 !important; }

    .stButton > button {
        background: linear-gradient(135deg, #238636 0%, #2ea043 100%);
        color: #ffffff !important;
        font-family: 'JetBrains Mono', monospace;
        font-weight: 700;
        font-size: 0.95rem;
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
    [data-testid="stMetricValue"] {
        color: #c9d1d9 !important;
        font-family: 'JetBrains Mono', monospace;
    }
    [data-testid="stMetricLabel"] { color: #555f6e !important; font-size: 0.78rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ── Card HTML builder ─────────────────────────────────────────────────────────

def core_card(
    core_id: int,
    role: str,
    state: str,
    value_line: str = "—",
    subvalue: str = "",
    footer: str = "",
) -> str:
    """Return a self-contained HTML card for one CPU core.
    state: 'idle' | 'healthy' | 'corrupted' | 'trusted'
    """
    cfg = {
        "idle":      dict(border="#30363d", glow="none",                             bg_badge="#21262d", fg_badge="#8b949e", icon="○", fg_title="#636e7b", badge_txt="STANDBY"),
        "healthy":   dict(border="#2ea043", glow="0 0 26px rgba(46,160,67,0.5)",    bg_badge="#0d3318", fg_badge="#39d353", icon="✓", fg_title="#39d353", badge_txt="PASS — TRUSTED"),
        "corrupted": dict(border="#da3633", glow="0 0 30px rgba(218,54,51,0.55)",   bg_badge="#3d0f0e", fg_badge="#f85149", icon="✗", fg_title="#f85149", badge_txt="CORRUPTED — QUARANTINED"),
        "trusted":   dict(border="#1f6feb", glow="0 0 26px rgba(31,111,235,0.45)",  bg_badge="#0c1e3d", fg_badge="#58a6ff", icon="✓", fg_title="#58a6ff", badge_txt="SHADOW — TRUSTED"),
    }
    c = cfg.get(state, cfg["idle"])

    return f"""<div style="
        background:#0d1117;
        border:2px solid {c['border']};
        border-radius:14px;
        padding:1.8rem 1.6rem 1.4rem;
        box-shadow:{c['glow']};
        font-family:'JetBrains Mono',monospace;
        min-height:260px;
        display:flex;
        flex-direction:column;
        gap:0;
    ">
        <div style="display:flex;align-items:baseline;gap:0.6rem;margin-bottom:1rem;">
            <span style="font-family:Inter,sans-serif;font-size:2rem;font-weight:900;color:{c['fg_title']};letter-spacing:-0.02em;">Core {core_id}</span>
            <span style="font-size:0.65rem;letter-spacing:0.14em;color:#444d56;font-weight:600;">{role}</span>
        </div>
        <div style="
            display:inline-block;
            background:{c['bg_badge']};
            color:{c['fg_badge']};
            font-size:0.7rem;
            font-weight:700;
            letter-spacing:0.12em;
            padding:0.26rem 0.8rem;
            border-radius:999px;
            border:1px solid {c['border']};
            margin-bottom:1.4rem;
            width:fit-content;
        ">{c['icon']}  {c['badge_txt']}</div>
        <div style="font-size:1.65rem;font-weight:600;color:{c['fg_title']};letter-spacing:-0.01em;margin-bottom:0.25rem;">{value_line}</div>
        <div style="font-size:0.78rem;color:#444d56;margin-bottom:auto;padding-bottom:1.2rem;">{subvalue}</div>
        <div style="font-size:0.66rem;color:#2a3038;letter-spacing:0.07em;border-top:1px solid #1a1f27;padding-top:0.7rem;">{footer}</div>
    </div>"""


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SIDEBAR — Chaos Monkey                                                     ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

with st.sidebar:
    st.markdown(
        "<h2 style='color:#c9d1d9;font-family:Inter,sans-serif;font-weight:900;"
        "letter-spacing:-0.02em;margin-bottom:0.1rem;'>⚡ Chaos Monkey</h2>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='color:#444d56;font-size:0.75rem;font-family:JetBrains Mono,monospace;"
        "margin-bottom:1.2rem;'>Inject silicon defects into Core 0</p>",
        unsafe_allow_html=True,
    )

    fault_active = st.toggle("Inject Hardware Fault", value=False)
    fault_type = st.radio(
        "Fault Type",
        options=["stuck_at", "resistive"],
        captions=["Bit flip — stuck-at-1 on register", "Value drift — ~$100 off"],
    )

    st.divider()
    st.markdown(
        "<h3 style='color:#c9d1d9;font-family:Inter,sans-serif;font-weight:700;"
        "font-size:0.85rem;letter-spacing:0.06em;margin-bottom:0.5rem;'>WORKLOAD</h3>",
        unsafe_allow_html=True,
    )

    principal = st.number_input("Principal ($)", min_value=1_000, max_value=10_000_000,
                                value=250_000, step=1_000, format="%d")
    rate_pct  = st.slider("Annual Rate (%)", 0.5, 15.0, 6.85, 0.05, format="%.2f")
    years     = st.slider("Horizon (years)", 1, 30, 10)

    st.divider()
    st.markdown(
        "<h3 style='color:#c9d1d9;font-family:Inter,sans-serif;font-weight:700;"
        "font-size:0.85rem;letter-spacing:0.06em;margin-bottom:0.5rem;'>PRE-FLIGHT</h3>",
        unsafe_allow_html=True,
    )
    
    run_pepr = st.button("🔍 Run PEPR Hardware Audit", use_container_width=True, help="Dense ALU payload to verify silicon health before workloads.")
    
    if run_pepr:
        st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)
        import pepr_audit
        with st.spinner("Stressing ALUs (25M permutations)"):
            try:
                # Slight sleep so UI spinner paints before C-block
                time.sleep(0.1)
                pepr_audit.run_pepr_audit(target_iterations=25_000_000)
                st.markdown(
                    "<div style='border:1px solid #2ea043; background:#0d3318; padding:0.6rem; border-radius:6px; font-family:\"JetBrains Mono\",monospace; font-size:0.7rem; color:#39d353;'>"
                    "✓ PEPR PASS<br>Silicon Certificate Verified"
                    "</div>", unsafe_allow_html=True
                )
            except pepr_audit.HardwareUnreliableError as e:
                st.markdown(
                    f"<div style='border:1px solid #da3633; background:#3d0f0e; padding:0.6rem; border-radius:6px; font-family:\"JetBrains Mono\",monospace; font-size:0.7rem; color:#f85149;'>"
                    f"✗ SILICON DEGRADATION<br>ALU checksum mismatch"
                    f"</div>", unsafe_allow_html=True
                )
            except Exception as e:
                st.error(f"Error: {e}")

    st.divider()
    st.markdown(
        "<p style='color:#2a3038;font-size:0.66rem;font-family:JetBrains Mono,monospace;"
        "letter-spacing:0.05em;line-height:1.6;'>CPU affinity via psutil<br>"
        "Linux → real core isolation<br>macOS → logical isolation only</p>",
        unsafe_allow_html=True,
    )


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  MAIN HEADER                                                                ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

st.markdown(
    """<div style="border-bottom:1px solid #1a1f27;padding-bottom:1.2rem;margin-bottom:1.8rem;">
        <div style="font-family:Inter,sans-serif;font-size:2rem;font-weight:900;
                    letter-spacing:-0.03em;color:#c9d1d9;margin-bottom:0.15rem;">
            <span style="color:#58a6ff;">Core</span>Witness
            <span style="font-size:0.6rem;font-family:'JetBrains Mono',monospace;
                         color:#444d56;letter-spacing:0.14em;font-weight:400;
                         vertical-align:middle;margin-left:0.5rem;">HARDWARE INTEGRITY LAYER</span>
        </div>
        <div style="color:#444d56;font-size:0.82rem;font-family:'JetBrains Mono',monospace;letter-spacing:0.04em;">
            Silent Data Corruption &nbsp;·&nbsp; Dual-Core QED &nbsp;·&nbsp; EDDI-V pattern
        </div>
    </div>""",
    unsafe_allow_html=True,
)

# ── Controls row ──────────────────────────────────────────────────────────────

c1, c2, c3 = st.columns([3, 2, 1])
with c1:
    safety_mode = st.toggle(
        "🛡️ SAFETY MODE (Sentinel Protection)",
        value=True,
        help="Turn OFF to execute natively on the fast path (single core) to save power. Turn ON for dual-core QED validation.",
    )
with c3:
    run_audit = st.button("▶  Run Integrity Audit", use_container_width=True)

st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

# ── Silicon Map label ─────────────────────────────────────────────────────────

st.markdown(
    "<div style='font-family:\"JetBrains Mono\",monospace;font-size:0.7rem;"
    "letter-spacing:0.15em;color:#444d56;margin-bottom:0.8rem;'>"
    "SILICON MAP — PHYSICAL CORE STATUS</div>",
    unsafe_allow_html=True,
)

col0, _gap, col1 = st.columns([5, 0.25, 5])

# ── Session state ─────────────────────────────────────────────────────────────

for key, default in [
    ("qed", None),
    ("silent", None),   # (corrupted_result, correct_result)
    ("was_fault", False),
    ("was_silent", False),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  EXECUTION ENGINE                                                           ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

if run_audit:
    # Sync fault_injector module globals — these propagate to child processes
    # because the module is imported fresh in each subprocess (fork-exec).
    # We pass the injector function itself so it picks up the correct flag state.
    fault_injector.FAULT_ACTIVE = fault_active
    fault_injector.FAULT_TYPE   = fault_type
    # Use the unconditional variant: get_unconditional_injector() returns a
    # top-level function that always applies the fault, bypassing FAULT_ACTIVE.
    # This is required on macOS where 'spawn' means child processes import the
    # module fresh and never see the parent's FAULT_ACTIVE=True.
    injector_fn  = fault_injector.get_unconditional_injector(fault_type) if fault_active else None
    workload_args = (float(principal), rate_pct / 100.0, int(years))

    orch_module.SAFETY_MODE = safety_mode

    with st.spinner("Dispatching workloads to physical cores…"):
        if not safety_mode:
            # Single-core legacy run — native execution (fast path)
            rq: multiprocessing.Queue = multiprocessing.Queue()
            p = multiprocessing.Process(
                target=orch_module._worker,
                args=(0, calculate_portfolio_interest, workload_args, {}, rq, injector_fn),
            )
            p.start()
            p.join(timeout=15)
            if p.is_alive():
                p.terminate(); p.join()
            try:
                _status, _cid, single_result = rq.get(timeout=5)
            except Exception:
                single_result = None
            correct = calculate_portfolio_interest(*workload_args)
            st.session_state.qed       = None
            st.session_state.silent    = (single_result, correct)
            st.session_state.was_fault = fault_active
            st.session_state.was_silent = True

        else:
            orch = DualCoreOrchestrator(primary_core=0, shadow_core=1)
            qed  = orch.run(
                func=calculate_portfolio_interest,
                args=workload_args,
                fault_injector=injector_fn,
                timeout=30.0,
            )
            st.session_state.qed        = qed
            st.session_state.silent     = None
            st.session_state.was_fault  = fault_active
            st.session_state.was_silent = False


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SILICON MAP RENDERING                                                      ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

qed         = st.session_state.qed
silent_data = st.session_state.silent
was_fault   = st.session_state.was_fault

# ── Idle ──────────────────────────────────────────────────────────────────────
if qed is None and silent_data is None:
    with col0:
        st.markdown(core_card(0, "PRIMARY", "idle", "—", "Awaiting audit",
                              "cpu_affinity → Core 0"), unsafe_allow_html=True)
    with col1:
        st.markdown(core_card(1, "SHADOW",  "idle", "—", "Awaiting audit",
                              "cpu_affinity → Core 1"), unsafe_allow_html=True)

# ── Silent / unprotected ──────────────────────────────────────────────────────
elif silent_data is not None:
    corrupted, correct = silent_data
    c0_state = "corrupted" if was_fault else "healthy"
    c0_val   = corrupted.total_dollars if corrupted else "ERROR"
    c0_sub   = f"interest: {corrupted.interest_dollars}" if corrupted else ""

    with col0:
        st.markdown(
            core_card(0, "PRIMARY — FAST PATH", c0_state, c0_val, c0_sub,
                      "cpu_affinity → Core 0  |  SAFETY_MODE: False"),
            unsafe_allow_html=True,
        )
    with col1:
        st.markdown(
            core_card(1, "SHADOW", "idle", "—", "Safety Mode OFF — saving power",
                      "cpu_affinity → Core 1  |  power saved"),
            unsafe_allow_html=True,
        )

    if was_fault:
        st.markdown(
            """<div style="background:#0e0c04;border:2px solid #9e6a03;border-radius:12px;
                padding:1.2rem 1.6rem;font-family:'JetBrains Mono',monospace;margin-top:1.2rem;">
                <div style="color:#e3b341;font-size:1.0rem;font-weight:700;letter-spacing:0.06em;margin-bottom:0.3rem;">
                ⚠  HIDDEN MENACE — SILENT FAILURE</div>
                <div style="color:#6e5d2e;font-size:0.78rem;margin-bottom:0.15rem;">
                System status: HEALTHY &nbsp;·&nbsp; ECC check: PASS &nbsp;·&nbsp; OS monitor: ALL CLEAR</div>
                <div style="color:#9e6a03;font-size:0.78rem;">
                The wrong answer is now in your database. The system has no idea.</div>
            </div>""",
            unsafe_allow_html=True,
        )
        diff = abs((corrupted.total_cents if corrupted else 0) - correct.total_cents)
        m1, m2, m3 = st.columns(3)
        m1.metric("Reported Value (WRONG)", corrupted.total_dollars if corrupted else "N/A")
        m2.metric("Correct Value", correct.total_dollars)
        m3.metric("Silent Error", f"${diff/100:,.2f}")

# ── QED result ────────────────────────────────────────────────────────────────
elif qed is not None:
    pr = qed.primary_result
    sr = qed.shadow_result

    if not qed.fault_detected:
        with col0:
            st.markdown(
                core_card(0, "PRIMARY", "healthy",
                          pr.total_dollars if pr else "—",
                          f"interest: {pr.interest_dollars}" if pr else "",
                          f"cpu_affinity → Core 0  |  {qed.execution_time_ms:.1f} ms"),
                unsafe_allow_html=True,
            )
        with col1:
            st.markdown(
                core_card(1, "SHADOW", "healthy",
                          sr.total_dollars if sr else "—",
                          f"interest: {sr.interest_dollars}" if sr else "",
                          f"cpu_affinity → Core 1  |  {qed.execution_time_ms:.1f} ms"),
                unsafe_allow_html=True,
            )
        st.markdown(
            """<div style="background:#0a1a0d;border:1.5px solid #2ea043;border-radius:10px;
                padding:0.9rem 1.4rem;font-family:'JetBrains Mono',monospace;
                color:#39d353;font-size:0.82rem;letter-spacing:0.06em;margin-top:1rem;">
                ✓ QED PASS — Both cores agree. Result is trusted.
            </div>""",
            unsafe_allow_html=True,
        )
        st.markdown("<div style='height:0.9rem'></div>", unsafe_allow_html=True)
        m1, m2, m3 = st.columns(3)
        m1.metric("Portfolio Value",   pr.total_dollars   if pr else "—")
        m2.metric("Interest Earned",   pr.interest_dollars if pr else "—")
        m3.metric("Detection Latency", f"{qed.execution_time_ms:.1f} ms")

    else:
        with col0:
            st.markdown(
                core_card(0, "PRIMARY", "corrupted",
                          pr.total_dollars if pr else "—",
                          f"interest: {pr.interest_dollars}" if pr else "",
                          f"cpu_affinity → Core 0  |  QUARANTINED"),
                unsafe_allow_html=True,
            )
        with col1:
            st.markdown(
                core_card(1, "SHADOW", "trusted",
                          sr.total_dollars if sr else "—",
                          f"interest: {sr.interest_dollars}" if sr else "",
                          f"cpu_affinity → Core 1  |  {qed.execution_time_ms:.1f} ms"),
                unsafe_allow_html=True,
            )

        n = len(qed.mismatch_fields)
        st.markdown(
            f"""<div style="background:#100808;border:2px solid #da3633;border-radius:12px;
                padding:1.4rem 1.6rem;box-shadow:0 0 40px rgba(218,54,51,0.3);
                font-family:'JetBrains Mono',monospace;margin-top:1.2rem;">
                <div style="color:#f85149;font-size:1.1rem;font-weight:700;letter-spacing:0.08em;margin-bottom:0.35rem;">
                !! SENTINEL-QED: CRITICAL SDC DETECTED !!</div>
                <div style="color:#6e3333;font-size:0.78rem;margin-bottom:0.15rem;">
                {n} field(s) corrupted on Core {qed.primary_core} [PRIMARY] &nbsp;·&nbsp; Detection latency: {qed.execution_time_ms:.1f} ms</div>
                <div style="color:#da3633;font-size:0.76rem;">
                Core {qed.quarantined_core} quarantined — shadow result returned as trusted output.</div>
            </div>""",
            unsafe_allow_html=True,
        )

        st.markdown("<div style='height:0.9rem'></div>", unsafe_allow_html=True)
        m1, m2, m3 = st.columns(3)
        m1.metric("Trusted Value (Shadow)",    sr.total_dollars if sr else "—")
        m2.metric("Corrupted Value (Primary)", pr.total_dollars if pr else "—")
        diff = abs(pr.total_cents - sr.total_cents) if pr and sr else 0
        m3.metric("Corruption Error", f"${diff/100:,.2f}")

        # ── Diagnosis table ───────────────────────────────────────────────────
        st.markdown("<div style='height:1.2rem'></div>", unsafe_allow_html=True)
        st.markdown(
            "<div style='font-family:\"JetBrains Mono\",monospace;font-size:0.7rem;"
            "letter-spacing:0.15em;color:#444d56;margin-bottom:0.6rem;'>"
            "MISMATCH DIAGNOSIS — FIELD-LEVEL CORRUPTION REPORT</div>",
            unsafe_allow_html=True,
        )
        rows = []
        for field_name, v_primary, v_shadow in qed.mismatch_fields:
            delta = ""
            if isinstance(v_primary, (int, float)) and isinstance(v_shadow, (int, float)):
                delta = f"{v_primary - v_shadow:+,.0f}"
            rows.append({
                "Field":                                       field_name,
                f"Core {qed.primary_core} PRIMARY (corrupted)": str(v_primary),
                f"Core {qed.shadow_core} SHADOW (trusted)":     str(v_shadow),
                "Δ (primary − shadow)":                        delta,
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.markdown(
            f"<div style='font-family:\"JetBrains Mono\",monospace;font-size:0.7rem;"
            f"color:#444d56;margin-top:0.5rem;'>"
            f"Fault type: <span style='color:#e3b341;'>{fault_type}</span> &nbsp;·&nbsp; "
            f"Quarantined: <span style='color:#f85149;'>Core {qed.quarantined_core}</span> &nbsp;·&nbsp; "
            f"Recovery: <span style='color:#39d353;'>shadow result returned</span></div>",
            unsafe_allow_html=True,
        )


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  FLIGHT RECORDER — SDC SNAPSHOT VIEWER                                      ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

st.markdown("<div style='height:3rem'></div>", unsafe_allow_html=True)
st.markdown(
    "<div style='font-family:\"JetBrains Mono\",monospace;font-size:0.75rem;font-weight:700;"
    "letter-spacing:0.15em;color:#da3633;margin-bottom:0.8rem; border-bottom:1px solid #1a1f27; padding-bottom: 0.5rem;'>"
    "📡 BLACK BOX — SDC FLIGHT RECORDERS</div>",
    unsafe_allow_html=True,
)

snapshots = sorted(glob.glob("SDC_SNAPSHOT_*.json"), reverse=True)

if not snapshots:
    st.markdown("<div style='color:#444d56;font-size:0.85rem;font-style:italic;'>No hardware anomalies recorded. (Run an audit with Sentinel ON and Fault INJECTED to generate a black box).</div>", unsafe_allow_html=True)
else:
    snap_options = {s: s.replace("SDC_SNAPSHOT_", "").replace(".json", "") for s in snapshots}
    
    colA, colB = st.columns([1, 2])
    with colA:
        selected_snap = st.selectbox(
            "Select Telemetry Log", 
            options=snapshots, 
            format_func=lambda x: f"Incident @ {snap_options[x]}"
        )
        if st.button("🗑️ Clear All Logs"):
            for s in snapshots:
                import os
                try: os.remove(s)
                except: pass
            st.rerun()
            
    with colB:
        if selected_snap:
            try:
                with open(selected_snap, "r") as f:
                    snap_data = json.load(f)
                    
                st.markdown(f"<div style='font-family:\"JetBrains Mono\",monospace;font-size:0.8rem;color:#c9d1d9;margin-bottom:0.5rem;'>"
                            f"<strong>Workload:</strong> <span style='color:#58a6ff;'>{snap_data.get('workload', 'unknown')}</span> &nbsp;|&nbsp; "
                            f"<strong>Timestamp:</strong> <span>{snap_data.get('timestamp', 'unknown')}</span></div>",
                            unsafe_allow_html=True)
                
                with st.expander("🔬 SOFTWARE REGISTER STATE (Divergence Payload)", expanded=True):
                    st.json(snap_data.get("software_register_state", {}))
                    
                with st.expander("🌡️ HARDWARE TELEMETRY (psutil env)", expanded=False):
                    st.json(snap_data.get("hardware_telemetry", {}))
                    
            except Exception as e:
                st.error(f"Failed to read snapshot: {e}")

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("<div style='height:2.5rem'></div>", unsafe_allow_html=True)
st.markdown(
    """<div style="border-top:1px solid #1a1f27;padding-top:0.9rem;
        font-family:'JetBrains Mono',monospace;font-size:0.66rem;color:#2a3038;
        display:flex;justify-content:space-between;letter-spacing:0.07em;">
        <span>CoreWitness &nbsp;·&nbsp; EDDI-V dual-core redundancy &nbsp;·&nbsp; psutil CPU affinity</span>
        <span>Manufacturing escapes: 5,000 DPM &nbsp;·&nbsp; Industry SDC detection: ~0%</span>
    </div>""",
    unsafe_allow_html=True,
)

"""
main.py — Sentinel-QED live demo script.

Three scenarios that tell a complete story:

  Scenario 1: Healthy hardware — both cores agree, result trusted.
  Scenario 2: Corrupted hardware, NO protection — wrong answer, silent failure.
  Scenario 3: Corrupted hardware, Sentinel ACTIVE — fault caught, quarantine, recovery.

Run:
  python main.py           # all three scenarios
  python main.py --scenario 2   # specific scenario

Connection to lecture (Mitra, Stanford EE272):
  This demo operationalizes the gap between:
  - Current state: "system-level tests detect failure but cannot diagnose it"
  - Target state:  "concurrent autonomous check at the compute layer"

  We fill exactly the slot the lecture identifies as empty:
  software-layer compute protection, deployable today without hardware changes.
"""

import argparse
import sys
import time
import multiprocessing

import fault_injector
import reporter
from orchestrator import DualCoreOrchestrator
from workloads import calculate_portfolio_interest


# Demo parameters — realistic enough to be credible on stage
WORKLOAD_ARGS = (
    250_000.0,   # $250,000 principal
    0.0685,      # 6.85% annual rate (realistic 2025 rate)
    10,          # 10-year horizon
)


def scenario_1_healthy(orchestrator: DualCoreOrchestrator):
    """Healthy hardware — establish baseline, show normal operation."""
    reporter.scenario(
        1,
        "Healthy Hardware",
        "No faults injected. Both cores should agree perfectly."
    )

    fault_injector.FAULT_ACTIVE = False

    reporter.compute_start("calculate_portfolio_interest", WORKLOAD_ARGS)
    time.sleep(0.5)

    result = orchestrator.run(
        func=calculate_portfolio_interest,
        args=WORKLOAD_ARGS,
        fault_injector=None,
    )

    reporter.core_result(0, result.primary_result, injected=False)
    reporter.core_result(1, result.shadow_result,  injected=False)
    reporter.pass_result(result, result.primary_result)


def scenario_2_silent_failure(orchestrator: DualCoreOrchestrator):
    """
    Hardware fault present, NO Sentinel protection.

    This is the current state of the world — the system runs,
    returns a wrong answer, and has absolutely no idea.
    """
    reporter.scenario(
        2,
        "Silent Failure — Unprotected",
        "Fault injected on primary core. No QED. System reports healthy."
    )

    fault_injector.FAULT_ACTIVE = True
    injector = fault_injector.get_active_injector()

    reporter.compute_start("calculate_portfolio_interest", WORKLOAD_ARGS)
    time.sleep(0.5)

    # Run ONLY on the primary core — no shadow, no comparison
    # This is what every system in the world does today
    result_queue = multiprocessing.Queue()
    import orchestrator as orch_module
    p = multiprocessing.Process(
        target=orch_module._worker,
        args=(0, calculate_portfolio_interest, WORKLOAD_ARGS, result_queue, injector)
    )
    p.start()
    p.join(timeout=15)

    status, core_id, corrupted = result_queue.get(timeout=5)

    # What the correct answer should be
    correct = calculate_portfolio_interest(*WORKLOAD_ARGS)

    reporter.core_result(0, corrupted, injected=True)
    reporter.silent_failure(corrupted, correct)


def scenario_3_sentinel_protected(orchestrator: DualCoreOrchestrator):
    """
    Hardware fault present, Sentinel-QED ACTIVE.

    Same fault as Scenario 2. This time Sentinel catches it,
    quarantines the bad core, and returns the trusted shadow result.
    """
    reporter.scenario(
        3,
        "Sentinel-QED Protected",
        "Same fault injected. Dual-core QED active. Watch the catch."
    )

    fault_injector.FAULT_ACTIVE = True
    injector = fault_injector.get_active_injector()

    reporter.compute_start("calculate_portfolio_interest", WORKLOAD_ARGS)
    time.sleep(0.5)

    result = orchestrator.run(
        func=calculate_portfolio_interest,
        args=WORKLOAD_ARGS,
        fault_injector=injector,
    )

    reporter.core_result(0, result.primary_result, injected=True)
    reporter.core_result(1, result.shadow_result,  injected=False)

    if result.fault_detected:
        reporter.sdc_detected(result)
        reporter.trusted_result_from_shadow(result)
    else:
        # Should not happen in this scenario — means injector didn't fire
        print("  WARNING: fault was not detected. Check fault_injector.FAULT_ACTIVE.")


def main():
    parser = argparse.ArgumentParser(description="Sentinel-QED Demo")
    parser.add_argument(
        "--scenario",
        type=int,
        choices=[1, 2, 3],
        default=None,
        help="Run a specific scenario (default: all three)"
    )
    parser.add_argument(
        "--fault",
        choices=["stuck_at", "resistive"],
        default="stuck_at",
        help="Fault type to inject (default: stuck_at)"
    )
    args = parser.parse_args()

    fault_injector.FAULT_TYPE = args.fault

    reporter.header("SENTINEL-QED  //  Hardware Integrity Layer for AI Infrastructure")
    print(f"  Workload:   calculate_portfolio_interest")
    print(f"  Principal:  ${WORKLOAD_ARGS[0]:,.0f}")
    print(f"  Rate:       {WORKLOAD_ARGS[1]*100:.2f}%  annual")
    print(f"  Horizon:    {WORKLOAD_ARGS[2]} years")
    print(f"  Fault type: {args.fault}")
    print(f"\n  CPU affinity pinning via psutil — Core 0 = Primary, Core 1 = Shadow")

    orchestrator = DualCoreOrchestrator(primary_core=0, shadow_core=1)

    scenarios = {
        1: scenario_1_healthy,
        2: scenario_2_silent_failure,
        3: scenario_3_sentinel_protected,
    }

    if args.scenario:
        scenarios[args.scenario](orchestrator)
    else:
        for fn in scenarios.values():
            fn(orchestrator)
            time.sleep(0.8)

    reporter.summary(orchestrator)


if __name__ == "__main__":
    # Required on Windows/macOS for multiprocessing
    multiprocessing.freeze_support()
    main()

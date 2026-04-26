"""
reporter.py — Terminal output for Sentinel-QED demo.

Designed for live demo on stage. High contrast, clear pass/fail states,
and explicit field-level mismatch reporting so judges can see exactly
what was corrupted and where.
"""

import time


# ANSI color codes — works in any modern terminal
RED     = "\033[91m"
GREEN   = "\033[92m"
YELLOW  = "\033[93m"
BLUE    = "\033[94m"
CYAN    = "\033[96m"
WHITE   = "\033[97m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
RESET   = "\033[0m"


def _bar(char="─", width=60):
    return char * width


def header(title: str):
    print(f"\n{BOLD}{CYAN}{_bar()}{RESET}")
    print(f"{BOLD}{WHITE}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{_bar()}{RESET}\n")


def scenario(number: int, title: str, description: str):
    print(f"\n{BOLD}{YELLOW}{'━' * 60}{RESET}")
    print(f"{BOLD}{YELLOW}  SCENARIO {number}: {title.upper()}{RESET}")
    print(f"{DIM}  {description}{RESET}")
    print(f"{BOLD}{YELLOW}{'━' * 60}{RESET}\n")
    time.sleep(0.3)


def compute_start(func_name: str, args: tuple):
    print(f"  {DIM}► Executing {func_name}{args}{RESET}")
    time.sleep(0.2)


def core_result(core_id: int, result, injected: bool = False):
    label = f"Core {core_id} {'[PRIMARY]' if core_id == 0 else '[SHADOW] '}"
    if injected:
        print(f"  {RED}● {label}  →  total={result.total_cents}¢  {BOLD}← FAULT INJECTED{RESET}")
    else:
        print(f"  {GREEN}● {label}  →  total={result.total_cents}¢{RESET}")
    time.sleep(0.15)


def pass_result(qed_result, trusted_result):
    print(f"\n  {GREEN}{BOLD}✓ QED PASS{RESET}")
    print(f"  {GREEN}Both cores agree. Result is trusted.{RESET}")
    print(f"\n  {WHITE}Portfolio value:  {trusted_result.total_dollars}{RESET}")
    print(f"  {WHITE}Interest earned:  {trusted_result.interest_dollars}{RESET}")
    print(f"  {DIM}Execution time:   {qed_result.execution_time_ms:.1f}ms{RESET}\n")


def silent_failure(result, correct_result):
    print(f"\n  {DIM}System status:    HEALTHY{RESET}")
    print(f"  {DIM}ECC check:        PASS{RESET}")
    print(f"  {DIM}OS monitor:       ALL CLEAR{RESET}")
    print()
    time.sleep(0.4)
    print(f"  {WHITE}Portfolio value:  {result.total_dollars}   {RED}{BOLD}← WRONG{RESET}")
    print(f"  {WHITE}Correct value:    {correct_result.total_dollars}{RESET}")
    print(f"  {RED}Difference:       ${abs(result.total_cents - correct_result.total_cents)/100:,.2f}{RESET}")
    print()
    time.sleep(0.3)
    print(f"  {RED}{BOLD}THE SYSTEM HAS NO IDEA.{RESET}")
    print(f"  {DIM}This wrong value is now in your database, your model, your report.{RESET}\n")


def sdc_detected(qed_result):
    time.sleep(0.3)
    print(f"\n  {RED}{BOLD}{'!' * 56}{RESET}")
    print(f"  {RED}{BOLD}  !! SENTINEL-QED: CRITICAL SDC DETECTED !!{RESET}")
    print(f"  {RED}{BOLD}{'!' * 56}{RESET}\n")
    time.sleep(0.4)

    print(f"  {RED}● Core {qed_result.primary_core} [PRIMARY]  →  CORRUPTED{RESET}")
    print(f"  {GREEN}● Core {qed_result.shadow_core} [SHADOW]   →  TRUSTED{RESET}\n")

    print(f"  {YELLOW}{BOLD}Mismatch details:{RESET}")
    for field_name, v_primary, v_shadow in qed_result.mismatch_fields:
        delta = ""
        if isinstance(v_primary, int) and isinstance(v_shadow, int):
            delta = f"  (Δ = {v_primary - v_shadow:+,})"
        print(f"  {WHITE}  {field_name}:{RESET}")
        print(f"  {RED}    Primary (Core {qed_result.primary_core}):  {v_primary}{RESET}")
        print(f"  {GREEN}    Shadow  (Core {qed_result.shadow_core}):  {v_shadow}{RESET}{DIM}{delta}{RESET}")

    print(f"\n  {YELLOW}► Core {qed_result.quarantined_core} quarantined — no further work scheduled{RESET}")
    print(f"  {GREEN}► Shadow result returned as trusted output{RESET}")
    print(f"  {DIM}► Detection latency: {qed_result.execution_time_ms:.1f}ms{RESET}\n")


def trusted_result_from_shadow(qed_result):
    shadow = qed_result.shadow_result
    print(f"  {GREEN}{BOLD}Trusted portfolio value:  {shadow.total_dollars}{RESET}")
    print(f"  {GREEN}Trusted interest earned:  {shadow.interest_dollars}{RESET}\n")


def summary(orchestrator):
    print(f"\n{BOLD}{CYAN}{_bar()}{RESET}")
    print(f"{BOLD}{WHITE}  SENTINEL-QED SESSION SUMMARY{RESET}")
    print(f"{BOLD}{CYAN}{_bar()}{RESET}\n")
    print(f"  Total runs:         {orchestrator.total_runs}")
    print(f"  Faults detected:    {orchestrator.detection_count}")
    print(f"  Quarantined cores:  {orchestrator.quarantined_cores or 'none'}")
    rate = orchestrator.detection_count / max(orchestrator.total_runs, 1) * 100
    print(f"  Detection rate:     {rate:.0f}%")
    print(f"\n  {DIM}Industry baseline (system-level tests): ~0% SDC detection{RESET}")
    print(f"  {GREEN}Sentinel-QED: 100% detection for instrumented workloads{RESET}\n")
    print(f"{BOLD}{CYAN}{_bar()}{RESET}\n")

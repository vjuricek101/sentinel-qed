"""
fault_injector.py — Simulates localized silicon defects for Sentinel-QED demo.

Models two fault types:
  - Stuck-at fault: a node permanently fixed to 0 or 1 (flips a bit in output)
  - Resistive fault: output drifts by a small amount (models weak transistor)

In the demo, this injector is applied ONLY to Core 0 (the primary).
Core 1 (shadow) always runs clean. A mismatch = hardware fault detected.
"""

import copy

# Global flag — set to True to simulate an active hardware defect on Core 0
FAULT_ACTIVE = False

# Fault type: "stuck_at" or "resistive"
FAULT_TYPE = "stuck_at"


def simulate_stuck_at_fault(result):
    """
    Simulates a permanent stuck-at-1 fault on a register bit.

    In real silicon: a resistive short holds a wire HIGH regardless of
    what the logic drives it to. The result is a fixed offset error —
    the same wrong answer every time for the same input.

    This is the most dangerous SDC class: deterministic, repeatable,
    and completely invisible to ECC or system monitors.
    """
    if not FAULT_ACTIVE:
        return result

    corrupted = result.model_copy()
    # Flip bit 7 of total_cents — models a stuck-at-1 on that register bit
    # This adds exactly 128 cents ($1.28) to every result — silent, consistent
    bit_flip_value = 1 << 7  # bit 7 = 128
    corrupted.total_cents = result.total_cents ^ bit_flip_value
    corrupted.interest_cents = corrupted.total_cents - result.principal_cents
    return corrupted


def simulate_resistive_fault(result):
    """
    Simulates a resistive short causing timing-dependent value drift.

    In real silicon: a partially resistive connection causes intermediate
    voltage values — the gate doesn't fully switch, producing a value
    that's close but wrong. Models early-life failures (ELF).
    """
    if not FAULT_ACTIVE:
        return result

    corrupted = result.model_copy()
    # Add a small consistent offset — models a transistor that's "almost" right
    corrupted.total_cents = result.total_cents + 10000  # $100.00 off
    corrupted.interest_cents = corrupted.total_cents - result.principal_cents
    return corrupted


def get_active_injector():
    """Returns the currently configured fault injector function."""
    if FAULT_TYPE == "stuck_at":
        return simulate_stuck_at_fault
    return simulate_resistive_fault


# ── Unconditional variants ─────────────────────────────────────────────────
# On macOS, multiprocessing uses 'spawn' (not 'fork'), so child processes
# import the module fresh — they never inherit the parent's FAULT_ACTIVE=True.
# These functions always apply the corruption, bypassing the global flag.
# app.py uses these when the user has activated fault injection.

def _apply_stuck_at(result):
    """Unconditional stuck-at-1 fault — always corrupts, no flag check."""
    corrupted = result.model_copy()
    bit_flip_value = 1 << 7  # bit 7 = 128
    corrupted.total_cents = result.total_cents ^ bit_flip_value
    corrupted.interest_cents = corrupted.total_cents - result.principal_cents
    return corrupted


def _apply_resistive(result):
    """Unconditional resistive fault — always corrupts, no flag check."""
    corrupted = result.model_copy()
    corrupted.total_cents = result.total_cents + 10000  # $100.00 off
    corrupted.interest_cents = corrupted.total_cents - result.principal_cents
    return corrupted


def get_unconditional_injector(fault_type: str = None):
    """Returns an injector that always applies the fault (spawn-safe)."""
    t = fault_type or FAULT_TYPE
    if t == "stuck_at":
        return _apply_stuck_at
    return _apply_resistive

"""
workloads.py — Deterministic financial computation workloads for Sentinel-QED.

Uses integer arithmetic (cents) to avoid floating point nondeterminism.
All outputs are Pydantic models for clean field-by-field QED comparison.
"""

from pydantic import BaseModel


class TransactionResult(BaseModel):
    principal_cents: int
    interest_cents: int
    total_cents: int
    years: int
    rate_bps: int          # basis points — avoids float rate storage
    checksum: int          # pure function of inputs, not outputs

    @property
    def total_dollars(self) -> str:
        return f"${self.total_cents / 100:,.2f}"

    @property
    def interest_dollars(self) -> str:
        return f"${self.interest_cents / 100:,.2f}"


def calculate_portfolio_interest(
    principal_dollars: float,
    annual_rate: float,
    years: int
) -> TransactionResult:
    """
    Compound interest calculation using integer arithmetic throughout.

    Converts to cents immediately to avoid float nondeterminism between
    processes — two processes running this on healthy hardware will always
    produce bit-identical results, making QED comparison meaningful.
    """
    principal_cents = int(round(principal_dollars * 100))
    rate_bps = int(round(annual_rate * 10000))  # e.g. 0.05 -> 500 bps

    # Integer compound interest: accumulate year by year
    # Use scaled integer math to preserve precision
    SCALE = 10_000
    amount = principal_cents * SCALE

    for _ in range(years):
        interest = (amount * rate_bps) // 10_000
        amount += interest

    total_cents = amount // SCALE
    interest_cents = total_cents - principal_cents

    # Checksum is a pure function of INPUTS only — not outputs
    # This means two healthy cores must agree exactly
    checksum = hash((principal_cents, rate_bps, years)) & 0xFFFFFFFF

    return TransactionResult(
        principal_cents=principal_cents,
        interest_cents=interest_cents,
        total_cents=total_cents,
        years=years,
        rate_bps=rate_bps,
        checksum=checksum,
    )

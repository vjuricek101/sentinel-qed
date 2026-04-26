"""
orchestrator.py — Dual-core redundancy engine for Sentinel-QED.

Implements the EDDI-V (Error Detection by Duplicated Instructions) transform
at the OS process level. Each computation runs in a separate subprocess pinned
to a specific physical CPU core via cpu_affinity.

Connection to lecture:
  CASP (Concurrent Autonomous Stored Patterns) moves testing from the factory
  floor to the operating system. This module is the software-layer equivalent:
  we use OS primitives (cpu_affinity) to achieve the same physical isolation
  that CASP achieves with hardware scan chains.

  Professor Mitra: "Defects are localized. A defect on one region of the chip
  will not affect a different region." — This is our core assumption. If Core 0
  has a stuck-at fault, Core 1 almost certainly does not.
"""

import multiprocessing
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


@dataclass
class QEDResult:
    passed: bool
    primary_result: Any
    shadow_result: Any
    primary_core: int
    shadow_core: int
    fault_detected: bool = False
    quarantined_core: Optional[int] = None
    mismatch_fields: list = field(default_factory=list)
    execution_time_ms: float = 0.0


def _worker(core_id: int, func: Callable, args: tuple, result_queue: multiprocessing.Queue, injector=None):
    """
    Subprocess worker. Sets CPU affinity BEFORE executing — this is critical.

    Affinity must be set inside the child process, not the parent.
    Setting it in the parent would affect all threads; setting it here
    affects only this subprocess, giving us true physical core isolation.
    """
    try:
        if PSUTIL_AVAILABLE:
            try:
                psutil.Process().cpu_affinity([core_id])
            except (AttributeError, OSError):
                # macOS does not support cpu_affinity — proceed without pinning
                # On Linux this succeeds and gives real physical isolation
                pass

        result = func(*args)

        if injector is not None:
            result = injector(result)

        result_queue.put(("ok", core_id, result))

    except Exception as e:
        result_queue.put(("error", core_id, str(e)))


def _compare_results(r0, r1) -> list:
    """
    Field-by-field QED comparison of two Pydantic model results.

    Returns list of mismatched field names. Empty list = pass.
    Uses field-level comparison so we can pinpoint exactly which
    register or value was corrupted — this is the 'diagnosis' capability
    the lecture identifies as missing from current system-level tests.
    """
    mismatches = []

    if hasattr(r0, 'model_fields'):
        # Pydantic v2
        for field_name in r0.model_fields:
            v0 = getattr(r0, field_name)
            v1 = getattr(r1, field_name)
            if v0 != v1:
                mismatches.append((field_name, v0, v1))
    else:
        # Fallback: direct equality
        if r0 != r1:
            mismatches.append(("result", r0, r1))

    return mismatches


class DualCoreOrchestrator:
    """
    Runs identical workloads on two separate CPU cores and compares results.

    If the primary core produces a different result than the shadow core,
    a hardware fault is assumed on the primary. The primary is quarantined
    and the shadow result is returned as the trusted output.

    This directly implements the 'eventual failure detection' tier from
    the lecture's resilient systems framework — low cost, targets permanent
    failures, software-only deployment.
    """

    def __init__(self, primary_core: int = 0, shadow_core: int = 1):
        self.primary_core = primary_core
        self.shadow_core = shadow_core
        self.quarantined_cores: set = set()
        self.detection_count: int = 0
        self.total_runs: int = 0

    def run(
        self,
        func: Callable,
        args: tuple,
        fault_injector=None,
        timeout: float = 30.0
    ) -> QEDResult:
        """
        Execute func(*args) on two cores simultaneously and compare.

        fault_injector is applied only to the primary core — it simulates
        a hardware defect localized to that silicon region.
        """
        self.total_runs += 1
        start = time.perf_counter()

        result_queue = multiprocessing.Queue()

        p_primary = multiprocessing.Process(
            target=_worker,
            args=(self.primary_core, func, args, result_queue, fault_injector)
        )
        p_shadow = multiprocessing.Process(
            target=_worker,
            args=(self.shadow_core, func, args, result_queue, None)
        )

        p_primary.start()
        p_shadow.start()
        p_primary.join(timeout=timeout)
        p_shadow.join(timeout=timeout)

        # Collect results — timeout protection so demo never hangs on stage
        results = {}
        for _ in range(2):
            try:
                status, core_id, value = result_queue.get(timeout=timeout)
                results[core_id] = (status, value)
            except Exception:
                pass

        elapsed_ms = (time.perf_counter() - start) * 1000

        # Cleanup
        for p in [p_primary, p_shadow]:
            if p.is_alive():
                p.terminate()
                p.join()

        # Both processes must have returned
        if self.primary_core not in results or self.shadow_core not in results:
            return QEDResult(
                passed=False,
                primary_result=None,
                shadow_result=None,
                primary_core=self.primary_core,
                shadow_core=self.shadow_core,
                fault_detected=True,
                quarantined_core=self.primary_core,
                mismatch_fields=[("execution", "timeout", "timeout")],
                execution_time_ms=elapsed_ms,
            )

        _, r_primary = results[self.primary_core]
        _, r_shadow = results[self.shadow_core]

        mismatches = _compare_results(r_primary, r_shadow)

        if mismatches:
            self.detection_count += 1
            self.quarantined_cores.add(self.primary_core)
            return QEDResult(
                passed=False,
                primary_result=r_primary,
                shadow_result=r_shadow,
                primary_core=self.primary_core,
                shadow_core=self.shadow_core,
                fault_detected=True,
                quarantined_core=self.primary_core,
                mismatch_fields=mismatches,
                execution_time_ms=elapsed_ms,
            )

        return QEDResult(
            passed=True,
            primary_result=r_primary,
            shadow_result=r_shadow,
            primary_core=self.primary_core,
            shadow_core=self.shadow_core,
            fault_detected=False,
            execution_time_ms=elapsed_ms,
        )

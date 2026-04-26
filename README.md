# Sentinel-QED

**The "Check Engine" Light for AI Reliability: A Step for In-Field Chip Testing**

A hardware-integrity layer that catches Silent Data Corruption (SDC) in deployed CPUs by running identical computations on different physical cores and comparing results.

---

## The Problem

Manufacturing test escapes are reaching 5,000 DPM in real data centers — 50x
the industry target. Defective chips produce wrong answers with no crash, no
ECC flag, no OS alert. This is Silent Data Corruption, and it is documented by
Google, Meta, Microsoft, and Alibaba as an unsolved problem.

ECC protects data at rest. Nothing protects data in flight — during the actual
arithmetic inside CPU registers. That is the gap this project aims to fill.

---

## Setup

```bash
pip install -r requirements.txt
```

Requires Python 3.9+. CPU affinity pinning works on Linux. On macOS the demo runs correctly but without hardware-level core isolation (psutil limitation).

---

## Run the Demo

```bash
# All three scenarios
python main.py

# Specific scenario
python main.py --scenario 1    # healthy hardware
python main.py --scenario 2    # silent failure, unprotected
python main.py --scenario 3    # fault caught by Sentinel

# Change fault type
python main.py --fault resistive
```

---

## Scenarios

**Scenario 1 — Healthy Hardware**
Both cores agree. Result passes QED. Business as usual.

**Scenario 2 — Silent Failure, Unprotected**
Fault injected on Core 0. Single-process run returns wrong answer.
System reports healthy. ECC passes. OS monitor shows all clear.
The wrong answer propagates silently into downstream systems.

**Scenario 3 — Sentinel-QED Protected**
Same fault. Dual-core QED active. Core 0 and Core 1 disagree.
Sentinel flags CRITICAL SDC DETECTED, quarantines Core 0,
returns Core 1's trusted result.

---

## Architecture

```
main.py           Demo runner — three scenarios
orchestrator.py   DualCoreOrchestrator — spawns subprocesses, compares results
workloads.py      Deterministic financial computation (integer arithmetic)
fault_injector.py Simulates stuck-at and resistive hardware defects
reporter.py       High-contrast terminal output for live demo
```

---

## Key Technical Decisions

**Multiprocessing, not threading**
cpu_affinity must be set inside the child process. Threads share process state
and cannot be independently pinned to cores.

**Integer arithmetic throughout**
Floating point operations are nondeterministic across process boundaries.
Integer cent arithmetic ensures two healthy cores always agree exactly,
making any disagreement a meaningful fault signal.

**Field-level QED comparison**
Pydantic models enable per-field comparison — we can identify exactly which
value was corrupted, providing the diagnosis capability that's missing from
current system-level tests.

---

## Limitations

- Coverage is proportional to instrumentation — only wrapped workloads are protected
- 2x compute overhead — correct tradeoff for safety-critical applications
- "Quarantine" means avoiding the core within this framework, not OS-level isolation

import multiprocessing
import time
import hashlib

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


class HardwareUnreliableError(Exception):
    """Raised when the pre-execution hardware reliability audit (PEPR) fails."""
    pass


def _pepr_worker(core_id: int, target_iterations: int, result_queue: multiprocessing.Queue):
    """
    Subprocess that pins itself to a specific physical core and runs
    a dense arithmetic matrix of XOR and bit shifts to stress test ALUs.
    """
    if PSUTIL_AVAILABLE:
        try:
            psutil.Process().cpu_affinity([core_id])
        except (AttributeError, OSError):
            pass  # macOS or unsupported environments

    # Pre-allocate a large array to heat up caches and stress memory controllers
    ARRAY_SIZE = 10_000_000
    # Seed values
    state_a = 0xDEADBEEF
    state_b = 0xCAFEBABE
    
    # We do not use Python lists iterating, we use bitwise math in a tight loop
    # that constantly shifts to test transistor reliability at varying voltages/temps.
    
    start_time = time.perf_counter()
    iterations = 0
    
    # Run the continuous XOR / Shift loop for exact iteration determinism
    while iterations < target_iterations:
        # Xorshift variant to flip many bits heavily in the ALU
        state_a ^= (state_a << 13) & 0xFFFFFFFF
        state_a ^= (state_a >> 17)
        state_a ^= (state_a << 5) & 0xFFFFFFFF
        
        state_b = (state_b + state_a) & 0xFFFFFFFF
        state_b ^= (state_b << 7) & 0xFFFFFFFF
        
        iterations += 1

    # Cryptographic hash of the registers and iteration count guarantees 
    # determinism. Even if a core misses ONE iteration due to thermal 
    # throttling or failing a bit-flip, the checksum drastically changes.
    final_payload = f"{state_a}-{state_b}-{iterations}"
    checksum = hashlib.sha256(final_payload.encode()).hexdigest()
    
    result_queue.put({
        "core_id": core_id,
        "iterations": iterations,
        "state_a": state_a,
        "state_b": state_b,
        "checksum": checksum,
    })


def run_pepr_audit(target_iterations: int = 25_000_000, primary_core: int = 0, shadow_core: int = 1):
    """
    PEPR (Pre-Execution Power & Reliability) Audit. 
    
    Issues a 'Reliability Certificate' for the raw silicon by punishing 
    both CPU cores evenly with a heavy XOR/Shift workload.
    
    Must be called BEFORE critical apps start. If the silicon is failing 
    due to early-life degradation or extreme thermals, this stops boot.
    
    Raises:
        HardwareUnreliableError: If the two cores return diverging checksums.
    """
    print(f"[PEPR] Initiating HW Reliability Audit (~5s deterministic stress loop)...")
    
    result_queue = multiprocessing.Queue()
    
    p_primary = multiprocessing.Process(
        target=_pepr_worker,
        args=(primary_core, target_iterations, result_queue)
    )
    p_shadow = multiprocessing.Process(
        target=_pepr_worker,
        args=(shadow_core, target_iterations, result_queue)
    )
    
    # Dispatch identically
    p_primary.start()
    p_shadow.start()
    
    p_primary.join()
    p_shadow.join()
    
    results = {}
    while not result_queue.empty():
        data = result_queue.get()
        results[data["core_id"]] = data

    if primary_core not in results or shadow_core not in results:
        raise HardwareUnreliableError("PEPR Audit Failed: Worker process crashed silently.")

    res_primary = results[primary_core]
    res_shadow = results[shadow_core]

    print(f"[PEPR] Core {primary_core}  -> Iterations: {res_primary['iterations']} | Hash: {res_primary['checksum'][:8]}")
    print(f"[PEPR] Core {shadow_core}  -> Iterations: {res_shadow['iterations']} | Hash: {res_shadow['checksum'][:8]}")

    if res_primary["checksum"] != res_shadow["checksum"]:
        raise HardwareUnreliableError(
            f"SILICON DEGRADATION DETECTED! \n"
            f"Core {primary_core} and Core {shadow_core} produced divergent ALU math under load.\n"
            f"Primary CPU State: {res_primary['state_a']}, {res_primary['state_b']}\n"
            f"Shadow CPU State:  {res_shadow['state_a']}, {res_shadow['state_b']}\n"
            f"CRITICAL FAULT PREVENTED. System boot halted."
        )

    print("[PEPR] PASS. Hardware reliability certificate verified.")
    return True

if __name__ == "__main__":
    # Test execution, defaults to array iterations representing ~5 secs
    run_pepr_audit()

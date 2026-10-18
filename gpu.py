"""
GPU memory readings from nvidia-smi.

Used to show that the LLM really has left the GPU before Blender renders.
The 8 GB card can't comfortably hold the ~5.6 GB model and a render at once.
Readings are for the whole card (Windows doesn't report per-process GPU
memory), so they include the desktop's own few hundred MiB.
"""

import subprocess
import threading
import time


def memory_used_mib():
    """GPU memory in use right now, in MiB, or None if nvidia-smi isn't available."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        return int(result.stdout.split()[0]) if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, IndexError, ValueError):
        return None


def wait_for_drop(before_mib, drop_mib=1000, timeout=10.0):
    """Poll until memory is at least drop_mib below before_mib, or timeout.

    Returns the last reading. Memory can take a moment to come back after the
    model is unloaded, while its process shuts down.
    """
    deadline = time.monotonic() + timeout
    reading = memory_used_mib()
    while reading is not None and before_mib is not None and reading > before_mib - drop_mib:
        if time.monotonic() > deadline:
            break
        time.sleep(0.25)
        reading = memory_used_mib()
    return reading


class PeakMemory:
    """Samples GPU memory in the background; .peak holds the highest reading.

        with PeakMemory() as gpu:
            render()
        print(gpu.peak)
    """

    def __init__(self, interval=0.25):
        self.interval = interval
        self.peak = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self):
        while not self._stop.is_set():
            reading = memory_used_mib()
            if reading is not None and (self.peak is None or reading > self.peak):
                self.peak = reading
            self._stop.wait(self.interval)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()

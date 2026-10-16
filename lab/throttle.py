"""throttle.py — CPU/GPU/temp/battery/idle governor.

Goal: the owner never notices the lab running.
All thresholds from config.yaml.
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import time
from datetime import datetime
from typing import Optional

import psutil

logger = logging.getLogger(__name__)

_IS_WINDOWS = platform.system() == "Windows"


# ---------------------------------------------------------------------------
# Throttle configuration
# ---------------------------------------------------------------------------

class Throttle:
    """Rate-limit the main loop based on system state."""

    def __init__(self, config) -> None:
        self.cfg = config
        self._set_nice()
        self._set_thread_env()

    def _set_nice(self) -> None:
        """Lower process priority."""
        try:
            p = psutil.Process()
            if _IS_WINDOWS:
                p.nice(psutil.IDLE_PRIORITY_CLASS)
            else:
                p.nice(19)
            logger.debug("Process nice set.")
        except Exception as exc:
            logger.debug("Could not set nice: %s", exc)

    def _set_thread_env(self) -> None:
        """Limit thread counts for numpy/pandas."""
        n = str(self.cfg.worker_threads)
        for var in ["OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"]:
            os.environ.setdefault(var, n)

    # --- Checks ---

    def _cpu_ok(self) -> bool:
        cpu = psutil.cpu_percent(interval=0.5)
        if cpu > self.cfg.max_cpu_percent:
            logger.debug("CPU %.0f%% > limit %.0f%%.", cpu, self.cfg.max_cpu_percent)
            return False
        return True

    def _temp_ok(self) -> bool:
        try:
            temps = psutil.sensors_temperatures()
            if not temps:
                return True
            max_temp = max(
                t.current
                for readings in temps.values()
                for t in readings
            )
            if max_temp > self.cfg.max_temp_c:
                logger.debug("Temp %.0f°C > limit %.0f°C.", max_temp, self.cfg.max_temp_c)
                return False
        except AttributeError:
            # sensors_temperatures not available on Windows
            try:
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    gpu_temp = float(result.stdout.strip())
                    if gpu_temp > self.cfg.max_temp_c:
                        logger.debug("GPU temp %.0f°C > limit.", gpu_temp)
                        return False
            except Exception:
                pass
        except Exception:
            pass
        return True

    def _battery_ok(self) -> bool:
        battery = psutil.sensors_battery()
        if battery is None:
            return True  # No battery (desktop)
        if self.cfg.require_ac_power and not battery.power_plugged:
            logger.debug("On battery — pausing.")
            return False
        if not battery.power_plugged and battery.percent < self.cfg.min_battery_percent:
            logger.debug("Battery %.0f%% < %.0f%% — pausing.", battery.percent, self.cfg.min_battery_percent)
            return False
        return True

    def _active_hours_ok(self) -> bool:
        active_hours = self.cfg.active_hours
        if not active_hours:
            return True
        now_t = datetime.now().strftime("%H:%M")
        start_s, end_s = active_hours.split("-")
        if start_s <= end_s:
            return start_s <= now_t <= end_s
        else:  # crosses midnight
            return now_t >= start_s or now_t <= end_s

    def _process_blocklist_ok(self) -> bool:
        blocklist = self.cfg.pause_if_processes
        if not blocklist:
            return True
        running = [p.name().lower() for p in psutil.process_iter(["name"])]
        for proc in blocklist:
            if proc.lower() in running:
                logger.debug("Blocked process '%s' is running.", proc)
                return False
        return True

    def ok(self) -> bool:
        """True if conditions allow the loop to proceed."""
        return (
            self._cpu_ok()
            and self._temp_ok()
            and self._battery_ok()
            and self._active_hours_ok()
            and self._process_blocklist_ok()
        )

    def wait_until_ok(self, max_wait_s: int = 300) -> None:
        """Block until conditions are ok, sleeping duty_sleep_seconds each iteration."""
        waited = 0
        while not self.ok():
            sleep_s = self.cfg.duty_sleep_seconds
            time.sleep(sleep_s)
            waited += sleep_s
            if waited > max_wait_s:
                logger.warning("Throttle: waited %ds. Proceeding anyway.", waited)
                return

    def duty_sleep(self) -> None:
        """Sleep the duty-cycle gap after each job."""
        time.sleep(self.cfg.duty_sleep_seconds)

    def get_status(self) -> dict:
        """Return current system status dict."""
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        battery = psutil.sensors_battery()

        gpu_temp: Optional[float] = None
        gpu_vram_free: Optional[int] = None
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=temperature.gpu,memory.free",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split(",")
                gpu_temp = float(parts[0].strip())
                gpu_vram_free = int(parts[1].strip())
        except Exception:
            pass

        return {
            "cpu_pct": cpu,
            "mem_used_mb": round(mem.used / 1024 / 1024, 1),
            "battery_pct": battery.percent if battery else None,
            "plugged": battery.power_plugged if battery else None,
            "gpu_temp_c": gpu_temp,
            "gpu_vram_free_mb": gpu_vram_free,
            "throttle_ok": self.ok(),
        }

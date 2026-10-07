"""
Persistent State Manager for TP-Link Easy Smart Switch Gateway.
Maintains per-switch boot times, reboot detection, and state persistence
across container restarts and updates.
"""

import json
import logging
import os
import time
from typing import Dict, Any

logger = logging.getLogger(__name__)

STATE_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "gateway_state.json")


class StateManager:
    """Manages persistent gateway state to prevent uptime resets and track device reboots."""

    def __init__(self, state_file: str = STATE_FILE_PATH):
        self.state_file = state_file
        self.switch_boot_times: Dict[int, float] = {}
        self.switch_last_pkts: Dict[int, int] = {}
        self._load()

    def _load(self):
        """Load persisted state from disk if available."""
        if not os.path.exists(self.state_file):
            return
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Keys in JSON are strings, convert to int
            for k, v in data.get("boot_times", {}).items():
                self.switch_boot_times[int(k)] = float(v)
            for k, v in data.get("last_pkts", {}).items():
                self.switch_last_pkts[int(k)] = int(v)
            logger.info("Loaded persistent state from %s (%d switches)", self.state_file, len(self.switch_boot_times))
        except Exception as e:
            logger.warning("Failed to load state from %s: %s", self.state_file, e)

    def save(self):
        """Save state to disk atomically using a temporary file."""
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            temp_file = f"{self.state_file}.tmp"
            data = {
                "saved_at": time.time(),
                "boot_times": {str(k): v for k, v in self.switch_boot_times.items()},
                "last_pkts": {str(k): v for k, v in self.switch_last_pkts.items()}
            }
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(temp_file, self.state_file)
        except Exception as e:
            logger.warning("Failed to save state to %s: %s", self.state_file, e)

    def get_boot_time(self, switch_id: int) -> float:
        """Get or initialize boot time for a specific switch."""
        if switch_id not in self.switch_boot_times:
            self.switch_boot_times[switch_id] = time.time()
            self.save()
        return self.switch_boot_times[switch_id]

    def record_packets_and_check_reboot(self, switch_id: int, total_pkts: int) -> bool:
        """
        Check if the physical switch rebooted based on packet counter reset.
        Returns True if a physical reboot was detected.
        """
        reboot_detected = False
        last_pkts = self.switch_last_pkts.get(switch_id, 0)

        # If counter drops significantly from a substantial value, the hardware rebooted
        if last_pkts > 1000 and total_pkts < 100:
            logger.warning(
                "[Switch %d] Physical reboot detected (Packets dropped from %d to %d). Resetting uptime.",
                switch_id,
                last_pkts,
                total_pkts
            )
            self.switch_boot_times[switch_id] = time.time()
            reboot_detected = True

        self.switch_last_pkts[switch_id] = total_pkts
        self.save()
        return reboot_detected

"""
NVOC - Privileged Controller Proxy

This module provides a controller interface that uses pkexec to run
privileged operations via the helper script, allowing the GUI to run
as a normal user.

Read operations (get_*) are done directly via NVML (no root needed).
Write operations (set_*) are done via pkexec helper.
"""

import subprocess
import json
import logging
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass

from .nvml_controller import (
    NVMLController, 
    NVMLError, 
    GPUInfo, 
    GPUStats, 
    PowerLimits, 
    ClockOffsets,
    SafetyLimits
)

logger = logging.getLogger(__name__)

# Find the helper script location
HELPER_SCRIPT = Path(__file__).parent / "helper.py"


class PrivilegedControllerError(Exception):
    """Error from privileged operations."""
    pass


class PrivilegedController:
    """
    Controller that uses pkexec for privileged operations.
    
    Read operations use direct NVML (no root needed).
    Write operations call the helper script via pkexec.
    """
    
    def __init__(self, gpu_index: int = 0):
        self._gpu_index = gpu_index
        self._reader: Optional[NVMLController] = None
        self._pkexec_path = shutil.which("pkexec")
        
        if not self._pkexec_path:
            logger.warning("pkexec not found, privileged operations may fail")
    
    def initialize(self) -> None:
        """Initialize the controller."""
        # Initialize reader for non-privileged operations
        self._reader = NVMLController(self._gpu_index)
        self._reader.initialize()
    
    def shutdown(self) -> None:
        """Shutdown the controller."""
        if self._reader:
            self._reader.shutdown()
            self._reader = None
    
    def __enter__(self):
        self.initialize()
        return self
    
    def __exit__(self, *args):
        self.shutdown()
        return False
    
    def _run_helper(self, *args) -> Dict[str, Any]:
        """
        Run the helper script via pkexec.
        
        Returns the parsed JSON response.
        Raises PrivilegedControllerError on failure.
        """
        if not HELPER_SCRIPT.exists():
            raise PrivilegedControllerError(f"Helper script not found: {HELPER_SCRIPT}")
        
        cmd = [
            self._pkexec_path or "pkexec",
            "python3",
            str(HELPER_SCRIPT),
            *[str(a) for a in args]
        ]
        
        logger.debug(f"Running helper: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0 and not result.stdout:
                # pkexec was cancelled or failed before running helper
                if "dismissed" in result.stderr.lower() or result.returncode == 126:
                    raise PrivilegedControllerError("Authentication cancelled")
                raise PrivilegedControllerError(
                    result.stderr or f"Helper failed with code {result.returncode}"
                )
            
            # Parse JSON response
            try:
                response = json.loads(result.stdout)
            except json.JSONDecodeError:
                raise PrivilegedControllerError(f"Invalid helper response: {result.stdout}")
            
            if not response.get("success"):
                raise PrivilegedControllerError(response.get("error", "Unknown error"))
            
            return response
            
        except subprocess.TimeoutExpired:
            raise PrivilegedControllerError("Operation timed out")
        except FileNotFoundError:
            raise PrivilegedControllerError("pkexec not found - install polkit")
    
    # =========================================================================
    # Read operations (no root needed, direct NVML)
    # =========================================================================
    
    def get_gpu_info(self) -> GPUInfo:
        """Get GPU information (no root needed)."""
        if not self._reader:
            raise PrivilegedControllerError("Controller not initialized")
        return self._reader.get_gpu_info()
    
    def get_gpu_stats(self) -> GPUStats:
        """Get GPU stats (no root needed)."""
        if not self._reader:
            raise PrivilegedControllerError("Controller not initialized")
        return self._reader.get_gpu_stats()
    
    def get_power_limits(self) -> PowerLimits:
        """Get power limits (no root needed)."""
        if not self._reader:
            raise PrivilegedControllerError("Controller not initialized")
        return self._reader.get_power_limits()
    
    def get_clock_offsets(self) -> ClockOffsets:
        """Get clock offsets (no root needed)."""
        if not self._reader:
            raise PrivilegedControllerError("Controller not initialized")
        return self._reader.get_clock_offsets()
    
    def get_fan_count(self) -> int:
        """Get fan count (no root needed)."""
        if not self._reader:
            raise PrivilegedControllerError("Controller not initialized")
        return self._reader.get_fan_count()
    
    def get_fan_speed(self, fan_index: int = 0) -> int:
        """Get fan speed (no root needed)."""
        if not self._reader:
            raise PrivilegedControllerError("Controller not initialized")
        return self._reader.get_fan_speed(fan_index)
    
    def reset_peak_clock(self) -> None:
        """Reset the peak clock counter (no root needed)."""
        if not self._reader:
            raise PrivilegedControllerError("Controller not initialized")
        self._reader.reset_peak_clock()
    
    # =========================================================================
    # Write operations (via pkexec helper)
    # =========================================================================
    
    def set_power_limit(self, watts: float) -> None:
        """Set power limit (requires authentication)."""
        self._run_helper("set-power-limit", watts)
        logger.info(f"Power limit set to {watts}W")
    
    def set_clock_offsets(
        self,
        core_offset_mhz: Optional[int] = None,
        memory_offset_mhz: Optional[int] = None
    ) -> Tuple[int, int]:
        """Set clock offsets (requires authentication)."""
        # Get current values if not specified
        if core_offset_mhz is None or memory_offset_mhz is None:
            current = self.get_clock_offsets()
            if core_offset_mhz is None:
                core_offset_mhz = current.core_offset_mhz
            if memory_offset_mhz is None:
                memory_offset_mhz = current.memory_offset_mhz
        
        response = self._run_helper("set-clock-offsets", core_offset_mhz, memory_offset_mhz)
        
        actual_core = response.get("core_offset", core_offset_mhz)
        actual_mem = response.get("memory_offset", memory_offset_mhz)
        
        logger.info(f"Clock offsets set to core:{actual_core}MHz, mem:{actual_mem}MHz")
        return (actual_core, actual_mem)
    
    def reset_clock_offsets(self) -> None:
        """Reset clock offsets to zero (requires authentication)."""
        self._run_helper("reset-clocks")
        logger.info("Clock offsets reset to stock")
    
    def set_fan_speed(self, speed_percent: int, fan_index: int = 0) -> int:
        """Set fan speed (requires authentication)."""
        response = self._run_helper("set-fan-speed", speed_percent, fan_index)
        actual = response.get("fan_speed", speed_percent)
        logger.info(f"Fan {fan_index} set to {actual}%")
        return actual
    
    def set_fan_auto(self, fan_index: int = 0) -> None:
        """Set fan to auto mode (requires authentication)."""
        self._run_helper("set-fan-auto", fan_index)
        logger.info(f"Fan {fan_index} set to auto")
    
    def set_all_fans_speed(self, speed_percent: int) -> None:
        """Set all fans to the same speed."""
        fan_count = self.get_fan_count()
        for i in range(max(1, fan_count)):
            self.set_fan_speed(speed_percent, fan_index=i)
    
    def set_all_fans_auto(self) -> None:
        """Set all fans to automatic control."""
        fan_count = self.get_fan_count()
        for i in range(max(1, fan_count)):
            self.set_fan_auto(fan_index=i)
    
    def apply_profile(self, profile_dict: Dict[str, Any]) -> None:
        """Apply a complete profile (requires authentication)."""
        self._run_helper("apply-profile", json.dumps(profile_dict))
        logger.info("Profile applied")
    
    # =========================================================================
    # Utility methods
    # =========================================================================
    
    def get_all_settings(self) -> Dict[str, Any]:
        """Get all current settings."""
        power = self.get_power_limits()
        clocks = self.get_clock_offsets()
        
        return {
            'power_limit_watts': power.current_watts,
            'core_clock_offset_mhz': clocks.core_offset_mhz,
            'memory_clock_offset_mhz': clocks.memory_offset_mhz,
        }
    
    def apply_settings(self, settings: Dict[str, Any]) -> None:
        """Apply settings dictionary."""
        self.apply_profile(settings)
    
    # =========================================================================
    # Advanced Overclocking
    # =========================================================================
    
    def set_gpu_locked_clocks(self, min_mhz: int, max_mhz: int) -> None:
        """Set locked clocks (requires authentication)."""
        self._run_helper("set-locked-clocks", min_mhz, max_mhz)
        logger.info(f"Locked clocks set to {min_mhz}-{max_mhz} MHz")

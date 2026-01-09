#!/usr/bin/env python3
"""
NVOC Privileged Helper

This script runs as root via pkexec to perform privileged GPU operations.
The main GUI calls this helper for operations that require root access.

Usage:
    pkexec nvoc-helper <command> [args...]

Commands:
    status                  - Get GPU status (JSON output)
    set-power-limit <watts> - Set power limit
    set-clock-offsets <core> <mem> - Set clock offsets
    set-fan-speed <percent> [fan_idx] - Set fan speed
    set-fan-auto [fan_idx]  - Set fan to auto mode
    apply-profile <json>    - Apply a complete profile
"""

import sys
import json
import logging
from typing import Dict, Any

# Add parent directory to path for imports
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nvoc.nvml_controller import NVMLController, SafetyLimits

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def output_json(data: Dict[str, Any]) -> None:
    """Output JSON result to stdout."""
    print(json.dumps(data))


def output_error(message: str) -> None:
    """Output error as JSON."""
    output_json({"success": False, "error": message})
    sys.exit(1)


def output_success(data: Dict[str, Any] = None) -> None:
    """Output success result."""
    result = {"success": True}
    if data:
        result.update(data)
    output_json(result)


def cmd_status() -> None:
    """Get GPU status."""
    with NVMLController() as ctrl:
        info = ctrl.get_gpu_info()
        stats = ctrl.get_gpu_stats()
        power = ctrl.get_power_limits()
        offsets = ctrl.get_clock_offsets()
        
        output_success({
            "gpu": {
                "name": info.name,
                "driver": info.driver_version,
                "vbios": info.vbios_version,
                "vram_total_mb": info.memory_total_mb,
            },
            "stats": {
                "temperature": stats.temperature_celsius,
                "fan_speed": stats.fan_speed_percent,
                "power_draw": stats.power_draw_watts,
                "power_limit": stats.power_limit_watts,
                "core_clock": stats.core_clock_mhz,
                "memory_clock": stats.memory_clock_mhz,
                "gpu_util": stats.gpu_utilization_percent,
                "mem_util": stats.memory_utilization_percent,
                "vram_used_mb": stats.memory_used_mb,
                "effective_core_clock": stats.effective_core_clock_mhz,
                "effective_memory_clock": stats.effective_memory_clock_mhz,
                "throttle_reasons": stats.throttle_reasons,
                "peak_core_clock": stats.peak_core_clock_mhz,
                "avg_core_clock": stats.avg_core_clock_mhz,
                "pcie_gen": stats.pcie_gen,
                "pcie_width": stats.pcie_width,
                "pcie_gen_max": stats.pcie_gen_max,
                "pcie_width_max": stats.pcie_width_max,
                "thermal_threshold": stats.thermal_threshold_celsius,
                "thermal_headroom": stats.thermal_headroom_celsius,
                "power_limit_active": stats.power_limit_active,
                "memory_errors": stats.memory_errors,
            },
            "power_limits": {
                "current": power.current_watts,
                "min": power.min_watts,
                "max": power.max_watts,
                "default": power.default_watts,
            },
            "offsets": {
                "core": offsets.core_offset_mhz,
                "memory": offsets.memory_offset_mhz,
            },
            "safety_limits": {
                "max_core_offset": SafetyLimits.MAX_CORE_CLOCK_OFFSET_MHZ,
                "max_memory_offset": SafetyLimits.MAX_MEMORY_CLOCK_OFFSET_MHZ,
                "min_fan_speed": SafetyLimits.MIN_FAN_SPEED_PERCENT,
            }
        })


def cmd_set_power_limit(watts: float) -> None:
    """Set power limit."""
    with NVMLController() as ctrl:
        ctrl.set_power_limit(watts)
        output_success({"power_limit": watts})


def cmd_set_clock_offsets(core: int, mem: int) -> None:
    """Set clock offsets."""
    with NVMLController() as ctrl:
        actual_core, actual_mem = ctrl.set_clock_offsets(
            core_offset_mhz=core,
            memory_offset_mhz=mem
        )
        output_success({
            "core_offset": actual_core,
            "memory_offset": actual_mem
        })


def cmd_set_locked_clocks(min_mhz: int, max_mhz: int) -> None:
    """Set locked clocks."""
    with NVMLController() as ctrl:
        ctrl.set_gpu_locked_clocks(min_mhz, max_mhz)
        output_success({"min_mhz": min_mhz, "max_mhz": max_mhz})


def cmd_reset_clocks() -> None:
    """Reset clock offsets to zero."""
    with NVMLController() as ctrl:
        ctrl.reset_clock_offsets()
        output_success()


def cmd_set_fan_speed(percent: int, fan_idx: int = 0) -> None:
    """Set fan speed."""
    with NVMLController() as ctrl:
        actual = ctrl.set_fan_speed(percent, fan_index=fan_idx)
        output_success({"fan_speed": actual, "fan_index": fan_idx})


def cmd_set_fan_auto(fan_idx: int = 0) -> None:
    """Set fan to auto mode."""
    with NVMLController() as ctrl:
        ctrl.set_fan_auto(fan_index=fan_idx)
        output_success({"fan_index": fan_idx, "mode": "auto"})


def cmd_apply_profile(profile_json: str) -> None:
    """Apply a complete profile from JSON."""
    try:
        profile = json.loads(profile_json)
    except json.JSONDecodeError as e:
        output_error(f"Invalid JSON: {e}")
        return
    
    with NVMLController() as ctrl:
        results = {}
        
        # Apply power limit
        if "power_limit_watts" in profile and profile["power_limit_watts"] is not None:
            ctrl.set_power_limit(profile["power_limit_watts"])
            results["power_limit"] = profile["power_limit_watts"]
        
        # Apply clock offsets
        core = profile.get("core_clock_offset_mhz")
        mem = profile.get("memory_clock_offset_mhz")
        if core is not None or mem is not None:
            actual_core, actual_mem = ctrl.set_clock_offsets(
                core_offset_mhz=core,
                memory_offset_mhz=mem
            )
            results["core_offset"] = actual_core
            results["memory_offset"] = actual_mem
        
        # Apply fan settings
        fan_mode = profile.get("fan_mode", "auto")
        if fan_mode == "auto":
            ctrl.set_all_fans_auto()
            results["fan_mode"] = "auto"
        elif fan_mode == "manual":
            speed = profile.get("fan_speed_percent", 50)
            ctrl.set_all_fans_speed(speed)
            results["fan_mode"] = "manual"
            results["fan_speed"] = speed
        
        output_success(results)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    
    command = sys.argv[1]
    
    try:
        if command == "status":
            cmd_status()
        
        elif command == "set-power-limit":
            if len(sys.argv) < 3:
                output_error("Usage: set-power-limit <watts>")
                return 1
            watts = float(sys.argv[2])
            cmd_set_power_limit(watts)
        
        elif command == "set-clock-offsets":
            if len(sys.argv) < 4:
                output_error("Usage: set-clock-offsets <core_mhz> <mem_mhz>")
                return 1
            core = int(sys.argv[2])
            mem = int(sys.argv[3])
            cmd_set_clock_offsets(core, mem)
            
        elif command == "set-locked-clocks":
            if len(sys.argv) < 4:
                output_error("Usage: set-locked-clocks <min_mhz> <max_mhz>")
                return 1
            min_mhz = int(sys.argv[2])
            max_mhz = int(sys.argv[3])
            cmd_set_locked_clocks(min_mhz, max_mhz)
        
        elif command == "reset-clocks":
            cmd_reset_clocks()
        
        elif command == "set-fan-speed":
            if len(sys.argv) < 3:
                output_error("Usage: set-fan-speed <percent> [fan_idx]")
                return 1
            percent = int(sys.argv[2])
            fan_idx = int(sys.argv[3]) if len(sys.argv) > 3 else 0
            cmd_set_fan_speed(percent, fan_idx)
        
        elif command == "set-fan-auto":
            fan_idx = int(sys.argv[2]) if len(sys.argv) > 2 else 0
            cmd_set_fan_auto(fan_idx)
        
        elif command == "apply-profile":
            if len(sys.argv) < 3:
                output_error("Usage: apply-profile <json>")
                return 1
            cmd_apply_profile(sys.argv[2])
        
        elif command == "apply-boot-profile":
            # Apply boot profile from config (for systemd service)
            from nvoc.config import get_config, set_applying_flag, clear_applying_flag, check_crash_recovery
            from nvoc.profiles import ProfileManager
            
            # Check for crash recovery
            if check_crash_recovery():
                output_success({"action": "boot-apply", "status": "skipped", "reason": "crash_recovery"})
                return 0
            
            config = get_config()
            if not config.boot_profile_name:
                output_success({"action": "boot-apply", "status": "skipped", "reason": "no_boot_profile"})
                return 0
            
            # Set crash-safe flag
            set_applying_flag()
            try:
                profile_manager = ProfileManager()
                profiles = profile_manager.list_profiles()
                profile = next((p for p in profiles if p.name == config.boot_profile_name), None)
                
                if profile is None:
                    clear_applying_flag()
                    output_error(f"Boot profile '{config.boot_profile_name}' not found")
                    return 1
                
                # Apply the profile
                with NVMLController() as controller:
                    if profile.power_limit_watts:
                        controller.set_power_limit(profile.power_limit_watts)
                    controller.set_clock_offsets(profile.core_offset_mhz, profile.memory_offset_mhz)
                    if profile.max_clock_mhz:
                        controller.set_gpu_locked_clocks(0, profile.max_clock_mhz)
                
                clear_applying_flag()
                output_success({"action": "boot-apply", "status": "success", "profile": config.boot_profile_name})
            except Exception as e:
                clear_applying_flag()
                output_error(f"Failed to apply boot profile: {e}")
                return 1
        
        elif command == "list-profiles":
            # List all available profiles (Phase 18 CLI)
            from nvoc.profiles import ProfileManager
            pm = ProfileManager()
            profiles = pm.list_profiles()
            output_success({"profiles": profiles})
        
        elif command == "list-gpus":
            # List all GPUs in system (Phase 18 multi-GPU)
            import pynvml
            try:
                pynvml.nvmlInit()
                count = pynvml.nvmlDeviceGetCount()
                gpus = []
                for i in range(count):
                    handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                    name = pynvml.nvmlDeviceGetName(handle)
                    gpus.append({"index": i, "name": name})
                pynvml.nvmlShutdown()
                output_success({"gpu_count": count, "gpus": gpus})
            except Exception as e:
                output_error(f"Failed to enumerate GPUs: {e}")
                return 1
        
        elif command == "help":
            # Print help message
            help_text = """NVOC CLI Commands:
  status                      - Get GPU status
  list-gpus                   - List all GPUs
  list-profiles               - List saved profiles
  set-power-limit <watts>     - Set power limit
  set-clock-offsets <core> <mem> - Set clock offsets
  set-locked-clocks <min> <max>  - Set frequency lock
  reset-clocks                - Reset clocks to default
  set-fan-speed <pct> [idx]   - Set fan speed
  set-fan-auto [idx]          - Set fan to auto
  apply-profile <json>        - Apply profile JSON
  apply-boot-profile          - Apply boot profile
  help                        - Show this help"""
            print(help_text)
            output_success({"action": "help"})
        
        else:
            output_error(f"Unknown command: {command}")
            return 1
        
        return 0
        
    except Exception as e:
        output_error(str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())

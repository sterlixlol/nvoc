"""
NVOC - NVIDIA Overclock for Wayland

A GPU overclocking application for NVIDIA GPUs that works natively on Wayland.
Uses the NVML API for direct GPU control without X11 dependencies.

Repository: https://github.com/your-username/nvoc
License: MIT
"""

__version__ = "0.1.0"
__author__ = "NVOC Contributors"
__license__ = "MIT"

from .nvml_controller import (
    NVMLController,
    NVMLError,
    GPUNotFoundError,
    PermissionError,
    SafetyLimitExceeded,
    GPUInfo,
    GPUStats,
    PowerLimits,
    ClockOffsets,
    SafetyLimits,
)

from .profiles import (
    Profile,
    ProfileManager,
    DefaultProfileManager,
    BUILTIN_PROFILES,
)

from .config import (
    AppConfig,
    ConfigManager,
    get_config,
    get_config_manager,
)

__all__ = [
    # Controller
    "NVMLController",
    "NVMLError",
    "GPUNotFoundError",
    "PermissionError",
    "SafetyLimitExceeded",
    "GPUInfo",
    "GPUStats",
    "PowerLimits",
    "ClockOffsets",
    "SafetyLimits",
    # Profiles
    "Profile",
    "ProfileManager",
    "DefaultProfileManager",
    "BUILTIN_PROFILES",
    # Config
    "AppConfig",
    "ConfigManager",
    "get_config",
    "get_config_manager",
]

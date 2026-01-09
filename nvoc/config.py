"""
NVOC - Configuration Module

Handles application settings and configuration.
"""

import json
import logging
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".config" / "nvoc"
CONFIG_FILE = CONFIG_DIR / "config.json"
CRASH_FLAG_FILE = CONFIG_DIR / ".applying"  # Crash-safe flag file


@dataclass
class AppConfig:
    """Application configuration."""
    
    # UI Settings
    dark_mode: bool = True
    window_width: int = 900
    window_height: int = 700
    
    # Monitoring settings
    monitoring_interval_ms: int = 1000  # Update interval for live stats
    
    # Startup behavior
    apply_default_profile_on_start: bool = False
    boot_profile_name: str = ""  # Profile to apply on boot (empty = none)
    minimize_to_tray: bool = False
    start_minimized: bool = False
    
    # Safety settings (these override SafetyLimits in controller)
    max_core_offset_mhz: int = 200
    max_memory_offset_mhz: int = 500
    min_fan_speed_percent: int = 30
    warning_temp_celsius: int = 80
    critical_temp_celsius: int = 90
    
    # Fan control settings
    fan_hysteresis_celsius: int = 3  # Temp hysteresis to prevent oscillation
    fan_ramp_step_percent: int = 5   # Max speed change per update cycle
    
    # Fan curve default (temp -> fan speed percentage)
    default_fan_curve: Dict[int, int] = field(default_factory=lambda: {
        30: 30,   # 30°C -> 30% fan
        50: 40,   # 50°C -> 40% fan
        60: 50,   # 60°C -> 50% fan
        70: 65,   # 70°C -> 65% fan
        80: 85,   # 80°C -> 85% fan
        85: 100,  # 85°C -> 100% fan
    })
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        """Create config from dictionary."""
        return cls(
            dark_mode=data.get("dark_mode", True),
            window_width=data.get("window_width", 900),
            window_height=data.get("window_height", 700),
            monitoring_interval_ms=data.get("monitoring_interval_ms", 1000),
            apply_default_profile_on_start=data.get("apply_default_profile_on_start", False),
            boot_profile_name=data.get("boot_profile_name", ""),
            minimize_to_tray=data.get("minimize_to_tray", False),
            start_minimized=data.get("start_minimized", False),
            max_core_offset_mhz=data.get("max_core_offset_mhz", 200),
            max_memory_offset_mhz=data.get("max_memory_offset_mhz", 500),
            min_fan_speed_percent=data.get("min_fan_speed_percent", 30),
            warning_temp_celsius=data.get("warning_temp_celsius", 80),
            critical_temp_celsius=data.get("critical_temp_celsius", 90),
            fan_hysteresis_celsius=data.get("fan_hysteresis_celsius", 3),
            fan_ramp_step_percent=data.get("fan_ramp_step_percent", 5),
            default_fan_curve=data.get("default_fan_curve", {
                30: 30, 50: 40, 60: 50, 70: 65, 80: 85, 85: 100
            }),
        )


class ConfigManager:
    """Manages application configuration."""
    
    def __init__(self, config_file: Optional[Path] = None):
        self.config_file = config_file or CONFIG_FILE
        self._config: Optional[AppConfig] = None
    
    @property
    def config(self) -> AppConfig:
        """Get current configuration, loading from file if needed."""
        if self._config is None:
            self._config = self.load()
        return self._config
    
    def load(self) -> AppConfig:
        """Load configuration from file."""
        if not self.config_file.exists():
            logger.info("No config file found, using defaults")
            return AppConfig()
        
        try:
            with open(self.config_file, 'r') as f:
                data = json.load(f)
            return AppConfig.from_dict(data)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to load config: {e}, using defaults")
            return AppConfig()
    
    def save(self, config: Optional[AppConfig] = None) -> bool:
        """Save configuration to file."""
        if config is not None:
            self._config = config
        
        if self._config is None:
            return False
        
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, 'w') as f:
                json.dump(self._config.to_dict(), f, indent=2)
            logger.info("Configuration saved")
            return True
        except IOError as e:
            logger.error(f"Failed to save config: {e}")
            return False
    
    def reset_to_defaults(self) -> AppConfig:
        """Reset configuration to defaults."""
        self._config = AppConfig()
        self.save()
        return self._config


# Global config manager instance
_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """Get the global config manager instance."""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


def get_config() -> AppConfig:
    """Get the current application configuration."""
    return get_config_manager().config


def save_config(config: AppConfig = None) -> bool:
    """Save the current application configuration."""
    return get_config_manager().save(config)


# Crash-Safe Fallback Functions
def set_applying_flag() -> None:
    """Set flag indicating settings are being applied (for crash detection)."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CRASH_FLAG_FILE.touch()
        logger.debug("Applying flag set")
    except IOError as e:
        logger.warning(f"Failed to set applying flag: {e}")


def clear_applying_flag() -> None:
    """Clear the applying flag after successful apply."""
    try:
        if CRASH_FLAG_FILE.exists():
            CRASH_FLAG_FILE.unlink()
            logger.debug("Applying flag cleared")
    except IOError as e:
        logger.warning(f"Failed to clear applying flag: {e}")


def check_crash_recovery() -> bool:
    """Check if previous apply crashed (flag exists on startup).
    
    Returns:
        True if crash detected (flag file exists), False otherwise.
    """
    if CRASH_FLAG_FILE.exists():
        logger.warning("Crash flag detected! Previous apply may have failed.")
        # Clean up the flag
        try:
            CRASH_FLAG_FILE.unlink()
        except IOError:
            pass
        return True
    return False


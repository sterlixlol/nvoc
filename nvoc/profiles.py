"""
NVOC - Profile Manager

Handles saving, loading, and managing overclock profiles.
Profiles are stored as JSON files in ~/.config/nvoc/profiles/
"""

import json
import logging
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# Default config directory
CONFIG_DIR = Path.home() / ".config" / "nvoc"
PROFILES_DIR = CONFIG_DIR / "profiles"


@dataclass
class Profile:
    """Overclock profile data structure."""
    name: str
    power_limit_watts: Optional[float] = None
    core_clock_offset_mhz: Optional[int] = None
    memory_clock_offset_mhz: Optional[int] = None
    max_clock_mhz: Optional[int] = None  # Frequency lock (for undervolting)
    fan_mode: str = "auto"  # "auto" or "manual"
    fan_speed_percent: Optional[int] = None
    fan_curve: Optional[Dict[int, int]] = None  # temp -> fan speed mapping
    apply_on_boot: bool = False  # Apply this profile on boot
    created_at: str = ""
    updated_at: str = ""
    description: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert profile to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Profile":
        """Create profile from dictionary."""
        # Handle any missing fields with defaults
        return cls(
            name=data.get("name", "Unnamed"),
            power_limit_watts=data.get("power_limit_watts"),
            core_clock_offset_mhz=data.get("core_clock_offset_mhz"),
            memory_clock_offset_mhz=data.get("memory_clock_offset_mhz"),
            max_clock_mhz=data.get("max_clock_mhz"),
            fan_mode=data.get("fan_mode", "auto"),
            fan_speed_percent=data.get("fan_speed_percent"),
            fan_curve=data.get("fan_curve"),
            apply_on_boot=data.get("apply_on_boot", False),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            description=data.get("description", "")
        )


class ProfileManager:
    """
    Manages overclock profiles - save, load, delete, list.
    
    Profiles are stored in ~/.config/nvoc/profiles/ as JSON files.
    """
    
    def __init__(self, profiles_dir: Optional[Path] = None):
        """
        Initialize profile manager.
        
        Args:
            profiles_dir: Custom profiles directory (default: ~/.config/nvoc/profiles/)
        """
        self.profiles_dir = profiles_dir or PROFILES_DIR
        self._ensure_directories()
    
    def _ensure_directories(self) -> None:
        """Create config directories if they don't exist."""
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_profile_path(self, name: str) -> Path:
        """Get the file path for a profile."""
        # Sanitize name for filename
        safe_name = "".join(c for c in name if c.isalnum() or c in "._- ").strip()
        safe_name = safe_name.replace(" ", "_").lower()
        return self.profiles_dir / f"{safe_name}.json"
    
    def list_profiles(self) -> List[str]:
        """
        List all available profile names.
        
        Returns:
            List of profile names
        """
        profiles = []
        for path in self.profiles_dir.glob("*.json"):
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                    profiles.append(data.get("name", path.stem))
            except (json.JSONDecodeError, IOError):
                logger.warning(f"Could not read profile: {path}")
        return sorted(profiles)
    
    def load_profile(self, name: str) -> Optional[Profile]:
        """
        Load a profile by name.
        
        Args:
            name: Profile name
            
        Returns:
            Profile object or None if not found
        """
        path = self._get_profile_path(name)
        
        if not path.exists():
            logger.warning(f"Profile not found: {name}")
            return None
        
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            return Profile.from_dict(data)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load profile {name}: {e}")
            return None
    
    def save_profile(self, profile: Profile) -> bool:
        """
        Save a profile.
        
        Args:
            profile: Profile object to save
            
        Returns:
            True if successful
        """
        path = self._get_profile_path(profile.name)
        
        # Update timestamps
        now = datetime.now().isoformat()
        if not profile.created_at:
            profile.created_at = now
        profile.updated_at = now
        
        try:
            with open(path, 'w') as f:
                json.dump(profile.to_dict(), f, indent=2)
            logger.info(f"Profile saved: {profile.name}")
            return True
        except IOError as e:
            logger.error(f"Failed to save profile {profile.name}: {e}")
            return False
    
    def delete_profile(self, name: str) -> bool:
        """
        Delete a profile.
        
        Args:
            name: Profile name
            
        Returns:
            True if deleted successfully
        """
        path = self._get_profile_path(name)
        
        if not path.exists():
            logger.warning(f"Profile not found: {name}")
            return False
        
        try:
            path.unlink()
            logger.info(f"Profile deleted: {name}")
            return True
        except IOError as e:
            logger.error(f"Failed to delete profile {name}: {e}")
            return False
    
    def create_profile_from_current(
        self,
        name: str,
        controller,  # NVMLController instance
        description: str = ""
    ) -> Profile:
        """
        Create a new profile from current GPU settings.
        
        Args:
            name: Profile name
            controller: NVMLController instance
            description: Optional description
            
        Returns:
            New Profile object
        """
        power = controller.get_power_limits()
        clocks = controller.get_clock_offsets()
        
        profile = Profile(
            name=name,
            power_limit_watts=power.current_watts,
            core_clock_offset_mhz=clocks.core_offset_mhz,
            memory_clock_offset_mhz=clocks.memory_offset_mhz,
            description=description
        )
        
        return profile
    
    def apply_profile(self, profile: Profile, controller) -> bool:
        """
        Apply a profile to the GPU.
        
        Args:
            profile: Profile to apply
            controller: NVMLController instance
            
        Returns:
            True if successful
        """
        try:
            # Apply power limit
            if profile.power_limit_watts is not None:
                controller.set_power_limit(profile.power_limit_watts)
            
            # Apply clock offsets
            if (profile.core_clock_offset_mhz is not None or 
                profile.memory_clock_offset_mhz is not None):
                controller.set_clock_offsets(
                    core_offset_mhz=profile.core_clock_offset_mhz,
                    memory_offset_mhz=profile.memory_clock_offset_mhz
                )
            
            # Apply frequency lock
            if profile.max_clock_mhz is not None and profile.max_clock_mhz > 0:
                controller.set_gpu_locked_clocks(0, profile.max_clock_mhz)
            else:
                # Reset frequency lock
                controller.set_gpu_locked_clocks(0, 0)
            
            # Apply fan settings
            if profile.fan_mode == "auto":
                controller.set_all_fans_auto()
            elif profile.fan_mode == "manual" and profile.fan_speed_percent is not None:
                controller.set_all_fans_speed(profile.fan_speed_percent)
            
            logger.info(f"Applied profile: {profile.name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to apply profile {profile.name}: {e}")
            return False
    
    def export_profile(self, name: str, export_path: Path) -> bool:
        """
        Export a profile to an external JSON file.
        
        Args:
            name: Profile name to export
            export_path: Destination file path
            
        Returns:
            True if successful
        """
        profile = self.load_profile(name)
        if profile is None:
            logger.error(f"Cannot export: profile '{name}' not found")
            return False
        
        try:
            export_data = {
                "nvoc_version": "1.0",
                "export_date": datetime.now().isoformat(),
                "profile": profile.to_dict()
            }
            with open(export_path, 'w') as f:
                json.dump(export_data, f, indent=2)
            logger.info(f"Exported profile '{name}' to {export_path}")
            return True
        except IOError as e:
            logger.error(f"Failed to export profile: {e}")
            return False
    
    def import_profile(self, import_path: Path, overwrite: bool = False) -> Optional[Profile]:
        """
        Import a profile from an external JSON file.
        
        Args:
            import_path: Source file path
            overwrite: Whether to overwrite existing profile with same name
            
        Returns:
            Imported Profile object or None if failed
        """
        try:
            with open(import_path, 'r') as f:
                data = json.load(f)
            
            # Handle both exported format and raw profile format
            if "profile" in data:
                profile_data = data["profile"]
            else:
                profile_data = data
            
            profile = Profile.from_dict(profile_data)
            
            # Check if profile already exists
            existing = self.load_profile(profile.name)
            if existing and not overwrite:
                logger.warning(f"Profile '{profile.name}' already exists. Use overwrite=True to replace.")
                return None
            
            # Save the imported profile
            if self.save_profile(profile):
                logger.info(f"Imported profile '{profile.name}' from {import_path}")
                return profile
            return None
            
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to import profile: {e}")
            return None


class DefaultProfileManager:
    """Manages the default profile that's applied on startup."""
    
    DEFAULT_PROFILE_FILE = CONFIG_DIR / "default_profile.txt"
    
    @classmethod
    def get_default(cls) -> Optional[str]:
        """Get the name of the default profile."""
        if not cls.DEFAULT_PROFILE_FILE.exists():
            return None
        
        try:
            return cls.DEFAULT_PROFILE_FILE.read_text().strip()
        except IOError:
            return None
    
    @classmethod
    def set_default(cls, profile_name: str) -> bool:
        """Set the default profile."""
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            cls.DEFAULT_PROFILE_FILE.write_text(profile_name)
            logger.info(f"Default profile set to: {profile_name}")
            return True
        except IOError as e:
            logger.error(f"Failed to set default profile: {e}")
            return False
    
    @classmethod
    def clear_default(cls) -> bool:
        """Clear the default profile."""
        if cls.DEFAULT_PROFILE_FILE.exists():
            try:
                cls.DEFAULT_PROFILE_FILE.unlink()
                logger.info("Default profile cleared")
                return True
            except IOError as e:
                logger.error(f"Failed to clear default profile: {e}")
                return False
        return True


# Built-in profiles
BUILTIN_PROFILES = {
    "stock": Profile(
        name="Stock",
        power_limit_watts=None,  # Use default
        core_clock_offset_mhz=0,
        memory_clock_offset_mhz=0,
        fan_mode="auto",
        description="Stock settings - no overclocking"
    ),
    "quiet": Profile(
        name="Quiet",
        power_limit_watts=None,
        core_clock_offset_mhz=-100,
        memory_clock_offset_mhz=0,
        fan_mode="manual",
        fan_speed_percent=40,
        description="Reduced power and fan noise"
    ),
    "performance": Profile(
        name="Performance",
        power_limit_watts=None,  # Will use max
        core_clock_offset_mhz=100,
        memory_clock_offset_mhz=200,
        fan_mode="auto",
        description="Moderate overclock for extra performance"
    ),
}

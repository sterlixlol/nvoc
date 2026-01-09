#!/usr/bin/env python3
"""
NVOC - NVIDIA Overclock for Wayland

Main application entry point.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, GLib

import sys
import logging
import argparse
from typing import Optional

from .nvml_controller import NVMLController, NVMLError
from .privileged_controller import PrivilegedController, PrivilegedControllerError
from .window import MainWindow
from .config import get_config_manager
from .profiles import ProfileManager, DefaultProfileManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class NVOCApplication(Adw.Application):
    """Main NVOC GTK4 Application."""
    
    def __init__(self):
        super().__init__(
            application_id="com.github.nvoc",
            flags=Gio.ApplicationFlags.NON_UNIQUE
        )
        
        self.window: Optional[MainWindow] = None
        self.controller: Optional[PrivilegedController] = None
        
        # Add command line options
        self.add_main_option(
            "version", ord('v'),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.NONE,
            "Show version information",
            None
        )
        
        self.add_main_option(
            "apply-default", ord('a'),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.NONE,
            "Apply default profile and exit (for systemd service)",
            None
        )
        
        self.add_main_option(
            "status", ord('s'),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.NONE,
            "Show GPU status and exit",
            None
        )
    
    def do_handle_local_options(self, options: GLib.VariantDict) -> int:
        """Handle command line options."""
        if options.contains("version"):
            from . import __version__
            print(f"NVOC version {__version__}")
            return 0
        
        if options.contains("status"):
            self._show_status()
            return 0
        
        if options.contains("apply-default"):
            return self._apply_default_profile()
        
        return -1  # Continue to do_activate
    
    def _show_status(self) -> None:
        """Print GPU status to console."""
        try:
            with NVMLController() as ctrl:
                info = ctrl.get_gpu_info()
                stats = ctrl.get_gpu_stats()
                power = ctrl.get_power_limits()
                clocks = ctrl.get_clock_offsets()
                
                print(f"GPU: {info.name}")
                print(f"Driver: {info.driver_version}")
                print(f"VBIOS: {info.vbios_version}")
                print(f"Temperature: {stats.temperature_celsius}°C")
                print(f"Fan Speed: {stats.fan_speed_percent}%")
                print(f"Power: {stats.power_draw_watts:.1f}W / {stats.power_limit_watts:.0f}W")
                print(f"Power Range: {power.min_watts:.0f}W - {power.max_watts:.0f}W")
                print(f"Core Clock: {stats.core_clock_mhz}MHz (offset: {clocks.core_offset_mhz:+d})")
                print(f"Memory Clock: {stats.memory_clock_mhz}MHz (offset: {clocks.memory_offset_mhz:+d})")
                print(f"GPU Load: {stats.gpu_utilization_percent}%")
                print(f"VRAM: {stats.memory_used_mb}MB / {stats.memory_total_mb}MB")
        except NVMLError as e:
            print(f"Error: {e}", file=sys.stderr)
    
    def _apply_default_profile(self, controller: Optional[PrivilegedController] = None) -> int:
        """Apply the default profile (for systemd service or startup)."""
        default_name = DefaultProfileManager.get_default()
        
        if not default_name:
            logger.info("No default profile set")
            return 0
        
        # Use existing controller or create temporary one
        ctx = None
        if controller:
            ctrl = controller
        else:
            ctx = NVMLController()
            ctrl = ctx
            
        try:
            if ctx:
                ctx.initialize()
                
            pm = ProfileManager()
            profile = pm.load_profile(default_name)
            
            if profile is None:
                # Try builtin profiles
                from .profiles import BUILTIN_PROFILES
                for name, p in BUILTIN_PROFILES.items():
                    if p.name == default_name:
                        profile = p
                        break
            
            if profile is None:
                logger.error(f"Profile not found: {default_name}")
                return 1
            
            pm.apply_profile(profile, ctrl)
            logger.info(f"Applied default profile: {default_name}")
            return 0
            
        except NVMLError as e:
            logger.error(f"Failed to apply profile: {e}")
            return 1
        finally:
            if ctx:
                ctx.shutdown()
    
    def do_activate(self) -> None:
        """Activate the application."""
        if self.window is not None:
            self.window.present()
            return
        
        # Initialize controller (uses pkexec for privileged operations)
        try:
            self.controller = PrivilegedController()
            self.controller.initialize()
            logger.info("NVML initialized successfully")
        except (NVMLError, PrivilegedControllerError) as e:
            logger.error(f"Failed to initialize NVML: {e}")
            self._show_error_dialog(str(e))
            return
        
        # Create main window
        self.window = MainWindow(self, self.controller)
        
        # Apply startup profile
        config = get_config_manager().config
        if config.apply_default_profile_on_start:
            self._apply_default_profile(self.controller)
        
        # Setup actions
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._on_about)
        self.add_action(about_action)
        
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", self._on_quit)
        self.add_action(quit_action)
        
        # Reset to Stock action
        reset_action = Gio.SimpleAction.new("reset_stock", None)
        reset_action.connect("activate", self._on_reset_stock)
        self.add_action(reset_action)
        
        # Settings action (navigates to settings page)
        settings_action = Gio.SimpleAction.new("settings", None)
        settings_action.connect("activate", self._on_settings)
        self.add_action(settings_action)
        
        self.window.present()
    
    def _on_about(self, action: Gio.SimpleAction, param) -> None:
        """Show about dialog."""
        from . import __version__
        
        about = Adw.AboutWindow(
            application_name="NVOC",
            application_icon="preferences-system-symbolic",
            developer_name="NVOC Contributors",
            version=__version__,
            website="https://github.com/sterlix/nvoc",
            issue_url="https://github.com/sterlix/nvoc/issues",
            license_type=Gtk.License.MIT_X11,
            comments="NVIDIA GPU Overclocking for Wayland",
            developers=["NVOC Contributors"],
        )
        about.set_transient_for(self.window)
        about.present()
    
    def _on_quit(self, action: Gio.SimpleAction, param) -> None:
        """Quit the application."""
        # Ensure window cleanup runs
        if self.window:
            self.window.close()
            
        if self.controller:
            self.controller.shutdown()
        self.quit()
    
    def _on_reset_stock(self, action: Gio.SimpleAction, param) -> None:
        """Reset all GPU settings to stock values."""
        if self.controller:
            try:
                self.controller.reset_clocks()
                self.controller.reset_power_limit()
                if self.window:
                    self.window.show_toast("Reset to stock values")
            except Exception as e:
                logger.error(f"Reset failed: {e}")
                if self.window:
                    self.window.show_toast(f"Reset failed: {e}")
    
    def _on_settings(self, action: Gio.SimpleAction, param) -> None:
        """Navigate to settings page."""
        if self.window:
            self.window.navigate_to("settings")
    
    def _show_error_dialog(self, message: str) -> None:
        """Show an error dialog."""
        dialog = Adw.MessageDialog(
            heading="NVOC Error",
            body=message
        )
        dialog.add_response("ok", "OK")
        dialog.present()
    
    def do_shutdown(self) -> None:
        """Clean shutdown."""
        if self.controller:
            self.controller.shutdown()
        Adw.Application.do_shutdown(self)


def main() -> int:
    """Main entry point."""
    app = NVOCApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())

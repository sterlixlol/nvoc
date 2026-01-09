"""
NVOC - Settings UI Component

Application settings page with configuration options.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib
import logging

from ..config import get_config, save_config

logger = logging.getLogger(__name__)


class SettingsPage(Gtk.Box):
    """Application settings and configuration page."""
    
    def __init__(self, controller, window=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        
        self.controller = controller
        self.window = window
        self.config = get_config()
        
        self.set_margin_top(16)
        self.set_margin_bottom(16)
        self.set_margin_start(24)
        self.set_margin_end(24)
        
        # Header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        title = Gtk.Label(label="Settings")
        title.add_css_class("page-title")
        title.set_halign(Gtk.Align.START)
        header.append(title)
        self.append(header)
        
        # Scrollable content
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_top(8)
        
        # ===== MONITORING SECTION =====
        monitor_frame = Gtk.Frame()
        monitor_frame.add_css_class("control-section")
        
        monitor_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        monitor_box.set_margin_top(16)
        monitor_box.set_margin_bottom(16)
        monitor_box.set_margin_start(16)
        monitor_box.set_margin_end(16)
        
        monitor_title = Gtk.Label(label="Monitoring")
        monitor_title.add_css_class("section-title")
        monitor_title.set_halign(Gtk.Align.START)
        monitor_box.append(monitor_title)
        
        # Update interval
        interval_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        interval_label = Gtk.Label(label="Update Interval")
        interval_label.add_css_class("body-text")
        interval_label.set_hexpand(True)
        interval_label.set_halign(Gtk.Align.START)
        interval_row.append(interval_label)
        
        self.interval_combo = Gtk.DropDown()
        self.interval_combo.set_model(Gtk.StringList.new(["Fast (250ms)", "Normal (500ms)", "Slow (1000ms)", "Very Slow (2000ms)"]))
        
        # Set current value
        current_ms = self.config.monitoring_interval_ms
        if current_ms <= 250:
            self.interval_combo.set_selected(0)
        elif current_ms <= 500:
            self.interval_combo.set_selected(1)
        elif current_ms <= 1000:
            self.interval_combo.set_selected(2)
        else:
            self.interval_combo.set_selected(3)
        
        self.interval_combo.connect("notify::selected", self._on_interval_changed)
        interval_row.append(self.interval_combo)
        monitor_box.append(interval_row)
        
        monitor_frame.set_child(monitor_box)
        content.append(monitor_frame)
        
        # ===== BEHAVIOR SECTION =====
        behavior_frame = Gtk.Frame()
        behavior_frame.add_css_class("control-section")
        
        behavior_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        behavior_box.set_margin_top(16)
        behavior_box.set_margin_bottom(16)
        behavior_box.set_margin_start(16)
        behavior_box.set_margin_end(16)
        
        behavior_title = Gtk.Label(label="Behavior")
        behavior_title.add_css_class("section-title")
        behavior_title.set_halign(Gtk.Align.START)
        behavior_box.append(behavior_title)
        
        # Apply on startup
        startup_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        startup_label = Gtk.Label(label="Apply default profile on startup")
        startup_label.add_css_class("body-text")
        startup_label.set_hexpand(True)
        startup_label.set_halign(Gtk.Align.START)
        startup_row.append(startup_label)
        
        self.startup_switch = Gtk.Switch()
        self.startup_switch.set_active(getattr(self.config, 'apply_default_profile_on_start', False))
        self.startup_switch.set_valign(Gtk.Align.CENTER)
        self.startup_switch.connect("notify::active", self._on_startup_changed)
        startup_row.append(self.startup_switch)
        behavior_box.append(startup_row)
        
        # Minimize to tray
        tray_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        tray_label = Gtk.Label(label="Minimize to system tray")
        tray_label.add_css_class("body-text")
        tray_label.set_hexpand(True)
        tray_label.set_halign(Gtk.Align.START)
        tray_row.append(tray_label)
        
        self.tray_switch = Gtk.Switch()
        self.tray_switch.set_active(getattr(self.config, 'minimize_to_tray', False))
        self.tray_switch.set_valign(Gtk.Align.CENTER)
        self.tray_switch.connect("notify::active", self._on_tray_changed)
        tray_row.append(self.tray_switch)
        behavior_box.append(tray_row)
        
        behavior_frame.set_child(behavior_box)
        content.append(behavior_frame)
        
        # ===== ABOUT SECTION =====
        about_frame = Gtk.Frame()
        about_frame.add_css_class("control-section")
        
        about_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        about_box.set_margin_top(16)
        about_box.set_margin_bottom(16)
        about_box.set_margin_start(16)
        about_box.set_margin_end(16)
        
        about_title = Gtk.Label(label="About NVOC")
        about_title.add_css_class("section-title")
        about_title.set_halign(Gtk.Align.START)
        about_box.append(about_title)
        
        version_label = Gtk.Label(label="Version 1.0.0 • Built with GTK4 + libadwaita")
        version_label.add_css_class("helper-text")
        version_label.set_halign(Gtk.Align.START)
        about_box.append(version_label)
        
        desc_label = Gtk.Label(label="A modern GPU overclocking utility for Linux with NVIDIA GPUs.")
        desc_label.add_css_class("body-text")
        desc_label.set_halign(Gtk.Align.START)
        desc_label.set_wrap(True)
        about_box.append(desc_label)
        
        # Export diagnostics button
        export_btn = Gtk.Button(label="📋 Export Diagnostics Bundle")
        export_btn.add_css_class("flat-action")
        export_btn.connect("clicked", self._on_export_diagnostics)
        export_btn.set_halign(Gtk.Align.START)
        export_btn.set_margin_top(8)
        about_box.append(export_btn)
        
        about_frame.set_child(about_box)
        content.append(about_frame)
        
        scroll.set_child(content)
        self.append(scroll)
    
    def _on_interval_changed(self, combo, param) -> None:
        intervals = [250, 500, 1000, 2000]
        selected = combo.get_selected()
        if selected < len(intervals):
            interval = intervals[selected]
            self.config.monitoring_interval_ms = interval
            save_config(self.config)
            
            # Apply dynamic update
            if self.window:
                self.window.set_monitoring_interval(interval)
    
    def _on_startup_changed(self, switch, param) -> None:
        self.config.apply_default_profile_on_start = switch.get_active()
        save_config(self.config)
    
    def _on_tray_changed(self, switch, param) -> None:
        self.config.minimize_to_tray = switch.get_active()
        save_config(self.config)
    
    def _on_export_diagnostics(self, btn) -> None:
        """Export a diagnostics bundle."""
        import json
        from pathlib import Path
        from datetime import datetime
        
        bundle = {
            "timestamp": datetime.now().isoformat(),
            "nvoc_version": "1.0.0",
        }
        
        # GPU info if available
        if self.controller:
            try:
                info = self.controller.get_gpu_info()
                bundle["gpu"] = {
                    "name": info.name,
                    "driver": info.driver_version,
                    "vbios": info.vbios_version,
                    "vram_mb": info.memory_total_mb,
                }
                
                stats = self.controller.get_gpu_stats()
                bundle["current_stats"] = {
                    "temp_c": stats.temperature_celsius,
                    "power_w": stats.power_draw_watts,
                    "power_limit_w": stats.power_limit_watts,
                    "core_mhz": stats.core_clock_mhz,
                    "mem_mhz": stats.memory_clock_mhz,
                    "fan_pct": stats.fan_speed_percent,
                }
            except Exception as e:
                bundle["gpu_error"] = str(e)
        
        # Save to Downloads
        export_path = Path.home() / "Downloads" / f"nvoc_diagnostics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        try:
            with open(export_path, 'w') as f:
                json.dump(bundle, f, indent=2)
            
            parent = self.get_root()
            if hasattr(parent, 'show_toast'):
                parent.show_toast(f"Exported diagnostics to Downloads")
        except Exception as e:
            logger.error(f"Failed to export diagnostics: {e}")

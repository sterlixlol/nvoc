"""
NVOC - Dashboard UI Component (v2.0)

Premium real-time GPU monitoring dashboard with:
- Compressed GPU Hero Card with copy button
- Live Mosaic cards with 60s sparklines
- Dynamic temperature tile with Thermal State chip
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk
import cairo
from collections import deque
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Sparkline colors (from design tokens)
COLORS = {
    'temp': (1.0, 0.302, 0.353),      # #FF4D5A
    'power': (0.965, 0.769, 0.271),   # #F6C445
    'clocks': (0.184, 0.486, 0.965),  # #2F7CF6
    'fan': (0.169, 0.839, 0.482),     # #2BD67B
    'vram': (0.478, 0.655, 1.0),      # #7AA7FF
    'grid': (0.141, 0.165, 0.212),    # #242A36
}


class Sparkline(Gtk.DrawingArea):
    """Compact 60-second sparkline graph."""
    
    def __init__(self, color_key: str = 'clocks', max_points: int = 60):
        super().__init__()
        self.data = deque(maxlen=max_points)
        self.color = COLORS.get(color_key, COLORS['clocks'])
        self.set_content_width(120)
        self.set_content_height(32)
        self.set_draw_func(self._draw)
    
    def add_value(self, value: float) -> None:
        self.data.append(value)
        self.queue_draw()
    
    def _draw(self, area, cr, width, height) -> None:
        if len(self.data) < 2:
            return
        
        # Clip to rounded rectangle
        radius = 6
        cr.new_path()
        cr.arc(radius, radius, radius, 3.14159, 1.5 * 3.14159)
        cr.arc(width - radius, radius, radius, 1.5 * 3.14159, 0)
        cr.arc(width - radius, height - radius, radius, 0, 0.5 * 3.14159)
        cr.arc(radius, height - radius, radius, 0.5 * 3.14159, 3.14159)
        cr.close_path()
        cr.clip()
        
        # Background
        cr.set_source_rgb(*COLORS['grid'])
        cr.rectangle(0, 0, width, height)
        cr.fill()
        
        # Calculate bounds
        min_val = min(self.data)
        max_val = max(self.data)
        range_val = max(max_val - min_val, 1)
        
        # Draw line
        cr.set_source_rgba(*self.color, 0.9)
        cr.set_line_width(2)
        
        points = list(self.data)
        for i, val in enumerate(points):
            x = (i / (len(points) - 1)) * width
            y = height - ((val - min_val) / range_val) * (height - 4) - 2
            
            if i == 0:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)
        
        cr.stroke()
        
        # Glow effect
        cr.set_source_rgba(*self.color, 0.15)
        cr.set_line_width(6)
        for i, val in enumerate(points):
            x = (i / (len(points) - 1)) * width
            y = height - ((val - min_val) / range_val) * (height - 4) - 2
            if i == 0:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)
        cr.stroke()


class AnimatedLabel(Gtk.Label):
    """A label that animates numeric value changes with smooth interpolation.
    
    Uses GLib.timeout_add for ~60fps updates with ease-out cubic easing.
    Duration: 180ms to match unified motion language.
    """
    
    def __init__(self, format_str: str = "{:.0f}", **kwargs):
        super().__init__(**kwargs)
        self._format = format_str
        self._current_value = 0.0
        self._target_value = 0.0
        self._start_value = 0.0
        self._animation_id = None
        self._animation_start = 0
        self._animation_duration = 180  # ms, matches motion tokens
        self._frame_interval = 16  # ~60fps
    
    def set_animated_value(self, value: float) -> None:
        """Set target value and start animation."""
        if self._animation_id:
            GLib.source_remove(self._animation_id)
            self._animation_id = None
        
        # Don't animate tiny changes
        if abs(value - self._current_value) < 0.5:
            self._current_value = value
            self._target_value = value
            self.set_label(self._format.format(value))
            return
        
        self._start_value = self._current_value
        self._target_value = value
        self._animation_start = GLib.get_monotonic_time() // 1000  # ms
        self._animation_id = GLib.timeout_add(self._frame_interval, self._animate_step)
    
    def _ease_out_cubic(self, t: float) -> float:
        """Ease-out cubic: decelerating to zero velocity."""
        return 1 - pow(1 - t, 3)
    
    def _animate_step(self) -> bool:
        """Animation frame callback."""
        now = GLib.get_monotonic_time() // 1000
        elapsed = now - self._animation_start
        progress = min(elapsed / self._animation_duration, 1.0)
        
        eased = self._ease_out_cubic(progress)
        self._current_value = self._start_value + (self._target_value - self._start_value) * eased
        self.set_label(self._format.format(self._current_value))
        
        if progress >= 1.0:
            self._current_value = self._target_value
            self._animation_id = None
            return False  # Stop animation
        return True  # Continue


class MetricCard(Gtk.Box):
    """A premium metric card with value, subtitle, and sparkline."""
    
    def __init__(self, title: str, unit: str = "", color_key: str = 'clocks'):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add_css_class("stat-card")
        self.set_hexpand(True)
        
        # Header row
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        self.title_label = Gtk.Label(label=title)
        self.title_label.add_css_class("metric-label")
        self.title_label.set_halign(Gtk.Align.START)
        self.title_label.set_hexpand(True)
        header.append(self.title_label)
        
        # Sparkline
        self.sparkline = Sparkline(color_key)
        header.append(self.sparkline)
        
        self.append(header)
        
        # Value row
        value_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        value_box.set_halign(Gtk.Align.START)
        
        # Use AnimatedLabel for smooth value transitions
        self.value_label = AnimatedLabel(format_str="{:.0f}")
        self.value_label.set_label("--")
        self.value_label.add_css_class("metric-value")
        value_box.append(self.value_label)
        
        if unit:
            self.unit_label = Gtk.Label(label=unit)
            self.unit_label.add_css_class("stat-unit")
            value_box.append(self.unit_label)
        
        self.append(value_box)
        
        # Subtitle
        self.subtitle_label = Gtk.Label(label="")
        self.subtitle_label.add_css_class("stat-subtitle")
        self.subtitle_label.set_halign(Gtk.Align.START)
        self.append(self.subtitle_label)
    
    def set_value(self, value, sparkline_val: float = None) -> None:
        """Set value with animation if numeric."""
        if isinstance(value, (int, float)):
            self.value_label.set_animated_value(float(value))
        else:
            self.value_label.set_label(str(value))
        if sparkline_val is not None:
            self.sparkline.add_value(sparkline_val)
    
    def set_subtitle(self, text: str) -> None:
        self.subtitle_label.set_label(text)


class TemperatureHero(Gtk.Box):
    """Premium temperature display with dynamic colors and Thermal State."""
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add_css_class("temp-gauge")
        self.add_css_class("hero-card")
        self.add_css_class("hero-card")
        self.set_halign(Gtk.Align.FILL)
        self.set_hexpand(True)
        self.set_valign(Gtk.Align.CENTER)
        
        # Temperature row
        temp_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        temp_row.set_halign(Gtk.Align.CENTER)
        
        # Use AnimatedLabel for smooth temperature transitions
        self.temp_label = AnimatedLabel(format_str="{:.0f}")
        self.temp_label.set_label("--")
        self.temp_label.add_css_class("temp-value-hero")
        temp_row.append(self.temp_label)
        
        unit_label = Gtk.Label(label="°C")
        unit_label.add_css_class("temp-unit-faded")
        unit_label.set_valign(Gtk.Align.END)
        unit_label.set_margin_bottom(16)
        temp_row.append(unit_label)
        
        self.append(temp_row)
        
        # Hotspot line (if available)
        self.hotspot_label = Gtk.Label(label="")
        self.hotspot_label.add_css_class("helper-text")
        self.append(self.hotspot_label)
        
        # Thermal State badge
        self.status_badge = Gtk.Label(label="Thermal State")
        self.status_badge.add_css_class("temp-badge")
        self.append(self.status_badge)
    
    def set_temperature(self, temp: int, hotspot: int = None) -> None:
        """Set temperature with smooth animation."""
        self.temp_label.set_animated_value(float(temp))
        
        if hotspot:
            self.hotspot_label.set_label(f"Hotspot {hotspot}°C")
        else:
            self.hotspot_label.set_label("")
        
        # Determine new thermal state
        if temp < 50:
            new_state = "cool"
        elif temp < 70:
            new_state = "warm"
        elif temp < 85:
            new_state = "hot"
        else:
            new_state = "critical"
        
        # Check if state changed
        old_state = getattr(self, '_current_state', None)
        state_changed = old_state is not None and old_state != new_state
        self._current_state = new_state
        
        # Remove old classes
        for cls in ["temp-cool", "temp-warm", "temp-hot", "temp-critical"]:
            self.remove_css_class(cls)
        for cls in ["badge-cool", "badge-warm", "badge-hot", "badge-critical"]:
            self.status_badge.remove_css_class(cls)
        
        # Apply thermal state with pulse if changed
        if state_changed:
            self.status_badge.add_css_class("chip-pulse")
            GLib.timeout_add(300, self._remove_pulse)
        
        if new_state == "cool":
            self.add_css_class("temp-cool")
            self.status_badge.add_css_class("badge-cool")
            self.status_badge.set_label("● Cool")
        elif new_state == "warm":
            self.add_css_class("temp-warm")
            self.status_badge.add_css_class("badge-warm")
            self.status_badge.set_label("● Normal")
        elif new_state == "hot":
            self.add_css_class("temp-hot")
            self.status_badge.add_css_class("badge-hot")
            self.status_badge.set_label("● Hot")
        else:
            self.add_css_class("temp-critical")
            self.status_badge.add_css_class("badge-critical")
            self.status_badge.set_label("⚠ Throttling")
    
    def _remove_pulse(self) -> bool:
        """Remove pulse class after animation completes."""
        self.status_badge.remove_css_class("chip-pulse")
        return False  # Don't repeat


class UtilizationBar(Gtk.Box):
    """Progress bar with label for utilization metrics."""
    
    def __init__(self, title: str):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add_css_class("progress-card")
        self.set_hexpand(True)
        
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        
        self.title_label = Gtk.Label(label=title)
        self.title_label.add_css_class("progress-title")
        self.title_label.set_halign(Gtk.Align.START)
        self.title_label.set_hexpand(True)
        header.append(self.title_label)
        
        self.value_label = Gtk.Label(label="")
        self.value_label.add_css_class("progress-value")
        header.append(self.value_label)
        
        self.append(header)
        
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_hexpand(True)
        self.append(self.progress_bar)
    
    def set_value(self, fraction: float, label: str = "") -> None:
        self.progress_bar.set_fraction(max(0.0, min(1.0, fraction)))
        self.value_label.set_label(label if label else f"{int(fraction * 100)}%")
        
        # Color coding
        for cls in ["progress-low", "progress-medium", "progress-high", "progress-critical"]:
            self.progress_bar.remove_css_class(cls)
        
        if fraction < 0.5:
            self.progress_bar.add_css_class("progress-low")
        elif fraction < 0.7:
            self.progress_bar.add_css_class("progress-medium")
        elif fraction < 0.85:
            self.progress_bar.add_css_class("progress-high")
        else:
            self.progress_bar.add_css_class("progress-critical")


class DashboardPage(Gtk.Box):
    """Premium GPU monitoring dashboard with Live Mosaic layout."""
    
    def __init__(self, controller):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        
        self.controller = controller
        self._updating = False
        
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        self.set_margin_start(24)
        self.set_margin_end(24)
        
        # ===== GPU HERO CARD =====
        gpu_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        gpu_card.add_css_class("gpu-header")
        
        # GPU info (left)
        gpu_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        gpu_info.set_hexpand(True)
        
        self.gpu_name_label = Gtk.Label(label="NVIDIA GPU")
        self.gpu_name_label.add_css_class("gpu-name")
        self.gpu_name_label.set_halign(Gtk.Align.START)
        gpu_info.append(self.gpu_name_label)
        
        self.gpu_info_label = Gtk.Label(label="Driver: -- | VBIOS: -- | VRAM: --")
        self.gpu_info_label.add_css_class("gpu-info")
        self.gpu_info_label.set_halign(Gtk.Align.START)
        gpu_info.append(self.gpu_info_label)
        
        gpu_card.append(gpu_info)
        
        # Copy button (right)
        copy_btn = Gtk.Button(icon_name="edit-copy-symbolic")
        copy_btn.add_css_class("flat-action")
        copy_btn.set_tooltip_text("Copy system info")
        copy_btn.connect("clicked", self._on_copy_info)
        copy_btn.set_valign(Gtk.Align.CENTER)
        gpu_card.append(copy_btn)
        
        self.append(gpu_card)
        
        # ===== MAIN CONTENT: Temp Hero + Mosaic Grid =====
        main_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
        main_content.set_vexpand(True)
        
        # Left: Temperature Hero + Controls
        left_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        left_col.set_valign(Gtk.Align.CENTER)
        
        self.temp_hero = TemperatureHero()
        left_col.append(self.temp_hero)
        
        # Offsets Display (Pill)
        offsets_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        offsets_box.add_css_class("offsets-display")
        offsets_box.set_halign(Gtk.Align.CENTER)
        
        self.core_offset_label = Gtk.Label(label="Core +0 MHz")
        self.core_offset_label.add_css_class("offset-label")
        offsets_box.append(self.core_offset_label)
        
        sep = Gtk.Label(label="•")
        sep.add_css_class("offset-sep")
        offsets_box.append(sep)
        
        self.mem_offset_label = Gtk.Label(label="Memory +0 MHz")
        self.mem_offset_label.add_css_class("offset-label")
        offsets_box.append(self.mem_offset_label)
        
        sep2 = Gtk.Label(label="•")
        sep2.add_css_class("offset-sep")
        offsets_box.append(sep2)
        
        self.status_chip = Gtk.Label(label="Idle")
        self.status_chip.add_css_class("status-chip")
        self.status_chip.add_css_class("chip-idle")
        offsets_box.append(self.status_chip)
        
        left_col.append(offsets_box)
        
        # Quick Actions (2x2 Grid)
        actions_frame = Gtk.Frame()
        actions_frame.add_css_class("control-section")
        
        actions_grid = Gtk.Grid()
        actions_grid.set_column_spacing(12)
        actions_grid.set_row_spacing(12)
        actions_grid.set_halign(Gtk.Align.FILL)
        actions_grid.set_hexpand(True)
        
        # Label spanning top
        actions_label = Gtk.Label(label="Quick Actions")
        actions_label.add_css_class("section-title")
        actions_label.set_halign(Gtk.Align.START)
        actions_label.set_margin_bottom(12)
        
        # Container for actions with label
        actions_wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        actions_wrapper.append(actions_label)
        
        # Buttons
        # Stock
        stock_btn = Gtk.Button(label="Stock")
        stock_btn.add_css_class("flat-action")
        stock_btn.set_tooltip_text("Reset to stock settings (0 offsets)")
        stock_btn.connect("clicked", self._on_quick_stock)
        stock_btn.set_hexpand(True)
        actions_grid.attach(stock_btn, 0, 0, 1, 1)
        
        # Quiet
        quiet_btn = Gtk.Button(label="Quiet")
        quiet_btn.add_css_class("flat-action")
        quiet_btn.set_tooltip_text("Undervolt for silence (+100 core, 1800 MHz cap)")
        quiet_btn.connect("clicked", self._on_quick_quiet)
        quiet_btn.set_hexpand(True)
        actions_grid.attach(quiet_btn, 1, 0, 1, 1)
        
        # Performance
        perf_btn = Gtk.Button(label="Performance")
        perf_btn.add_css_class("flat-action")
        perf_btn.set_tooltip_text("Maximum clocks (+200 core, +500 memory)")
        perf_btn.connect("clicked", self._on_quick_performance)
        perf_btn.set_hexpand(True)
        actions_grid.attach(perf_btn, 0, 1, 1, 1)
        
        # Optimize
        optimize_btn = Gtk.Button(label="Auto-Optimize")
        optimize_btn.add_css_class("suggested-action")
        optimize_btn.set_tooltip_text("Analyze thermals and apply optimal settings")
        optimize_btn.connect("clicked", self._on_auto_optimize)
        optimize_btn.set_hexpand(True)
        actions_grid.attach(optimize_btn, 1, 1, 1, 1)
        
        actions_wrapper.append(actions_grid)
        actions_frame.set_child(actions_wrapper)
        
        left_col.append(actions_frame)
        
        main_content.append(left_col)
        
        # Right: Mosaic Grid (3x2)
        right_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        right_col.set_hexpand(True)
        
        # Quad Grid (2x2) for Metrics
        quad_grid = Gtk.Grid()
        quad_grid.set_column_spacing(16)
        quad_grid.set_row_spacing(16)
        quad_grid.set_row_homogeneous(True)
        quad_grid.set_column_homogeneous(True)
        quad_grid.set_hexpand(True)
        
        self.power_card = MetricCard("POWER", "W", "power")
        quad_grid.attach(self.power_card, 0, 0, 1, 1)
        
        self.clocks_card = MetricCard("CORE CLOCK", "MHz", "clocks")
        quad_grid.attach(self.clocks_card, 1, 0, 1, 1)
        
        self.fan_card = MetricCard("FAN", "%", "fan")
        quad_grid.attach(self.fan_card, 0, 1, 1, 1)
        
        self.vram_card = MetricCard("VRAM", "MB", "vram")
        quad_grid.attach(self.vram_card, 1, 1, 1, 1)
        
        right_col.append(quad_grid)
        
        # Row 3: Utilization bars
        util_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        util_box.set_vexpand(True)  # Expand to align with left column
        util_box.set_valign(Gtk.Align.END)  # Align to bottom
        
        self.gpu_util = UtilizationBar("GPU UTILIZATION")
        util_box.append(self.gpu_util)
        
        self.vram_util = UtilizationBar("VRAM UTILIZATION")
        util_box.append(self.vram_util)
        
        right_col.append(util_box)
        
        main_content.append(right_col)
        self.append(main_content)
        
        # Initial load
        self._load_gpu_info()
    
    def _load_gpu_info(self) -> None:
        if not self.controller:
            return
        try:
            info = self.controller.get_gpu_info()
            self.gpu_name_label.set_label(info.name)
            self.gpu_info_label.set_label(
                f"Driver: {info.driver_version} | VBIOS: {info.vbios_version} | "
                f"VRAM: {info.memory_total_mb}MB"
            )
            self._gpu_info = info
        except Exception as e:
            logger.error(f"Failed to load GPU info: {e}")
            self.gpu_name_label.set_label("GPU Error")
    
    def _on_copy_info(self, btn) -> None:
        if hasattr(self, '_gpu_info'):
            info = self._gpu_info
            text = f"{info.name}\nDriver: {info.driver_version}\nVBIOS: {info.vbios_version}\nVRAM: {info.memory_total_mb}MB"
            clipboard = Gdk.Display.get_default().get_clipboard()
            clipboard.set(text)
    
    def update_stats(self) -> None:
        if not self.controller or self._updating:
            return
        
        self._updating = True
        
        try:
            stats = self.controller.get_gpu_stats()
            offsets = self.controller.get_clock_offsets()
            
            # Temperature hero
            self.temp_hero.set_temperature(stats.temperature_celsius)
            
            # Metric cards with sparklines
            self.power_card.set_value(f"{stats.power_draw_watts:.0f}", stats.power_draw_watts)
            power_pct = (stats.power_draw_watts / stats.power_limit_watts * 100) if stats.power_limit_watts > 0 else 0
            self.power_card.set_subtitle(f"{power_pct:.0f}% of {stats.power_limit_watts:.0f}W limit")
            
            self.clocks_card.set_value(str(stats.core_clock_mhz), stats.core_clock_mhz)
            self.clocks_card.set_subtitle(f"Mem: {stats.memory_clock_mhz} MHz")
            
            self.fan_card.set_value(str(stats.fan_speed_percent), stats.fan_speed_percent)
            if stats.fan_speed_percent == 0:
                self.fan_card.set_subtitle("Zero-RPM Mode")
            else:
                self.fan_card.set_subtitle("")
            
            self.vram_card.set_value(str(stats.memory_used_mb), stats.memory_used_mb)
            self.vram_card.set_subtitle(f"of {stats.memory_total_mb} MB")
            
            # Utilization bars
            self.gpu_util.set_value(stats.gpu_utilization_percent / 100.0)
            self.vram_util.set_value(
                stats.memory_used_mb / stats.memory_total_mb if stats.memory_total_mb > 0 else 0,
                f"{stats.memory_used_mb}MB / {stats.memory_total_mb}MB"
            )
            
            # Offsets
            core_sign = "+" if offsets.core_offset_mhz >= 0 else ""
            mem_sign = "+" if offsets.memory_offset_mhz >= 0 else ""
            self.core_offset_label.set_label(f"Core {core_sign}{offsets.core_offset_mhz} MHz")
            self.mem_offset_label.set_label(f"Memory {mem_sign}{offsets.memory_offset_mhz} MHz")
            
            # Status chip
            is_active = stats.gpu_utilization_percent > 50
            self.status_chip.set_label("Active" if is_active else "Idle")
            self.status_chip.remove_css_class("chip-active")
            self.status_chip.remove_css_class("chip-idle")
            self.status_chip.add_css_class("chip-active" if is_active else "chip-idle")
            
        except Exception as e:
            logger.error(f"Failed to update stats: {e}")
        finally:
            self._updating = False
    
    def _show_toast(self, message: str) -> None:
        """Show a toast notification via parent window."""
        parent = self.get_root()
        if hasattr(parent, 'show_toast'):
            parent.show_toast(message)
    
    def _on_quick_stock(self, btn) -> None:
        """Apply stock settings (zero offsets)."""
        if not self.controller:
            return
        try:
            self.controller.set_clock_offsets(0, 0)
            self.controller.set_fan_mode("auto")
            self._show_toast("Applied: Stock settings")
        except Exception as e:
            self._show_toast(f"Failed: {e}")
    
    def _on_quick_quiet(self, btn) -> None:
        """Apply quiet/undervolt preset."""
        if not self.controller:
            return
        try:
            # Undervolt: low clock cap with small positive offset
            self.controller.set_max_frequency_lock(1800)
            self.controller.set_clock_offsets(100, 0)
            self._show_toast("Applied: Quiet (1800 MHz cap)")
        except Exception as e:
            self._show_toast(f"Failed: {e}")
    
    def _on_quick_performance(self, btn) -> None:
        """Apply performance preset."""
        if not self.controller:
            return
        try:
            # Performance: max clocks with offsets
            self.controller.set_max_frequency_lock(0)  # Unlimited
            self.controller.set_clock_offsets(200, 500)
            self._show_toast("Applied: Performance (+200/+500)")
        except Exception as e:
            self._show_toast(f"Failed: {e}")
    
    def _on_auto_optimize(self, btn) -> None:
        """Analyze thermals and apply optimal settings automatically."""
        if not self.controller:
            return
        
        try:
            stats = self.controller.get_gpu_stats()
            temp = stats.temperature_celsius
            
            # Thermal headroom analysis
            if temp < 50:
                # Plenty of headroom - aggressive performance
                self.controller.set_max_frequency_lock(0)  # Unlimited
                self.controller.set_clock_offsets(200, 500)
                self.controller.set_fan_mode("auto")
                self._show_toast(f"Optimized: Cool ({temp}°C) → Performance mode")
            elif temp < 70:
                # Moderate headroom - balanced approach
                self.controller.set_max_frequency_lock(0)
                self.controller.set_clock_offsets(150, 250)
                self.controller.set_fan_mode("auto")
                self._show_toast(f"Optimized: Normal ({temp}°C) → Balanced mode")
            elif temp < 80:
                # Limited headroom - conservative undervolt
                self.controller.set_max_frequency_lock(1950)
                self.controller.set_clock_offsets(100, 0)
                self.controller.set_fan_mode("auto")
                self._show_toast(f"Optimized: Warm ({temp}°C) → Quiet UV mode")
            else:
                # Critical - stock with boost cap
                self.controller.set_max_frequency_lock(1800)
                self.controller.set_clock_offsets(0, 0)
                self.controller.set_fan_mode("auto")
                self._show_toast(f"Optimized: Hot ({temp}°C) → Safe mode")
        except Exception as e:
            self._show_toast(f"Optimize failed: {e}")



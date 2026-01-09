"""
NVOC - Overclock UI Component

Controls for power limit, core clock offset, and memory clock offset.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib

from typing import Optional, Callable
import logging

from ..nvml_controller import SafetyLimits
from ..narratives import get_narrative

logger = logging.getLogger(__name__)


class LabeledSlider(Gtk.Box):
    """A slider with title, current value display, and min/max labels."""
    
    def __init__(
        self,
        title: str,
        min_val: float,
        max_val: float,
        step: float = 1.0,
        unit: str = "",
        format_func: Optional[Callable[[float], str]] = None,

        tick_interval: Optional[float] = 50.0,
        warning_threshold: Optional[float] = None  # Absolute value where warning starts
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        
        self.unit = unit
        self.format_func = format_func or (lambda x: f"{x:.0f}")
        self._callback = None
        self._setting_value = False  # Flag to prevent callback during programmatic set
        
        self.warning_threshold = warning_threshold
        self.tick_interval = tick_interval
        self.add_css_class("labeled-slider")
        
        # Consistent set size
        # Consistent set size
        # self.set_halign(Gtk.Align.START) # Reverted: let it fill
        # self.set_size_request(550, -1)   # Reverted: let it fill
        
        # Header with title and value
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        header.set_margin_bottom(4)
        
        self.title_label = Gtk.Label(label=title)
        self.title_label.add_css_class("slider-title")
        self.title_label.set_halign(Gtk.Align.START)
        self.title_label.set_hexpand(True)
        header.append(self.title_label)
        
        self.value_label = Gtk.Label(label=f"{self.format_func(min_val)}{unit}")
        self.value_label.add_css_class("slider-value")
        self.value_label.set_width_chars(16)  # Increased reservation to prevent jitter
        self.value_label.set_xalign(1.0)  # Right-align text
        header.append(self.value_label)
        
        self.append(header)
        
        # Slider
        self.adjustment = Gtk.Adjustment(
            value=min_val,
            lower=min_val,
            upper=max_val,
            step_increment=step,
            page_increment=step  # reduced from step*10 to prevent large jumps
        )
        
        self.scale = Gtk.Scale(
            orientation=Gtk.Orientation.HORIZONTAL,
            adjustment=self.adjustment
        )
        self.scale.add_css_class("elite-scale")
        self.scale.set_draw_value(False)
        self.scale.set_hexpand(True)
        
        # Alignment fix: Pull the track left to align with text
        # Scale widgets have internal padding for the knob; -12px offsets this.
        self.scale.set_margin_start(-12)
        self.scale.set_margin_end(10) # Small positive margin to prevent edge jitter
        
        self.update_marks(min_val, max_val)
        
        self.scale.connect("value-changed", self._on_value_changed)
        self.append(self.scale)
        
        # Tracking applied state
        self._applied_value = min_val # Default to min or initial
    
    def set_applied_value(self, value: float) -> None:
        """Set the 'active' value to calculate pending state."""
        self._applied_value = value
        self._update_visual_state(self.scale.get_value())
    
    def _on_value_changed(self, scale: Gtk.Scale) -> None:
        """Update the value label and visual state."""
        # Don't trigger callback if we're setting value programmatically
        if self._setting_value:
            return
        
        value = scale.get_value()
        self.value_label.set_label(f"{self.format_func(value)}{self.unit}")
        
        self._update_visual_state(value)
        
        if self._callback:
            self._callback(value)
            
    def _update_visual_state(self, value: float) -> None:
        """Update CSS classes based on value zones and pending state."""
        scale = self.scale
        
        # 1. Pending State (Saturation/Breathe)
        # Compare with epsilon for float equality
        is_pending = abs(value - self._applied_value) > 0.01
        if is_pending:
            scale.add_css_class("slider-pending")
        else:
            scale.remove_css_class("slider-pending")
            
        # 2. Semantic Zones (Escalation)
        scale.remove_css_class("slider-zone-default")
        scale.remove_css_class("slider-zone-high")
        scale.remove_css_class("slider-danger")
        
        # Calculate ratio
        lower = self.adjustment.get_lower()
        upper = self.adjustment.get_upper()
        range_val = upper - lower
        
        if range_val <= 0: return

        # Normalize relative to range
        if lower < 0 < upper:
            # Bipolar (Offset)
            ratio = abs(value) / max(abs(lower), abs(upper))
        else:
            # Unipolar (Power)
            ratio = (value - lower) / range_val
            
        # Explicit warning threshold takes precedence
        if self.warning_threshold is not None and abs(value) >= self.warning_threshold:
             scale.add_css_class("slider-danger")
             return

        # Semantic Zones
        # >90% -> High Intensity (Compressed gradient, focused pressure)
        if ratio > 0.90:
            scale.add_css_class("slider-zone-high")
        # >60% -> Default/Engaged (Thicker glow, resistance)
        elif ratio > 0.60:
            scale.add_css_class("slider-zone-default")
        # Else -> Safe/Calm (Standard)
    
    def get_value(self) -> float:
        """Get current slider value."""
        return self.adjustment.get_value()
    
    def set_value(self, value: float) -> None:
        """Set slider value without triggering callback."""
        self._setting_value = True
        try:
            self.adjustment.set_value(value)
            self.value_label.set_label(f"{self.format_func(value)}{self.unit}")
            self._update_visual_state(value)
        finally:
            self._setting_value = False
    
    def set_range(self, min_val: float, max_val: float) -> None:
        """Update the slider range and refresh marks."""
        self._setting_value = True
        try:
            self.adjustment.set_lower(min_val)
            self.adjustment.set_upper(max_val)
            self.update_marks(min_val, max_val)
        finally:
            self._setting_value = False
            
    def update_marks(self, min_val: float, max_val: float) -> None:
        """Rebuild scale marks for the new range."""
        self.scale.clear_marks()
        
        # Endpoints
        self.scale.add_mark(min_val, Gtk.PositionType.BOTTOM, self.format_func(min_val))
        self.scale.add_mark(max_val, Gtk.PositionType.BOTTOM, self.format_func(max_val))
        
        # Zero mark if bipolar
        if min_val < 0 < max_val:
            self.scale.add_mark(0, Gtk.PositionType.BOTTOM, "0")
            
        # Interval marks
        if self.tick_interval and self.tick_interval > 0:
            start = (int(min_val / self.tick_interval) * self.tick_interval)
            if start < min_val:
                start += self.tick_interval
            
            curr = start
            while curr < max_val:
                if abs(curr - min_val) > 1e-6 and abs(curr - max_val) > 1e-6 and abs(curr) > 1e-6:
                     self.scale.add_mark(curr, Gtk.PositionType.BOTTOM, None)
                curr += self.tick_interval

    def connect_changed(self, callback: Callable[[float], None]) -> None:
        """Connect a callback for value changes."""
        self._callback = callback


class OverclockPage(Gtk.Box):
    """Page for overclocking controls - power limit, clock offsets."""
    
    def __init__(self, controller):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        
        self.controller = controller
        self._applying = False  # Prevent feedback loops during apply
        self._updating = False  # Reentrancy guard for UI updates
        self._pending_changes = False  # Track if sliders have been modified
        self._applied_values = {  # Track last applied values for change-diff
            'power': None,
            'core': None,
            'memory': None,
            'lock': None
        }
        
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        self.set_margin_start(24)
        self.set_margin_end(24)
        
        # Warning banner
        warning_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        warning_box.add_css_class("warning-banner")
        
        warning_icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        warning_icon.set_valign(Gtk.Align.CENTER)
        warning_box.append(warning_icon)
        
        warning_text = Gtk.Label(
            label="Overclocking can cause system instability. Changes require root privileges."
        )
        warning_text.set_wrap(True)
        warning_text.set_hexpand(True)
        warning_text.set_valign(Gtk.Align.CENTER)
        warning_text.set_halign(Gtk.Align.START)
        warning_box.append(warning_text)
        
        self.append(warning_box)
        
        # Scrollable content
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)

        # Live Stats Section
        stats_frame = Gtk.Frame()
        stats_frame.add_css_class("control-section")
        
        stats_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        stats_box.set_margin_top(12)
        stats_box.set_margin_bottom(12)
        stats_box.set_margin_start(16)
        stats_box.set_margin_end(16)
        
        # Header
        stats_title = Gtk.Label(label="Live Statistics")
        stats_title.add_css_class("section-title")
        stats_title.set_halign(Gtk.Align.START)
        stats_box.append(stats_title)
        
        # Grid for stats
        stats_grid = Gtk.Grid()
        stats_grid.set_column_spacing(16)
        stats_grid.set_row_spacing(4)
        
        # Effective Clocks
        stats_grid.attach(Gtk.Label(label="Effective Core:", halign=Gtk.Align.START, css_classes=["dim-label"]), 0, 0, 1, 1)
        self.eff_core_label = Gtk.Label(label="-- MHz", halign=Gtk.Align.START, css_classes=["stat-value-small"])
        stats_grid.attach(self.eff_core_label, 1, 0, 1, 1)
        
        # Last Load Peak
        stats_grid.attach(Gtk.Label(label="Last Load Peak:", halign=Gtk.Align.START, css_classes=["dim-label"]), 0, 1, 1, 1)
        peak_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.peak_label = Gtk.Label(label="-- MHz", halign=Gtk.Align.START, css_classes=["stat-value-small"])
        peak_box.append(self.peak_label)
        reset_peak_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        reset_peak_btn.add_css_class("tiny-btn")
        reset_peak_btn.set_valign(Gtk.Align.CENTER)
        reset_peak_btn.set_tooltip_text("Reset Peak Counter")
        reset_peak_btn.connect("clicked", self._on_reset_peak_clicked)
        peak_box.append(reset_peak_btn)
        stats_grid.attach(peak_box, 1, 1, 1, 1)
        
        # Throttle Status
        stats_grid.attach(Gtk.Label(label="Throttle Status:", halign=Gtk.Align.START, css_classes=["dim-label"]), 0, 2, 1, 1)
        self.throttle_label = Gtk.Label(label="--", halign=Gtk.Align.START)
        stats_grid.attach(self.throttle_label, 1, 2, 1, 1)
        
        # Rolling Average Clock (30s)
        stats_grid.attach(Gtk.Label(label="Avg Clock (30s):", halign=Gtk.Align.START, css_classes=["dim-label"]), 0, 3, 1, 1)
        self.avg_clock_label = Gtk.Label(label="-- MHz", halign=Gtk.Align.START, css_classes=["stat-value-small"])
        stats_grid.attach(self.avg_clock_label, 1, 3, 1, 1)
        
        # PCIe Link State
        stats_grid.attach(Gtk.Label(label="PCIe Link:", halign=Gtk.Align.START, css_classes=["dim-label"]), 0, 4, 1, 1)
        self.pcie_label = Gtk.Label(label="--", halign=Gtk.Align.START, css_classes=["stat-value-small"])
        stats_grid.attach(self.pcie_label, 1, 4, 1, 1)
        
        # Thermal Headroom
        stats_grid.attach(Gtk.Label(label="Thermal Margin:", halign=Gtk.Align.START, css_classes=["dim-label"]), 0, 5, 1, 1)
        self.thermal_label = Gtk.Label(label="--", halign=Gtk.Align.START, css_classes=["stat-value-small"])
        stats_grid.attach(self.thermal_label, 1, 5, 1, 1)
        
        # Power Limit Status
        stats_grid.attach(Gtk.Label(label="Power Limit:", halign=Gtk.Align.START, css_classes=["dim-label"]), 0, 6, 1, 1)
        self.power_limit_label = Gtk.Label(label="✓ Headroom", halign=Gtk.Align.START)
        stats_grid.attach(self.power_limit_label, 1, 6, 1, 1)
        
        stats_box.append(stats_grid)
        
        # Method Info
        method_label = Gtk.Label(label="Undervolt Method: Frequency Curve Control (NVIDIA Standard)")
        method_label.add_css_class("caption")
        method_label.set_halign(Gtk.Align.START)
        method_label.set_margin_top(8)
        stats_box.append(method_label)
        
        # Stability Indicator
        stability_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        stability_box.set_margin_top(4)
        stability_label = Gtk.Label(label="Stability:", css_classes=["dim-label"])
        stability_box.append(stability_label)
        self.stability_value = Gtk.Label(label="✓ No errors")
        self.stability_value.set_markup("<span foreground='#2ecc71'>✓ No errors</span>")
        stability_box.append(self.stability_value)
        stats_box.append(stability_box)
        
        stats_frame.set_child(stats_box)
        content.append(stats_frame)
        
        # Power Limit Section
        power_frame = Gtk.Frame()
        power_frame.add_css_class("control-section")
        
        power_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        power_box.set_margin_top(16)
        power_box.set_margin_bottom(16)
        power_box.set_margin_start(16)
        power_box.set_margin_end(16)
        
        power_title = Gtk.Label(label="⚡ Power Limit")
        power_title.add_css_class("section-title")
        power_title.set_halign(Gtk.Align.START)
        power_box.append(power_title)
        
        power_desc = Gtk.Label(
            label="Adjusts the maximum power the GPU can draw. Higher limits may improve performance."
        )
        power_desc.add_css_class("section-desc")
        power_desc.set_halign(Gtk.Align.START)
        power_desc.set_wrap(True)
        power_box.append(power_desc)
        
        # Power limit info (will be populated with real values)
        self.power_info_label = Gtk.Label(label="")
        self.power_info_label.add_css_class("power-info")
        self.power_info_label.set_halign(Gtk.Align.START)
        power_box.append(self.power_info_label)
        
        # Initialize with safe defaults, will be updated with real GPU limits
        self.power_slider = LabeledSlider(
            title="Power Limit",
            min_val=50,   # Placeholder, updated in _load_current_values
            max_val=200,  # Placeholder, updated in _load_current_values
            step=5,
            unit=" W"
        )
        self.power_slider.connect_changed(self._on_slider_changed)
        power_box.append(self.power_slider)
        
        # Buttons Logic
        power_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        power_actions.set_halign(Gtk.Align.END)
        
        # Reset Power
        reset_power_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        reset_power_btn.add_css_class("flat-action")
        reset_power_btn.set_tooltip_text("Reset to Default Power Limit")
        reset_power_btn.connect("clicked", self._on_reset_power_clicked)
        power_actions.append(reset_power_btn)
        
        # Apply Power
        apply_power_btn = Gtk.Button(label="Apply Power Limit")
        apply_power_btn.add_css_class("flat-action")
        apply_power_btn.connect("clicked", self._on_apply_power_clicked)
        power_actions.append(apply_power_btn)
        
        power_box.append(power_actions)
        
        power_frame.set_child(power_box)
        content.append(power_frame)
        
        # Clock Offsets Section
        clocks_frame = Gtk.Frame()
        clocks_frame.add_css_class("control-section")
        
        clocks_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        clocks_box.set_margin_top(16)
        clocks_box.set_margin_bottom(16)
        clocks_box.set_margin_start(16)
        clocks_box.set_margin_end(16)
        
        clocks_title = Gtk.Label(label="Clock Offsets")
        clocks_title.add_css_class("section-title")
        clocks_title.set_halign(Gtk.Align.START)
        clocks_box.append(clocks_title)
        
        clocks_desc = Gtk.Label(
            label=(
                f"Offset the GPU clocks from their default values. "
                f"Safety limited to ±{SafetyLimits.MAX_CORE_CLOCK_OFFSET_MHZ}MHz core, "
                f"±{SafetyLimits.MAX_MEMORY_CLOCK_OFFSET_MHZ}MHz memory.\n"
                f"Note: Offsets are only active under GPU load."
            )
        )
        clocks_desc.add_css_class("section-desc")
        clocks_desc.set_halign(Gtk.Align.START)
        clocks_desc.set_wrap(True)
        clocks_box.append(clocks_desc)
        
        # Core clock slider
        self.core_slider = LabeledSlider(
            title="Core Clock Offset",
            min_val=-SafetyLimits.MAX_CORE_CLOCK_OFFSET_MHZ,
            max_val=SafetyLimits.MAX_CORE_CLOCK_OFFSET_MHZ,
            step=5,
            unit=" MHz",
            format_func=lambda x: f"{x:+.0f}" if x != 0 else "0",
            warning_threshold=200  # Warning if > 200 MHz
        )
        self.core_slider.connect_changed(self._on_slider_changed)
        clocks_box.append(self.core_slider)
        
        # Memory clock slider
        self.memory_slider = LabeledSlider(
            title="Memory Clock Offset",
            min_val=-SafetyLimits.MAX_MEMORY_CLOCK_OFFSET_MHZ,
            max_val=SafetyLimits.MAX_MEMORY_CLOCK_OFFSET_MHZ,
            step=50,
            unit=" MHz",
            format_func=lambda x: f"{x:+.0f}" if x != 0 else "0",
            warning_threshold=500
        )
        self.memory_slider.connect_changed(self._on_slider_changed)
        clocks_box.append(self.memory_slider)
        
        # Buttons Logic
        clocks_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        clocks_actions.set_halign(Gtk.Align.END)
        
        # Reset Clocks
        reset_clocks_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        reset_clocks_btn.add_css_class("flat-action")
        reset_clocks_btn.set_tooltip_text("Reset Clock Offsets (0 MHz)")
        reset_clocks_btn.connect("clicked", self._on_reset_clocks_clicked)
        clocks_actions.append(reset_clocks_btn)
        
        # Apply Clocks
        apply_clocks_btn = Gtk.Button(label="Apply Clock Offsets")
        apply_clocks_btn.add_css_class("flat-action")
        apply_clocks_btn.connect("clicked", self._on_apply_clocks_clicked)
        clocks_actions.append(apply_clocks_btn)
        
        clocks_box.append(clocks_actions)
        
        clocks_frame.set_child(clocks_box)
        content.append(clocks_frame)

        # Advanced / Undervolt Section
        adv_frame = Gtk.Frame()
        adv_frame.add_css_class("control-section")
        
        adv_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        adv_box.set_margin_top(16)
        adv_box.set_margin_bottom(16)
        adv_box.set_margin_start(16)
        adv_box.set_margin_end(16)
        
        adv_title = Gtk.Label(label="⚡ Boost Ceiling (Undervolt)")
        adv_title.add_css_class("section-title")
        adv_title.set_halign(Gtk.Align.START)
        adv_box.append(adv_title)
        
        adv_desc = Gtk.Label(
            label="Cap maximum boost clock to reduce power and heat. Combine with negative Core Offset for undervolting. Set to 0 to disable (unlimited)."
        )
        adv_desc.add_css_class("section-desc")
        adv_desc.set_halign(Gtk.Align.START)
        adv_desc.set_wrap(True)
        adv_box.append(adv_desc)
        
        self.lock_slider = LabeledSlider(
            title="Boost Ceiling",
            min_val=0,
            max_val=3000,
            step=15,  # 15 MHz steps for finer control
            unit=" MHz",
            format_func=lambda x: "Unlimited" if x == 0 else f"{x:.0f}",
            tick_interval=500
        )
        self.lock_slider.connect_changed(self._on_slider_changed)
        adv_box.append(self.lock_slider)
        
        # Interaction warning
        lock_warning = Gtk.Label(label="Effective cap after apply shown as 'Readback' in Live Statistics.")
        lock_warning.add_css_class("helper-text")
        lock_warning.set_halign(Gtk.Align.START)
        adv_box.append(lock_warning)
        
        # Presets Box
        preset_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        preset_box.set_halign(Gtk.Align.START)
        preset_box.set_margin_bottom(8)
        
        preset_label = Gtk.Label(label="Presets:")
        preset_label.add_css_class("dim-label")
        preset_box.append(preset_label)
        
        # Conservative
        btn_conservative = Gtk.Button()
        c_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        c_title = Gtk.Label(label="Conservative")
        c_title.add_css_class("nav-label") # Reuse nav-label for bold small text
        c_desc = Gtk.Label(label="Lower clocks, max efficiency")
        c_desc.add_css_class("auto-hint") # Reuse auto-hint for small gray text
        c_box.append(c_title)
        c_box.append(c_desc)
        btn_conservative.set_child(c_box)
        btn_conservative.set_tooltip_text("Caps boost at ~1800 MHz for maximum stability.")
        btn_conservative.connect("clicked", lambda x: self._apply_preset(1800, 150))
        preset_box.append(btn_conservative)
        
        # Balanced
        btn_balanced = Gtk.Button()
        b_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        b_title = Gtk.Label(label="Balanced")
        b_title.add_css_class("nav-label")
        b_desc = Gtk.Label(label="Reduced voltage, minimal loss")
        b_desc.add_css_class("auto-hint")
        b_box.append(b_title)
        b_box.append(b_desc)
        btn_balanced.set_child(b_box)
        btn_balanced.set_tooltip_text("Caps boost at ~1950 MHz for performance-focused tuning.")
        btn_balanced.connect("clicked", lambda x: self._apply_preset(1950, 200))
        preset_box.append(btn_balanced)
        
        adv_box.append(preset_box)

        # Buttons Logic
        lock_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        lock_actions.set_halign(Gtk.Align.END)
        
        # Reset Lock
        reset_lock_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        reset_lock_btn.add_css_class("flat-action")
        reset_lock_btn.set_tooltip_text("Reset Frequency Lock (Disabled)")
        reset_lock_btn.connect("clicked", self._on_reset_lock_clicked)
        lock_actions.append(reset_lock_btn)
        
        # Apply Lock
        apply_lock_btn = Gtk.Button(label="Apply Frequency Lock")
        apply_lock_btn.add_css_class("suggested-action")
        apply_lock_btn.connect("clicked", self._on_apply_lock_clicked)
        lock_actions.append(apply_lock_btn)
        
        adv_box.append(lock_actions)
        
        adv_frame.set_child(adv_box)
        content.append(adv_frame)
        
        scroll.set_child(content)
        self.append(scroll)
        
        # Sticky action footer bar
        self.action_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.action_bar.add_css_class("action-footer")
        self.action_bar.set_halign(Gtk.Align.FILL)
        
        # Status label on the left
        self.status_label = Gtk.Label(label="")
        self.status_label.add_css_class("action-status")
        self.status_label.set_halign(Gtk.Align.START)
        self.status_label.set_hexpand(True)
        self.action_bar.append(self.status_label)
        
        # Buttons on the right
        self.reset_button = Gtk.Button(label="Reset to Stock")
        self.reset_button.add_css_class("destructive-action")
        self.reset_button.connect("clicked", self._on_reset_clicked)
        self.action_bar.append(self.reset_button)
        
        # Test Mode (temporary apply with auto-revert)
        self.test_button = Gtk.Button(label="Test (5m)")
        self.test_button.set_tooltip_text("Apply changes temporarily for 5 minutes, then auto-revert")
        self.test_button.connect("clicked", self._on_test_clicked)
        self.action_bar.append(self.test_button)
        self._test_timer_id = None  # Timer for auto-revert
        
        self.apply_button = Gtk.Button(label="Apply Changes")
        self.apply_button.add_css_class("suggested-action")
        self.apply_button.connect("clicked", self._on_apply_clicked)
        self.action_bar.append(self.apply_button)
        
        self.append(self.action_bar)
        
        # Load current values
        self._load_current_values()
    
    def _load_current_values(self) -> None:
        """Load current GPU values into sliders and stats."""
        if self._updating or self.controller is None:
            return
        
        self._updating = True
        try:
            # 1. Power constraints
            power = self.controller.get_power_limits()
            self.power_slider.set_range(power.min_watts, power.max_watts)
            self.power_slider.set_value(power.current_watts)
            self.power_slider.set_applied_value(power.current_watts)
            
            # Show power limit info
            self.power_info_label.set_label(
                f"Range: {power.min_watts:.0f}W - {power.max_watts:.0f}W | "
                f"Default: {power.default_watts:.0f}W"
            )
            
            # 2. Clock Offsets
            offsets = self.controller.get_clock_offsets()
            self.core_slider.set_value(offsets.core_offset_mhz)
            self.core_slider.set_applied_value(offsets.core_offset_mhz)
            self.memory_slider.set_value(offsets.memory_offset_mhz)
            self.memory_slider.set_applied_value(offsets.memory_offset_mhz)
            
            # 3. Live Stats (Effective Clocks & Throttle)
            stats = self.controller.get_gpu_stats()
            
            # Effective Core
            self.eff_core_label.set_label(f"{stats.effective_core_clock_mhz} MHz")
            
            # Last Load Peak
            if stats.peak_core_clock_mhz > 0:
                self.peak_label.set_label(f"{stats.peak_core_clock_mhz} MHz")
            else:
                self.peak_label.set_label("-- MHz")
            
            # Throttle Status
            if not stats.throttle_reasons:
                 self.throttle_label.set_markup("<span foreground='#2ecc71'>✓ No Throttling</span>")
            else:
                 reasons_str = ", ".join(stats.throttle_reasons)
                 self.throttle_label.set_markup(f"<span foreground='#e67e22'>⚠ {reasons_str}</span>")
            
            # Phase 13: Extended Monitoring Display
            # Rolling Average Clock
            if stats.avg_core_clock_mhz > 0:
                self.avg_clock_label.set_label(f"{stats.avg_core_clock_mhz} MHz")
            else:
                self.avg_clock_label.set_label("-- MHz")
            
            # PCIe Link State
            if stats.pcie_gen > 0:
                pcie_status = f"Gen{stats.pcie_gen} x{stats.pcie_width}"
                if stats.pcie_gen < stats.pcie_gen_max or stats.pcie_width < stats.pcie_width_max:
                    pcie_status += f" (Max: Gen{stats.pcie_gen_max} x{stats.pcie_width_max})"
                self.pcie_label.set_label(pcie_status)
            else:
                self.pcie_label.set_label("--")
            
            # Thermal Headroom
            if stats.thermal_headroom_celsius > 20:
                self.thermal_label.set_markup(f"<span foreground='#2ecc71'>+{stats.thermal_headroom_celsius}°C</span>")
            elif stats.thermal_headroom_celsius > 10:
                self.thermal_label.set_markup(f"<span foreground='#f5c211'>+{stats.thermal_headroom_celsius}°C</span>")
            else:
                self.thermal_label.set_markup(f"<span foreground='#e01b24'>+{stats.thermal_headroom_celsius}°C</span>")
            
            # Power Limit Status
            if stats.power_limit_active:
                self.power_limit_label.set_markup("<span foreground='#e67e22'>⚠ Active</span>")
            else:
                self.power_limit_label.set_markup("<span foreground='#2ecc71'>✓ Headroom</span>")
            
            # Stability Indicator (memory errors)
            if stats.memory_errors > 0:
                self.stability_value.set_markup(f"<span foreground='#e01b24'>⚠ {stats.memory_errors} errors</span>")
            else:
                self.stability_value.set_markup("<span foreground='#2ecc71'>✓ No errors</span>")
            
            # Update applied values on initial load
            if self._applied_values['power'] is None:
                self._applied_values = {
                    'power': power.current_watts,
                    'core': offsets.core_offset_mhz,
                    'memory': offsets.memory_offset_mhz,
                    'lock': 0 
                }
                # Also sync the lock slider
                self.lock_slider.set_value(0)
                self.lock_slider.set_applied_value(0)
                self._update_status_label()
            
        except Exception as e:
            logger.error(f"Failed to load current values: {e}")
        finally:
            self._updating = False
            
    def _on_apply_clicked(self, button: Gtk.Button) -> None:
        """Apply ALL settings."""
        self._on_apply_power_clicked(button)
        self._on_apply_clocks_clicked(button)
        self._on_apply_lock_clicked(button)

    def _on_apply_power_clicked(self, button: Gtk.Button) -> None:
        if self.controller is None: return
        try:
            power_watts = self.power_slider.get_value()
            self.controller.set_power_limit(power_watts)
            self._applied_values['power'] = power_watts
            self.power_slider.set_applied_value(power_watts)
            self._update_status_label()
            self._show_toast(get_narrative("power") or "Power profile active.")
        except Exception as e:
            self._show_toast(f"Error: {e}")

    def _on_apply_clocks_clicked(self, button: Gtk.Button) -> None:
        if self.controller is None: return
        try:
            core = int(self.core_slider.get_value())
            mem = int(self.memory_slider.get_value())
            self.controller.set_clock_offsets(core_offset_mhz=core, memory_offset_mhz=mem)
            self._applied_values['core'] = core
            self._applied_values['memory'] = mem
            self.core_slider.set_applied_value(core)
            self.memory_slider.set_applied_value(mem)
            self._update_status_label()
            self._show_toast(get_narrative("clocks") or "Clock offsets applied.")
        except Exception as e:
            self._show_toast(f"Error: {e}")

    def _on_apply_lock_clicked(self, button: Gtk.Button) -> None:
        if self.controller is None: return
        try:
            max_lock = int(self.lock_slider.get_value())
            self.controller.set_gpu_locked_clocks(0, max_lock)
            self._applied_values['lock'] = max_lock
            self.lock_slider.set_applied_value(max_lock)
            self._update_status_label()
            self._show_toast(get_narrative("apply") or "Settings locked in.")
        except Exception as e:
            self._show_toast(f"Error: {e}")

    def _on_reset_power_clicked(self, button: Gtk.Button) -> None:
        if self.controller is None: return
        try:
             limits = self.controller.get_power_limits()
             self.controller.set_power_limit(limits.default_watts)
             self.power_slider.set_value(limits.default_watts)
             self._show_toast("Power limit reset to default")
        except Exception as e:
             self._show_toast(f"Error: {e}")

    def _on_reset_clocks_clicked(self, button: Gtk.Button) -> None:
        if self.controller is None: return
        try:
             self.controller.reset_clock_offsets()
             self.core_slider.set_value(0)
             self.memory_slider.set_value(0)
             self._show_toast("Clock offsets reset")
        except Exception as e:
             self._show_toast(f"Error: {e}")

    def _on_reset_lock_clicked(self, button: Gtk.Button) -> None:
        if self.controller is None: return
        try:
             self.controller.set_gpu_locked_clocks(0, 0)
             self.lock_slider.set_value(0)
             self._show_toast("Frequency lock disabled (reset)")
        except Exception as e:
             self._show_toast(f"Error: {e}")

    def _apply_preset(self, max_lock: int, core_offset: int) -> None:
        if self.controller is None: return
        try:
            # Set Lock
            self.controller.set_gpu_locked_clocks(0, max_lock)
            self.lock_slider.set_value(max_lock)
            
            # Set Core Offset (Preserve Memory)
            current_mem = int(self.memory_slider.get_value())
            self.controller.set_clock_offsets(core_offset_mhz=core_offset, memory_offset_mhz=current_mem)
            self.core_slider.set_value(core_offset)
            
            self._show_toast(f"Applied Preset: {max_lock} MHz @ +{core_offset} MHz")
        except Exception as e:
            self._show_toast(f"Error: {e}")
    
    def _on_reset_clicked(self, button: Gtk.Button) -> None:
        """Reset to stock values."""
        if self.controller is None:
            return
        
        try:
            # Reset clock offsets to 0
            self.controller.reset_clock_offsets()
            # Reset locked clocks
            self.controller.set_gpu_locked_clocks(0, 0)
            
            # Reload values
            self.lock_slider.set_value(0)
            self._load_current_values()
            
            logger.info("Reset to stock values")
            self._show_toast("Reset to stock values")
            
        except Exception as e:
            logger.error(f"Failed to reset: {e}")
            self._show_toast(f"Error: {e}")
    
    def _show_toast(self, message: str) -> None:
        """Show a toast notification (if parent window supports it)."""
        # Find the parent window
        parent = self.get_root()
        if hasattr(parent, 'show_toast'):
            parent.show_toast(message)
        else:
            logger.info(f"Toast: {message}")
    
    def refresh(self) -> None:
        """Refresh displayed values from GPU."""
        if not self._applying and not self._updating:
            self._load_current_values()

    def _update_status_label(self) -> None:
        """Update the action bar status label based on pending changes."""
        if self._applied_values['power'] is None:
            return
        
        # Check for differences between current sliders and applied values
        power_diff = abs(self.power_slider.get_value() - self._applied_values['power']) > 0.5
        core_diff = int(self.core_slider.get_value()) != self._applied_values['core']
        mem_diff = int(self.memory_slider.get_value()) != self._applied_values['memory']
        lock_diff = int(self.lock_slider.get_value()) != self._applied_values['lock']
        
        self._pending_changes = power_diff or core_diff or mem_diff or lock_diff
        
        if self._pending_changes:
            changes = []
            if power_diff:
                changes.append(f"Power: {self._applied_values['power']:.0f}W → {self.power_slider.get_value():.0f}W")
            if core_diff:
                changes.append(f"Core: {self._applied_values['core']:+d} → {int(self.core_slider.get_value()):+d} MHz")
            if mem_diff:
                changes.append(f"Mem: {self._applied_values['memory']:+d} → {int(self.memory_slider.get_value()):+d} MHz")
            if lock_diff:
                applied_lock = "Disabled" if self._applied_values['lock'] == 0 else f"{self._applied_values['lock']} MHz"
                new_lock = "Disabled" if int(self.lock_slider.get_value()) == 0 else f"{int(self.lock_slider.get_value())} MHz"
                changes.append(f"Lock: {applied_lock} → {new_lock}")
            
            self.status_label.set_markup(f"<span foreground='#f5c211'>🟡 Pending: {', '.join(changes)}</span>")
        else:
            self.status_label.set_markup("<span foreground='#2ecc71'>🟢 Active</span>")

    def _on_reset_peak_clicked(self, button: Gtk.Button) -> None:
        """Reset the peak clock counter."""
        if self.controller is None: return
        try:
            self.controller.reset_peak_clock()
            self.peak_label.set_label("-- MHz")
            self._show_toast("Peak counter reset")
        except Exception as e:
            self._show_toast(f"Error: {e}")

    def _on_slider_changed(self, value: float) -> None:
        """Called when any slider value changes to update pending state."""
        if not self._updating:
            self._update_status_label()

    def _on_test_clicked(self, button: Gtk.Button) -> None:
        """Apply changes temporarily for 5 minutes, then auto-revert."""
        if self.controller is None:
            return
        
        # Cancel any existing test timer
        if self._test_timer_id is not None:
            GLib.source_remove(self._test_timer_id)
            self._test_timer_id = None
        
        # Save current values for revert
        try:
            power = self.controller.get_power_limits()
            offsets = self.controller.get_clock_offsets()
            self._pre_test_values = {
                'power': power.current_watts,
                'core': offsets.core_offset_mhz,
                'memory': offsets.memory_offset_mhz
            }
        except Exception as e:
            self._show_toast(f"Error saving state: {e}")
            return
        
        # Apply current slider values
        self._on_apply_clicked(button)
        
        # Start 5-minute revert timer (300,000 ms)
        self._test_timer_id = GLib.timeout_add(300000, self._on_test_revert)
        self.test_button.set_label("Testing...")
        self.test_button.set_sensitive(False)
        self._show_toast("Test mode: Settings will revert in 5 minutes")

    def _on_test_revert(self) -> bool:
        """Revert to pre-test values (called by timer)."""
        if self.controller is None or not hasattr(self, '_pre_test_values'):
            return False
        
        try:
            # Revert to saved values
            self.controller.set_power_limit(self._pre_test_values['power'])
            self.controller.set_clock_offsets(
                self._pre_test_values['core'],
                self._pre_test_values['memory']
            )
            self.controller.set_gpu_locked_clocks(0, 0)  # Disable freq lock
            
            # Update sliders to show reverted values
            self.power_slider.set_value(self._pre_test_values['power'])
            self.core_slider.set_value(self._pre_test_values['core'])
            self.memory_slider.set_value(self._pre_test_values['memory'])
            self.lock_slider.set_value(0)
            
            self._show_toast("Test complete: Settings reverted")
        except Exception as e:
            logger.error(f"Failed to revert test: {e}")
            self._show_toast(f"Revert error: {e}")
        finally:
            self.test_button.set_label("Test (5m)")
            self.test_button.set_sensitive(True)
            self._test_timer_id = None
        
        return False  # Don't repeat the timer

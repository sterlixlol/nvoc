"""
NVOC - Fan Control UI Component

Fan speed control with manual mode and custom fan curves.

FIXES:
- Proper commanded vs reported fan speed tracking
- Background daemon loop for curve mode (independent of UI)
- Reentrancy guards to prevent recursion
- Success/failure toasts
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk

from typing import Dict, List, Tuple, Optional
import logging
import threading
import time

from ..nvml_controller import SafetyLimits

logger = logging.getLogger(__name__)


class FanState:
    """
    Tracks fan control state.
    Separates commanded values from hardware-reported values.
    """
    def __init__(self):
        self.mode: str = "auto"  # "auto", "manual", "curve"
        self.commanded_speed: Optional[int] = None  # What we asked for
        self.reported_speed: Optional[int] = None   # What NVML reports (often 0 or wrong)
        self.current_temp: int = 0
        self.curve: Dict[int, int] = {}
        self._lock = threading.Lock()
    
    def set_mode(self, mode: str, speed: Optional[int] = None):
        with self._lock:
            self.mode = mode
            if mode == "manual":
                self.commanded_speed = speed
            elif mode == "auto":
                self.commanded_speed = None
    
    def get_display_speed(self) -> str:
        """Get a display string for fan speed."""
        with self._lock:
            if self.mode == "auto":
                    return f"{self.reported_speed}%"
            else:
                cmd = self.commanded_speed or 0
                if self.reported_speed is not None and self.reported_speed > 0:
                    return f"Target: {cmd}% (HW: {self.reported_speed}%)"
                else:
                    return f"Target: {cmd}% (HW: unavailable)"


class FanCurveDaemon:
    """
    Background daemon that runs the fan curve.
    Runs in a separate thread, independent of UI.
    """
    def __init__(self, controller, state: FanState):
        self.controller = controller
        self.state = state
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
    
    def start(self, curve: Dict[int, int]):
        """Start the fan curve daemon."""
        if self._running:
            self.stop()
        
        self.state.curve = curve.copy()
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Fan curve daemon started")
    
    def stop(self):
        """Stop the fan curve daemon."""
        if self._running:
            self._running = False
            self._stop_event.set()
            if self._thread:
                self._thread.join(timeout=3.0)
            logger.info("Fan curve daemon stopped")
    
    def _run_loop(self):
        """Main loop - runs every 1.5 seconds."""
        while self._running and not self._stop_event.is_set():
            try:
                self._update_fan_from_curve()
            except Exception as e:
                logger.error(f"Fan curve update error: {e}")
            
            # Sleep for 1.5 seconds, but check stop event frequently
            self._stop_event.wait(timeout=1.5)
    
    def _update_fan_from_curve(self):
        """Calculate and apply fan speed based on curve with hysteresis and ramp."""
        if not self.controller or not self.state.curve:
            return
        
        try:
            from ..config import get_config
            config = get_config()
            
            stats = self.controller.get_gpu_stats()
            temp = stats.temperature_celsius
            prev_temp = self.state.current_temp
            self.state.current_temp = temp
            
            curve = self.state.curve
            sorted_temps = sorted(curve.keys())
            
            if not sorted_temps:
                return
            
            # Apply hysteresis: only change target if temp moved past hysteresis threshold
            hysteresis = config.fan_hysteresis_celsius
            if hasattr(self, '_last_curve_temp'):
                temp_delta = temp - self._last_curve_temp
                if abs(temp_delta) < hysteresis:
                    # Use previous target, don't recalculate
                    target_speed = self._last_target_speed if hasattr(self, '_last_target_speed') else None
                    if target_speed is not None:
                        # Apply ramp limiting
                        target_speed = self._apply_ramp_limit(target_speed, config.fan_ramp_step_percent)
                        self.controller.set_all_fans_speed(target_speed)
                        self.state.commanded_speed = target_speed
                        return
            
            self._last_curve_temp = temp
            
            # Interpolate fan speed from curve
            if temp <= sorted_temps[0]:
                target_speed = curve[sorted_temps[0]]
            elif temp >= sorted_temps[-1]:
                target_speed = curve[sorted_temps[-1]]
            else:
                target_speed = curve[sorted_temps[0]]
                for i in range(len(sorted_temps) - 1):
                    t1, t2 = sorted_temps[i], sorted_temps[i + 1]
                    if t1 <= temp <= t2:
                        s1, s2 = curve[t1], curve[t2]
                        # Linear interpolation
                        target_speed = s1 + (s2 - s1) * (temp - t1) / (t2 - t1)
                        break
            
            # Apply min floor
            target_speed = max(config.min_fan_speed_percent, int(target_speed))
            self._last_target_speed = target_speed
            
            # Apply ramp limiting
            target_speed = self._apply_ramp_limit(target_speed, config.fan_ramp_step_percent)
            
            # Apply fan speed
            self.controller.set_all_fans_speed(target_speed)
            self.state.commanded_speed = target_speed
            
        except Exception as e:
            logger.error(f"Curve calculation error: {e}")

    def _apply_ramp_limit(self, target: int, max_step: int) -> int:
        """Limit speed change to max_step per cycle."""
        current = self.state.commanded_speed or target
        if target > current:
            return min(target, current + max_step)
        elif target < current:
            return max(target, current - max_step)
        return target


class FanCurveEditor(Gtk.DrawingArea):
    """Visual fan curve editor - click to add/move points."""
    
    def __init__(self):
        super().__init__()
        
        self._curve_points: List[Tuple[int, int]] = [
            (30, 30),   # 30°C -> 30%
            (50, 40),   # 50°C -> 40%
            (60, 50),   # 60°C -> 50%
            (70, 65),   # 70°C -> 65%
            (80, 85),   # 80°C -> 85%
            (90, 100),  # 90°C -> 100%
        ]
        self._selected_point: Optional[int] = None
        self._dragging = False
        self._callback = None
        
        self.set_content_width(400)
        self.set_content_height(250)
        self.set_hexpand(True)
        
        self.set_draw_func(self._draw)
        
        # Mouse interaction
        click_gesture = Gtk.GestureClick()
        click_gesture.connect("pressed", self._on_click)
        click_gesture.connect("released", self._on_release)
        self.add_controller(click_gesture)
        
        drag_gesture = Gtk.GestureDrag()
        drag_gesture.connect("drag-update", self._on_drag)
        self.add_controller(drag_gesture)
        
        # Right-click to delete points
        right_click = Gtk.GestureClick()
        right_click.set_button(3)  # Right mouse button
        right_click.connect("pressed", self._on_right_click)
        self.add_controller(right_click)
    
    def _draw(self, area, cr, width, height) -> None:
        """Draw the fan curve graph."""
        padding = 50  # Increased padding for labels
        graph_width = width - padding * 2
        graph_height = height - padding * 2
        
        # Background (match design system bg_subtle #141820)
        cr.set_source_rgb(0.078, 0.094, 0.125)  # #141820
        cr.rectangle(0, 0, width, height)
        cr.fill()
        
        # Graph area background (bg_surface #171A20)
        cr.set_source_rgb(0.090, 0.102, 0.125)  # #171A20
        cr.rectangle(padding, padding, graph_width, graph_height)
        cr.fill()
        
        # Grid lines (#242A36)
        cr.set_source_rgba(0.141, 0.165, 0.212, 0.7)  # #242A36
        cr.set_line_width(1)
        
        # Vertical grid (temperature)
        for temp in range(20, 101, 20):
            x = padding + (temp - 20) / 80 * graph_width
            cr.move_to(x, padding)
            cr.line_to(x, padding + graph_height)
            cr.stroke()
        
        # Horizontal grid (fan speed)
        for speed in range(0, 101, 20):
            y = padding + graph_height - (speed / 100 * graph_height)
            cr.move_to(padding, y)
            cr.line_to(padding + graph_width, y)
            cr.stroke()
        
        # Axis labels (#7E879A text_muted)
        cr.set_source_rgb(0.494, 0.529, 0.604)  # #7E879A
        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(10)
        
        # Temperature labels (X axis)
        for temp in range(20, 101, 20):
            x = padding + (temp - 20) / 80 * graph_width
            cr.move_to(x - 10, height - 25)  # Moved up
            cr.show_text(f"{temp}°C")
        
        # Fan speed labels (Y axis)
        for speed in range(0, 101, 20):
            y = padding + graph_height - (speed / 100 * graph_height)
            cr.move_to(5, y + 4)
            cr.show_text(f"{speed}%")
        
        # Draw the curve
        if len(self._curve_points) >= 2:
            # Sort points by temperature
            sorted_points = sorted(self._curve_points, key=lambda p: p[0])
            
            # Fill area under curve
            cr.set_source_rgba(0.3, 0.6, 0.9, 0.3)
            cr.move_to(padding, padding + graph_height)
            
            for temp, speed in sorted_points:
                x = padding + (temp - 20) / 80 * graph_width
                y = padding + graph_height - (speed / 100 * graph_height)
                cr.line_to(x, y)
            
            cr.line_to(padding + graph_width, padding + graph_height)
            cr.close_path()
            cr.fill()
            
            # Draw curve line (#2F7CF6 accent)
            cr.set_source_rgb(0.184, 0.486, 0.965)  # #2F7CF6
            cr.set_line_width(2.5)
            
            first_point = sorted_points[0]
            x = padding + (first_point[0] - 20) / 80 * graph_width
            y = padding + graph_height - (first_point[1] / 100 * graph_height)
            cr.move_to(x, y)
            
            for temp, speed in sorted_points[1:]:
                x = padding + (temp - 20) / 80 * graph_width
                y = padding + graph_height - (speed / 100 * graph_height)
                cr.line_to(x, y)
            
            cr.stroke()
            
            # Draw points
            for i, (temp, speed) in enumerate(self._curve_points):
                x = padding + (temp - 20) / 80 * graph_width
                y = padding + graph_height - (speed / 100 * graph_height)
                
                # Point circle
                if i == self._selected_point:
                    cr.set_source_rgb(0.965, 0.769, 0.271)  # #F6C445 warning (selected)
                else:
                    cr.set_source_rgb(0.184, 0.486, 0.965)  # #2F7CF6 accent
                
                cr.arc(x, y, 6, 0, 2 * 3.14159)
                cr.fill()
                
                # Point outline
                cr.set_source_rgb(1.0, 1.0, 1.0)
                cr.set_line_width(2)
                cr.arc(x, y, 6, 0, 2 * 3.14159)
                cr.stroke()
        
        # Axis titles (#AAB2C2 text_secondary)
        cr.set_source_rgb(0.667, 0.698, 0.761)  # #AAB2C2
        cr.set_font_size(12)
        cr.move_to(width / 2 - 40, height - 8)  # Centered bottom label
        cr.show_text("Temperature")
    
    def _get_point_at_coords(self, x: float, y: float) -> Optional[int]:
        """Find if a point is at given coordinates."""
        width = self.get_width()
        height = self.get_height()
        padding = 50
        graph_width = width - padding * 2
        graph_height = height - padding * 2
        
        for i, (temp, speed) in enumerate(self._curve_points):
            px = padding + (temp - 20) / 80 * graph_width
            py = padding + graph_height - (speed / 100 * graph_height)
            
            if abs(x - px) <= 10 and abs(y - py) <= 10:
                return i
        
        return None
    
    def _on_click(self, gesture, n_press, x, y) -> None:
        """Handle click - select or create point."""
        point_idx = self._get_point_at_coords(x, y)
        
        if point_idx is not None:
            self._selected_point = point_idx
            self._dragging = True
        else:
            # Add new point
            width = self.get_width()
            height = self.get_height()
            padding = 50
            graph_width = width - padding * 2
            graph_height = height - padding * 2
            
            if padding <= x <= width - padding and padding <= y <= height - padding:
                temp = int(20 + (x - padding) / graph_width * 80)
                speed = int(100 - (y - padding) / graph_height * 100)
                
                temp = max(20, min(100, temp))
                speed = max(SafetyLimits.MIN_FAN_SPEED_PERCENT, min(100, speed))
                
                self._curve_points.append((temp, speed))
                self._selected_point = len(self._curve_points) - 1
                self._notify_change()
        
        self.queue_draw()
    
    def _on_right_click(self, gesture, n_press, x, y) -> None:
        """Handle right-click - delete point."""
        point_idx = self._get_point_at_coords(x, y)
        if point_idx is not None and len(self._curve_points) > 2:
            del self._curve_points[point_idx]
            self._selected_point = None
            self._notify_change()
            self._notify_change()
            self.queue_draw()
    
    def _on_release(self, gesture, n_press, x, y) -> None:
        """Handle release."""
        self._dragging = False
    
    def _on_drag(self, gesture, offset_x, offset_y) -> None:
        """Handle drag - move selected point."""
        if not self._dragging or self._selected_point is None:
            return
        
        width = self.get_width()
        height = self.get_height()
        padding = 50
        graph_width = width - padding * 2
        graph_height = height - padding * 2
        
        success, start_x, start_y = gesture.get_start_point()
        if not success:
            return
        
        x = start_x + offset_x
        y = start_y + offset_y
        
        temp = int(20 + (x - padding) / graph_width * 80)
        speed = int(100 - (y - padding) / graph_height * 100)
        
        temp = max(20, min(100, temp))
        speed = max(SafetyLimits.MIN_FAN_SPEED_PERCENT, min(100, speed))
        
        self._curve_points[self._selected_point] = (temp, speed)
        self._notify_change()
        self.queue_draw()
    
    def _notify_change(self) -> None:
        if self._callback:
            self._callback(self.get_curve())
    
    def get_curve(self) -> Dict[int, int]:
        return {temp: speed for temp, speed in self._curve_points}
    
    def set_curve(self, curve: Dict[int, int]) -> None:
        self._curve_points = [(temp, speed) for temp, speed in curve.items()]
        self._selected_point = None
        self.queue_draw()
    
    def connect_changed(self, callback) -> None:
        self._callback = callback


class FansPage(Gtk.Box):
    """Fan control page with manual mode and custom curves."""
    
    def __init__(self, controller):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        
        self.controller = controller
        self._updating = False  # Reentrancy guard
        
        # Fan state tracking
        self._fan_state = FanState()
        self._curve_daemon: Optional[FanCurveDaemon] = None
        
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        self.set_margin_start(24)
        self.set_margin_end(24)
        
        # Mode selection
        mode_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        mode_box.set_halign(Gtk.Align.CENTER)
        
        mode_label = Gtk.Label(label="Fan Control Mode:")
        mode_label.add_css_class("mode-label")
        mode_box.append(mode_label)
        
        self.mode_dropdown = Gtk.DropDown.new_from_strings(
            ["Automatic (GPU Controlled)", "Manual (Fixed Speed)", "Custom Curve"]
        )
        self.mode_dropdown.set_selected(0)
        self.mode_dropdown.connect("notify::selected", self._on_mode_changed)
        mode_box.append(self.mode_dropdown)
        
        self.append(mode_box)
        
        # Stack for different mode contents
        self.mode_stack = Gtk.Stack()
        self.mode_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.mode_stack.set_vexpand(True)
        
        # Auto mode content - informative, not empty
        auto_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        auto_box.set_valign(Gtk.Align.CENTER)
        auto_box.set_halign(Gtk.Align.CENTER)
        auto_box.set_margin_top(24)
        auto_box.set_margin_bottom(24)
        
        # Info card
        auto_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        auto_card.add_css_class("auto-card")
        auto_card.set_halign(Gtk.Align.CENTER)
        
        # Header row with icon
        header_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header_row.set_halign(Gtk.Align.CENTER)
        
        auto_icon = Gtk.Image.new_from_icon_name("emblem-default-symbolic")
        auto_icon.set_pixel_size(24)
        auto_icon.add_css_class("auto-check-icon")
        header_row.append(auto_icon)
        
        auto_label = Gtk.Label(label="GPU-Controlled Fan Curve")
        auto_label.add_css_class("auto-title")
        header_row.append(auto_label)
        
        auto_card.append(header_row)
        
        # Description
        auto_desc = Gtk.Label(
            label="The GPU's firmware is managing fan speeds based on its\n"
                  "internal temperature targets. This is the safest mode."
        )
        auto_desc.add_css_class("auto-desc")
        auto_desc.set_justify(Gtk.Justification.CENTER)
        auto_card.append(auto_desc)
        
        auto_box.append(auto_card)
        
        # Live status
        self.auto_speed_label = Gtk.Label(label="Fan Speed: 0%")
        self.auto_speed_label.add_css_class("auto-speed")
        auto_box.append(self.auto_speed_label)
        
        # Action hint
        switch_hint = Gtk.Label(label="Switch to Manual or Custom Curve for direct control")
        switch_hint.add_css_class("auto-hint")
        auto_box.append(switch_hint)
        
        self.mode_stack.add_named(auto_box, "auto")
        
        # Manual mode content
        manual_wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        manual_wrapper.set_valign(Gtk.Align.CENTER)
        manual_wrapper.set_halign(Gtk.Align.CENTER)
        manual_wrapper.set_margin_top(24)
        manual_wrapper.set_margin_bottom(24)
        
        # Reuse auto-card style for consistency
        manual_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        manual_card.add_css_class("auto-card")
        manual_card.set_size_request(500, -1)  # Constrain width
        manual_wrapper.append(manual_card)
        
        # Header
        m_header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        m_header.set_halign(Gtk.Align.CENTER)
        
        m_title = Gtk.Label(label="Fixed Fan Speed")
        m_title.add_css_class("auto-title")
        m_header.append(m_title)
        
        m_desc = Gtk.Label(label="Set a constant speed for all fans. This overrides the default curve.")
        m_desc.add_css_class("auto-desc")
        m_desc.set_wrap(True)
        m_desc.set_max_width_chars(50)
        m_desc.set_justify(Gtk.Justification.CENTER)
        m_header.append(m_desc)
        
        manual_card.append(m_header)
        
        # Live Value Display
        self.manual_value_display = Gtk.Label(label="50%")
        self.manual_value_display.add_css_class("temp-value-hero")
        self.manual_value_display.set_halign(Gtk.Align.CENTER)
        manual_card.append(self.manual_value_display)
        
        # Manual speed slider
        self.manual_slider = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL,
            SafetyLimits.MIN_FAN_SPEED_PERCENT,
            100,
            1
        )
        self.manual_slider.set_value(50)
        self.manual_slider.set_hexpand(True)
        self.manual_slider.set_draw_value(False)
        self.manual_slider.set_margin_start(24)
        self.manual_slider.set_margin_end(24)
        
        self.manual_slider.add_mark(SafetyLimits.MIN_FAN_SPEED_PERCENT, Gtk.PositionType.BOTTOM, "Min Safe")
        self.manual_slider.add_mark(50, Gtk.PositionType.BOTTOM, None)
        self.manual_slider.add_mark(100, Gtk.PositionType.BOTTOM, "100%")
        
        self.manual_slider.connect("value-changed", self._on_manual_slider_changed)
        
        manual_card.append(self.manual_slider)
        
        # Target display
        self.manual_target_label = Gtk.Label(label="")
        self.manual_target_label.add_css_class("target-label")
        self.manual_target_label.set_halign(Gtk.Align.CENTER)
        manual_card.append(self.manual_target_label)
        
        manual_apply = Gtk.Button(label="Apply Fan Speed")
        manual_apply.add_css_class("suggested-action")
        manual_apply.set_halign(Gtk.Align.CENTER)
        manual_apply.connect("clicked", self._on_manual_apply)
        manual_card.append(manual_apply)
        
        self.mode_stack.add_named(manual_wrapper, "manual")
        
        # Custom curve content
        curve_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        
        curve_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        
        curve_label = Gtk.Label(label="Custom Fan Curve")
        curve_label.add_css_class("curve-title")
        curve_label.set_hexpand(True)
        curve_label.set_halign(Gtk.Align.START)
        curve_header.append(curve_label)
        
        # Curve status indicator
        self.curve_status = Gtk.Label(label="")
        self.curve_status.add_css_class("curve-status")
        curve_header.append(self.curve_status)
        
        curve_box.append(curve_header)
        
        curve_desc = Gtk.Label(
            label="Click to add points, drag to move, right-click to delete.\n"
                  "Fan speed adjusts automatically based on GPU temperature."
        )
        curve_desc.add_css_class("curve-desc")
        curve_desc.set_halign(Gtk.Align.START)
        curve_desc.set_justify(Gtk.Justification.LEFT)
        curve_desc.set_xalign(0)
        curve_box.append(curve_desc)
        
        # Fan curve editor
        self.curve_editor = FanCurveEditor()
        curve_box.append(self.curve_editor)
        
        # Curve controls
        curve_controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        curve_controls.set_halign(Gtk.Align.CENTER)
        
        reset_curve = Gtk.Button(label="Reset to Default")
        reset_curve.connect("clicked", self._on_reset_curve)
        curve_controls.append(reset_curve)
        
        self.apply_curve_btn = Gtk.Button(label="Apply Curve")
        self.apply_curve_btn.add_css_class("suggested-action")
        self.apply_curve_btn.connect("clicked", self._on_apply_curve)
        curve_controls.append(self.apply_curve_btn)
        
        self.stop_curve_btn = Gtk.Button(label="Stop Curve")
        self.stop_curve_btn.add_css_class("destructive-action")
        self.stop_curve_btn.connect("clicked", self._on_stop_curve)
        self.stop_curve_btn.set_sensitive(False)
        curve_controls.append(self.stop_curve_btn)
        
        curve_box.append(curve_controls)
        
        self.mode_stack.add_named(curve_box, "curve")
        
        self.append(self.mode_stack)
        
        # Current status
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
        status_box.set_halign(Gtk.Align.CENTER)
        status_box.add_css_class("fan-status")
        
        self.current_temp_label = Gtk.Label(label="GPU Temp: --°C")
        status_box.append(self.current_temp_label)
        
        self.current_speed_label = Gtk.Label(label="Fan: --")
        status_box.append(self.current_speed_label)
        
        self.append(status_box)
    
    def _on_mode_changed(self, dropdown, param) -> None:
        """Handle mode change."""
        if self._updating:
            return
        
        selected = dropdown.get_selected()
        
        # Stop curve daemon when leaving curve mode
        if self._curve_daemon:
            self._curve_daemon.stop()
            self._curve_daemon = None
            self._update_curve_buttons(False)
        
        if selected == 0:  # Auto
            self.mode_stack.set_visible_child_name("auto")
            self._set_auto_mode()
        elif selected == 1:  # Manual
            self.mode_stack.set_visible_child_name("manual")
        else:  # Custom curve
            self.mode_stack.set_visible_child_name("curve")
    
    def _set_auto_mode(self) -> None:
        """Set fans to automatic control."""
        if self.controller is None:
            return
        
        try:
            self.controller.set_all_fans_auto()
            self._fan_state.set_mode("auto")
            self._show_toast("Fans set to automatic control")
            logger.info("Fans set to automatic control")
        except Exception as e:
            self._show_toast(f"Failed: {e}")
            logger.error(f"Failed to set auto mode: {e}")
    
    def _on_manual_slider_changed(self, scale: Gtk.Scale) -> None:
        """Update manual value display."""
        val = int(scale.get_value())
        self.manual_value_display.set_label(f"{val}%")

    def _on_manual_apply(self, button) -> None:
        """Apply manual fan speed."""
        if self.controller is None:
            return
        
        try:
            speed = int(self.manual_slider.get_value())
            self.controller.set_all_fans_speed(speed)
            self._fan_state.set_mode("manual", speed)
            self._show_toast(f"Fan speed set to {speed}%")
            logger.info(f"Fan speed set to {speed}%")
        except Exception as e:
            self._show_toast(f"Failed: {e}")
            logger.error(f"Failed to set fan speed: {e}")
    
    def _on_reset_curve(self, button) -> None:
        """Reset to default curve."""
        default_curve = {30: 30, 50: 40, 60: 50, 70: 65, 80: 85, 90: 100}
        self.curve_editor.set_curve(default_curve)
    
    def _on_apply_curve(self, button) -> None:
        """Start applying the custom fan curve."""
        if self.controller is None:
            return
        
        curve = self.curve_editor.get_curve()
        if len(curve) < 2:
            self._show_toast("Need at least 2 points in curve")
            return
        
        # Start the curve daemon
        self._fan_state.set_mode("curve")
        self._curve_daemon = FanCurveDaemon(self.controller, self._fan_state)
        self._curve_daemon.start(curve)
        
        self._update_curve_buttons(True)
        self._show_toast("Fan curve activated")
        logger.info("Custom fan curve activated")
    
    def _on_stop_curve(self, button) -> None:
        """Stop the fan curve and return to auto."""
        if self._curve_daemon:
            self._curve_daemon.stop()
            self._curve_daemon = None
        
        self._update_curve_buttons(False)
        self._set_auto_mode()
        self._show_toast("Fan curve stopped")
    
    def _update_curve_buttons(self, curve_active: bool) -> None:
        """Update button states based on curve status."""
        self.apply_curve_btn.set_sensitive(not curve_active)
        self.stop_curve_btn.set_sensitive(curve_active)
        
        if curve_active:
            self.curve_status.set_label("● ACTIVE")
            self.curve_status.add_css_class("curve-active")
        else:
            self.curve_status.set_label("")
            self.curve_status.remove_css_class("curve-active")
    
    def _show_toast(self, message: str) -> None:
        """Show a toast notification."""
        parent = self.get_root()
        if hasattr(parent, 'show_toast'):
            parent.show_toast(message)
        else:
            logger.info(f"Toast: {message}")
    
    def update_stats(self) -> None:
        """Update displayed fan stats."""
        if self._updating or self.controller is None:
            return
        
        self._updating = True
        try:
            stats = self.controller.get_gpu_stats()
            
            # Update state with reported values
            self._fan_state.reported_speed = stats.fan_speed_percent
            self._fan_state.current_temp = stats.temperature_celsius
            
            # Update temperature display with color coding
            temp = stats.temperature_celsius
            if temp < 45:
                temp_status = "Cool"
            elif temp < 65:
                temp_status = "Normal"
            elif temp < 80:
                temp_status = "Hot"
            else:
                temp_status = "⚠️ CRITICAL"
            
            self.current_temp_label.set_label(f"GPU: {temp}°C ({temp_status})")
            
            # Update fan speed display (commanded vs reported)
            speed_display = self._fan_state.get_display_speed()
            
            # Fan Wording Polish
            if self._fan_state.mode == "auto" and stats.fan_speed_percent == 0:
                self.current_speed_label.set_label("Fan: 0% (Zero-RPM)")
                self.auto_speed_label.set_label("Fan Speed: 0% (Zero-RPM Mode)")
            else:
                self.current_speed_label.set_label(f"Fan: {speed_display}")
                self.auto_speed_label.set_label(f"Fan Speed: {speed_display}")
            
            # Update manual mode target display
            if self._fan_state.mode == "manual" and self._fan_state.commanded_speed:
                self.manual_target_label.set_label(
                    f"Target: {self._fan_state.commanded_speed}%"
                )
            
        except Exception as e:
            logger.error(f"Failed to update fan stats: {e}")
        finally:
            self._updating = False

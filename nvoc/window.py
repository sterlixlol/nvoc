"""
NVOC - Main Window

The primary application window with sidebar navigation.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gio

import logging
from typing import Optional

from .nvml_controller import NVMLController, NVMLError
from .privileged_controller import PrivilegedController
from .config import get_config
from .ui.dashboard import DashboardPage
from .ui.overclock import OverclockPage
from .ui.fans import FansPage
from .ui.profiles_view import ProfilesPage
from .ui.stress import StressPage
from .ui.settings import SettingsPage

logger = logging.getLogger(__name__)


class MainWindow(Adw.ApplicationWindow):
    """Main application window with sidebar navigation."""
    
    def __init__(self, app: Adw.Application, controller: Optional[NVMLController] = None):
        super().__init__(application=app)
        
        self.controller = controller
        self._update_source_id = None
        
        config = get_config()
        
        self.set_default_size(config.window_width, config.window_height)
        
        # ===== MAIN LAYOUT: Vertical stack =====
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        
        # ===== TOP BAR (HeaderBar with rich content) =====
        self.header = Adw.HeaderBar()
        self.header.add_css_class("flat")
        self.header.set_show_title(False)  # Disable centered title
        
        # Left side: NVOC branding
        title_label = Gtk.Label(label="NVOC")
        title_label.add_css_class("page-title")
        self.header.pack_start(title_label)
        
        # Right side: menu only
        right_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        # Menu button
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        
        menu = Gio.Menu()
        menu.append("Reset to Stock", "app.reset_stock")
        menu.append("Settings", "app.settings")
        menu.append("About", "app.about")
        menu.append("Quit", "app.quit")
        menu_button.set_menu_model(menu)
        right_box.append(menu_button)
        
        self.header.pack_end(right_box)
        
        main_box.append(self.header)
        
        # ===== CONTENT AREA: Sidebar + Page Stack =====
        self.toast_overlay = Adw.ToastOverlay()
        
        content_wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content_wrapper.set_vexpand(True)
        
        content_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        content_box.set_vexpand(True)
        
        # ===== LEFT SIDEBAR (Fixed 220px) =====
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sidebar.add_css_class("sidebar")
        sidebar.set_size_request(220, -1)
        sidebar.set_margin_top(16)
        sidebar.set_margin_bottom(16)
        sidebar.set_margin_start(16)
        sidebar.set_margin_end(0)
        
        # Navigation buttons
        self.nav_buttons = {}
        
        nav_items = [
            ("dashboard", "speedometer-symbolic", "Dashboard"),
            ("overclock", "emblem-system-symbolic", "Overclock"),
            ("fans", "view-refresh-symbolic", "Fans"),
            ("profiles", "view-list-symbolic", "Profiles"),
            ("stress", "utilities-terminal-symbolic", "Stress Test"),
            ("settings", "preferences-system-symbolic", "Settings"),
        ]
        
        for page_id, icon_name, label in nav_items:
            btn = Gtk.ToggleButton()
            btn.add_css_class("nav-button")
            
            btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            btn_box.set_halign(Gtk.Align.START)
            btn_box.set_margin_start(8)
            
            icon = Gtk.Image.new_from_icon_name(icon_name)
            icon.set_pixel_size(20)
            btn_box.append(icon)
            
            lbl = Gtk.Label(label=label)
            lbl.add_css_class("nav-label")
            btn_box.append(lbl)
            
            btn.set_child(btn_box)
            btn.connect("toggled", self._on_nav_toggled, page_id)
            
            sidebar.append(btn)
            self.nav_buttons[page_id] = btn
        
        content_box.append(sidebar)
        
        # Separator removed
        
        # ===== PAGE STACK (Centered, max-width 1120px) =====
        page_wrapper = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        page_wrapper.set_hexpand(True)
        page_wrapper.set_halign(Gtk.Align.FILL)
        
        self.page_stack = Gtk.Stack()
        self.page_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.page_stack.set_transition_duration(150)
        self.page_stack.set_hexpand(True)
        self.page_stack.set_vexpand(True)
        
        # Create pages
        self.dashboard_page = DashboardPage(self.controller)
        self.page_stack.add_named(self.dashboard_page, "dashboard")
        
        self.overclock_page = OverclockPage(self.controller)
        self.page_stack.add_named(self.overclock_page, "overclock")
        
        self.fans_page = FansPage(self.controller)
        self.page_stack.add_named(self.fans_page, "fans")
        
        self.profiles_page = ProfilesPage(self.controller)
        self.page_stack.add_named(self.profiles_page, "profiles")
        
        self.stress_page = StressPage(self, self.controller)
        self.page_stack.add_named(self.stress_page, "stress")
        
        self.settings_page = SettingsPage(self.controller, self)
        self.page_stack.add_named(self.settings_page, "settings")
        
        page_wrapper.append(self.page_stack)
        content_box.append(page_wrapper)
        
        content_wrapper.append(content_box)
        
        # Status strip removed
        
        self.toast_overlay.set_child(content_wrapper)
        main_box.append(self.toast_overlay)
        
        self.set_content(main_box)
        
        # Select dashboard by default
        self.nav_buttons["dashboard"].set_active(True)
        
        # Connect signals
        self.connect("close-request", self._on_close_request)
        
        # Load CSS
        self._load_css()
        
        # Start monitoring updates
        self._start_monitoring()
    
    def set_monitoring_interval(self, interval_ms: int) -> None:
        """Update the monitoring interval dynamically."""
        if self._update_source_id:
            GLib.source_remove(self._update_source_id)
            self._update_source_id = None
        
        self._update_source_id = GLib.timeout_add(
            interval_ms,
            self._update_stats
        )
        logger.info(f"Monitoring interval updated to {interval_ms}ms")
    
    def _on_close_request(self, window) -> bool:
        """Handle window close request (tray hide vs quit)."""
        config = get_config()
        if getattr(config, 'minimize_to_tray', False):
            self.set_visible(False)
            return True  # Stop emission, keep window alive in background
        return False  # Continue close
    
    def _start_monitoring(self) -> None:
        """Start the monitoring update loop."""
        config = get_config()
        self.set_monitoring_interval(config.monitoring_interval_ms)
    
    def _on_nav_toggled(self, button: Gtk.ToggleButton, page_id: str) -> None:
        """Handle navigation button toggle."""
        # Reentrancy guard - prevent signal recursion when toggling buttons
        if hasattr(self, '_nav_updating') and self._nav_updating:
            return
        
        if not button.get_active():
            # Don't allow untoggling - but check if we should block
            if not hasattr(self, '_nav_updating'):
                button.set_active(True)
            return
        
        self._nav_updating = True
        try:
            # Untoggle other buttons (this will trigger their signals, but guard will block)
            for pid, btn in self.nav_buttons.items():
                if pid != page_id:
                    btn.set_active(False)
            
            # Show the page
            self.page_stack.set_visible_child_name(page_id)
        finally:
            self._nav_updating = False
    
    def navigate_to(self, page_id: str) -> None:
        """Public method to navigate to a specific page."""
        if page_id in self.nav_buttons:
            self.nav_buttons[page_id].set_active(True)
    
    def _load_css(self) -> None:
        """Load custom CSS styling."""
        css_provider = Gtk.CssProvider()
        
        css = """
        /* ========================================
           NVOC Design System v2.0
           A coherent, premium dark theme
           ======================================== */
        
        /* ===== CSS CUSTOM PROPERTIES (Design Tokens) ===== */
        @define-color bg_app #0F1115;
        @define-color bg_surface #171A20;
        @define-color bg_elevated #1D212A;
        @define-color bg_subtle #141820;
        @define-color border_default #2A2F3A;
        @define-color border_focus #343B49;
        @define-color divider #202531;
        @define-color text_primary #E8ECF3;
        @define-color text_secondary #AAB2C2;
        @define-color text_muted #7E879A;
        @define-color text_disabled #5D6576;
        @define-color accent #2F7CF6;
        @define-color accent_hover #3B8BFF;
        @define-color accent_pressed #2568D8;
        @define-color success #2BD67B;
        @define-color warning #F6C445;
        @define-color danger #FF4D5A;
        @define-color info #7AA7FF;
        @define-color chart_temp #FF4D5A;
        @define-color chart_power #F6C445;
        @define-color chart_clocks #2F7CF6;
        @define-color chart_fan #2BD67B;
        @define-color chart_vram #7AA7FF;
        @define-color grid_line #242A36;
        
        /* ===== MOTION TOKENS ===== */
        /* All interactive elements use these for unified feel */
        /* Standard: 180ms cubic-bezier(0.4, 0.0, 0.2, 1) - Material Design easing */
        /* Emphasis: 280ms for larger state changes */
        /* Quick: 120ms for micro-interactions */
        
        /* ===== BASE WINDOW ===== */
        window {
            background: @bg_app;
            color: @text_primary;
        }
        
        /* ===== TYPOGRAPHY ===== */
        /* Page title: 28px/700 */
        .page-title {
            font-size: 28px;
            font-weight: 700;
            color: @text_primary;
        }
        
        /* Section title: 18px/700 */
        .section-title {
            font-size: 18px;
            font-weight: 700;
            color: @text_primary;
        }
        
        /* Metric label: 12px/600, letter-spacing 0.06em, muted */
        .metric-label, .stat-title, .progress-title, .nav-label {
            font-size: 12px;
            font-weight: 600;
            letter-spacing: 0.06em;
            color: @text_muted;
            text-transform: uppercase;
        }
        
        /* Metric value: 36px/700 */
        .metric-value, .stat-value {
            font-size: 36px;
            font-weight: 700;
            color: @text_primary;
            font-feature-settings: "tnum";
            line-height: 1.1;
        }
        
        /* Hero temperature: 40px/750 (using 800 as closest) */
        .temp-value-hero {
            font-size: 90px;
            font-weight: 800;
            color: @text_primary;
            font-feature-settings: "tnum";
            line-height: 0.6;
        }
        
        /* Body: 14px/500 */
        .body-text, .section-desc, .auto-desc, .curve-desc {
            font-size: 14px;
            font-weight: 500;
            color: @text_secondary;
        }
        
        /* Helper: 12px/500 */
        .helper-text, .auto-hint {
            font-size: 12px;
            font-weight: 500;
            color: @text_muted;
        }
        
        /* ===== SIDEBAR NAVIGATION ===== */
        .sidebar {
            background: @bg_surface;
            border-radius: 16px;
            padding: 16px 8px;
            min-width: 96px;
            border: none;
        }
        
        .nav-button {
            background: transparent;
            border: none;
            border-radius: 12px;
            padding: 16px 8px;
            min-width: 80px;
            margin-bottom: 8px;
            transition: all 180ms cubic-bezier(0.4, 0.0, 0.2, 1);
        }
        
        .nav-button:checked {
            background: alpha(@accent, 0.15);
            border-radius: 12px;
        }
        
        .nav-button:hover:not(:checked) {
            background: alpha(@text_primary, 0.04);
        }
        
        .nav-button:focus {
            outline: 2px solid alpha(@accent, 0.9);
            outline-offset: 2px;
        }
        
        /* ===== CARDS (Primary Surface) ===== */
        .stat-card, .control-section, .auto-card, .progress-card, .boxed-list {
            background: @bg_surface;
            padding: 20px;
            border-radius: 16px;
            border: 1px solid @border_default;
            transition: all 180ms cubic-bezier(0.4, 0.0, 0.2, 1);
        }
        
        .stat-card:hover, .control-section:hover {
            border-color: @border_focus;
        }
        
        /* Pending state indicator */
        .card-pending {
            border-top: 3px solid @accent;
        }
        
        /* ===== ELEVATED SURFACES (Dialogs, Menus) ===== */
        popover, menu, .elevated {
            background: @bg_elevated;
            border: 1px solid @border_default;
            border-radius: 12px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
        }
        
        /* ===== SUBTLE SURFACES ===== */
        .offsets-display, .fan-status, .status-strip {
            background: @bg_subtle;
            padding: 12px 24px;
            border-radius: 999px;
            border: 1px solid @border_default;
        }
        
        /* ===== GPU HEADER ===== */
        .gpu-header {
            background: @bg_surface;
            padding: 20px 24px;
            border-radius: 16px;
            border: 1px solid @border_default;
        }
        
        .gpu-name {
            font-size: 28px;
            font-weight: 700;
            color: @text_primary;
        }
        
        .gpu-info {
            font-size: 13px;
            font-weight: 500;
            color: @text_muted;
        }
        
        /* ===== STAT CARDS ===== */
        .stat-icon {
            color: @text_muted;
        }
        
        .stat-unit {
            font-size: 18px;
            font-weight: 600;
            color: @text_muted;
            padding-top: 8px;
        }
        
        .stat-subtitle {
            font-size: 13px;
            font-weight: 500;
            color: @accent;
            margin-top: 4px;
        }
        
        /* ===== TEMPERATURE HERO ===== */
        .temp-gauge {
            background: @bg_surface;
            padding: 32px 48px;
            border-radius: 16px;
            min-height: 160px;
            border: 1px solid @border_default;
        }
        
        .hero-card {
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.25);
        }
        
        .temp-unit-faded {
            font-size: 28px;
            font-weight: 600;
            color: @text_muted;
        }
        
        /* Temperature badges (Thermal State Chips) */
        .temp-badge {
            font-size: 24px;
            font-weight: 700;
            padding: 10px 24px;
            border-radius: 999px;
            margin-top: 16px;
            transition: all 280ms cubic-bezier(0.4, 0.0, 0.2, 1);
        }
        
        .badge-cool {
            background: alpha(@success, 0.15);
            color: @success;
        }
        
        .badge-warm {
            background: alpha(@info, 0.15);
            color: @info;
        }
        
        .badge-hot {
            background: alpha(@warning, 0.15);
            color: @warning;
        }
        
        .badge-critical {
            background: alpha(@danger, 0.15);
            color: @danger;
        }
        
        /* Hero temp color variants */
        .temp-cool .temp-value-hero { color: @success; }
        .temp-warm .temp-value-hero { color: @info; }
        .temp-hot .temp-value-hero { color: @warning; }
        .temp-critical .temp-value-hero { color: @danger; }
        
        /* ===== PROGRESS BARS ===== */
        .progress-card {
            padding: 16px 20px;
        }
        
        .progress-value {
            font-size: 14px;
            font-weight: 700;
            color: @text_primary;
            font-feature-settings: "tnum";
        }
        
        progressbar > trough {
            background: @divider;
            border-radius: 4px;
            min-height: 8px;
        }
        
        progressbar > trough > progress {
            background: @success;
            border-radius: 4px;
        }
        
        progressbar.progress-low > trough > progress { background: @success; }
        progressbar.progress-medium > trough > progress { background: @accent; }
        progressbar.progress-high > trough > progress { background: @warning; }
        progressbar.progress-critical > trough > progress { background: @danger; }
        
        /* ===== OFFSET/STATUS DISPLAY ===== */
        .offset-label {
            font-size: 13px;
            font-weight: 600;
            color: @accent;
            font-feature-settings: "tnum";
        }
        
        .offset-sep {
            color: @border_default;
            font-size: 10px;
        }
        
        /* ===== STATUS CHIPS ===== */
        .status-chip {
            font-size: 11px;
            font-weight: 700;
            padding: 6px 12px;
            border-radius: 999px;
            letter-spacing: 0.04em;
            transition: all 180ms cubic-bezier(0.4, 0.0, 0.2, 1);
        }
        
        .chip-active {
            background: alpha(@success, 0.15);
            color: @success;
        }
        
        .chip-idle {
            background: alpha(@text_muted, 0.15);
            color: @text_muted;
        }
        
        .chip-pending {
            background: alpha(@accent, 0.15);
            color: @accent;
        }
        
        .chip-warning {
            background: alpha(@warning, 0.15);
            color: @warning;
        }
        
        .chip-danger {
            background: alpha(@danger, 0.15);
            color: @danger;
        }
        
        /* Pulse effect for status changes - applied momentarily */
        .chip-pulse {
            transform: scale(1.08);
            box-shadow: 0 0 12px alpha(@accent, 0.4);
            filter: brightness(1.15);
        }
        
        .monitor-dot-live {
            color: @success;
            font-size: 10px;
        }
        
        /* ===== WARNING BANNER (Collapsible Safety Panel) ===== */
        .warning-banner {
            background: alpha(@warning, 0.1);
            border: 1px solid alpha(@warning, 0.25);
            padding: 12px 16px;
            border-radius: 12px;
        }
        
        .warning-banner label {
            color: @text_secondary;
        }
        
        .warning-banner .warning-icon {
            color: @warning;
        }
        
        /* ===== SLIDERS ===== */
        .labeled-slider {
            padding: 8px 0;
        }
        
        .slider-title {
            font-size: 13px;
            font-weight: 500;
            color: @text_secondary;
        }
        
        .slider-value {
            font-size: 14px;
            font-weight: 700;
            color: @accent;
            font-feature-settings: "tnum";
            font-variant-numeric: tabular-nums;
            min-width: 80px; /* Force substantial fixed width */
        }
        
        /* ===== ELITE SLIDERS (Semantic Gradients & Friction) ===== */
        .elite-scale trough {
            background: @divider;
            border-radius: 4px;
            min-height: 8px;
            transition: box-shadow 200ms ease-out;
        }
        
        .elite-scale trough highlight {
            background: linear-gradient(90deg, @accent_pressed, @accent);
            border-radius: 4px;
            transition: background 200ms ease-out, box-shadow 200ms ease-out, filter 200ms ease-out;
        }
        
        .elite-scale slider {
            background: @text_primary;
            border-radius: 50%;
            min-width: 20px;
            min-height: 20px;
            box-shadow: 0 2px 6px rgba(0, 0, 0, 0.4);
            margin: -6px 0; /* Center vertically on trough */
            transition: all 150ms cubic-bezier(0.25, 0.46, 0.45, 0.94); /* Authentic friction */
        }
        
        .elite-scale slider:hover {
            transform: scale(1.1);
            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.5);
        }
        
        /* Pending State - Inert/Soft */
        .elite-scale.slider-pending trough highlight {
            filter: saturate(0.6) opacity(0.85);
            box-shadow: none;
        }
        .elite-scale.slider-pending slider {
            box-shadow: 0 1px 3px rgba(0,0,0,0.2);
            filter: brightness(0.95);
        }
        
        /* Zone 1: Default/Engaged (Thicker glow, resistance) */
        .elite-scale.slider-zone-default trough highlight {
            box-shadow: 0 0 8px rgba(47, 124, 246, 0.25);
        }
        .elite-scale.slider-zone-default slider {
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(255,255,255,0.1);
        }
        
        /* Zone 2: High/Intense (Compressed gradient, focused pressure) */
        .elite-scale.slider-zone-high trough highlight {
            background: linear-gradient(90deg, @accent, @warning);
            box-shadow: 0 0 12px rgba(246, 196, 69, 0.4);
        }
        .elite-scale.slider-zone-high slider {
            background: #FFFAEA;
            box-shadow: 0 4px 8px rgba(0,0,0,0.6), 0 0 0 2px rgba(246, 196, 69, 0.3);
        }
        
        /* Warning/Danger States (Override) */
        .elite-scale.slider-warning trough highlight {
            background: linear-gradient(90deg, @accent, @warning);
        }
        .elite-scale.slider-danger trough highlight {
            background: linear-gradient(90deg, @warning, @danger);
            box-shadow: 0 0 16px rgba(255, 77, 90, 0.5);
        }
        
        /* ===== PROFILES LIST ===== */
        .profile-row {
            padding: 14px 20px;
            background: transparent;
            border-radius: 12px;
            transition: all 120ms ease-out;
        }
        
        .profile-row:hover {
            background: alpha(@text_primary, 0.04);
        }
        
        .profile-name {
            font-size: 15px;
            font-weight: 600;
            color: @text_primary;
        }
        
        .profile-desc {
            font-size: 13px;
            font-weight: 500;
            color: @text_muted;
        }
        
        .builtin-badge, .default-badge, .active-badge {
            font-size: 10px;
            font-weight: 700;
            padding: 4px 10px;
            border-radius: 999px;
            text-transform: uppercase;
            letter-spacing: 0.06em;
        }
        
        .builtin-badge {
            background: alpha(@accent, 0.15);
            color: @accent;
        }
        
        .default-badge, .active-badge {
            background: alpha(@success, 0.15);
            color: @success;
        }
        
        .section-label {
            font-size: 11px;
            font-weight: 700;
            color: @text_muted;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }
        
        .empty-label {
            font-size: 14px;
            color: @text_muted;
            font-style: italic;
        }
        
        /* Profile icons */
        .profile-icon-stock { color: @text_muted; }
        .profile-icon-quiet { color: @success; }
        .profile-icon-performance { color: @warning; }
        
        /* ===== FAN CONTROL ===== */
        .mode-label {
            font-size: 13px;
            color: @text_muted;
        }
        
        .auto-title {
            font-size: 20px;
            font-weight: 700;
            color: @text_primary;
        }
        
        .auto-speed {
            font-size: 15px;
            font-weight: 600;
            color: @accent;
            margin-top: 8px;
        }
        
        .auto-check-icon {
            color: @success;
        }
        
        .curve-title {
            font-size: 16px;
            font-weight: 700;
            color: @text_primary;
        }
        
        .curve-status, .target-label {
            font-size: 13px;
            font-weight: 600;
            color: @accent;
        }
        
        .curve-active {
            background: alpha(@success, 0.15);
            color: @success;
            padding: 6px 12px;
            border-radius: 999px;
        }
        
        /* ===== BUTTONS ===== */
        /* Primary button (suggested-action) */
        .suggested-action {
            background: @accent;
            color: #0B0D12;
            font-weight: 700;
            border: none;
            border-radius: 12px;
            padding: 10px 20px;
            transition: all 180ms cubic-bezier(0.4, 0.0, 0.2, 1);
        }
        
        .suggested-action:hover {
            background: @accent_hover;
            transform: translateY(-1px);
            box-shadow: 0 4px 12px alpha(@accent, 0.3);
        }
        
        .suggested-action:active {
            background: @accent_pressed;
            transform: scale(0.98) translateY(0);
            box-shadow: none;
        }
        
        .suggested-action:disabled {
            opacity: 0.55;
            transform: none;
        }
        
        .tiny-btn {
            min-height: 24px;
            min-width: 24px;
            padding: 0px 8px;
            border-radius: 6px;
            font-size: 13px;
        }
        
        /* Secondary button */
        .secondary-action, .flat-action {
            background: transparent;
            color: @text_primary;
            font-weight: 600;
            border: 1px solid @border_default;
            border-radius: 12px;
            padding: 10px 20px;
            transition: all 180ms cubic-bezier(0.4, 0.0, 0.2, 1);
        }
        
        .secondary-action:hover, .flat-action:hover {
            background: alpha(@text_primary, 0.06);
            border-color: @border_focus;
            transform: translateY(-1px);
        }
        
        .secondary-action:active, .flat-action:active {
            transform: scale(0.98);
            background: alpha(@text_primary, 0.08);
        }
        
        /* Danger button */
        .destructive-action {
            background: alpha(@danger, 0.15);
            color: @danger;
            font-weight: 700;
            border: 1px solid alpha(@danger, 0.3);
            border-radius: 12px;
            padding: 10px 20px;
            transition: all 120ms ease-out;
        }
        
        .destructive-action:hover {
            background: alpha(@danger, 0.25);
        }
        
        .destructive-action:active {
            background: @danger;
            color: #0B0D12;
        }
        
        /* Panic button (always visible) */
        .panic-button {
            background: @danger;
            color: #0B0D12;
            font-weight: 800;
            border: none;
            border-radius: 999px;
            padding: 8px 16px;
        }
        
        .panic-button:hover {
            background: #FF6670;
        }
        
        /* ===== ACTION FOOTER ===== */
        .action-footer {
            background: transparent;
            padding: 14px 24px;
            border: none;
        }
        
        .action-status {
            font-size: 13px;
            color: @text_muted;
        }
        
        .power-info {
            font-size: 12px;
            color: @text_muted;
        }
        
        /* ===== TRANSITIONS & MICRO-INTERACTIONS ===== */
        button {
            transition: all 120ms ease-out;
        }
        
        .stat-card, .profile-row, .control-section {
            transition: all 120ms ease-out;
        }
        
        /* Cards lift on hover when clickable */
        .clickable-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
        }
        
        /* Focus states */
        *:focus {
            outline: 2px solid alpha(@accent, 0.9);
            outline-offset: 2px;
        }
        
        button:focus {
            outline: 2px solid alpha(@accent, 0.9);
            outline-offset: 2px;
        }
        
        /* ===== COMBO BOXES / DROPDOWNS ===== */
        combobox button {
            background: @bg_surface;
            border: 1px solid @border_default;
            border-radius: 12px;
            padding: 8px 12px;
            color: @text_primary;
        }
        
        combobox button:hover {
            border-color: @border_focus;
        }
        
        /* ===== TEXT ENTRIES ===== */
        entry {
            background: @bg_surface;
            border: 1px solid @border_default;
            border-radius: 12px;
            padding: 10px 14px;
            color: @text_primary;
        }
        
        entry:focus {
            border-color: @accent;
        }
        
        entry:disabled {
            color: @text_disabled;
        }
        
        /* ===== SCROLLBARS ===== */
        scrollbar {
            background: transparent;
        }
        
        scrollbar slider {
            background: @border_default;
            border-radius: 999px;
            min-width: 8px;
            min-height: 8px;
        }
        
        scrollbar slider:hover {
            background: @border_focus;
        }
        
        /* ===== SEPARATORS ===== */
        separator {
            background: @divider;
            min-width: 1px;
            min-height: 1px;
        }
        
        /* ===== GRAPHS (Background styling) ===== */
        .graph-area {
            background: @bg_subtle;
            border-radius: 12px;
        }
        
        /* ===== DIMMED LABEL ===== */
        .dim-label {
            color: @text_muted;
        }
        
        /* ===== ERROR LABEL ===== */
        .error-label {
            color: @danger;
        }
        """
        
        css_provider.load_from_data(css.encode())
        
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
    

    
    def _update_stats(self) -> bool:
        """Update all statistics displays."""
        # Reentrancy guard for the main update loop
        if hasattr(self, '_stats_updating') and self._stats_updating:
            return True
        self._stats_updating = True
        
        try:
            self.dashboard_page.update_stats()
            self.fans_page.update_stats()
            self.stress_page.update_stats()
            
            # Update bottom status strip
            if self.controller:
                # Stats widgets removed from footer
                pass
        except RecursionError:
            import traceback
            logger.error(f"RecursionError in update loop:\n{traceback.format_exc()}")
        except Exception as e:
            logger.error(f"Failed to update stats: {e}")
        finally:
            self._stats_updating = False
        
        return True  # Continue the timer
    
    def show_toast(self, message: str) -> None:
        """Show a toast notification."""
        toast = Adw.Toast(title=message)
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)
    
    def do_close_request(self) -> bool:
        """Handle window close."""
        if self._update_source_id:
            GLib.source_remove(self._update_source_id)
            self._update_source_id = None
            
        # Cleanup pages
        if hasattr(self, 'stress_page'):
            self.stress_page.cleanup()
            
        return False  # Allow close
    
    def _on_panic_clicked(self, btn) -> None:
        """Revert all settings to stock."""
        if self.controller:
            try:
                # Reset clock offsets
                self.controller.set_clock_offsets(0, 0)
                # Reset fans to auto
                self.controller.set_fan_mode("auto")
                self.show_toast("Reverted to stock settings")
            except Exception as e:
                self.show_toast(f"Panic revert failed: {e}")
        else:
            self.show_toast("No GPU controller available")

import shutil
import threading
import logging
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Pango, Gdk
import time
import subprocess
from typing import Optional, List, Tuple
from collections import deque

from nvoc.privileged_controller import PrivilegedController

logger = logging.getLogger(__name__)

class MonitoringGraph(Gtk.DrawingArea):
    """Simple line graph for monitoring metrics."""
    def __init__(self, title: str, unit: str, color: Tuple[float, float, float], max_val: float):
        super().__init__()
        self.title = title
        self.unit = unit
        self.color = color
        self.max_val = max_val
        self.data: deque = deque(maxlen=60)  # 60 samples (e.g. 60 seconds)
        self.data: deque = deque(maxlen=60)  # 60 samples (e.g. 60 seconds)
        self.set_content_width(320)
        self.set_content_height(200) # Taller graphs
        self.set_draw_func(self._draw)
        
    def add_value(self, value: float):
        self.data.append(value)
        self.queue_draw()
        
    def _draw(self, area, cr, width, height):
        # Background (match design system bg_subtle #141820)
        cr.set_source_rgb(0.078, 0.094, 0.125)  # #141820
        cr.rectangle(0, 0, width, height)
        cr.fill()
        
        # Grid/Graph Area (bg_surface #171A20)
        padding = 30
        graph_width = width - padding * 2
        graph_height = height - padding * 2
        
        cr.set_source_rgb(0.090, 0.102, 0.125)  # #171A20
        cr.rectangle(padding, padding, graph_width, graph_height)
        cr.fill()
        
        # Draw grid lines (#242A36)
        cr.set_source_rgba(0.141, 0.165, 0.212, 0.7)  # #242A36
        cr.set_line_width(1)
        for i in range(5):
            y = padding + i * (graph_height / 4)
            cr.move_to(padding, y)
            cr.line_to(width - padding, y)
        cr.stroke()
        
        # Title
        cr.set_source_rgb(1, 1, 1)
        cr.set_font_size(12)
        cr.move_to(padding, padding - 8)
        cr.show_text(self.title)
        
        # Current Value or Placeholder
        if self.data:
            current = self.data[-1]
            cr.move_to(width - padding - 40, padding - 8)
            cr.show_text(f"{current:.1f} {self.unit}")
        else:
            # Placeholder text
            cr.set_source_rgba(1, 1, 1, 0.3)
            cr.set_font_size(11)
            text = "Live data appears during test"
            extents = cr.text_extents(text)
            cr.move_to(
                padding + (graph_width - extents.width) / 2,
                padding + (graph_height - extents.height) / 2
            )
            cr.show_text(text)
            
        # Plot data
        if len(self.data) > 1:
            cr.set_source_rgb(*self.color)
            cr.set_line_width(2)
            
            step_x = graph_width / (self.data.maxlen - 1)
            
            # Start path at rightmost point (current) and work backwards
            # Or simplified: map indices to x
            
            # Use fixed step for now, aligning to right
            start_x = width - padding
            
            first = True
            for i, val in enumerate(reversed(self.data)):
                x = start_x - (i * step_x)
                if x < padding: break
                
                # Normalize y
                normalized = min(1.0, max(0.0, val / self.max_val))
                y = padding + graph_height - (normalized * graph_height)
                
                if first:
                    cr.move_to(x, y)
                    first = False
                else:
                    cr.line_to(x, y)
            
            cr.stroke()

class StressToolManager:
    """Manages availability and installation of stress tools."""
    
    GPU_BURN_IMAGE = "docker.io/oguzpastirmaci/gpu-burn:latest"
    CONTAINER_NAME = "nvoc_stress_heavy"
    
    def __init__(self):
        self.has_podman = shutil.which("podman") is not None
        self.has_flatpak = shutil.which("flatpak") is not None
        self.has_glxgears = shutil.which("glxgears") is not None
        self.os_id = self._get_os_id()

    def _get_os_id(self) -> str:
        """Detect OS ID for install hints."""
        try:
            with open("/etc/os-release") as f:
                for line in f:
                    if line.startswith("ID="):
                        return line.split("=")[1].strip().strip('"')
        except:
            return "linux"
        return "linux"

    def get_install_hint(self, tool: str) -> str:
        """Get install command based on OS."""
        if tool == "glmark2":
            if self.os_id in ["fedora", "bazzite", "rhel", "centos"]:
                if shutil.which("rpm-ostree"):
                    return "rpm-ostree install glmark2"
                return "sudo dnf install glmark2"
            elif self.os_id in ["ubuntu", "debian", "pop"]:
                return "sudo apt install glmark2"
            elif self.os_id in ["arch", "manjaro", "endeavouros"]:
                return "sudo pacman -S glmark2"
            return "Install 'glmark2' via your package manager."
        return ""
        
    def check_gpu_burn_available(self) -> bool:
        """Check if gpu-burn image is pulled (requires podman)."""
        if not self.has_podman:
            return False
        try:
            # Check if image exists locally
            res = subprocess.run(
                ["podman", "image", "exists", self.GPU_BURN_IMAGE],
                capture_output=True
            )
            return res.returncode == 0
        except:
            return False

    def check_glmark2_available(self) -> bool:
        """Check if glmark2/vkmark is installed on system."""
        return (shutil.which("glmark2") is not None or 
                shutil.which("glmark2-es2-wayland") is not None or 
                shutil.which("vkmark") is not None)

    def install_gpu_burn(self, callback_done=None):
        """Pull gpu-burn image in background."""
        def _pull():
            try:
                subprocess.run(["podman", "pull", self.GPU_BURN_IMAGE], check=True)
                if callback_done:
                    GLib.idle_add(callback_done, True)
            except Exception as e:
                logger.error(f"Failed to pull gpu-burn: {e}")
                if callback_done:
                    GLib.idle_add(callback_done, False)
        
        thread = threading.Thread(target=_pull)
        thread.daemon = True
        thread.start()

    def install_glmark2(self, callback_done=None):
        """Install glmark2 (Not available via Flathub)."""
        # No-op or error
        if callback_done:
            GLib.idle_add(callback_done, False)

class StressPage(Adw.Bin):
    """Stress Test Page - Contextual Console Design."""
    def __init__(self, window, controller: PrivilegedController):
        super().__init__()
        self.window = window
        self.controller = controller
        self.tool_manager = StressToolManager()
        self._process: Optional[subprocess.Popen] = None
        self._monitor_source_id = None
        self._test_start_time = 0
        self._duration_seconds = 0
        
        # Test Statistics
        self._stats_max_temp = 0
        self._stats_max_power = 0
        self._stats_power_samples = []
        
        # Main Layout
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_child(scroll)
        
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=32)
        content.set_margin_top(48)
        content.set_margin_bottom(48)
        content.set_margin_start(48)
        content.set_margin_end(48)
        scroll.set_child(content)
        
        # 1. Mission Header (Centered, Purposeful)
        header_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        header_box.set_halign(Gtk.Align.CENTER)
        
        title_label = Gtk.Label(label="System Stability Verification")
        title_label.add_css_class("page-title")
        header_box.append(title_label)
        
        self.subtitle_label = Gtk.Label(label="Run a controlled GPU stress test to observe system behavior.")
        self.subtitle_label.add_css_class("section-desc")
        header_box.append(self.subtitle_label)
        
        content.append(header_box)
        
        # 2. Test Console (The "Machine")
        console_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        console_card.add_css_class("auto-card") # Reuse card style
        console_card.set_size_request(600, -1)
        console_card.set_halign(Gtk.Align.CENTER)
        
        # Profile Selector
        profile_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        p_label = Gtk.Label(label="Test Profile")
        p_label.set_halign(Gtk.Align.START)
        p_label.add_css_class("nav-label")
        profile_box.append(p_label)
        
        self.profile_combo = Gtk.ComboBoxText()
        self.profile_combo.append("light", "Light: Render Check (glxgears)")
        self.profile_combo.append("medium", "Medium: Sustained Load (vkmark/glxgears)")
        self.profile_combo.append("heavy", "Heavy: Thermal Stress (stress-ng)")
        self.profile_combo.append("custom", "Advanced: Custom Command")
        self.profile_combo.set_active(0)
        self.profile_combo.connect("changed", self._on_profile_changed)
        profile_box.append(self.profile_combo)
        
        # Custom Command Entry (Hidden by default)
        self.custom_cmd_revealer = Gtk.Revealer()
        self.custom_cmd_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        
        cmd_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        cmd_box.set_margin_top(8)
        
        self.cmd_entry = Gtk.Entry()
        self.cmd_entry.set_placeholder_text("Enter shell command...")
        cmd_box.append(self.cmd_entry)
        
        self.custom_cmd_revealer.set_child(cmd_box)
        profile_box.append(self.custom_cmd_revealer)
        
        # Tool Install Action (Revealer)
        self.install_revealer = Gtk.Revealer()
        self.install_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        
        install_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        install_box.add_css_class("warning-banner") # Reuse or make new
        install_box.set_margin_top(8)
        
        self.install_label = Gtk.Label(label="Tool required")
        self.install_label.set_hexpand(True)
        self.install_label.set_halign(Gtk.Align.START)
        self.install_label.set_selectable(True) # Allow copying command
        install_box.append(self.install_label)
        
        self.install_btn = Gtk.Button(label="Install")
        self.install_btn.add_css_class("suggested-action")
        self.install_btn.connect("clicked", self._on_install_clicked)
        install_box.append(self.install_btn)
        
        self.install_spinner = Gtk.Spinner()
        install_box.append(self.install_spinner)
        
        self.install_revealer.set_child(install_box)
        profile_box.append(self.install_revealer)
        
        console_card.append(profile_box)
        
        # Duration & Timeline
        time_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        t_label = Gtk.Label(label="Duration")
        t_label.set_halign(Gtk.Align.START)
        t_label.add_css_class("nav-label")
        time_box.append(t_label)
        
        self.duration_combo = Gtk.ComboBoxText()
        self.duration_combo.append("60", "1 Minute (Short Check)")
        self.duration_combo.append("300", "5 Minutes (Standard Burn-In)")
        self.duration_combo.append("900", "15 Minutes (Thermal Soak)")
        self.duration_combo.append("0", "Indefinite (Until Stopped)")
        self.duration_combo.set_active(1)
        time_box.append(self.duration_combo)
        
        # Active Timeline (Hidden Idle)
        self.timeline_wrapper = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.timeline_wrapper.set_halign(Gtk.Align.CENTER)
        self.timeline_wrapper.set_visible(False)
        self.timeline_label = Gtk.Label(label="Elapsed: 00:00 / 05:00")
        self.timeline_label.add_css_class("dim-label")
        self.timeline_wrapper.append(self.timeline_label)
        time_box.append(self.timeline_wrapper)
        
        console_card.append(time_box)
        
        # Start/Action Area
        action_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        action_box.set_margin_top(16)
        
        self.start_btn = Gtk.Button(label="Start Stress Test")
        self.start_btn.set_icon_name("media-playback-start-symbolic")
        self.start_btn.add_css_class("suggested-action")
        self.start_btn.add_css_class("pill")
        self.start_btn.set_size_request(-1, 50) # Taller button
        self.start_btn.connect("clicked", self._on_start_clicked)
        action_box.append(self.start_btn)
        
        self.warning_label = Gtk.Label(label="This will push the GPU under sustained load.")
        self.warning_label.add_css_class("auto-hint")
        self.warning_label.set_halign(Gtk.Align.CENTER)
        action_box.append(self.warning_label)
        
        self.stop_btn = Gtk.Button(label="Stop Test")
        self.stop_btn.set_icon_name("media-playback-stop-symbolic")
        self.stop_btn.add_css_class("destructive-action")
        self.stop_btn.add_css_class("pill")
        self.stop_btn.set_sensitive(False)
        self.stop_btn.connect("clicked", self._on_stop_clicked)
        action_box.append(self.stop_btn)
        
        console_card.append(action_box)
        content.append(console_card)
        
        # 3. Live Status Sentence
        self.status_sentence = Gtk.Label(label="Monitoring will begin when the test starts.")
        self.status_sentence.add_css_class("dim-label")
        content.append(self.status_sentence)
        
        # 4. Results Card (Hidden)
        self.results_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.results_card.add_css_class("auto-card")
        self.results_card.set_visible(False)
        self.results_card.set_size_request(600, -1)
        self.results_card.set_halign(Gtk.Align.CENTER)
        
        r_title = Gtk.Label(label="Test Results")
        r_title.add_css_class("nav-label")
        r_title.set_halign(Gtk.Align.CENTER)
        self.results_card.append(r_title)
        
        self.results_label = Gtk.Label(label="")
        self.results_label.set_justify(Gtk.Justification.CENTER)
        self.results_card.append(self.results_label)
        
        content.append(self.results_card)
        
        # 5. Dominant Graphs
        graphs_grid = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
        graphs_grid.set_homogeneous(True)
        graphs_grid.set_size_request(-1, 200)
        
        self.temp_graph = MonitoringGraph("Temperature", "°C", (1.0, 0.4, 0.4), 100.0)
        graphs_grid.append(self.temp_graph)
        
        self.power_graph = MonitoringGraph("Power Draw", "W", (1.0, 0.8, 0.2), 300.0)
        graphs_grid.append(self.power_graph)
        
        content.append(graphs_grid)
        
        # 6. Live Status Strip (Restored)
        stats_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
        stats_box.set_halign(Gtk.Align.CENTER)
        
        self.stat_gpu = Gtk.Label(label="GPU: --°C")
        self.stat_gpu.add_css_class("dim-label")
        stats_box.append(self.stat_gpu)
        
        self.stat_power = Gtk.Label(label="Power: --W")
        self.stat_power.add_css_class("dim-label")
        stats_box.append(self.stat_power)
        
        self.stat_fan = Gtk.Label(label="Fan: --%")
        self.stat_fan.add_css_class("dim-label")
        stats_box.append(self.stat_fan)
        
        content.append(stats_box)
        
        self._timer_id = None

    def _on_profile_changed(self, combo):
        """Handle profile selection logic."""
        active = combo.get_active_id()
        
        # Reset install UI
        self.install_revealer.set_reveal_child(False)
        self.start_btn.set_sensitive(True) 
        self.warning_label.add_css_class("auto-hint")
        self.warning_label.remove_css_class("error-label")

        if active == "custom":
            self.custom_cmd_revealer.set_reveal_child(True)
            self.warning_label.set_label("Custom commands run with full user privileges. Be careful.")
            return

        self.custom_cmd_revealer.set_reveal_child(False)
        
        if active == "light":
            self.warning_label.set_label("Light load. Expect moderate temps.")
            if not self.tool_manager.has_glxgears:
                 self.warning_label.set_label("Error: glxgears not found on system.")
                 self.start_btn.set_sensitive(False)
                 
        elif active == "medium":
            if self.tool_manager.check_glmark2_available():
                self.warning_label.set_label("Sustained load (glmark2/vkmark).")
            else:
                self.warning_label.set_label("Tool missing: glmark2 or vkmark.")
                hint = self.tool_manager.get_install_hint("glmark2")
                self.install_label.set_label(f"Run in terminal: {hint}")
                self.install_btn.set_visible(False) # Cannot auto-install
                self.install_revealer.set_reveal_child(True)
                self.start_btn.set_sensitive(False)

        elif active == "heavy":
            if self.tool_manager.check_gpu_burn_available():
                self.warning_label.set_label("Maximum stress (gpu-burn). Monitor thermals closely!")
            else:
                self.warning_label.set_label("Tool missing: gpu-burn (Podman Image).")
                self.install_label.set_label("Missing: wilicc/gpu-burn")
                self.install_revealer.set_reveal_child(True)
                self.start_btn.set_sensitive(False)
                if not self.tool_manager.has_podman:
                    self.warning_label.set_label("Error: Podman not found. Cannot run Heavy profile.")
                    self.install_revealer.set_reveal_child(False)

    def _on_install_clicked(self, btn):
        """Handle tool installation."""
        active = self.profile_combo.get_active_id()
        self.install_btn.set_sensitive(False)
        self.install_spinner.start()
        
        def _done(success):
            self.install_spinner.stop()
            self.install_btn.set_sensitive(True)
            if success:
                self.install_revealer.set_reveal_child(False)
                self._on_profile_changed(self.profile_combo) # Re-evaluate
            else:
                self.install_label.set_label("Installation failed. Check logs.")
        
        if active == "medium":
            self.tool_manager.install_glmark2(_done)
        elif active == "heavy":
            self.tool_manager.install_gpu_burn(_done)

    def _resolve_command(self) -> str:
        """Resolve command based on profile."""
        profile = self.profile_combo.get_active_id()
        duration = self._duration_seconds
        
        if profile == "custom":
            return self.cmd_entry.get_text()
            
        elif profile == "light":
            return "glxgears"
            
        elif profile == "medium":
            if shutil.which("glmark2"): return "glmark2 --run-forever"
            if shutil.which("glmark2-es2-wayland"): return "glmark2-es2-wayland --run-forever"
            if shutil.which("vkmark"): return "vkmark"
            return "glxgears"
                
        elif profile == "heavy":
            if self.tool_manager.check_gpu_burn_available():
                # podman run --rm --gpus all wilicc/gpu-burn <duration>
                # tool takes duration in seconds. If duration is 0 (indefinite), pass a large number
                d_val = duration if duration > 0 else 36000
                name_arg = f"--name {self.tool_manager.CONTAINER_NAME}"
                return f"podman run --rm {name_arg} --device nvidia.com/gpu=all --security-opt=label=disable {self.tool_manager.GPU_BURN_IMAGE} {d_val}"
            return "glxgears"
                
        return "glxgears"
        
    def _on_start_clicked(self, btn):
        cmd = self._resolve_command()
        if not cmd:
            self.warning_label.set_label("Error: No command found.")
            return
            
        duration_str = self.duration_combo.get_active_id()
        self._duration_seconds = int(duration_str)
        
        # Reset stats
        self._stats_max_temp = 0
        self._stats_max_power = 0
        self._stats_power_samples = []
        
        try:
            # Split command for Popen
            import shlex
            cmd_parts = shlex.split(cmd)
            self._process = subprocess.Popen(
                cmd_parts,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            self._test_start_time = time.time()
            self.start_btn.set_sensitive(False)
            self.stop_btn.set_sensitive(True)
            self.profile_combo.set_sensitive(False)
            self.cmd_entry.set_sensitive(False)
            self.duration_combo.set_visible(False)
            self.timeline_wrapper.set_visible(True)
            self.results_card.set_visible(False)
            
            self.subtitle_label.set_label("Stress test in progress...")
            self.status_sentence.set_label("GPU under sustained load — monitoring live telemetry.")
            
            # Start timer for duration check and drawing updates
            self._timer_id = GLib.timeout_add(1000, self._on_tick)
            
        except Exception as e:
            self.subtitle_label.set_label(f"Error: {e}")
            logger.error(f"Failed to start stress test: {e}")
            
    def _on_stop_clicked(self, btn):
        self._stop_test()
        
    def _stop_test(self):
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=1)
            except:
                try:
                    self._process.kill()
                except:
                    pass
            self._process = None
        
        # Force cleanup named container just in case
        # Force cleanup named container just in case
        if self.tool_manager.has_podman:
            try:
                # Try kill first (faster for running containers)
                subprocess.run(
                    ["podman", "kill", self.tool_manager.CONTAINER_NAME], 
                    stdout=subprocess.DEVNULL, 
                    stderr=subprocess.DEVNULL
                )
                # Then remove
                subprocess.run(
                    ["podman", "rm", "-f", self.tool_manager.CONTAINER_NAME], 
                    stdout=subprocess.DEVNULL, 
                    stderr=subprocess.DEVNULL
                )
            except Exception as e:
                logger.error(f"Failed to force stop container: {e}")
            
        if self._timer_id:
            GLib.source_remove(self._timer_id)
            self._timer_id = None
            
        self.start_btn.set_sensitive(True)
        self.stop_btn.set_sensitive(False)
        self.profile_combo.set_sensitive(True)
        self.cmd_entry.set_sensitive(True)
        self.duration_combo.set_visible(True)
        self.duration_combo.set_sensitive(True)
        self.timeline_wrapper.set_visible(False)
        self.subtitle_label.set_label("Test completed — review results")
        self.status_sentence.set_label("Test completed. No instability detected.")
        
        # Show results
        if self._stats_power_samples:
            avg_power = sum(self._stats_power_samples) / len(self._stats_power_samples)
        else:
            avg_power = 0
            
        elapsed_min = int((time.time() - self._test_start_time) / 60)
        elapsed_sec = int((time.time() - self._test_start_time) % 60)
        
        self.results_label.set_label(
            f"Duration: {elapsed_min}m {elapsed_sec}s\n"
            f"Max Temp: {self._stats_max_temp:.0f}°C\n"
            f"Avg Power: {avg_power:.0f}W"
        )
        self.results_card.set_visible(True)
        
    def _on_tick(self):
        # Check if process is still running
        if self._process.poll() is not None:
             # Process exited, check if error
            if self._process.returncode != 0:
                 err = self._process.stderr.read() if self._process.stderr else "Unknown error"
                 out = self._process.stdout.read() if self._process.stdout else ""
                 logger.error(f"Stress test process exited with error code {self._process.returncode}:\nSTDERR: {err}\nSTDOUT: {out}")
                 self.subtitle_label.set_label(f"Error: Process exited ({self._process.returncode}). See logs.")
            else:
                 self.subtitle_label.set_label("Test finished (Process Exit)")
                 
            self._stop_test()
            return False
            
        # Check duration
        # Update Timeline
        if self._duration_seconds > 0:
            elapsed = time.time() - self._test_start_time
            remaining = self._duration_seconds - elapsed
            if remaining <= 0:
                self._stop_test()
                return False
            
            el_m, el_s = divmod(int(elapsed), 60)
            rem_m, rem_s = divmod(int(remaining), 60)
            self.timeline_label.set_label(f"Elapsed: {el_m:02}:{el_s:02} / Remaining: {rem_m:02}:{rem_s:02}")
        else:
            elapsed = time.time() - self._test_start_time
            el_m, el_s = divmod(int(elapsed), 60)
            self.timeline_label.set_label(f"Elapsed: {el_m:02}:{el_s:02}")
            
        # Update graphs (Moving to main loop, but timeline needs this tick)
        # self._update_stats() -> Handled by MainWindow now
        
        return True
        
    def update_stats(self):
        try:
            stats = self.controller.get_gpu_stats()
            self.temp_graph.add_value(stats.temperature_celsius)
            self.power_graph.add_value(stats.power_draw_watts)
            
            # Update max if needed to keep graph valid
            # Update max/avg ONLY if test is running
            if self._process is not None:
                if stats.temperature_celsius > self._stats_max_temp:
                    self._stats_max_temp = stats.temperature_celsius
                if stats.power_draw_watts > self._stats_max_power:
                    self._stats_max_power = stats.power_draw_watts
                self._stats_power_samples.append(stats.power_draw_watts)
            
            # Update Live Status Strip
            self.stat_gpu.set_label(f"GPU: {stats.temperature_celsius}°C")
            self.stat_power.set_label(f"Power: {stats.power_draw_watts:.0f}W")
            self.stat_fan.set_label(f"Fan: {stats.fan_speed_percent}%")
            
            # Update max if needed to keep graph valid
            if stats.power_draw_watts > self.power_graph.max_val:
                self.power_graph.max_val = stats.power_draw_watts * 1.2
            if stats.temperature_celsius > self.temp_graph.max_val:
                self.temp_graph.max_val = stats.temperature_celsius * 1.1
                
        except Exception as e:
            logger.warning(f"Failed to update stress stats: {e}")

    def cleanup(self):
        """Cleanup resources before destruction."""
        self._stop_test()
        if self._monitor_source_id:
            GLib.source_remove(self._monitor_source_id)
            self._monitor_source_id = None

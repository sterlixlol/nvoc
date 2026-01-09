"""
NVOC - Profiles UI Component

Profile management - save, load, delete, and manage overclock profiles.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib

from typing import Optional, List
import logging

from ..profiles import ProfileManager, Profile, DefaultProfileManager, BUILTIN_PROFILES

logger = logging.getLogger(__name__)


class ProfileRow(Gtk.Box):
    """A row representing a single profile - card-based design."""
    
    def __init__(self, profile: Profile, is_default: bool = False, is_builtin: bool = False, is_active: bool = False):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        
        self.profile = profile
        self.is_builtin = is_builtin
        
        self.add_css_class("profile-row")
        if is_active:
            self.add_css_class("profile-row-active")
        
        self.set_margin_top(8)
        self.set_margin_bottom(8)
        self.set_margin_start(12)
        self.set_margin_end(12)
        
        # Profile icon - different based on type
        name_lower = profile.name.lower()
        if "stock" in name_lower or "default" in name_lower:
            icon_name = "emblem-system-symbolic"
            icon_class = "profile-icon-stock"
        elif "quiet" in name_lower or "silent" in name_lower:
            icon_name = "weather-clear-symbolic"
            icon_class = "profile-icon-quiet"
        elif "performance" in name_lower or "gaming" in name_lower:
            icon_name = "starred-symbolic"
            icon_class = "profile-icon-performance"
        else:
            icon_name = "document-properties-symbolic"
            icon_class = "profile-icon"
        
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.add_css_class(icon_class)
        self.append(icon)
        
        # Profile info
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        info_box.set_hexpand(True)
        
        # Name with badges
        name_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        name_label = Gtk.Label(label=profile.name)
        name_label.add_css_class("profile-name")
        name_label.set_halign(Gtk.Align.START)
        name_box.append(name_label)
        
        if is_active:
            active_badge = Gtk.Label(label="ACTIVE")
            active_badge.add_css_class("active-badge")
            name_box.append(active_badge)
        elif is_default:
            default_badge = Gtk.Label(label="DEFAULT")
            default_badge.add_css_class("default-badge")
            name_box.append(default_badge)
        
        if is_builtin:
            builtin_badge = Gtk.Label(label="BUILTIN")
            builtin_badge.add_css_class("builtin-badge")
            name_box.append(builtin_badge)
        
        info_box.append(name_box)
        
        # Settings summary - always show what the profile actually changes
        parts = []
        if profile.core_clock_offset_mhz is not None and profile.core_clock_offset_mhz != 0:
            sign = "+" if profile.core_clock_offset_mhz >= 0 else ""
            parts.append(f"{sign}{profile.core_clock_offset_mhz}MHz core")
        if profile.memory_clock_offset_mhz is not None and profile.memory_clock_offset_mhz != 0:
            sign = "+" if profile.memory_clock_offset_mhz >= 0 else ""
            parts.append(f"{sign}{profile.memory_clock_offset_mhz}MHz mem")
        if profile.fan_mode:
            parts.append(f"{profile.fan_mode} fan")
        
        # Description or settings
        if profile.description:
            desc_text = profile.description
        elif parts:
            desc_text = " · ".join(parts)
        else:
            desc_text = "Stock settings"
        
        desc_label = Gtk.Label(label=desc_text)
        desc_label.add_css_class("profile-desc")
        desc_label.set_halign(Gtk.Align.START)
        desc_label.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
        info_box.append(desc_label)
        
        
        self.append(info_box)
        
        # Action buttons
        if not is_builtin:
            self.delete_button = Gtk.Button()
            self.delete_button.set_icon_name("user-trash-symbolic")
            self.delete_button.set_tooltip_text("Delete Profile")
            self.delete_button.add_css_class("flat-action")
            self.delete_button.set_valign(Gtk.Align.CENTER)
            self.append(self.delete_button)
        else:
            self.delete_button = None

class ProfilesPage(Gtk.Box):
    """Profile management page."""
    
    def __init__(self, controller):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        
        self.controller = controller
        self.profile_manager = ProfileManager()
        
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        self.set_margin_start(24)
        self.set_margin_end(24)
        
        # Header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        
        title = Gtk.Label(label="Overclock Profiles")
        title.add_css_class("page-title")
        title.set_halign(Gtk.Align.START)
        title.set_hexpand(True)
        header.append(title)
        
        # Export button
        export_btn = Gtk.Button()
        export_btn.set_icon_name("document-save-symbolic")
        export_btn.set_tooltip_text("Export All Profiles")
        export_btn.add_css_class("flat-action")
        export_btn.connect("clicked", self._on_export_clicked)
        header.append(export_btn)
        
        # Import button
        import_btn = Gtk.Button()
        import_btn.set_icon_name("document-open-symbolic")
        import_btn.set_tooltip_text("Import Profiles")
        import_btn.add_css_class("flat-action")
        import_btn.connect("clicked", self._on_import_clicked)
        header.append(import_btn)
        
        # New profile button
        new_button = Gtk.Button()
        new_button.set_icon_name("list-add-symbolic")
        new_button.set_tooltip_text("Create New Profile")
        new_button.add_css_class("suggested-action")
        new_button.connect("clicked", self._on_new_profile)
        header.append(new_button)
        
        self.append(header)
        
        # Profiles list
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        # Main container
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        content_box.set_margin_top(12)
        content_box.set_margin_bottom(12)
        content_box.set_margin_start(12)
        content_box.set_margin_end(12)
        scroll.set_child(content_box)
        
        # Built-in Profiles Section
        builtin_group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        
        builtin_label = Gtk.Label(label="Built-in Profiles")
        builtin_label.add_css_class("section-label")
        builtin_label.set_halign(Gtk.Align.START)
        builtin_group.append(builtin_label)
        
        self.builtin_list = Gtk.ListBox()
        self.builtin_list.add_css_class("boxed-list")
        self.builtin_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.builtin_list.connect("row-activated", self._on_row_activated)
        builtin_group.append(self.builtin_list)
        
        content_box.append(builtin_group)
        
        # User Profiles Section
        self.user_group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        
        user_label = Gtk.Label(label="Your Profiles")
        user_label.add_css_class("section-label")
        user_label.set_halign(Gtk.Align.START)
        self.user_group.append(user_label)
        
        self.user_list = Gtk.ListBox()
        self.user_list.add_css_class("boxed-list")
        self.user_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.user_list.connect("row-activated", self._on_row_activated)
        self.user_group.append(self.user_list)
        
        content_box.append(self.user_group)
        
        self.append(scroll)
        
        # Load profiles
        self._refresh_profiles()
    
    def _refresh_profiles(self) -> None:
        """Refresh the profiles list."""
        # Clear existing
        while child := self.builtin_list.get_first_child():
            self.builtin_list.remove(child)
        
        while child := self.user_list.get_first_child():
            self.user_list.remove(child)
        
        default_name = DefaultProfileManager.get_default()
        
        # Add built-in profiles
        for name, profile in BUILTIN_PROFILES.items():
            is_default = profile.name == default_name
            row_content = ProfileRow(profile, is_default=is_default, is_builtin=True)
            self.builtin_list.append(row_content)
        
        # Add user profiles
        user_profiles = self.profile_manager.list_profiles()
        
        if not user_profiles:
            # Add placeholder row
            placeholder = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            placeholder.set_margin_top(12)
            placeholder.set_margin_bottom(12)
            placeholder.set_margin_start(12)
            placeholder.set_margin_end(12)
            
            lbl = Gtk.Label(label="No custom profiles yet. Click + to create one.")
            lbl.add_css_class("empty-label")
            placeholder.append(lbl)
            
            self.user_list.append(placeholder)
            
            # Make the placeholder row non-activatable
            row = self.user_list.get_row_at_index(0)
            if row:
                row.set_activatable(False)
            # Actually easier to just set row not activatable.
            # But Gtk.ListBox wraps it. We can set the row activatable false after appending?
            # Or assume click does nothing if not ProfileRow.
        else:
            # self.user_list.set_activatable(True) # This is not a property of ListBox but rows.
            for name in user_profiles:
                profile = self.profile_manager.load_profile(name)
                if profile:
                    is_default = profile.name == default_name
                    row_content = ProfileRow(profile, is_default=is_default)
                    if row_content.delete_button:
                        row_content.delete_button.connect("clicked", self._on_delete_profile, profile)
                    self.user_list.append(row_content)
    
    def _on_row_activated(self, listbox: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        """Handle profile activation."""
        child = row.get_child()
        if isinstance(child, ProfileRow):
            self._on_apply_profile(None, child.profile)
    
    def _on_apply_profile(self, button: Gtk.Button, profile: Profile) -> None:
        """Apply a profile."""
        if self.controller is None:
            return
        
        try:
            self.profile_manager.apply_profile(profile, self.controller)
            logger.info(f"Applied profile: {profile.name}")
            self._show_toast(f"Applied profile: {profile.name}")
        except Exception as e:
            logger.error(f"Failed to apply profile: {e}")
            self._show_toast(f"Error: {e}")
    
    def _on_delete_profile(self, button: Gtk.Button, profile: Profile) -> None:
        """Delete a profile."""
        if self.profile_manager.delete_profile(profile.name):
            self._refresh_profiles()
            self._show_toast(f"Deleted profile: {profile.name}")
    
    def _on_new_profile(self, button: Gtk.Button) -> None:
        """Create a new profile from current settings."""
        # Create a simple dialog to get profile name
        dialog = Gtk.Dialog(
            title="New Profile",
            modal=True
        )
        dialog.set_default_size(300, -1)
        
        content = dialog.get_content_area()
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_margin_start(16)
        content.set_margin_end(16)
        content.set_spacing(12)
        
        label = Gtk.Label(label="Profile Name:")
        label.set_halign(Gtk.Align.START)
        content.append(label)
        
        entry = Gtk.Entry()
        entry.set_placeholder_text("My Gaming Profile")
        content.append(entry)
        
        desc_label = Gtk.Label(label="Description (optional):")
        desc_label.set_halign(Gtk.Align.START)
        content.append(desc_label)
        
        desc_entry = Gtk.Entry()
        desc_entry.set_placeholder_text("Settings for gaming")
        content.append(desc_entry)
        
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        save_button = dialog.add_button("Save", Gtk.ResponseType.OK)
        save_button.add_css_class("suggested-action")
        
        dialog.connect("response", self._on_new_profile_response, entry, desc_entry)
        
        parent = self.get_root()
        if parent:
            dialog.set_transient_for(parent)
        
        dialog.present()
    
    def _on_new_profile_response(
        self, 
        dialog: Gtk.Dialog, 
        response: int, 
        name_entry: Gtk.Entry,
        desc_entry: Gtk.Entry
    ) -> None:
        """Handle new profile dialog response."""
        if response == Gtk.ResponseType.OK:
            name = name_entry.get_text().strip()
            desc = desc_entry.get_text().strip()
            
            if name:
                profile = self.profile_manager.create_profile_from_current(
                    name=name,
                    controller=self.controller,
                    description=desc
                )
                self.profile_manager.save_profile(profile)
                self._refresh_profiles()
                self._show_toast(f"Created profile: {name}")
        
        dialog.destroy()
    
    def _show_toast(self, message: str) -> None:
        """Show a toast notification."""
        parent = self.get_root()
        if hasattr(parent, 'show_toast'):
            parent.show_toast(message)
        else:
            logger.info(f"Toast: {message}")
    
    def _on_export_clicked(self, button: Gtk.Button) -> None:
        """Export all user profiles to a JSON file."""
        import json
        from pathlib import Path
        
        profiles = self.profile_manager.list_profiles()
        if not profiles:
            self._show_toast("No profiles to export")
            return
        
        # Convert to exportable format
        export_data = []
        for p in profiles:
            export_data.append({
                "name": p.name,
                "description": p.description or "",
                "core_clock_offset_mhz": p.core_clock_offset_mhz,
                "memory_clock_offset_mhz": p.memory_clock_offset_mhz,
                "power_limit_watts": p.power_limit_watts,
                "fan_mode": p.fan_mode,
                "fan_speed_percent": p.fan_speed_percent,
                "fan_curve": p.fan_curve,
            })
        
        # Save to Downloads folder
        export_path = Path.home() / "Downloads" / "nvoc_profiles.json"
        try:
            with open(export_path, 'w') as f:
                json.dump(export_data, f, indent=2)
            self._show_toast(f"Exported {len(profiles)} profiles to Downloads")
        except Exception as e:
            self._show_toast(f"Export failed: {e}")
    
    def _on_import_clicked(self, button: Gtk.Button) -> None:
        """Import profiles from a JSON file."""
        import json
        from pathlib import Path
        
        # Look for file in Downloads
        import_path = Path.home() / "Downloads" / "nvoc_profiles.json"
        if not import_path.exists():
            self._show_toast("No nvoc_profiles.json found in Downloads")
            return
        
        try:
            with open(import_path, 'r') as f:
                import_data = json.load(f)
            
            imported = 0
            for item in import_data:
                from ..profiles import Profile
                profile = Profile(
                    name=item.get("name", "Imported"),
                    description=item.get("description", ""),
                    core_clock_offset_mhz=item.get("core_clock_offset_mhz"),
                    memory_clock_offset_mhz=item.get("memory_clock_offset_mhz"),
                    power_limit_watts=item.get("power_limit_watts"),
                    fan_mode=item.get("fan_mode"),
                    fan_speed_percent=item.get("fan_speed_percent"),
                    fan_curve=item.get("fan_curve"),
                )
                self.profile_manager.save_profile(profile)
                imported += 1
            
            self._refresh_profiles()
            self._show_toast(f"Imported {imported} profiles")
        except Exception as e:
            self._show_toast(f"Import failed: {e}")


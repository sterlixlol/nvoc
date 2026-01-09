# NVOC - NVIDIA Overclocking software for Wayland

A native Wayland GPU overclocking application for NVIDIA GPUs using GTK4 and libadwaita.

## Features

- **Power Limit Control** - Adjust GPU power limits within safe bounds
- **Clock Offsets** - Core and memory clock overclocking
- **Fan Control** - Automatic, manual, or custom fan curves
- **Real-time Monitoring** - Temperature, power, clocks, utilization with live graphs
- **Profiles** - Save and load overclock presets
- **Stress Testing** - Built-in GPU stress test module
- **Boot-time Apply** - Systemd service to apply settings on startup

## Installation

### AppImage (Recommended - Works on any distro)

```bash
# Download the AppImage
chmod +x NVOC-*.AppImage
./NVOC-*.AppImage

# First run: install polkit policy for privilege escalation
sudo cp data/com.github.nvoc.policy /usr/share/polkit-1/actions/
```

### From Source

```bash
git clone https://github.com/nvoc/nvoc.git
cd nvoc
pip install .
nvoc
```

### System Dependencies

**Fedora/Bazzite:**
```bash
sudo dnf install python3-gobject gtk4 libadwaita polkit
```

**Ubuntu/Debian:**
```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 policykit-1
```

**Arch Linux:**
```bash
sudo pacman -S python-gobject gtk4 libadwaita polkit
```

## How It Works

1. **GUI runs as your normal user** - no sudo needed
2. **Read operations** (monitoring) - direct NVML access
3. **Write operations** (overclock/fan) - uses `pkexec` for privilege escalation
4. You get a password prompt only when applying changes

## Building AppImage

```bash
./build-appimage.sh
```

This creates `NVOC-0.1.0-x86_64.AppImage` that runs on any Linux distribution.

## Command Line

```bash
nvoc --status        # Show GPU status
nvoc --apply-default # Apply default profile (for systemd)
nvoc --version       # Show version
```

## License

MIT License - see [LICENSE](LICENSE)

#!/bin/bash
# NVOC Installation Script for Bazzite/Silverblue/Kinoite (Immutable Fedora)
#
# This script installs NVOC to the user's home directory and sets up Polkit.
# For immutable distros, we use /etc/ instead of /usr/share/ for system files.
#
# Run with: sudo ./install.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Detect if we're on an immutable distro
if [ -f /run/ostree-booted ]; then
    echo "=== NVOC Installer (Immutable Fedora Detected) ==="
    IMMUTABLE=true
    # For immutable distros, use /etc/ which is writable
    POLKIT_DIR="/etc/polkit-1/actions"
    INSTALL_DIR="/var/opt/nvoc"
    DESKTOP_DIR="/var/lib/flatpak/exports/share/applications"
    if [ ! -d "$DESKTOP_DIR" ]; then
        DESKTOP_DIR="/usr/local/share/applications"
    fi
else
    echo "=== NVOC Installer ==="
    IMMUTABLE=false
    POLKIT_DIR="/usr/share/polkit-1/actions"
    INSTALL_DIR="/opt/nvoc"
    DESKTOP_DIR="/usr/share/applications"
fi

echo ""

# Check for root
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root (sudo ./install.sh)"
   exit 1
fi

# Check for required commands
for cmd in python3 pkexec; do
    if ! command -v $cmd &> /dev/null; then
        echo "Error: $cmd is not installed"
        exit 1
    fi
done

echo "Installing NVOC to $INSTALL_DIR..."

# Create install directory
mkdir -p "$INSTALL_DIR"

# Copy files
cp -r "$SCRIPT_DIR/nvoc" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"

# Set permissions
chmod -R 755 "$INSTALL_DIR"
chmod 755 "$INSTALL_DIR/nvoc/helper.py"

echo "Installing Polkit policy to $POLKIT_DIR..."

# Create polkit directory if needed
mkdir -p "$POLKIT_DIR"

# Install polkit policy
cp "$SCRIPT_DIR/data/com.github.nvoc.policy" "$POLKIT_DIR/"
chmod 644 "$POLKIT_DIR/com.github.nvoc.policy"

echo "Installing desktop entry..."

# Create desktop dir if needed
mkdir -p "$DESKTOP_DIR" 2>/dev/null || true
mkdir -p /usr/local/share/applications 2>/dev/null || true

# Install desktop entry (try multiple locations for compatibility)
if [ -d "$DESKTOP_DIR" ] && [ -w "$DESKTOP_DIR" ]; then
    cp "$SCRIPT_DIR/data/nvoc.desktop" "$DESKTOP_DIR/"
    sed -i "s|Exec=.*|Exec=/usr/local/bin/nvoc|" "$DESKTOP_DIR/nvoc.desktop"
fi

# Also try /usr/local/share/applications as fallback
if [ -d "/usr/local/share/applications" ]; then
    cp "$SCRIPT_DIR/data/nvoc.desktop" /usr/local/share/applications/ 2>/dev/null || true
    sed -i "s|Exec=.*|Exec=/usr/local/bin/nvoc|" /usr/local/share/applications/nvoc.desktop 2>/dev/null || true
fi

echo "Creating launcher script..."

# Create launcher script (goes in /usr/local/bin which is usually writable)
mkdir -p /usr/local/bin
cat > /usr/local/bin/nvoc << EOF
#!/bin/bash
cd "$INSTALL_DIR"
exec python3 -m nvoc.main "\$@"
EOF

chmod 755 /usr/local/bin/nvoc

echo ""
echo "=== Installation Complete ==="
echo ""
echo "You can now run NVOC:"
echo "  - From terminal: nvoc"
echo "  - From app menu: Search for 'NVOC' (may need to log out/in)"
echo ""
echo "Note: Make sure nvidia-ml-py is installed:"
echo "  pip install nvidia-ml-py"
echo ""

if [ "$IMMUTABLE" = true ]; then
    echo "NOTE: On Bazzite/Silverblue, some changes may require a reboot."
    echo ""
fi

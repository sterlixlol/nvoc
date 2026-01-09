#!/bin/bash
# NVOC AppImage Build Script
# Creates an AppImage that works on any Linux distribution

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="NVOC"
VERSION="0.1.0"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}Building NVOC AppImage v${VERSION}${NC}"

# Create AppDir structure
APPDIR="${SCRIPT_DIR}/NVOC.AppDir"
rm -rf "${APPDIR}"
mkdir -p "${APPDIR}/usr/bin"
mkdir -p "${APPDIR}/usr/lib/python3/dist-packages"
mkdir -p "${APPDIR}/usr/share/applications"
mkdir -p "${APPDIR}/usr/share/icons/hicolor/256x256/apps"
mkdir -p "${APPDIR}/usr/share/polkit-1/actions"

echo -e "${YELLOW}Copying NVOC application...${NC}"

# Copy NVOC package
cp -r "${SCRIPT_DIR}/nvoc" "${APPDIR}/usr/lib/python3/dist-packages/"

# Copy desktop file
cp "${SCRIPT_DIR}/data/nvoc.desktop" "${APPDIR}/usr/share/applications/"
cp "${SCRIPT_DIR}/data/nvoc.desktop" "${APPDIR}/"

# Copy icon
cp "${SCRIPT_DIR}/data/icons/hicolor/256x256/apps/nvoc.png" "${APPDIR}/usr/share/icons/hicolor/256x256/apps/"
cp "${SCRIPT_DIR}/data/icons/hicolor/256x256/apps/nvoc.png" "${APPDIR}/nvoc.png"

# Copy polkit policy
cp "${SCRIPT_DIR}/data/com.github.nvoc.policy" "${APPDIR}/usr/share/polkit-1/actions/"

# Copy AppRun
cp "${SCRIPT_DIR}/AppRun" "${APPDIR}/"
chmod +x "${APPDIR}/AppRun"

echo -e "${YELLOW}Installing Python dependencies...${NC}"

# Install pynvml into AppDir
pip3 install --target="${APPDIR}/usr/lib/python3/dist-packages" nvidia-ml-py --quiet

echo -e "${YELLOW}Downloading appimagetool...${NC}"

# Download appimagetool if not present
if [ ! -f "${SCRIPT_DIR}/appimagetool" ]; then
    wget -q "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage" -O "${SCRIPT_DIR}/appimagetool"
    chmod +x "${SCRIPT_DIR}/appimagetool"
fi

echo -e "${YELLOW}Building AppImage...${NC}"

# Build AppImage
ARCH=x86_64 "${SCRIPT_DIR}/appimagetool" "${APPDIR}" "${SCRIPT_DIR}/NVOC-${VERSION}-x86_64.AppImage"

# Cleanup
rm -rf "${APPDIR}"

echo -e "${GREEN}✓ AppImage created: NVOC-${VERSION}-x86_64.AppImage${NC}"
echo ""
echo "To run:"
echo "  chmod +x NVOC-${VERSION}-x86_64.AppImage"
echo "  ./NVOC-${VERSION}-x86_64.AppImage"
echo ""
echo -e "${YELLOW}Note: First run requires installing the polkit policy:${NC}"
echo "  sudo cp data/com.github.nvoc.policy /usr/share/polkit-1/actions/"

#!/usr/bin/env bash
set -euo pipefail

PKG_DIR="/opt/tax-installer"
BIN_DIR="/usr/local/bin"
DESKTOP_FILE="$HOME/.local/share/applications/tax-installer.desktop"

echo "=== Tax Installer - Uninstall ==="
echo ""
echo "This will remove:"
echo "  - $BIN_DIR/tax"
echo "  - $BIN_DIR/tax-gui"
echo "  - $PKG_DIR/"
echo "  - $DESKTOP_FILE"
echo ""

read -rp "Continue? [y/N]: " confirm
if [[ "$confirm" != [yY] ]]; then
    echo "Cancelled."
    exit 0
fi

echo ""

echo "[1/4] Removing CLI tool..."
sudo rm -f "$BIN_DIR/tax"

echo "[2/4] Removing GUI launcher..."
sudo rm -f "$BIN_DIR/tax-gui"

echo "[3/4] Removing GUI package..."
sudo rm -rf "$PKG_DIR"

echo "[4/4] Removing desktop entry..."
rm -f "$DESKTOP_FILE"
if command -v update-desktop-database &>/dev/null; then
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
fi

echo ""
echo "Done! Tax Installer has been removed."

#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
PKG_DIR="/opt/tax-installer"
BIN_DIR="/usr/local/bin"

echo "=== Tax Installer - Setup ==="
echo ""

# Install CLI
echo "[1/3] Installing CLI tool..."
sudo install -Dm755 "$DIR/tax" "$BIN_DIR/tax"

# Install Python package
echo "[2/3] Installing GUI package to $PKG_DIR..."
sudo mkdir -p "$PKG_DIR"
sudo cp "$DIR/__init__.py"    "$PKG_DIR/"
sudo cp "$DIR/model.py"       "$PKG_DIR/"
sudo cp "$DIR/service.py"     "$PKG_DIR/"
sudo cp "$DIR/view.py"        "$PKG_DIR/"
sudo cp "$DIR/controller.py"  "$PKG_DIR/"

# Install GUI entry point
echo "[3/3] Installing GUI launcher..."
cat <<'ENTRY' | sudo tee "$BIN_DIR/tax-gui" > /dev/null
#!/usr/bin/env python3
import sys
sys.path.insert(0, "/opt/tax-installer")
from view import main
main()
ENTRY
sudo chmod +x "$BIN_DIR/tax-gui"

# Desktop entry
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/tax-installer.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Tax Installer
Comment=Practical tar.xz/gz installer for Linux
Exec=tax-gui %F
Icon=package-x-generic
Terminal=false
Categories=System;Utility;
MimeType=application/x-compressed-tar;application/x-xz-compressed-tar;application/gzip;application/x-bzip2-compressed-tar;
DESKTOP

echo ""
echo "Done! You can now:"
echo "  - CLI:  tax install <archive>"
echo "  - GUI:  tax-gui  (or find 'Tax Installer' in your app menu)"

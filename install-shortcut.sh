#!/usr/bin/env bash
# Creates a desktop shortcut that starts the dashboard and opens it in the browser.
set -e
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
DEST="${XDG_DESKTOP_DIR:-$HOME/Desktop}"
mkdir -p "$DEST"
cat > "$DEST/ShadowCheck.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Shadow Check
Comment=Open the Shadow Check dashboard
Exec="$HERE/launch-dashboard.sh"
Path=$HERE
Icon=security-high
Terminal=false
Categories=Utility;
DESK
chmod +x "$DEST/ShadowCheck.desktop" "$HERE/launch-dashboard.sh"
gio set "$DEST/ShadowCheck.desktop" metadata::trusted true 2>/dev/null || true
echo "Shortcut created: $DEST/ShadowCheck.desktop"

#!/bin/bash
# Install the request watcher as a systemd user service, so it survives a
# reboot.
#
# The watcher has now been found dead twice, and both times the symptom was the
# same: requests silently not appearing. Neither time was a bug in the watcher
# -- it was started from a shell, and a shell does not survive a reboot. This
# makes systemd own it instead.
#
# Re-run this after upgrading node: yt-dlp is invoked as `--js-runtimes node`
# and node lives under nvm, whose path carries the version number. A systemd
# service gets none of the login shell's PATH, so the version is resolved here
# and written into the unit.
#
# Usage: ./scripts/install-watcher-service.sh
set -uo pipefail

UNIT_NAME=beatznbox-watcher.service
UNIT_DIR=~/.config/systemd/user
UNIT="$UNIT_DIR/$UNIT_NAME"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PY=~/demucs-env/bin/python

[ -x "$VENV_PY" ] || { echo "no python at $VENV_PY -- is the demucs venv there?"; exit 1; }

# node is resolved from THIS shell, which has nvm's PATH; the service will not.
NODE="$(command -v node || true)"
[ -n "$NODE" ] || { echo "node not on PATH -- yt-dlp needs it, install it first"; exit 1; }
NODE_BIN="$(dirname "$NODE")"
echo "node:   $NODE"
echo "python: $VENV_PY"

# A copy started by hand would poll the same queue alongside the service and
# both would try to process the same request.
if pgrep -f "[w]atch-requests.py" >/dev/null; then
  echo "stopping the hand-started watcher (pid $(pgrep -f '[w]atch-requests.py' | tr '\n' ' '))"
  pkill -f "[w]atch-requests.py"
  sleep 2
fi

mkdir -p "$UNIT_DIR" ~/.beatznbox
cat > "$UNIT" <<EOF
[Unit]
Description=BeatznBox request watcher
After=default.target

[Service]
Type=simple
WorkingDirectory=$REPO
Environment=PATH=$NODE_BIN:%h/demucs-env/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=$VENV_PY -u $REPO/scripts/watch-requests.py
Restart=always
RestartSec=30
StandardOutput=append:%h/.beatznbox/watch-requests.log
StandardError=append:%h/.beatznbox/watch-requests.log

[Install]
WantedBy=default.target
EOF
echo "wrote $UNIT"

systemctl --user daemon-reload
systemctl --user enable --now "$UNIT_NAME"

# Without linger, user services stop at logout and do not start until the next
# login -- which is most of what this script is trying to fix.
if [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]; then
  echo "enabling linger so the service starts at boot, before you log in"
  if ! loginctl enable-linger "$USER" 2>/dev/null; then
    echo
    echo "  !! linger needs root. Run this yourself, once:"
    echo "       sudo loginctl enable-linger $USER"
    echo "     Until you do, the watcher starts when you log in, not at boot."
    echo
  fi
fi

sleep 3
systemctl --user --no-pager status "$UNIT_NAME" | head -12
echo
echo "logs:    tail -f ~/.beatznbox/watch-requests.log"
echo "restart: systemctl --user restart $UNIT_NAME   # needed after editing watch-requests.py"

#!/usr/bin/env bash
# Install only the website publisher; leave the existing bot and Supervisor alone.
set -euo pipefail

repository_root="$(cd "$(dirname "$0")/.." && pwd)"
snapshot_path="/root/crytodatarun/scholar_state.json"
calendar="*-*-* 12:17:00 Europe/Madrid"

service_unit() {
  cat <<EOF
[Unit]
Description=Publish Scholar snapshot to fransdata.com
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=root
WorkingDirectory=$repository_root
Environment="PATH=$repository_root/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment=GIT_TERMINAL_PROMPT=0
Environment="GIT_SSH_COMMAND=/usr/bin/ssh -i /root/.ssh/fransdata_pages -o IdentitiesOnly=yes -o BatchMode=yes"
ExecStart=/usr/bin/flock -n /run/lock/fransdata-scholar.lock /bin/bash "$repository_root/scripts/publish_scholar_snapshot.sh" "$snapshot_path"
TimeoutStartSec=15min
EOF
}

timer_unit() {
  cat <<EOF
[Unit]
Description=Daily Scholar publication at 12:17 Europe/Madrid

[Timer]
OnCalendar=$calendar
Persistent=true
Unit=fransdata-scholar.service

[Install]
WantedBy=timers.target
EOF
}

if [[ "${1:-}" == "--dry-run" && $# -eq 1 ]]; then
  service_unit
  timer_unit
  exit 0
fi
if [[ $# -ne 0 || $EUID -ne 0 ]]; then
  echo "Usage: sudo bash scripts/install_scholar_timer.sh (or --dry-run without sudo)" >&2
  exit 2
fi

for executable in /usr/bin/flock /usr/bin/ssh /bin/bash; do
  test -x "$executable"
done
test -r "$snapshot_path"
test -r /root/.ssh/fransdata_pages
test -x "$repository_root/.venv/bin/python3"
"$repository_root/.venv/bin/python3" -c 'import bs4, requests'
systemd-analyze calendar "$calendar" >/dev/null

staging_dir="$(mktemp -d)"
trap 'rm -rf "$staging_dir"' EXIT
service_unit > "$staging_dir/fransdata-scholar.service"
timer_unit > "$staging_dir/fransdata-scholar.timer"
systemd-analyze verify "$staging_dir/fransdata-scholar.service" "$staging_dir/fransdata-scholar.timer"
install -m 644 "$staging_dir/fransdata-scholar.service" /etc/systemd/system/fransdata-scholar.service
install -m 644 "$staging_dir/fransdata-scholar.timer" /etc/systemd/system/fransdata-scholar.timer
systemctl daemon-reload
systemctl enable --now fransdata-scholar.timer
systemctl list-timers fransdata-scholar.timer --no-pager

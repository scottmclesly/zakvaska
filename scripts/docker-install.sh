#!/bin/sh
# Install or update zakvaska with Docker, on a Raspberry Pi or any Linux box.
#
#   curl -fsSL https://raw.githubusercontent.com/scottmclesly/zakvaska/main/scripts/docker-install.sh | sh
#
# Run it again whenever you want the newest version: it is the updater too.
#
# What it does, in order, and nothing else:
#   1. installs Docker with Docker's own script, if Docker is not there;
#   2. makes ~/zakvaska holding docker-compose.yml and a two-line .env;
#   3. fills in your time zone from the system, once, and never overwrites it;
#   4. pulls the image, starts it, and waits until it answers.
#
# Your notebook lives in the Docker volume `zakvaska-data`. Nothing here
# touches it: updating keeps every feeding and photo.
#
# Choices, all optional, set before the command:
#   ZAKVASKA_DIR=~/zakvaska   where the two small files go
#   ZAKVASKA_PORT=8420        the port to open in the browser
#   ZAKVASKA_TZ=Europe/Riga   your time zone, if the guess would be wrong
set -eu

REPO_RAW="https://raw.githubusercontent.com/scottmclesly/zakvaska/main"
DIR="${ZAKVASKA_DIR:-$HOME/zakvaska}"

say() { printf '==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

case "$(uname -m)" in
  x86_64|amd64|aarch64|arm64) ;;
  armv7l|armv6l)
    die "this is a 32-bit system. The image is built for 64-bit only: put the 64-bit Raspberry Pi OS on the card (Pi 3 or newer) and run this again." ;;
  *) die "unsupported processor: $(uname -m)" ;;
esac

command -v curl >/dev/null 2>&1 || die "curl is needed. Install it with: sudo apt install curl"

# --- 1. Docker ---------------------------------------------------------
SUDO=""
if ! command -v docker >/dev/null 2>&1; then
  say "Docker is not installed. Installing it with Docker's own script (asks for your password)."
  curl -fsSL https://get.docker.com | sudo sh
  # So that next time docker works without sudo. Takes effect at next login.
  sudo usermod -aG docker "$(id -un)" || true
fi
if ! docker info >/dev/null 2>&1; then
  # Just installed, or this user is not in the docker group yet.
  sudo docker info >/dev/null 2>&1 || die "Docker is installed but not running. Try: sudo systemctl start docker"
  SUDO="sudo"
fi
$SUDO docker compose version >/dev/null 2>&1 \
  || die "this Docker has no 'docker compose'. Install it with: sudo apt install docker-compose-plugin"

# --- 2. The two files --------------------------------------------------
mkdir -p "$DIR"
cd "$DIR"
say "Fetching docker-compose.yml into $DIR"
curl -fsSL "$REPO_RAW/docker-compose.yml" -o docker-compose.yml.new
mv docker-compose.yml.new docker-compose.yml

# --- 3. Settings: written once, yours afterwards -------------------------
guess_tz() {
  if [ -n "${TZ:-}" ]; then echo "$TZ"; return; fi
  if command -v timedatectl >/dev/null 2>&1; then
    tz="$(timedatectl show -p Timezone --value 2>/dev/null || true)"
    [ -n "$tz" ] && { echo "$tz"; return; }
  fi
  [ -r /etc/timezone ] && { cat /etc/timezone; return; }
  link="$(readlink /etc/localtime 2>/dev/null || true)"
  case "$link" in *zoneinfo/*) echo "${link##*zoneinfo/}"; return ;; esac
  echo "America/New_York"
}

if [ ! -f .env ]; then
  PORT="${ZAKVASKA_PORT:-8420}"
  ZONE="${ZAKVASKA_TZ:-$(guess_tz)}"
  say "Writing .env (port $PORT, time zone $ZONE)"
  {
    echo "# zakvaska settings. Edit, then run:  docker compose up -d"
    echo "ZAKVASKA_PORT=$PORT"
    echo "ZAKVASKA_TZ=$ZONE"
  } > .env
else
  say "Keeping your existing .env"
fi
PORT="$(sed -n 's/^ZAKVASKA_PORT=//p' .env | tail -n 1)"
PORT="${PORT:-8420}"

# --- 4. Pull, start, wait ------------------------------------------------
say "Pulling the newest image"
$SUDO docker compose pull
say "Starting zakvaska"
$SUDO docker compose up -d

say "Waiting for it to answer"
i=0
until curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -ge 60 ]; then
    $SUDO docker compose logs --tail 30 || true
    die "it did not come up within two minutes. The log above says why."
  fi
  sleep 2
done

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
echo "zakvaska is running."
echo "  On this machine:      http://127.0.0.1:$PORT"
[ -n "${IP:-}" ] && echo "  From your phone/PC:   http://$IP:$PORT"
echo
echo "It starts by itself after a reboot. To update, run this script again."
echo "To stop it:  cd $DIR && docker compose down    (the notebook is kept)"

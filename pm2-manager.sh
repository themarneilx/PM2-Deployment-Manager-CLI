#!/usr/bin/env bash
set -euo pipefail
umask 077
PM2_MANAGER_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
export PYTHONDONTWRITEBYTECODE=1
command -v python3 >/dev/null 2>&1 || { printf 'Python 3.9+ is required.\n' >&2; exit 1; }
if (($#)); then
    exec python3 "$PM2_MANAGER_ROOT/lib/backend.py" "$@"
fi
# shellcheck source=lib/common.sh
source "$PM2_MANAGER_ROOT/lib/common.sh"
# shellcheck source=lib/deployment.sh
source "$PM2_MANAGER_ROOT/lib/deployment.sh"
# shellcheck source=lib/environment.sh
source "$PM2_MANAGER_ROOT/lib/environment.sh"
# shellcheck source=lib/profiles.sh
source "$PM2_MANAGER_ROOT/lib/profiles.sh"
# shellcheck source=lib/menu.sh
source "$PM2_MANAGER_ROOT/lib/menu.sh"
trap 'printf "\n"' INT
main_menu

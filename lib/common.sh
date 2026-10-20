#!/usr/bin/env bash
backend() { python3 "$PM2_MANAGER_ROOT/lib/backend.py" "$@"; }
prompt() {
    local variable=$1 label=$2 fallback=${3:-} answer
    read -r -p "$label${fallback:+ [$fallback]}: " answer || return 1
    printf -v "$variable" '%s' "${answer:-$fallback}"
}
choose_app() {
    backend list
    prompt PM2_SELECTED_APP 'Application name'
}
run_action() {
    if ! backend "$@"; then printf 'Operation did not complete. Review the error above.\n' >&2; fi
}
pause_menu() { local answer; read -r -p 'Press Enter to return to the menu.' answer || true; }

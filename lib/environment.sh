#!/usr/bin/env bash
environment_menu() {
    local choice env_file
    printf '1) Review keys  2) Create protected file  3) Apply current environment with redeploy\n'
    prompt choice 'Choice' 1 || return
    choose_app || return
    case "$choice" in
        1) run_action env-keys --name "$PM2_SELECTED_APP" ;;
        2) run_action env-create --name "$PM2_SELECTED_APP" ;;
        3)
            prompt env_file 'Replacement absolute env file (blank keeps current references)' || return
            if [[ -n $env_file ]]; then run_action env-apply --name "$PM2_SELECTED_APP" --env-file "$env_file"; else run_action env-apply --name "$PM2_SELECTED_APP"; fi ;;
        *) printf 'Unknown choice.\n' ;;
    esac
}

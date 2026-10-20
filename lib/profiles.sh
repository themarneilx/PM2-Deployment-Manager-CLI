#!/usr/bin/env bash
profiles_menu() {
    local choice file
    run_action profiles
    printf '1) Load and deploy JSON profile  2) Save JSON draft  3) Update from JSON profile\n'
    prompt choice 'Choice' 1 || return
    prompt file 'Absolute JSON profile path' || return
    case "$choice" in
        1) run_action deploy --profile "$file" ;;
        2) run_action profile-save --file "$file" ;;
        3) run_action update --profile "$file" ;;
        *) printf 'Unknown choice.\n' ;;
    esac
}

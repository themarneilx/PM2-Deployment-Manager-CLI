#!/usr/bin/env bash
main_menu() {
    local choice file mode
    while true; do
        printf '\n========== PM2 DEPLOYMENT MANAGER ==========\n'
        printf '%s\n' '1) Deploy / adopt application' '2) List applications' '3) Update application' '4) Start application' '5) Stop application' '6) Restart / reload application' '7) View logs' '8) Monitor application' '9) Environment variables' '10) Startup / save process list' '11) Deployment profiles' '12) Health check' '13) Remove managed application' '14) Backups / restore / recovery' '15) Dependencies / diagnostics / Nginx export' '0) Exit'
        prompt choice 'Choice' || return
        case "$choice" in
            1) deploy_wizard ;;
            2) run_action list ;;
            3) choose_app && run_action update --name "$PM2_SELECTED_APP" ;;
            4) choose_app && run_action start --name "$PM2_SELECTED_APP" ;;
            5) choose_app && run_action stop --name "$PM2_SELECTED_APP" ;;
            6) choose_app && run_action reload --name "$PM2_SELECTED_APP" ;;
            7)
                choose_app || return
                prompt mode 'Logs: snapshot or follow (Ctrl+C leaves logs)' snapshot || return
                if [[ $mode == follow ]]; then run_action logs --name "$PM2_SELECTED_APP" --follow; else run_action logs --name "$PM2_SELECTED_APP"; fi ;;
            8)
                choose_app || return
                printf 'Refreshing every 3 seconds. Ctrl+C returns to menu.\n'
                (trap 'exit 0' INT TERM; while true; do backend monitor --name "$PM2_SELECTED_APP" || break; sleep 3; done) || true ;;
            9) environment_menu ;;
            10)
                prompt mode 'Startup: preview, install, replace, or save' preview || return
                case "$mode" in
                    preview) run_action startup ;;
                    install) run_action startup --install ;;
                    replace) run_action startup --install --replace ;;
                    save) run_action save ;;
                    *) printf 'Unknown choice.\n' ;;
                esac ;;
            11) profiles_menu ;;
            12) choose_app && run_action health --name "$PM2_SELECTED_APP" ;;
            13) choose_app && run_action remove --name "$PM2_SELECTED_APP" ;;
            14)
                prompt mode 'Backup: create, restore, recover, or releases' create || return
                case "$mode" in
                    create|releases) choose_app || return; if [[ $mode == create ]]; then run_action backup --name "$PM2_SELECTED_APP"; else run_action releases --name "$PM2_SELECTED_APP"; fi ;;
                    restore|recover) prompt file 'Absolute backup or journal path' || return; run_action "$mode" --file "$file" ;;
                    *) printf 'Unknown choice.\n' ;;
                esac ;;
            15)
                prompt mode 'Tools: doctor, dependencies, logrotate, or export' doctor || return
                case "$mode" in
                    doctor|dependencies|logrotate) run_action "$mode" ;;
                    export) choose_app && run_action export --name "$PM2_SELECTED_APP" ;;
                    *) printf 'Unknown choice.\n' ;;
                esac ;;
            0) return ;;
            *) printf 'Choose a number from 0 to 15.\n' ;;
        esac
        pause_menu
    done
}

#!/usr/bin/env bash
deploy_wizard() {
    local app_name project port host install build env_file framework mode strategy entry manager health memory action
    local -a args=()
    prompt action 'Operation: deploy, update, adopt' deploy || return
    case "$action" in deploy|update|adopt) ;; *) printf 'Unknown deployment operation.\n'; return ;; esac
    if [[ $action == update ]]; then
        choose_app || return
        run_action update --name "$PM2_SELECTED_APP"
        return
    fi
    prompt app_name 'Application name' example-app || return
    prompt project 'Absolute project path' || return
    run_action inspect --path "$project"
    prompt framework 'Framework: auto, nextjs, express, nestjs, node, vite, custom' auto || return
    prompt mode 'Next.js mode: standard or standalone (auto-detected where possible)' standard || return
    prompt manager 'Package manager: auto, npm, pnpm, yarn, bun' auto || return
    prompt port 'Unprivileged application port' 3000 || return
    prompt host 'Bind IP (loopback recommended behind Nginx)' 127.0.0.1 || return
    prompt env_file 'Absolute environment file path (blank for none)' || return
    prompt install 'Dependencies: lockfile, existing, skip' lockfile || return
    prompt build 'Run production build? y/n' y || return
    prompt strategy 'Deployment: release or in-place' release || return
    prompt entry 'Relative Node entry (blank uses framework/start script)' || return
    prompt health 'HTTP health path' / || return
    prompt memory 'Memory restart threshold' 512M || return
    args=("$action" --name "$app_name" --path "$project" --framework "$framework" --mode "$mode" --package-manager "$manager" --port "$port" --host "$host" --install "$install" --strategy "$strategy" --health-path "$health" --memory "$memory")
    [[ -z $env_file ]] || args+=(--env-file "$env_file")
    [[ -z $entry ]] || args+=(--entry "$entry")
    if [[ $build == y || $build == Y ]]; then args+=(--build); else args+=(--no-build); fi
    if [[ $framework == vite ]]; then
        printf 'Vite preview is intended for preview; static production output is normally served by Nginx.\n'
        local preview; prompt preview 'Explicitly allow preview server? y/n' n || return
        [[ $preview != y ]] || args+=(--vite-ack)
    fi
    if [[ $framework == custom ]]; then
        local command_json
        prompt command_json 'Command as JSON argv array, e.g. ["node","server.js"]' || return
        args+=(--command-json "$command_json")
    fi
    run_action "${args[@]}"
}

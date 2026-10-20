# PM2 Deployment Manager CLI

An interactive Bash tool for deploying Next.js and other Node applications with PM2. It stages releases, checks that the intended process owns the configured listener, probes HTTP health, and restores the previous definition if a replacement fails.

This repository is separate from [Nginx Manager CLI](https://github.com/themarneilx/Nginx-Manager-cli). It exports upstream metadata for Nginx; it does not change Nginx, certificates, DNS, Cloudflare, or firewall rules.

## Requirements and Linux support

Run as the normal application owner. Linux, Bash 4+, Python 3.9+, Node.js, and your application's package manager are required. PM2 7.0.4 requires Node 18 or newer; the application and installed Next.js version may require a newer Node version. The manager checks their declared `engines.node` with semver.

Arch Linux is the primary development environment. Deployment uses Linux `/proc` rather than distro-specific package commands, so the same CLI can run on Debian, Ubuntu, Fedora, openSUSE, and other Linux distributions with those prerequisites. `doctor` reads `/etc/os-release` and detects available tools. Reboot startup installation requires a running **systemd** system. Other init systems can use deployment/process commands and configure their own reboot integration. These distributions have not all been tested on live hosts.

Install Node, Python, Bash and npm using your distro's package manager. Select Node with nvm, fnm, asdf or another version manager before running the tool, or pass `--node /absolute/path/to/node`. The selected Node, PM2 and package-manager executable paths are pinned in each profile; rerun startup setup when a Node upgrade changes its path.

```bash
git clone https://github.com/themarneilx/PM2-Deployment-Manager-CLI.git
cd PM2-Deployment-Manager-CLI
./pm2-manager.sh doctor
./pm2-manager.sh dependencies   # prompts before user-local npm installation
./pm2-manager.sh                # interactive menu
```

`dependencies` installs PM2 and semver under the manager's private state directory. It does not install global npm packages, use sudo, or start a PM2 daemon. Existing PM2 installations can be selected with `--pm2 /absolute/path/to/pm2`. Normal read-only queries use a direct PM2 RPC connection and cannot create a daemon. Direct RPC is tested against PM2 7.0.4; an incompatible PM2 installation produces an error without falling back to a mutating query.

## Deploy an application

```bash
./pm2-manager.sh deploy \
  --name example-app \
  --path /home/exampleuser/apps/example-app \
  --framework nextjs \
  --host 127.0.0.1 --port 3107 \
  --package-manager npm --install lockfile --build \
  --env-file /home/exampleuser/secrets/example-app.env \
  --health-path / --memory 512M
```

The summary shows owner, paths, bind address, environment **names**, dependency/build settings and process scope before confirmation. `--dry-run` previews without writing state, installing packages, building, or starting PM2. `--yes` accepts ordinary operation confirmations for automation; review a dry run first. The interactive menu calls the same backend as the CLI.

Profiles default to one fork instance and loopback binding. A fork deployment has a restart gap. Cluster mode is intentionally rejected because application session/state handling must be tested separately. Ports below 1024 are refused; put Nginx in front of the application. A wildcard bind requires explicit selection and appears in the preview. Health checks reject a wildcard listener when the profile requests loopback.

Framework detection reads `package.json`, lockfiles, router directories and Next config text. Dynamic Next configuration may require explicitly selecting `--mode standalone`. Multiple lockfiles require an explicit package manager unless `packageManager` resolves the choice. An exact `packageManager` declaration must match the selected executable version; select its version with your existing version manager before deploying. Package lifecycle scripts are application code: install/build only trusted projects. Lockfile installs include development dependencies for the production build; runtime uses `NODE_ENV=production`.

Next.js standard mode runs its installed Next CLI with explicit host and port. Standalone mode locates `.next/standalone/**/server.js` and copies `public` and `.next/static` beside that server. Set `--entry` when a monorepo produces multiple server entries. Use the workspace root containing the correct lockfile and build script. Static `output: 'export'` applications should be served by Nginx. See [Next.js examples](examples/nextjs.md) and [Express/Node examples](examples/express.md).

## Releases, updates and rollback

```bash
./pm2-manager.sh update example-app
./pm2-manager.sh update example-app --git-pull
./pm2-manager.sh releases example-app
./pm2-manager.sh backup example-app
./pm2-manager.sh restore --file /absolute/path/to/private-backup.json
./pm2-manager.sh recover --file /absolute/path/to/private-journal.json
```

Default `release` deployment copies source to a new private directory outside the source tree, installs from a lockfile, builds there, then replaces only the exact owned PM2 process. It omits `.git`, `.env*`, existing dependencies and old build outputs unless explicitly needed by `--install existing` or `--no-build`. External symlinks are refused; dependency symlinks are preserved only within the copied project. Use a self-contained workspace root.

A failed install/build leaves the running release intact. A failed process/health swap restores the previous process options and profile. Interruptions during swaps create private recovery journals. SIGKILL or machine failure requires the explicit `recover` command. Guarded recovery refuses externally changed definitions or state. Failed/old releases, logs and private journals are retained for diagnosis; disk cleanup is manual after checking which releases/backups refer to them.

`--strategy in-place` is available for deliberate use but refuses build/install/Git changes when running processes use that source. Sources containing `.env*` are refused in this mode because frameworks could load unselected environment values. Release deployment is recommended. Git updates require a clean, attached checkout and use fetch plus `pull --ff-only`; the tool never resets, stashes, discards changes, or silently changes branches. Git pull changes the source checkout and is not undone by release rollback.

Rollback restores code/process references and private environment snapshots. It cannot undo database migrations, uploads, external API effects, dependency registry changes, or arbitrary side effects of application build scripts. Metadata backups omit environment values, PM2 dumps and log contents and refer to **retained local releases**. They are not portable disaster-recovery archives. Make independent protected backups of code, data and secrets.

## Environment variables

```bash
./pm2-manager.sh env-create --name example-app
./pm2-manager.sh env-keys example-app
./pm2-manager.sh env-apply example-app
./pm2-manager.sh env-apply example-app --env-file /home/exampleuser/secrets/replacement.env
```

Values entered with `env-create` are hidden and written with mode 600. Existing files are never overwritten. Otherwise create/edit a protected dotenv file locally and select it explicitly. Multiple `--env-file` flags merge in order; later values win. References are saved in profiles; values live only in private release snapshots. Build and runtime receive the same selected values, plus production host/port settings. Shell substitutions and variable interpolation are treated literally, never evaluated.

`NEXT_PUBLIC_` values are compiled into browser bundles. Changes require rebuilding; a managed Next update without a build is refused if public values changed. Keep Supabase service-role keys, `sb_secret_` keys and JWT signing secrets server-only. Public variables containing privileged key names/values or legacy service-role JWTs are rejected. Supabase publishable variable names are not hardcoded.

The manager redacts selected values, multiline fragments, common encoded forms and common token patterns in captured builds and runtime output. Arbitrary application encodings or secrets read from unrelated files cannot be identified reliably. Do not log secrets in application code. An adopted app's pre-existing log files remain outside this capture mechanism; use explicitly selected env files so log viewing can redact known values.

## Existing PM2 applications and process commands

```bash
./pm2-manager.sh list
./pm2-manager.sh status example-app
./pm2-manager.sh health example-app
./pm2-manager.sh start example-app
./pm2-manager.sh stop example-app
./pm2-manager.sh restart example-app
./pm2-manager.sh reload example-app
./pm2-manager.sh logs example-app --lines 100
./pm2-manager.sh logs example-app --kind stderr --follow
./pm2-manager.sh monitor example-app
./pm2-manager.sh remove example-app
```

`monitor` prints a current sample; the menu refreshes it every three seconds. It reports PM2 metrics and CPU/RSS for the launcher plus descendants. The launcher's memory watchdog also checks summed application-tree RSS, because PM2 observes the launcher PID. Summed RSS can count shared pages more than once. `Ctrl+C` leaves logs/monitoring without stopping the application. Optional `logrotate` asks before installing `pm2-logrotate` for this user's daemon and preserves an existing installation/configuration.

Every mutation targets an exact managed name/ID and checks its script, cwd, interpreter, arguments and private ownership marker. There are no global restart/delete commands. `reload` uses a controlled fork restart and does not claim zero downtime. Health requires PM2 online with a PID, stable restart count, a listener owned by that process tree, TCP connectivity and two acceptable local HTTP responses. Redirects are not followed. Customize `--health-path`, `--accepted-status 200,204`, retries, intervals and timeouts for the app.

An existing unmanaged name blocks deployment. To deliberately record its current single-fork definition without restarting it:

```bash
./pm2-manager.sh adopt --name example-app \
  --path /home/exampleuser/apps/example-app \
  --framework node --entry server.js --install skip --no-build \
  --host 127.0.0.1 --port 3107
./pm2-manager.sh health example-app
```

Adoption preserves its external environment and logs. A later update creates a managed release and selects new environment files explicitly. If an adopted process disappears, deploy a managed update to reconstruct it; the manager will not guess its external secret environment. Retained-release restore is available after its first managed update. Removal deletes only the selected PM2 process and active manager profile; releases, environment files, logs, certificates and Nginx config are retained. Run `save` separately to change reboot persistence.

## Reboot startup

```bash
./pm2-manager.sh save               # review this user's COMPLETE process list
./pm2-manager.sh startup            # print generated unit and existing service status
./pm2-manager.sh startup --install  # separate confirmation; fixed sudo commands
```

`save` checks online managed apps' health and previews all processes, including unmanaged ones, before persisting this user's complete PM2 list. PM2 dumps can contain unmanaged secrets, so the home must be private (700) and dump files are protected (600). Stopped apps are explicitly reported and saved as stopped.

Startup generates `pm2-<user>.service` with the normal owner, private umask, explicit home/PM2_HOME/PATH, and pinned Node/PM2 executable paths. It uses fixed `sudo install`, `sudo systemctl daemon-reload` and `sudo systemctl enable` argv; it never evaluates text printed by `pm2 startup`. Installation does not start/restart the service immediately. The service controls this user's entire PM2 daemon at boot/shutdown.

Existing PM2 units for the owner/home are detected and preserved. Only a unit previously created by this manager can be replaced with `startup --install --replace`; review other units manually to avoid duplicate daemons. After a runtime-path upgrade, redeploy using the new paths, review/save the process list, then regenerate the unit. Startup requires a non-root owner even when other commands use the exceptional `--allow-root` opt-in.

## Profiles, paths and integration

```bash
./pm2-manager.sh profile-template --name example-app \
  --path /home/exampleuser/apps/example-app > example-app.json
# Edit this JSON data locally, then:
./pm2-manager.sh profile-save --file /absolute/path/to/example-app.json
./pm2-manager.sh profiles
./pm2-manager.sh deploy --profile /absolute/path/to/example-app.json --dry-run
./pm2-manager.sh export example-app
```

Profiles contain validated JSON settings and environment file references. Unknown fields and executable shell profiles are rejected. Draft edits take effect only through deploy/update. See [the profile template](templates/deployment-profile.example.json). Ecosystems use `.config.cjs` so a project's `"type": "module"` cannot change their interpretation. Generated ecosystems contain private snapshot **paths**, not secret values.

Default state: `$HOME/.local/state/pm2-deployment-manager`; PM2 home: `$PM2_HOME` or `$HOME/.pm2`. Override with `--state-dir`, `--pm2-home`, or environment variable `PM2_MANAGER_STATE`. Set these environment variables before opening the menu. State directories require mode 700 and ownership by the deployment user; source/env files cannot be group/world writable. All commands accept shared `--node`, `--pm2`, `--dry-run`, `--yes` and `--allow-root` flags. Use `COMMAND --help` for command-specific arguments. Exit codes: 0 success, 1 operation/validation failure, 2 invalid CLI usage, 130 interruption.

`export` prints nonsecret JSON with the app's localhost upstream and health metadata. For `app.example.com`, configure that upstream separately in Nginx Manager CLI. No Tor listener, virtual host, TLS redirect or Supabase callback is modified here.

## Development and verification

Bash handles prompts and menu flow. Python's standard library handles schema validation, private state, transactions, Git, process checks and health. Small CommonJS helpers launch the application, validate semver and query PM2 without auto-starting it. There are no Python package dependencies.

```bash
npm ci --ignore-scripts
npm test
npm run test:integration
bash -n pm2-manager.sh lib/*.sh
shellcheck -x pm2-manager.sh lib/*.sh
```

Tests use temporary directories and mocks. Real integration tests opt in with `PM2_TEST_BIN`, use a disposable `PM2_HOME`, and clean up only that daemon. They verify actual deployment, health, repeated-deploy idempotency, failed-update rollback, retained-release restore, scoped process operations and an unrelated process surviving with the same PID. No real systemd service is installed by the tests. Next build/standalone detection is covered with fixtures; application-specific production builds and reboot behavior still require validation on the target host. See [architecture](docs/design.md) and [walkthrough](docs/walkthrough.md).

Reference behavior: [PM2 ecosystems](https://pm2.keymetrics.io/docs/usage/application-declaration/), [PM2 startup](https://pm2.keymetrics.io/docs/usage/startup/), [Next.js standalone output](https://nextjs.org/docs/app/api-reference/config/next-config-js/output), [Next.js environment variables](https://nextjs.org/docs/app/guides/environment-variables), [Supabase API keys](https://supabase.com/docs/guides/getting-started/api-keys), and [systemd environment quoting](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html#Environment=).

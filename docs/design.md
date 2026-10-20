# PM2 Deployment Manager design and implementation plan

Manage HTTP Node applications with PM2 under their normal deployment owner. Public examples
use example-app and app.example.com. Nginx configuration and other deployment tools remain
independent; this CLI exports upstream metadata for separate web-server configuration.

## Architecture

Bash owns the SSH menu, prompts and modular command entry points. Python parses CLI arguments.
A Python 3.9+ standard-library backend validates JSON profiles, safely handles filesystem
state, orchestrates package/build/PM2 subprocesses, and guards release/rollback transactions.
A small CommonJS launcher loads private runtime environment data in memory, forwards signals
to the real application, and redacts output before PM2 receives it. Ecosystem files contain
only paths and nonsecret process settings, never secret values. Command inputs are argv data,
never eval/source. The same backend powers interactive and automated commands.

Run as a normal deployment user. Pin actual Node/PM2/package-manager paths, preserve the
selected PM2_HOME and refuse other users' state. Read-only commands never start a missing
PM2 daemon. A new daemon may start only after a confirmed process operation. PM2 mutations
address exact IDs verified against managed metadata or an explicitly adopted definition.
No restart/delete all, no automatic global npm or Node installation, no Nginx/Cloudflare edits.

## Deployment strategy

The default strategy copies source into a new private release directory, omitting .git,
secret env files, and old build artifacts. Dependency/build commands run there with a pinned
Node path and private environment snapshot. Existing dependency mode copies node_modules;
lockfile mode uses npm ci, pnpm frozen-lockfile, Yarn immutable/frozen-lockfile or Bun frozen
lockfile as appropriate. Conflicting lockfiles require an explicit package-manager selection.
Use declared project engines and the installed framework's actual engines, with semver
resolved from an existing npm/PM2/project installation; never guess Next.js requirements.

Standard Next launches the project's Next executable with explicit host/port. Standalone
launches its generated server.js with PORT/HOSTNAME, copying public and .next/static to the
correct standalone directory. Detect monorepo/multiple standalone entries and require an
explicit entry when ambiguous. Nest/generic/Express/custom argv commands are supported.
Vite preview/dev is explicitly acknowledged and documented as unsuitable for normal production.
Fork/one instance is the default; clustering is not automatically enabled. In-place builds
are refused while any PM2 process uses that source. Fork replacement has a restart gap;
there is no zero-downtime claim.

After a successful build, record private recovery state, displace only the verified prior
process, start the new definition and verify PM2 PID/status, stable restarts, listener/TCP
and HTTP status against configured acceptance rules. Commit profiles/metadata only after
health passes. On failure/interrupt restore the exact previous definition/release where safe.
Hash/signature guards refuse to overwrite concurrent PM2/manual state changes. A SIGKILL
journal can be recovered explicitly. No rollback of DB migrations, uploads or external effects.

## Secrets, startup and ownership

Select environment files as data, never shell code; show keys only. Copy values to a private
snapshot for both build and runtime. Env expansion is deliberately not shell evaluation.
Reject service-role/secret Supabase values in NEXT_PUBLIC variables. Explain public values
require rebuilds. Generated snapshots/logs/state are private; backup/export omit secrets.
Application/build output is redacted using known values and credential patterns.

Startup integration previews an owned systemd unit for the current non-root user, pinned
Node and PM2 binaries and PM2_HOME. Detect existing units for that user/home before creating
another. Never eval PM2's printed sudo command. Optional installation runs fixed sudo install/
systemctl argv after a separate explicit confirmation; it never starts/stops the live service.
PM2 save is a separate whole-current-user-list action with a displayed process list and health
checks; never silently alter another user's daemon or dump. Protect PM2 dumps with mode 600.

Unmanaged processes are listed separately. Explicit adoption records the verified existing
process identity without restarting it; a private recovery snapshot is required before later
replacement so its existing runtime environment can be restored. No silent import/overwrite.

## Implementation sequence and checks

1. Validation/profile/env/framework/runtime tests first, then implement data helpers.
2. PM2 identity/health tests first, then implement process adapter and CJS launcher.
3. Stage/build/swap/rollback tests first, then implement release transactions and journals.
4. Add startup/adoption/backup/logging/export, Bash menu and shared CLI handlers.
5. Run Bash syntax, ShellCheck, Python/Node checks, mocked tests and real PM2 tests using a
   disposable PM2_HOME and local HTTP fixture; never use production PM2 or systemd.
6. Independent safety review; fix important findings with regressions, document limitations,
   then initialize this directory's own Git repository and push the requested GitHub remote.

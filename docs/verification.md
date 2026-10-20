# Verification record

Validated locally on Arch Linux as a normal user with Node 26.12.0, npm 12.2.1, PM2 7.0.4 and ShellCheck 0.11.0.

- `PM2_TEST_BIN=/absolute/path/to/pm2 npm test`: **48 tests passed**, including the real PM2 lifecycle test, in 26.4 seconds.
- Bash syntax and ShellCheck: passed for the entry point and all Bash modules.
- Node syntax: passed for all CommonJS helpers and the ecosystem template.
- Python syntax: passed for backend modules and tests.
- `systemd-analyze verify --man=no` on a temporary generated service unit: passed. No service was installed or enabled.
- Menu list → return → exit: passed using a temporary state/home; neither directory nor a PM2 daemon was created.
- Independent safety review: findings corrected with regression tests, including multiline-secret redaction, full process identity, bind scope, active-source protection, build dependencies, read-only PM2 queries, adopted logs, stopped-state rollback, save-state validation and absent-process journal finalization.

The real PM2 test used a disposable home and local HTTP fixture. It verified successful deployment, repeated-request idempotency, private redacted logs, failed-update rollback, successful update, retained-release restore, stopped-state rollback, start/restart, private PM2 save and scoped removal. An unrelated fixture process retained its PID through these operations. The temporary daemon was cleaned up; the normal user's default PM2 home was not created.

These checks do not establish successful production builds for every Next.js/Node application or successful reboot on every Linux distribution. Next.js artifact handling uses fixtures; systemd integration was syntax-checked and previewed without changing a live service. GitHub Actions is configured for Ubuntu with Node 22 and 24.

CI follow-up: the initial GitHub run exposed a test fixture that assumed `/usr/bin/node`; it now resolves the selected Node/npm executables from PATH. Further integration coverage reproduces a start after stopped rollback and requires the update to fail at the HTTP health check rather than an earlier guard. The local follow-up run with Node 22.23.3 passed **51 tests**, including actual PM2, in 30.0 seconds. The port probe accepts reusable recently closed sockets, and starting a manager-owned `autostart: false` rollback definition uses a guarded process swap.

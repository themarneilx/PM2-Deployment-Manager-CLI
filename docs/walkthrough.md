# Deployment walkthrough

1. Run `./pm2-manager.sh doctor` as the application's normal owner. Select the intended Node/package-manager versions and install a user-local PM2 with `dependencies` if needed.
2. Open `./pm2-manager.sh`. Choose deploy, enter `example-app`, its absolute source path, port `3107`, and loopback `127.0.0.1`. Select environment files, lockfile install and production build. Review the summary and confirm.
3. Run `health example-app`, inspect redacted logs, and use `export example-app` to obtain the Nginx upstream. Configure `app.example.com` separately in Nginx Manager CLI.
4. Choose startup → save. Review the complete per-user PM2 list, including other applications. Choose startup → preview, then install only after reviewing paths and existing services. This does not restart the running daemon.
5. Choose update. The new code builds outside the active release. A failed build preserves the current process; a failed HTTP check restores the previous definition. The CLI exits with failure even when rollback succeeds so automation notices the failed update.
6. Create a metadata backup before a subsequent update. Choose restore and select that backup to reactivate its retained release. Files outside manager state, database migrations and source Git changes are not undone.
7. To manage an existing PM2 application, select adopt explicitly and verify its identity/port. Adoption does not restart it. A later managed update replaces only that app after staging successfully.

The automated demonstration is `npm run test:integration`. It starts a temporary HTTP fixture and an unrelated PM2 process in a disposable home, exercises success and failure paths, verifies the unrelated PID stays unchanged, and kills only the temporary daemon on exit.

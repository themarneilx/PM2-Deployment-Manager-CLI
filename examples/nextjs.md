# Next.js deployment examples

Use a separate clean checkout as deployment source. Keep secrets in a protected file outside the project. Verify the selected Node version against the installed Next release.

```bash
./pm2-manager.sh deploy --name example-app \
  --path /home/exampleuser/apps/example-app --framework nextjs \
  --host 127.0.0.1 --port 3107 --install lockfile --build \
  --env-file /home/exampleuser/secrets/example-app.env
./pm2-manager.sh health example-app
./pm2-manager.sh export example-app
```

App Router and Pages Router use the same Next server entry. Standard mode requires `node_modules/next/dist/bin/next` and `.next/BUILD_ID`.

For standalone output, set `output: 'standalone'` in the application's Next configuration, then select `--mode standalone`. The staged build must produce `.next/standalone/.../server.js`. The manager copies `public` and `.next/static` beside that server. For an ambiguous monorepo output, pass its relative `--entry .next/standalone/apps/example-app/server.js`. External workspace symlinks require deploying from a self-contained workspace root.

`--no-build --install existing` accepts an explicitly prepared production build plus its local dependencies. The manager cannot verify the provenance or public environment embedded in prebuilt bundles; rebuild when public values change.

Set Supabase's externally visible application URL and allowed redirect URLs in Supabase separately, such as `https://app.example.com/auth/callback`. This CLI does not edit Supabase, Nginx, Cloudflare or TLS settings.

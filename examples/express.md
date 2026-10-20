# Express, NestJS and generic Node

An Express app should use the selected host and port explicitly:

```javascript
app.listen(Number(process.env.PORT), process.env.HOST || '127.0.0.1');
```

```bash
./pm2-manager.sh deploy --name example-api \
  --path /home/exampleuser/apps/example-api --framework express \
  --entry server.js --no-build --install lockfile \
  --host 127.0.0.1 --port 3200 --health-path /health
```

For NestJS, use its production build and entry, for example `--framework nestjs --build --entry dist/main.js`. Package scripts are selected with `--build-script` and `--start-script`; the default names are `build` and `start`. Configure the application to honor `HOST` and `PORT`. HTTP health refuses a public wildcard listener when loopback was requested.

For a custom executable, use an argv array, never a shell command string:

```bash
./pm2-manager.sh deploy --name example-worker-api \
  --path /home/exampleuser/apps/example-worker-api --framework custom \
  --command-json '["node","server.js","--production"]' \
  --no-build --install skip --port 3300
```

Only HTTP applications are supported by deployment health checks. Do not pass secrets as command arguments. A Vite static build normally belongs in Nginx; a deliberate preview deployment requires `--framework vite --vite-ack --start-script preview` and is not presented as a production web-server recommendation.

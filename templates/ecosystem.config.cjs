'use strict';
// Generated releases use this shape with private launch/snapshot paths and a unique marker.
module.exports = {
  apps: [{
    name: 'example-app',
    cwd: '/home/exampleuser/.local/state/pm2-deployment-manager/releases/example-app/RELEASE',
    script: 'launcher.cjs',
    args: ['/home/exampleuser/.local/state/pm2-deployment-manager/releases/example-app/RELEASE/launch.json'],
    interpreter: '/usr/bin/node',
    exec_mode: 'fork',
    instances: 1,
    watch: false,
    autorestart: true,
    kill_timeout: 8000,
    restart_delay: 1500,
    max_memory_restart: '512M',
    env: { NODE_ENV: 'production', PORT: '3107', HOSTNAME: '127.0.0.1', PM2_MANAGER_NONCE: 'GENERATED_PER_RELEASE' }
  }]
};

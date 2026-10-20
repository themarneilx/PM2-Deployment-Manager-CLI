'use strict';
// Direct RPC avoids PM2 CLI's automatic daemon startup and filesystem initialization.
const path = require('node:path');
const root = path.dirname(path.dirname(process.argv[2]));
const axon = require(path.join(root, 'modules/pm2-axon'));
const rpc = require(path.join(root, 'modules/pm2-axon-rpc'));
const socket = axon.socket('req');
const client = new rpc.Client(socket);
let done = false;
function finish(code, value) {
  if (done) return;
  done = true;
  if (code === 0) process.stdout.write(JSON.stringify(value));
  socket.close();
  process.exitCode = code;
  setTimeout(() => process.exit(code), 20);
}
setTimeout(() => finish(1), 2500).unref();
socket.on('error', () => finish(1));
socket.on('connect', () => client.call('getMonitorData', {}, (error, data) => finish(error ? 1 : 0, data)));
socket.connect(process.argv[3]);

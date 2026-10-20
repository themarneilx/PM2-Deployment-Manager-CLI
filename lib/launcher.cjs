'use strict';
const fs = require('node:fs');
const path = require('node:path');
const cp = require('node:child_process');
const readline = require('node:readline');
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const values = JSON.parse(fs.readFileSync(config.env_file, 'utf8'));
const env = {};
for (const key of ['HOME','USER','LOGNAME','LANG','LC_ALL','TZ']) if (process.env[key]) env[key] = process.env[key];
Object.assign(env, values, {PATH: config.path, NODE_ENV: 'production', PORT: String(config.port), HOSTNAME: config.host, HOST: config.host});
const replacements = [...new Set(Object.values(values).flatMap(v => [v, encodeURIComponent(v), ...v.split('\n')]).filter(Boolean))].sort((a,b) => b.length-a.length);
function clean(value) {
  let text = value.replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '');
  for (const secret of replacements) text = text.split(secret).join('[REDACTED]');
  return text.replace(/(Bearer\s+)\S+/gi,'$1[REDACTED]')
    .replace(/((?:access_token|refresh_token|token|password|secret|api[_-]?key|authorization|cookie|set-cookie)\s*[:=]\s*)[^\s,;]+/gi,'$1[REDACTED]')
    .replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g,'[REDACTED]')
    .replace(/\bsb_secret_[A-Za-z0-9_-]+/g,'[REDACTED]');
}
const child = cp.spawn(config.command[0], config.command.slice(1), {cwd: config.cwd, env, shell: false, detached: true, stdio: ['ignore','pipe','pipe']});
for (const [stream, output] of [[child.stdout,process.stdout],[child.stderr,process.stderr]]) {
  readline.createInterface({input: stream}).on('line', line => output.write(clean(line)+'\n'));
}
function signalGroup(signal) {
  if (!child.pid) return;
  try { process.kill(-child.pid, signal); } catch (error) { if (error.code !== 'ESRCH') throw error; }
}
let stopping = false;
for (const signal of ['SIGINT','SIGTERM']) process.on(signal, () => {
  if (stopping) return;
  stopping = true;
  signalGroup(signal);
  const timer = setTimeout(() => signalGroup('SIGKILL'), Math.max(500, config.kill_timeout-500));
  timer.unref();
});
// PM2 observes the launcher PID; enforce the application tree's RSS limit too.
const pageSizeResult = cp.spawnSync('getconf',['PAGESIZE'],{encoding:'utf8',env:{PATH:config.path},shell:false});
const pageSize = Number(pageSizeResult.stdout?.trim()) || 4096;
const memoryTimer = setInterval(() => {
  if (!config.memory_bytes || stopping || !child.pid) return;
  try {
    const rows = fs.readdirSync('/proc').filter(x => /^\d+$/.test(x)).flatMap(id => {
      try { const fields = fs.readFileSync('/proc/'+id+'/stat','utf8').split(') ').pop().split(' '); return [{id:Number(id),parent:Number(fields[1]),rss:Number(fields[21])*pageSize}]; }
      catch { return []; }
    });
    const ids = new Set([child.pid]);
    for (let changed=true; changed;) { changed=false; for (const row of rows) if (ids.has(row.parent) && !ids.has(row.id)) { ids.add(row.id); changed=true; } }
    const rss = rows.filter(row => ids.has(row.id)).reduce((sum,row) => sum+row.rss,0);
    if (rss > config.memory_bytes) { process.stderr.write('Application tree exceeded configured memory threshold; restarting.\n'); signalGroup('SIGTERM'); setTimeout(() => signalGroup('SIGKILL'),Math.max(500,config.kill_timeout-500)).unref(); }
  } catch { /* A disappearing /proc entry is retried on the next sample. */ }
},5000);
memoryTimer.unref();
child.on('error', error => { process.stderr.write(clean('Application launch failed: '+error.message)+'\n'); process.exitCode=1; });
child.on('exit', (code,signal) => { signalGroup('SIGTERM'); setTimeout(() => signalGroup('SIGKILL'),Math.max(500,config.kill_timeout-500)).unref(); process.exitCode=code === null ? (stopping ? 0 : 1) : code; });

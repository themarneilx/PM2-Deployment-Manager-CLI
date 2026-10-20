'use strict';
const fs = require('node:fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
let semver;
for (const root of input.roots) {
  try { semver = require(require.resolve('semver', {paths: [root]})); break; } catch {}
}
if (!semver) { console.error('Cannot resolve semver from npm/PM2/project; install npm or PM2 before checking engines.'); process.exit(2); }
if (!semver.validRange(input.range)) { console.error('Invalid declared Node engine range.'); process.exit(2); }
console.log(JSON.stringify({version: process.versions.node, range: input.range, satisfied: semver.satisfies(process.versions.node, input.range)}));

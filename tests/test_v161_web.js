// Regression check for the exact JavaScript used by the GitHub Pages filters.
// Requires only Node built-ins. The production app is not modified by this test.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('docs/app.js', 'utf8');
function pick(name) {
  const begin = source.indexOf('function ' + name + '(');
  assert.ok(begin >= 0, 'Missing ' + name);
  const next = source.indexOf('\nfunction ', begin + 1);
  const nextAsync = source.indexOf('\nasync function ', begin + 1);
  const boundaries = [next, nextAsync].filter(index => index >= 0);
  const end = boundaries.length ? Math.min(...boundaries) : source.length;
  return source.slice(begin, end);
}
const ctx = vm.createContext({});
vm.runInContext(['dayNumber', 'latestDate', 'recentMatch'].map(pick).join('\n'), ctx);
const today = ctx.dayNumber('2026-10-30');
function magazine(issued) {
  return { by: { tpml: {date: issued} } };
}
assert.equal(ctx.recentMatch(magazine('2026-11-05'), '30', 'tpml', today), true,
  'Early online release with a future print date must be visible');
assert.equal(ctx.recentMatch(magazine('2026-11-05'), '90', '', today), true);
assert.equal(ctx.recentMatch(magazine('2026-10-24'), '30', 'tpml', today), true);
assert.equal(ctx.recentMatch(magazine('2026-08-01'), '30', 'tpml', today), false);
assert.equal(ctx.recentMatch(magazine('2026-08-01'), 'old90', 'tpml', today), true);
assert.equal(ctx.recentMatch(magazine('2026-11-05'), 'old90', 'tpml', today), false);
console.log('V1.6.1 frontend date filters: passed');

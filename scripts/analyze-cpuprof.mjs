#!/usr/bin/env node
// Top self-time frames from a Node `.cpuprofile` (V8 sampling profile).
//
// Generate one with:
//   node --cpu-prof --cpu-prof-dir=./perf/cpuprof <entry>
//   # or:  node --cpu-prof --cpu-prof-dir=./perf/cpuprof --import tsx <entry>.ts
// Or save from Chrome DevTools Performance → ... → "Save profile" (.cpuprofile).
//
// Usage:
//   node scripts/analyze-cpuprof.mjs <file.cpuprofile> [topN]
//   node scripts/analyze-cpuprof.mjs <file.cpuprofile> 30 --skip-system
//
// Self-time = time the sampler caught each node *itself* on the stack top
// (not its children). Aggregated by function + last two URL path segments
// so anonymous arrow functions in the same file collapse sensibly.

import fs from 'node:fs';

const args = process.argv.slice(2);
const file = args[0];
const topN = Number.isFinite(Number(args[1])) ? Number(args[1]) : 25;
const skipSystem = args.includes('--skip-system');

if (!file) {
  console.error('usage: node analyze-cpuprof.mjs <file.cpuprofile> [topN] [--skip-system]');
  process.exit(2);
}

const prof = JSON.parse(fs.readFileSync(file, 'utf8'));
const { nodes, samples, timeDeltas: deltas } = prof;

const byId = new Map();
for (const n of nodes) byId.set(n.id, n);

// Self-time per node: sum the deltas of samples whose top frame is this node.
const selfTime = new Map();
for (let i = 0; i < samples.length; i++) {
  const id = samples[i];
  const dt = deltas[i] ?? 0;
  selfTime.set(id, (selfTime.get(id) ?? 0) + dt);
}

const total = [...selfTime.values()].reduce((a, b) => a + b, 0);

// V8 emits synthetic frames `(program)`, `(idle)`, `(garbage collector)` etc.
// They are real signal (40% in (program) means lots of time outside named JS
// functions) but they swamp the table. --skip-system hides them so the next
// real frame is visible.
const SYSTEM_FRAMES = new Set([
  '(program)', '(idle)', '(garbage collector)', '(root)', '(no symbol)',
]);

const byFn = new Map();
for (const [id, t] of selfTime) {
  const n = byId.get(id);
  const cf = n.callFrame;
  const fn = cf.functionName || '(anonymous)';
  if (skipSystem && SYSTEM_FRAMES.has(fn)) continue;
  // Compress URLs to last two path segments — full file paths overflow the table.
  const url = cf.url || '';
  const short = url ? url.split(/[\\/]/).slice(-2).join('/') : '(internal)';
  const key = `${fn} @ ${short}:${cf.lineNumber}`;
  byFn.set(key, (byFn.get(key) ?? 0) + t);
}

const sorted = [...byFn.entries()].sort((a, b) => b[1] - a[1]).slice(0, topN);

console.log(`Total self-time: ${(total / 1000).toFixed(1)} ms across ${samples.length} samples`);
if (skipSystem) console.log(`(system frames hidden — drop --skip-system to see (program)/(idle)/etc.)`);
console.log();
console.log('  self_ms   self%  function @ file:line');
console.log('  -------  ------  --------------------');
for (const [k, t] of sorted) {
  const ms = (t / 1000).toFixed(1).padStart(7);
  const pct = ((t / total) * 100).toFixed(1).padStart(5);
  console.log(`  ${ms}  ${pct}%  ${k}`);
}

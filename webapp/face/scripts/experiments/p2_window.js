// Part 2a: accuracy vs analysis length. The first T s of each 30 s scan; truth = mean HR over [0, T].
// N=40 M=A,D2 node scripts/experiments/p2_window.js
import { scan, SEEDS, bpmFor, truthIn, cut } from './motion.js';
import { METHODS } from './p1_motion.js';
import { table, q, frac, pct, f1 } from '../robustness/gen.js';
const N = +process.env.N || 40;
const KEYS = (process.env.M || 'A,D2,F7').split(',');
const TS = [6, 8, 10, 12, 15, 20, 30];
const CELLS = [['still', 1], ['tremor', 1], ['combo', 1], ['talk', 1], ['nod', 1]];
const OBS = process.env.OBS || 'ideal';
for (const key of KEYS) {
  const [label, fn] = METHODS.find(([l]) => l.startsWith(key + ' '));
  const rows = [];
  for (const [sc, lv] of CELLS) {
    const data = SEEDS(N).map((seed, i) => scan({ scenario: sc, seed, bpm: bpmFor(i), motionScale: lv, obs: OBS }));
    const row = [`${sc}×${lv}`];
    for (const T of TS) {
      const res = data.map(({ samples, beats }) => { const r = fn(cut(samples, 0, T)); const e = Math.abs(r.bpm - truthIn(beats, 0, T).bpm); return { e, p: r.quality.pass }; });
      row.push(`${f1(q(res.map(x => x.e), 0.5))} · ${pct(frac(res, x => x.e <= 5))} · ${pct(frac(res, x => x.p))} · ${pct(frac(res, x => x.p && x.e > 5))}`);
    }
    rows.push(row);
  }
  table(`P2a [${OBS}] ${label} — 셀 = |err| 중앙 · ±5 · PASS · 거짓PASS (n=${N}; 30 s 열이 대조군)`, ['시나리오', ...TS.map(t => `${t} s`)], rows);
}

// Area 5: harmonic / subharmonic lock. node scripts/robustness/05_harmonic.js
import { SEEDS, runOne, REAL } from './evalrun.js';
import { table, frac, pct, f1, q } from './gen.js';
const N = +process.env.N || 20;
const shapes = [
  ['사인 (h2=0)', { sinus: true, h2: 0 }],
  ['사인+h2 0.8', { sinus: true, h2: 0.8 }],
  ['사인+h2 1.5 (2차>기본)', { sinus: true, h2: 1.5 }],
  ['PPG 가우스 sw0.1 dicrotic0.3', {}],
  ['PPG 뾰족 sw0.06 dicrotic0.6', { sw: 0.06, dicrotic: 0.6 }],
];
const bpms = [42, 45, 50, 55, 60, 90, 120, 150];
for (const amp of [1, 0.5]) {
  const rows = [];
  for (const [l, sh] of shapes) {
    const row = [l];
    for (const bpm of bpms) {
      const runs = SEEDS(N).map(seed => runOne({ ...REAL, rrJitterMs: 15, rsaMs: 10, amp, noise: 0.5, bpm, shape: sh, seed }));
      const ok = frac(runs, x => x.abs <= 5), dbl = frac(runs, x => Math.abs(x.r.bpm - 2 * x.truth.bpm) <= 5), half = frac(runs, x => Math.abs(x.r.bpm - x.truth.bpm / 2) <= 5);
      const dblPass = frac(runs, x => x.pass && Math.abs(x.r.bpm - 2 * x.truth.bpm) <= 5);
      row.push(`${pct(ok)} / 2×${pct(dbl)}${dblPass ? '(P' + pct(dblPass) + ')' : ''}${half ? ' ½×' + pct(half) : ''}`);
    }
    rows.push(row);
  }
  table(`5. 고조파 잠김 — amp ${amp}, noise 0.5. 셀 = ±5bpm 정답률 / 2배 선택률 (P=2배인데 PASS)`, ['파형 \\ 실제 bpm', ...bpms], rows);
}

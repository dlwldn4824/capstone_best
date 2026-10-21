// HRV gate calibration: RMSSD error vs snrDb (current SNR definition). node scripts/robustness/12_hrv_gate.js
import { SEEDS, REAL } from './evalrun.js';
import { analyze } from '../../src/pipeline/index.js';
import { gen, table, q, pct, frac, f1 } from './gen.js';
const pool = [];
for (const amp of [0.7, 1, 1.5, 2, 3]) for (const noise of [0.1, 0.3, 0.5]) for (const jit of [0, 20, 40, 60])
  SEEDS(8).forEach((seed, i) => { const { samples, truth } = gen({ ...REAL, rsaMs: 0, rrJitterMs: jit, amp, noise, bpm: 58 + (i * 9) % 40, seed }); const r = analyze(samples); pool.push({ snr: r.snrDb, e: r.rmssd - truth.rmssd, t: truth.rmssd, pairs: r.hrvPairs, pass: r.quality.pass }); });
const bins = [[-99, 3], [3, 6], [6, 8], [8, 10], [10, 12], [12, 14], [14, 99]];
table(`12. RMSSD 오차 vs snrDb (n=${pool.length}, 진폭·잡음·지터 0–60 혼합)`, ['snrDb', 'n', '오차 중앙', '|오차| 중앙', '|오차| p90', '|오차|≤15ms', '참 RMSSD 0인데 측정>25'],
  bins.map(([a, b]) => { const s = pool.filter(x => x.snr >= a && x.snr < b && Number.isFinite(x.e)); const z = s.filter(x => x.t < 1);
    return [`[${a},${b})`, s.length, f1(q(s.map(x => x.e), 0.5)), f1(q(s.map(x => Math.abs(x.e)), 0.5)), f1(q(s.map(x => Math.abs(x.e)), 0.9)), s.length ? pct(frac(s, x => Math.abs(x.e) <= 15)) : '-', z.length ? pct(frac(z, x => x.e > 25)) : '-']; }));

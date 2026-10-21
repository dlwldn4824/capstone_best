// Area 6: HRV bias, noise floor, propagation to Baevsky SI -> stress -> zone. node scripts/robustness/06_hrv.js
import { SEEDS, runOne, REAL, stressScore, stressZone } from './evalrun.js';
import { hrvFromRR } from '../../src/pipeline/hrv.js';
import { table, frac, pct, f1, q } from './gen.js';
const N = +process.env.N || 30;

// reference implementation's Baevsky (capstone_best vitals.js): MxDMn floor 0.05 s, needs >=10 intervals
function siRef(rr) {
  if (rr.length < 10) return null;
  const cnt = new Map(); for (const v of rr) { const k = Math.floor(v / 50); cnt.set(k, (cnt.get(k) || 0) + 1); }
  let kb = null, best = -1; for (const k of [...cnt.keys()].sort((a, b) => a - b)) if (cnt.get(k) > best) { best = cnt.get(k); kb = k; }
  const mo = (kb * 50 + 25) / 1000, amo = best / rr.length * 100;
  return amo / (2 * mo * Math.max((Math.max(...rr) - Math.min(...rr)) / 1000, 0.05));
}
const rows = [], zrows = [];
for (const [nl, ncfg] of [['깨끗 amp2 n0.1', { amp: 2, noise: 0.1 }], ['보통 amp1 n0.3', { amp: 1, noise: 0.3 }], ['약함 amp1 n0.6', { amp: 1, noise: 0.6 }]]) {
  for (const jit of [0, 20, 40, 60]) {
    const runs = SEEDS(N).map((seed, i) => runOne({ ...REAL, rsaMs: 0, rrJitterMs: jit, bpm: 60 + (i * 7) % 31, ...ncfg, seed }));
    const tR = runs.map(x => x.truth.rmssd), mR = runs.map(x => x.r.rmssd);
    const stT = runs.map(x => stressScore(hrvFromRR(x.truth.rr).baevskySI));
    const stM = runs.map(x => stressScore(x.r.baevskySI));
    const stRefT = runs.map(x => stressScore(siRef(x.truth.rr))), stRefM = runs.map(x => stressScore(siRef(x.r.rr)));
    const shown = runs.filter(x => x.m.stress != null);
    rows.push([nl, jit, f1(q(runs.map(x => x.snr), 0.5)), f1(q(tR, 0.5)), `${f1(q(mR, 0.5))} [${f1(q(mR, 0.1))}–${f1(q(mR, 0.9))}]`,
      f1(q(runs.map(x => x.r.rmssd - x.truth.rmssd), 0.5)), `${f1(q(stT, 0.5))} → ${f1(q(stM, 0.5))}`, `${f1(q(stRefT, 0.5))} → ${f1(q(stRefM, 0.5))}`,
      pct(frac(runs, (x, i) => stressZone(stT[i]) === stressZone(stM[i]))), pct(shown.length / runs.length),
      pct(frac(runs, x => x.m.hrv_conf === 'high'))]);
  }
}
table('6. HRV — RR 지터별 RMSSD와 스트레스 전파 (RSA 0, bpm 60–90)', ['신호', 'RR 지터 ms', 'SNR 중앙', '참 RMSSD', '측정 RMSSD 중앙 [p10–p90]', '편향 중앙', '스트레스 참→측정 (현행 MxDMn .01)', '참→측정 (참조 .05, ≥10RR)', '구간(zone) 일치', '스트레스 표시됨', "hrv_conf 'high'"], rows);

// Part 1c: failure modes of motion regression. node scripts/experiments/p1c_risk.js
//  - nodHR: nodding at exactly the heart rate (the reference then contains the pulse frequency)
//  - bcgPx: pulse-synchronous head motion (ballistocardiography) in the landmarks
import { scan, SEEDS, bpmFor } from './motion.js';
import { METHODS } from './p1_motion.js';
import { table, q, frac, pct, f1 } from '../robustness/gen.js';
const N = +process.env.N || 30;
const KEYS = ['A', 'C', 'D1', 'D2', 'F5', 'F7', 'G1', 'G2'];
const cells = [['still', { bcgPx: 0.3 }], ['still', { bcgPx: 1 }], ['still', { bcgPx: 1, obs: 'hard' }], ['nodHR', {}], ['nodHR', { motionScale: 0.5 }], ['nod', { bcgPx: 0.5 }]];
for (const [sc, extra] of cells) {
  const data = SEEDS(N).map((seed, i) => scan({ scenario: sc, seed, bpm: bpmFor(i), ...extra }));
  table(`P1c ${sc} ${JSON.stringify(extra)} (n=${N})`, ['방법', '|err| 중앙', '±5', 'PASS', '거짓 PASS', 'SNR 중앙'],
    KEYS.map(k => { const [l, fn] = METHODS.find(([x]) => x.startsWith(k + ' ')); const res = data.map(({ samples, truth }) => { const r = fn(samples); return { e: Math.abs(r.bpm - truth.bpm), p: r.quality.pass, snr: r.snrDb }; });
      return [l, f1(q(res.map(x => x.e), 0.5)), pct(frac(res, x => x.e <= 5)), pct(frac(res, x => x.p)), pct(frac(res, x => x.p && x.e > 5)), f1(q(res.map(x => x.snr), 0.5))]; }));
}

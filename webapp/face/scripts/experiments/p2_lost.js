// Part 2c: what a shorter scan loses — RMSSD, respiration, blink rate at 10/15/20/30 s, with the production code.
// N=40 node scripts/experiments/p2_lost.js
import { scan, SEEDS, bpmFor, truthIn, cut } from './motion.js';
import { analyze } from '../../src/pipeline/index.js';
import { faceState } from '../../src/pipeline/face.js';
import { table, q, frac, pct, f1 } from '../robustness/gen.js';
const N = +process.env.N || 40;
const CELLS = [['still', 1, {}], ['still', 1, { amp: 2, noise: 0.1 }], ['tremor', 1, {}], ['combo', 1, {}]];
for (const [sc, lv, extra] of CELLS) {
  const data = SEEDS(N).map((seed, i) => scan({ scenario: sc, seed, bpm: bpmFor(i), motionScale: lv, ...extra }));
  const rows = [10, 15, 20, 30].map(T => {
    const res = data.map(({ samples, beats, truth }) => {
      const s = cut(samples, 0, T), r = analyze(s), f = faceState(s), tt = truthIn(beats, 0, T);
      const rel = r.hrvReliable && r.quality.pass && r.rmssd > 0 && r.rmssd <= 200;
      return { pass: r.quality.pass, e: Math.abs(r.bpm - tt.bpm), rel, rmErr: Math.abs(r.rmssd - tt.rmssd), rmTrue: tt.rmssd,
        respOk: r.quality.pass && Number.isFinite(r.resp.rate) && r.resp.rate >= 8 && r.resp.rate <= 30, respErr: Math.abs(r.resp.rate - truth.respPerMin),
        blinkShown: f.durationSec >= 20, blinkErr: Math.abs(f.blinkPerMin - truth.blinkPerMin), blinkRel: Math.abs(f.blinkPerMin - truth.blinkPerMin) / truth.blinkPerMin };
    });
    const relR = res.filter(x => x.rel), respR = res.filter(x => x.respOk);
    return [`${T} s`, pct(frac(res, x => x.pass && x.e <= 5)), pct(relR.length / res.length), relR.length ? f1(q(relR.map(x => x.rmErr), 0.5)) : '-', f1(q(res.map(x => x.rmErr), 0.5)),
      pct(respR.length / res.length), respR.length ? f1(q(respR.map(x => x.respErr), 0.5)) : '-',
      pct(frac(res, x => x.blinkShown)), f1(q(res.map(x => x.blinkErr), 0.5)), pct(q(res.map(x => x.blinkRel), 0.5))];
  });
  table(`P2c ${sc}×${lv}${Object.keys(extra).length ? ' ' + JSON.stringify(extra) : ''} (n=${N}; 30 s 행이 대조군)`,
    ['길이', 'PASS∧±5', 'RMSSD 표시(hrvReliable)', 'RMSSD |err| 표시분', 'RMSSD |err| 전체', '호흡 표시', '호흡 |err| 표시분', '깜빡임 표시(≥20 s)', '깜빡임 |err| 회/분', '깜빡임 상대오차'], rows);
}

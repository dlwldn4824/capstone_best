// Area 10: quickBpm live display after 8-12 s. node scripts/robustness/10_quick.js
import { SEEDS, REAL, bpmFor } from './evalrun.js';
import { quickBpm } from '../../src/pipeline/index.js';
import { gen, table, frac, pct, f1, q } from './gen.js';
const N = +process.env.N || 40;
const cells = [
  ['REAL 30fps', {}], ['REAL amp0.6 n0.5', { amp: 0.6, noise: 0.5 }],
  ['24fps 드롭15% 지터10', { fps: 24, dropFrac: 0.15, tsJitterMs: 10 }],
  ['30fps + 놓침 1회', { gaps: 1, gapMin: 0.5, gapMax: 1.5 }],
  ['끄덕임 1.2Hz chroma30% 4px', { motionHz: 1.2, motionShade: 0.006, motionChroma: 0.3, motionPx: 4 }],
];
const rows = [];
for (const [l, c] of cells) {
  const row = [l];
  for (const T of [8, 10, 12]) {
    const errs = SEEDS(N).map((seed, i) => {
      const { samples, truth } = gen({ ...REAL, bpm: bpmFor(i), ...c, seed, dur: T });
      const r = quickBpm(samples);
      return Number.isFinite(r.bpm) ? Math.abs(r.bpm - truth.bpm) : NaN;
    });
    row.push(`${f1(q(errs, 0.5))} / ${pct(frac(errs, e => e > 10))} / ${pct(frac(errs, e => !Number.isFinite(e)))}`);
  }
  rows.push(row);
}
table('10. quickBpm (실시간 표시). 셀 = |err| 중앙 / >10bpm 비율 / 표시 없음', ['조건', '8 s', '10 s', '12 s'], rows);

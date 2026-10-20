// Area 3: motion. node scripts/robustness/03_motion.js
import { sweep, STD_HEADER, stdRow } from './evalrun.js';
import { table, frac, pct } from './gen.js';
const N = +process.env.N || 30;
const cells = [
  ['기준', {}],
  ['끄덕임 0.8Hz shade0.5% 4px', { motionHz: 0.8, motionShade: 0.005, motionPx: 4 }],
  ['끄덕임 1.2Hz shade0.5% 4px', { motionHz: 1.2, motionShade: 0.005, motionPx: 4 }],
  ['끄덕임 1.2Hz shade1% spec0.2% 6px', { motionHz: 1.2, motionShade: 0.01, motionSpec: 0.002, motionPx: 6 }],
  ['말하기 2.0Hz shade0.5% spec0.1% 3px', { motionHz: 2.0, motionShade: 0.005, motionSpec: 0.001, motionPx: 3 }],
  ['말하기 2.5Hz shade1% 3px', { motionHz: 2.5, motionShade: 0.01, motionPx: 3 }],
  ['끄덕임 1.5Hz shade1% 15px (7.5% 폭)', { motionHz: 1.5, motionShade: 0.01, motionPx: 15 }],
  ['끄덕임 1.2Hz shade0.5% chroma30% 4px', { motionHz: 1.2, motionShade: 0.005, motionChroma: 0.3, motionPx: 4 }],
  ['끄덕임 1.2Hz shade1% chroma30% 6px', { motionHz: 1.2, motionShade: 0.01, motionChroma: 0.3, motionPx: 6 }],
  ['말하기 2.0Hz shade0.5% chroma30% 3px', { motionHz: 2.0, motionShade: 0.005, motionChroma: 0.3, motionPx: 3 }],
  ['끄덕임 0.9Hz shade0.3% chroma20% 3px', { motionHz: 0.9, motionShade: 0.003, motionChroma: 0.2, motionPx: 3 }],
  ['느린 이동 60px/30s + 조명 드리프트0.1', { slowDriftPx: 60, drift: 0.1 }],
  ['느린 이동 150px/30s', { slowDriftPx: 150 }],
];
const rows = [];
for (const [l, c] of cells) {
  const runs = sweep(c, N);
  const near = frac(runs, x => c.motionHz && Math.abs(x.r.bpm - c.motionHz * 60) < 3);
  rows.push([...stdRow(l, runs), pct(frac(runs, x => x.r.quality.motionOk)), c.motionHz ? pct(near) : '-']);
}
table('3. 움직임 (REAL 프로필)', [...STD_HEADER, 'motion 조건 통과', 'bpm이 움직임 주파수에 고정'], rows);

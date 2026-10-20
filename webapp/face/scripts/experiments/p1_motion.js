// Part 1: motion compensation. N=30 node scripts/experiments/p1_motion.js
// For every scenario x level x seed the SAME Sample[] goes through every method.
import { scan, SEEDS, bpmFor, SCENARIOS } from './motion.js';
import { analyzeX, GATE } from './methods.js';
const NOMOUTH = { ...GATE, mouth: null };
import { analyze } from '../../src/pipeline/index.js';
import { table, q, frac, pct, f1 } from '../robustness/gen.js';

const N = +process.env.N || 30;
const LEVELS = (process.env.LEVELS || '1,2').split(',').map(Number);
const OBS = process.env.OBS || 'ideal';
const ONLY = process.env.SC ? process.env.SC.split(',') : Object.keys(SCENARIOS);
export const METHODS = [
  ['A 기준 analyze() (POS, 최고 ROI)', s => analyze(s)],
  ['B1 CHROM', s => analyzeX(s, { extract: 'chrom' })],
  ['B2 LGI', s => analyzeX(s, { extract: 'lgi' })],
  ['B3 OMIT 근사', s => analyzeX(s, { extract: 'omit' })],
  ['C POS + 창별 ROI 융합', s => analyzeX(s, { fuse: 'window' })],
  ['D1 POS + 움직임 회귀(WLS)', s => analyzeX(s, { cancel: 'wls' })],
  ['D2 POS + NLMS', s => analyzeX(s, { cancel: 'nlms' })],
  ['D3 RGB 채널 회귀 → POS', s => analyzeX(s, { cancel: 'rgb' })],
  ['E1 POS + 버스트 게이팅(움직임+입)', s => analyzeX(s, { gate: true })],
  ['E2 POS + 버스트 게이팅(움직임만)', s => analyzeX(s, { gate: true, gateOpt: NOMOUTH })],
  ['F1 POS + WLS + 게이팅', s => analyzeX(s, { cancel: 'wls', gate: true })],
  ['F2 POS + 융합 + WLS + 게이팅', s => analyzeX(s, { fuse: 'window', cancel: 'wls', gate: true })],
  ['F3 CHROM + WLS + 게이팅', s => analyzeX(s, { extract: 'chrom', cancel: 'wls', gate: true })],
  ['F4 POS + 융합 + WLS', s => analyzeX(s, { fuse: 'window', cancel: 'wls' })],
  ['F5 POS + NLMS + 게이팅(움직임만)', s => analyzeX(s, { cancel: 'nlms', gate: true, gateOpt: NOMOUTH })],
  ['F6 POS + WLS + 게이팅(움직임만)', s => analyzeX(s, { cancel: 'wls', gate: true, gateOpt: NOMOUTH })],
  ['F7 POS + 융합 + NLMS', s => analyzeX(s, { fuse: 'window', cancel: 'nlms' })],
  // rescue-only: keep the production result when it passes; run motion regression only when it fails
  ['G1 기준, 실패 시에만 NLMS', s => { const a = analyze(s); if (a.quality.pass) return a; const b = analyzeX(s, { cancel: 'nlms' }); return b.quality.pass ? b : a; }],
  ['G2 융합, 실패 시에만 융합+NLMS', s => { const a = analyzeX(s, { fuse: 'window' }); if (a.quality.pass) return a; const b = analyzeX(s, { fuse: 'window', cancel: 'nlms' }); return b.quality.pass ? b : a; }],
];
const SEL = process.env.M ? process.env.M.split(',') : null;
const methods = SEL ? METHODS.filter(([l]) => SEL.some(k => l.startsWith(k + ' '))) : METHODS;

if (process.env.P1_SKIP) { } else {
const agg = methods.map(() => ({ abs: [], pass: [], ms: [] }));
for (const lv of LEVELS) for (const sc of ONLY) {
  if (sc === 'still' && lv !== LEVELS[0]) continue;
  const data = SEEDS(N).map((seed, i) => scan({ scenario: sc, seed, bpm: bpmFor(i), motionScale: lv, obs: OBS }));
  const rows = methods.map(([label, fn], mi) => {
    const res = data.map(({ samples, truth }) => { const t0 = performance.now(); const r = fn(samples); const ms = performance.now() - t0; return { abs: Math.abs(r.bpm - truth.bpm), pass: r.quality.pass, ms }; });
    agg[mi].abs.push(...res.map(x => x.abs)); agg[mi].pass.push(...res.map(x => x.pass)); agg[mi].ms.push(...res.map(x => x.ms));
    return [label, f1(q(res.map(x => x.abs), 0.5)), pct(frac(res, x => x.abs <= 5)), pct(frac(res, x => x.abs <= 3)), pct(frac(res, x => x.pass)),
      pct(frac(res, x => x.pass && x.abs > 5)), pct(frac(res, x => x.pass && x.abs <= 5)), f1(q(res.map(x => x.ms), 0.5))];
  });
  table(`P1 [${OBS}] ${sc} ×${lv} (n=${N})`, ['방법', '|err| 중앙', '±5', '±3', 'PASS', '거짓 PASS', 'PASS∧±5', 'ms 중앙'], rows);
}
table(`P1 [${OBS}] 전체 합계 (시나리오 ${ONLY.join('/')} × 강도 ${LEVELS.join('/')}, n=${agg[0].abs.length})`, ['방법', '|err| 중앙', '±5', '±3', 'PASS', '거짓 PASS', 'PASS∧±5', 'ms 중앙 / p90'],
  methods.map(([l], mi) => { const a = agg[mi], z = a.abs.map((v, i) => ({ v, p: a.pass[i] }));
    return [l, f1(q(a.abs, 0.5)), pct(frac(a.abs, v => v <= 5)), pct(frac(a.abs, v => v <= 3)), pct(frac(a.pass, v => v)), pct(frac(z, x => x.p && x.v > 5)), pct(frac(z, x => x.p && x.v <= 5)), `${f1(q(a.ms, 0.5))} / ${f1(q(a.ms, 0.9))}`]; }));
}

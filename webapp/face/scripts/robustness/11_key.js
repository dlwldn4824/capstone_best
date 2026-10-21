// Before/after key table. node scripts/robustness/11_key.js
// false-PASS = quality.pass && |err| > 5 bpm (over all runs). Uses Result fields only (not src/logic).
import { SEEDS, REAL, bpmFor } from './evalrun.js';
import { analyze } from '../../src/pipeline/index.js';
import { gen, table, frac, pct, f1, q } from './gen.js';
const N = +process.env.N || 40;
const run = (cfg, i, seed) => { const { samples, truth } = gen({ ...REAL, bpm: bpmFor(i), ...cfg, seed }); const r = analyze(samples); return { r, truth, abs: Math.abs(r.bpm - truth.bpm) }; };
const cells = [
  ['REAL 기준', {}],
  ['REAL amp0.7 n0.5', { amp: 0.7, noise: 0.5 }],
  ['24fps+드롭15%+지터10+놓침1', { fps: 24, dropFrac: 0.15, tsJitterMs: 10, gaps: 1 }],
  ['얼굴 놓침 2회 0.5–2s', { gaps: 2 }],
  ['얼굴 놓침 3회 1–2s', { gaps: 3, gapMin: 1 }],
  ['드롭 40%', { dropFrac: 0.4 }],
  ['화면광 1.3Hz 1%', { screenHz: 1.3, screenAmp: 0.01 }],
  ['화면광 2.2Hz 1%', { screenHz: 2.2, screenAmp: 0.01 }],
  ['120Hz 2% chroma @29.5fps', { flickerHz: 120, flickerAmp: 0.02, flickerChroma: 0.3, fps: 29.5 }],
  ['끄덕임 1.2Hz shade1% chroma 6px', { motionHz: 1.2, motionShade: 0.01, motionChroma: 0.3, motionPx: 6 }],
  ['끄덕임 1.2Hz shade0.5% chroma 4px', { motionHz: 1.2, motionShade: 0.005, motionChroma: 0.3, motionPx: 4 }],
  ['말하기 2Hz shade0.5% chroma 3px', { motionHz: 2.0, motionShade: 0.005, motionChroma: 0.3, motionPx: 3 }],
  ['amp 0.35 n0.5', { amp: 0.35, noise: 0.5 }],
  ['50bpm 사인+h2 1.5', { bpm: 50, shape: { sinus: true, h2: 1.5 } }],
  ['45bpm 사인+h2 0.8', { bpm: 45, shape: { sinus: true, h2: 0.8 } }],
  ['45bpm PPG 뾰족', { bpm: 45, shape: { sw: 0.06, dicrotic: 0.6 } }],
  ['맥 없음 + 화면광 1.3Hz 0.3%', { noPulse: true, screenHz: 1.3, screenAmp: 0.003 }],
  ['맥 없음 (잡음만)', { noPulse: true }],
];
const rows = [];
for (const [l, c] of cells) {
  const runs = SEEDS(N).map((s, i) => run(c, i, s));
  const reasons = {};
  for (const x of runs) if (!x.r.quality.pass) reasons[x.r.quality.reason] = (reasons[x.r.quality.reason] || 0) + 1;
  rows.push([l, c.noPulse ? '-' : pct(frac(runs, x => x.abs <= 5)), pct(frac(runs, x => x.r.quality.pass)), c.noPulse ? pct(frac(runs, x => x.r.quality.pass)) : pct(frac(runs, x => x.r.quality.pass && x.abs > 5)),
    Object.entries(reasons).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${k}${v}`).join(' ')]);
}
table(`11. 핵심 조건 (n=${N})`, ['조건', '±5bpm', 'PASS', '거짓 PASS', 'FAIL 사유'], rows);

// HRV: stress-relevant reliability at jitter 0 (true RMSSD 0) and 40
const hr = [];
for (const [l, c] of [['amp2 n0.1', { amp: 2, noise: 0.1 }], ['amp1 n0.3', { amp: 1, noise: 0.3 }], ['amp1 n0.6', { amp: 1, noise: 0.6 }]]) for (const j of [0, 40]) {
  const runs = SEEDS(30).map((s, i) => { const { samples, truth } = gen({ ...REAL, rsaMs: 0, rrJitterMs: j, bpm: 60 + (i * 7) % 31, ...c, seed: s }); return { r: analyze(samples), truth }; });
  const rel = runs.filter(x => x.r.hrvReliable === true);
  hr.push([l, j, f1(q(runs.map(x => x.truth.rmssd), 0.5)), f1(q(runs.map(x => x.r.rmssd), 0.5)), 'hrvReliable' in runs[0].r ? pct(rel.length / runs.length) : '(없음)', rel.length ? f1(q(rel.map(x => x.r.rmssd), 0.5)) : '-']);
}
table('11b. HRV 신뢰 플래그', ['신호', '지터', '참 RMSSD', '측정 RMSSD 중앙', 'hrvReliable', '신뢰분 RMSSD 중앙'], hr);

// resp
const rr = [];
for (const [l, c, t] of [['호흡 15/분', {}, 15], ['호흡 없음', { respAmp: 0, respHeadPx: 0 }, null], ['호흡 없음+드리프트0.1', { respAmp: 0, respHeadPx: 0, drift: 0.1 }, null], ['호흡 약함', { respAmp: 0.003, respHeadPx: 0.3 }, 15]]) {
  const runs = SEEDS(30).map((s, i) => { const { samples } = gen({ ...REAL, bpm: bpmFor(i), ...c, seed: s }); return analyze(samples).resp; });
  if (!runs[0]) { rr.push([l, '(Result.resp 없음)', '-']); continue; }
  const shown = runs.filter(x => Number.isFinite(x.rate));
  rr.push([l, pct(shown.length / runs.length), t == null ? '-' : pct(frac(shown, x => Math.abs(x.rate - t) > 3))]);
}
table('11c. 호흡 (Result.resp)', ['조건', '값 표시', '표시 중 |err|>3'], rr);

// Area 7: test-retest / minimal detectable change. node scripts/robustness/07_retest.js
import { runOne, REAL } from './evalrun.js';
import { table, f1, q, pct, frac } from './gen.js';
const N = +process.env.N || 40;
const profiles = [
  ['70bpm 지터30 RSA20', { bpm: 70, rrJitterMs: 30, rsaMs: 20 }],
  ['85bpm 지터15 RSA10', { bpm: 85, rrJitterMs: 15, rsaMs: 10 }],
  ['62bpm 지터50 RSA30', { bpm: 62, rrJitterMs: 50, rsaMs: 30 }],
];
const sigs = [['신호 좋음 amp1.5 n0.3', { amp: 1.5, noise: 0.3 }], ['보통 amp1 n0.4', { amp: 1, noise: 0.4 }], ['약함 amp0.7 n0.5', { amp: 0.7, noise: 0.5 }]];
const d = (a, b) => (a == null || b == null || !Number.isFinite(a) || !Number.isFinite(b) ? NaN : Math.abs(a - b));
const sd = a => { const f = a.filter(Number.isFinite); const m = f.reduce((x, y) => x + y, 0) / f.length; return Math.sqrt(f.reduce((s, v) => s + (v - m) ** 2, 0) / (f.length - 1)); };
for (const sameBeats of [true, false]) {
  const rows = [];
  for (const [sl, sc] of sigs) for (const [pl, pc] of profiles) {
    const dd = { bpm: [], rmssd: [], stress: [], score: [] }, sdiff = { bpm: [], rmssd: [], stress: [], score: [] };
    let both = 0;
    for (let i = 0; i < N; i++) {
      const bs = 5000 + i;
      const a = runOne({ ...REAL, ...pc, ...sc, seed: 2 * i + 1, beatSeed: sameBeats ? bs : 7000 + 2 * i });
      const b = runOne({ ...REAL, ...pc, ...sc, seed: 2 * i + 2, beatSeed: sameBeats ? bs : 7001 + 2 * i });
      const pairs = { bpm: [a.r.bpm, b.r.bpm], rmssd: [a.m.rmssd, b.m.rmssd], stress: [a.m.stress, b.m.stress], score: [a.score, b.score] };
      for (const k in pairs) { dd[k].push(d(...pairs[k])); sdiff[k].push(pairs[k][0] != null && pairs[k][1] != null ? pairs[k][0] - pairs[k][1] : NaN); }
      if (a.m.stress != null && b.m.stress != null) both++;
    }
    const cell = k => `${f1(q(dd[k], 0.5))} / ${f1(q(dd[k], 0.95))} / ${f1(1.96 * sd(sdiff[k]))}`;
    rows.push([sl, pl, cell('bpm'), cell('rmssd'), cell('stress'), cell('score'), pct(frac(dd.stress, v => v >= 17))]);
  }
  table(`7${sameBeats ? 'a' : 'b'}. 반복측정 차이 — ${sameBeats ? '같은 박동열, 독립 잡음 (순수 측정 잡음)' : '같은 생리 통계, 다른 박동열 (실제 재측정)'}. 셀 = |Δ| 중앙 / p95 / MDC95(=1.96·SD(Δ))`,
    ['신호', '생리', 'bpm', 'RMSSD ms', '스트레스 0–100', '컨디션 점수', '|Δ스트레스|≥17 (64→47 크기) 비율'], rows);
}

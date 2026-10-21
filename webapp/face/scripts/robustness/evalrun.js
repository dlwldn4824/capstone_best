import { analyze, quickBpm } from '../../src/pipeline/index.js';
import { toMetrics, healthScore, stressScore, stressZone } from './legacy_check.js';
import { gen, resampleUniform, q, mean, frac, f1, pct } from './gen.js';

export const SEEDS = n => Array.from({ length: n }, (_, i) => 1000 + i * 7);

export function runOne(cfg, { fix = false } = {}) {
  const { samples, truth } = gen(cfg);
  const s = fix ? resampleUniform(samples, 30) : samples;
  const r = analyze(s, fix ? { fs: 30 } : {});
  const m = toMetrics(r, s);
  const hs = healthScore(m, 7.5, 1, 3);
  return {
    truth, r, m, score: hs.score,
    err: r.bpm - truth.bpm, abs: Math.abs(r.bpm - truth.bpm),
    snr: r.snrDb, pass: r.quality.pass, reason: r.quality.reason,
    rmssdErr: r.rmssd - truth.rmssd,
    n: samples.length,
  };
}

// summary row for a sweep cell
export function summarize(runs) {
  const abs = runs.map(x => x.abs);
  const passRuns = runs.filter(x => x.pass);
  return {
    med: q(abs, 0.5), p90: q(abs, 0.9),
    w5: frac(runs, x => x.abs <= 5),
    pass: frac(runs, x => x.pass),
    falseAcc: runs.length ? frac(runs, x => x.pass && x.abs > 5) : NaN,
    passBad: passRuns.length ? frac(passRuns, x => x.abs > 5) : NaN,
    snr: q(runs.map(x => x.snr), 0.5),
    rmssdBias: mean(runs.map(x => x.rmssdErr)),
  };
}
export const STD_HEADER = ['조건', 'n', '|err| 중앙/p90', '±5bpm', 'PASS율', 'PASS인데 >5bpm (전체 대비)', 'SNR 중앙', 'RMSSD 편향(ms)'];
export function stdRow(label, runs) {
  const s = summarize(runs);
  return [label, runs.length, `${f1(s.med)} / ${f1(s.p90)}`, pct(s.w5), pct(s.pass), pct(s.falseAcc), f1(s.snr), f1(s.rmssdBias)];
}
export { analyze, quickBpm, toMetrics, healthScore, stressScore, stressZone };

// "Realistic but kind" baseline: decent pulse, mild noise, some HRV, breathing.
export const REAL = { amp: 1, noise: 0.3, drift: 0.03, rrJitterMs: 30, rsaMs: 20, respAmp: 0.01, respHeadPx: 1 };
export const bpmFor = i => 55 + ((i * 13) % 66);   // 55..120 spread over seeds
export function sweep(cfg, nSeeds = 20, opt = {}) {
  return SEEDS(nSeeds).map((seed, i) => runOne({ ...REAL, bpm: bpmFor(i), ...cfg, seed }, opt));
}

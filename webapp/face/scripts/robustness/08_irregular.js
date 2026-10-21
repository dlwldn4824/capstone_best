// Area 8: irregular flag false-positive / sensitivity. node scripts/robustness/08_irregular.js
import { SEEDS, runOne, REAL } from './evalrun.js';
import { irregularOf } from './legacy_check.js';
import { table, frac, pct, f1, q } from './gen.js';
const N = +process.env.N || 60;
const rows = [];
for (const [sl, sc] of [['깨끗 amp2 n0.1', { amp: 2, noise: 0.1 }], ['amp2 n0.2', { amp: 2, noise: 0.2 }], ['amp1.5 n0.2', { amp: 1.5, noise: 0.2 }]]) {
  for (const [rl, rc] of [['정상 지터20 RSA20', { rrJitterMs: 20, rsaMs: 20 }], ['정상 지터40 RSA30', { rrJitterMs: 40, rsaMs: 30 }], ['정상 지터60 RSA40', { rrJitterMs: 60, rsaMs: 40 }], ['AF 유사 (50% 박동 ×0.6–1.4)', { rrJitterMs: 20, afFrac: 0.5 }]]) {
    const runs = SEEDS(N).map((seed, i) => runOne({ ...REAL, ...sc, ...rc, bpm: 60 + (i * 7) % 31, seed }));
    const hi = runs.filter(x => x.m.signal === 'high');
    rows.push([sl, rl, f1(q(runs.map(x => x.snr), 0.5)), pct(hi.length / runs.length), hi.length ? pct(frac(hi, x => x.m.irregular === true)) : '-',
      pct(frac(runs, x => irregularOf(x.truth.rr) === true)), pct(frac(runs, x => irregularOf(x.r.rr) === true))]);
  }
}
table('8. 불규칙 플래그', ['신호', '실제 리듬', 'SNR 중앙', "signal 'high' 비율", "high 중 irregular=true", '참 RR로 판정 시 true', '측정 RR(신호 무관) true'], rows);

// Area 9: respiration (resp.js) confident-wrong. node scripts/robustness/09_resp.js
import { SEEDS, runOne, REAL } from './evalrun.js';
import { table, frac, pct, f1, q } from './gen.js';
const N = +process.env.N || 40;
const cells = [
  ['호흡 15/분 (밝기1% + 머리 1px)', { respHz: 0.25, respAmp: 0.01, respHeadPx: 1 }, 15],
  ['호흡 15/분 약함 (밝기0.3%, 머리 0.3px)', { respHz: 0.25, respAmp: 0.003, respHeadPx: 0.3 }, 15],
  ['호흡 10/분 (밝기1% + 머리 1px)', { respHz: 1 / 6, respAmp: 0.01, respHeadPx: 1 }, 10],
  ['호흡 성분 없음', { respAmp: 0, respHeadPx: 0 }, null],
  ['호흡 없음 + 조명 드리프트 0.1', { respAmp: 0, respHeadPx: 0, drift: 0.1 }, null],
  ['호흡 15/분 + 머리 흔들림 0.4Hz(24/분) 3px', { respHz: 0.25, motionHz: 0.4, motionPx: 3, motionShade: 0.003 }, 15],
  ['호흡 15/분 + 느린 이동 60px', { respHz: 0.25, slowDriftPx: 60 }, 15],
];
const rows = [];
for (const [l, c, truth] of cells) {
  const runs = SEEDS(N).map((seed, i) => runOne({ ...REAL, ...c, bpm: 60 + (i * 7) % 31, seed }));
  const shown = runs.filter(x => x.m.rr != null);
  const errs = shown.map(x => truth == null ? NaN : Math.abs(x.m.rr - truth));
  rows.push([l, pct(shown.length / runs.length), pct(frac(runs, x => x.m.rr_conf === 'mid')),
    shown.length ? `${f1(q(shown.map(x => x.m.rr), 0.1))}–${f1(q(shown.map(x => x.m.rr), 0.9))}` : '-',
    truth == null ? 'n/a (참 없음)' : `${f1(q(errs, 0.5))} / ${f1(q(errs, 0.9))}`,
    truth == null ? '-' : (shown.length ? pct(frac(shown, x => Math.abs(x.m.rr - truth) > 3)) : '-')]);
}
table('9. 호흡수 (resp.js)', ['조건', '값 표시 비율', "rr_conf 'mid'", '표시된 값 p10–p90 (회/분)', '|err| 중앙/p90', '표시 중 |err|>3회/분'], rows);

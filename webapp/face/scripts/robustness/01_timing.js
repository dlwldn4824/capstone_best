// Area 1: timing irregularities. node scripts/robustness/01_timing.js
import { sweep, summarize, STD_HEADER, stdRow } from './evalrun.js';
import { table, f1, pct } from './gen.js';
const N = +process.env.N || 30;
const cells = [
  ['30fps 균일 (기준)', {}],
  ['15fps 균일', { fps: 15 }], ['20fps 균일', { fps: 20 }], ['24fps 균일', { fps: 24 }],
  ['드롭 10%', { dropFrac: 0.1 }], ['드롭 20%', { dropFrac: 0.2 }], ['드롭 40%', { dropFrac: 0.4 }],
  ['타임스탬프 지터 ±5ms', { tsJitterMs: 5 }], ['지터 ±15ms', { tsJitterMs: 15 }],
  ['얼굴 놓침 1회 0.5–2s', { gaps: 1 }], ['얼굴 놓침 2회', { gaps: 2 }], ['얼굴 놓침 3회 1–2s', { gaps: 3, gapMin: 1 }],
  ['rAF 60Hz 중복프레임 50%', { dupFrac: 0.5 }],
  ['현실 조합: 24fps+드롭15%+지터10+놓침1', { fps: 24, dropFrac: 0.15, tsJitterMs: 10, gaps: 1 }],
  ['저전력: 15fps+드롭20%+놓침2', { fps: 15, dropFrac: 0.2, tsJitterMs: 10, gaps: 2 }],
];
const rows = [], fixRows = [];
for (const [label, cfg] of cells) {
  const runs = sweep(cfg, N);
  const fixed = sweep(cfg, N, { fix: true });
  const sf = summarize(fixed);
  const errs = runs.map(x => x.err), meanErr = errs.reduce((a, b) => a + b, 0) / errs.length;
  rows.push([...stdRow(label, runs), f1(meanErr), f1(runs.reduce((a, x) => a + x.r.fsEstimated, 0) / runs.length)]);
  fixRows.push([label, `${f1(sf.med)} / ${f1(sf.p90)}`, pct(sf.w5), pct(sf.pass), f1(sf.rmssdBias)]);
}
table('1. 타이밍 — 현재 파이프라인 (REAL 프로필, bpm 55–120)', [...STD_HEADER, '평균 부호 오차', 'fs 추정'], rows);
table('1b. 같은 데이터, 시간축 균일 재표본화(30Hz 선형) 후 analyze(fs=30) — 제안 수정', ['조건', '|err| 중앙/p90', '±5bpm', 'PASS율', 'RMSSD 편향'], fixRows);

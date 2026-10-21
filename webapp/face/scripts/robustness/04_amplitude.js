// Area 4: low pulse amplitude, SNR calibration, noise-only false pass. node scripts/robustness/04_amplitude.js
import { sweep, STD_HEADER, stdRow } from './evalrun.js';
import { table, frac, pct, f1, q } from './gen.js';
const N = +process.env.N || 40;
const amps = [1.5, 1, 0.7, 0.5, 0.35, 0.25, 0.18, 0.12, 0.08];
const all = [];
const rows = [];
for (const amp of amps) {
  const runs = sweep({ amp, noise: 0.5 }, N);
  all.push(...runs);
  rows.push(stdRow(`amp ${amp} (green std ${(0.32 * amp).toFixed(2)}%), noise 0.5`, runs));
}
table('4a. 맥파 진폭 스윕 (REAL, 잡음 0.5)', STD_HEADER, rows);

// calibration of OUR snrDb over all runs (incl. mildly perturbed ones)
const extra = [];
for (const amp of [1, 0.5, 0.25]) for (const c of [{ motionHz: 1.2, motionShade: 0.006, motionChroma: 0.3, motionPx: 4 }, { dropFrac: 0.2 }, { gaps: 1 }, { screenHz: 1.6, screenAmp: 0.004 }]) extra.push(...sweep({ amp, noise: 0.5, ...c }, 15));
const pool = [...all, ...extra];
const bins = [[-99, -6], [-6, -3], [-3, 0], [0, 3], [3, 6], [6, 10], [10, 99]];
table(`4b. SNR(우리 정의) 보정표 — 풀 ${pool.length}회 (진폭 스윕 + 움직임/드롭/놓침/화면광 혼합)`, ['snrDb 구간', 'n', 'P(|err|≤2)', 'P(|err|≤5)', '|err| p90'],
  bins.map(([a, b]) => { const s = pool.filter(x => x.snr >= a && x.snr < b); return [`[${a}, ${b})`, s.length, s.length ? pct(frac(s, x => x.abs <= 2)) : '-', s.length ? pct(frac(s, x => x.abs <= 5)) : '-', f1(q(s.map(x => x.abs), 0.9))]; }));

// noise-only: no pulse at all
const noiseCells = [
  ['맥파 없음, 백색잡음 0.5만', { noPulse: true, drift: 0, respAmp: 0, respHeadPx: 0 }],
  ['맥파 없음, REAL(드리프트·호흡)', { noPulse: true }],
  ['맥파 없음, 잡음 0.2', { noPulse: true, noise: 0.2 }],
  ['맥파 없음 + 화면광 1.3Hz 0.3%', { noPulse: true, screenHz: 1.3, screenAmp: 0.003 }],
];
const nRows = [];
for (const [l, c] of noiseCells) {
  const runs = sweep(c, 100);
  const sig = runs.map(x => x.m.signal);
  nRows.push([l, runs.length, f1(q(runs.map(x => x.snr), 0.5)), f1(q(runs.map(x => x.snr), 0.95)), pct(frac(runs, x => x.pass)), pct(frac(sig, s => s === 'mid')), pct(frac(sig, s => s === 'high')), pct(frac(runs, x => x.m.stress != null))]);
}
table('4c. 잡음만(맥 없음) 입력 — 거짓 통과율', ['입력', 'n', 'SNR 중앙', 'SNR p95', 'PASS율(SNR≥0)', "signal 'mid'", "signal 'high'", '스트레스 숫자 표시'], nRows);

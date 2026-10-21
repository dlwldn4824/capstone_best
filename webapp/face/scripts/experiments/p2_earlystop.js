// Part 2b: early-stopping rules simulated as if live (1 s updates). N=40 M=A node scripts/experiments/p2_earlystop.js
// Every second t (6..30): live estimate on the last 10 s (growing before 10 s) and the full-analysis result on [0, t].
// A rule stops at t when its condition holds; the reported result is the full analysis on [0, t] (bpm + quality gates).
// If it never fires by maxSec, the result is the full analysis at maxSec. Truth = mean HR over [0, stop].
import { scan, SEEDS, bpmFor, truthIn, cut } from './motion.js';
import { METHODS } from './p1_motion.js';
import { table, q, frac, pct, f1, mean } from '../robustness/gen.js';
import { estimateBpm } from '../../src/pipeline/spectrum.js';
import { SEARCH_BAND, SPEC_OPTS } from '../../src/pipeline/index.js';
const N = +process.env.N || 40;
const KEYS = (process.env.M || 'A').split(',');
const OBS = process.env.OBS || 'ideal';
const CELLS = (process.env.CELLS || 'still:1,tremor:1,combo:1,talk:1,nod:1').split(',').map(c => c.split(':')).map(([a, b]) => [a, +b]);
const T0 = 6, TMAX = 30;
const EXTRA = JSON.parse(process.env.EXTRA || '{}');   // e.g. EXTRA='{"amp":0.4,"noise":0.6}' for a weak-signal stress test

function liveTrace(samples, beats, fn) {
  const tr = [];
  for (let t = T0; t <= TMAX; t++) {
    const live = fn(cut(samples, Math.max(0, t - 10), t));
    let peaks = [];
    const lp = live.pulse || live.debug?.pulse;
    if (lp) { const sp = estimateBpm(lp, 30, SEARCH_BAND, 1024, SPEC_OPTS); for (let i = 1; i < sp.power.length - 1; i++) if (sp.power[i] >= sp.power[i - 1] && sp.power[i] >= sp.power[i + 1] && sp.power[i] >= 0.3) peaks.push(sp.freqs[i]); }
    const full = t === TMAX || t >= 8 ? fn(cut(samples, 0, t)) : { bpm: NaN, quality: { pass: false } };
    tr.push({ t, live: live.bpm, snr: live.snrDb, peaks, full: full.bpm, pass: full.quality.pass, truth: truthIn(beats, 0, t).bpm });
  }
  return tr;
}
const at = (tr, t) => tr[t - T0];

// stability rule: last K live estimates all within ±tol of the newest; optional live SNR floor; optional full-analysis PASS
const stab = ({ min, K, tol, snr = -Infinity, needPass = false, max }) => tr => {
  for (let t = Math.max(min, T0 + K - 1); t <= max; t++) {
    const w = []; for (let k = 0; k < K; k++) w.push(at(tr, t - k));
    if (w.some(x => !Number.isFinite(x.live))) continue;
    if (w.every(x => Math.abs(x.live - w[0].live) <= tol) && w[0].snr >= snr && (!needPass || at(tr, t).pass)) return { t, early: t < max };
  }
  return { t: max, early: false };
};
// Kalman peak tracker: z = spectral peak nearest the track (within ±12 bpm), else the top peak with inflated R.
// Stop when posterior sd <= sdStop, last K innovations within ±tol, t >= min, and (optionally) full PASS.
const kalman = ({ min, max, sdStop = 1.5, K = 3, tol = 4, needPass = true, qv = 0.25 }) => tr => {
  let x = NaN, P = 225; const innov = [];
  for (let t = T0; t <= max; t++) {
    const u = at(tr, t);
    if (!Number.isFinite(u.live)) { P += qv; innov.length = 0; continue; }
    if (!Number.isFinite(x)) { x = u.live; P = 100; continue; }
    P += qv;
    let z = u.live, R = 4 * Math.max(1, 10 ** ((3 - u.snr) / 10));
    const near = u.peaks.filter(f => Math.abs(f - x) <= 12).sort((a, b) => Math.abs(a - x) - Math.abs(b - x));
    if (near.length) z = near[0]; else R *= 25;
    const kg = P / (P + R); innov.push(z - x); x += kg * (z - x); P *= 1 - kg;
    if (innov.length > K) innov.shift();
    if (t >= min && Math.sqrt(P) <= sdStop && innov.length === K && innov.every(v => Math.abs(v) <= tol) && (!needPass || u.pass)) return { t, early: t < max };
  }
  return { t: max, early: false };
};
const RULES = [
  ['대조군: 고정 30 s', () => ({ t: 30, early: false })],
  ['고정 20 s', () => ({ t: 20, early: false })],
  ['고정 15 s', () => ({ t: 15, early: false })],
  ['참고 앱: 3연속 ±3, 최소 8, 최대 20', stab({ min: 8, K: 3, tol: 3, max: 20 })],
  ['3연속 ±3, 최소 8, 최대 30', stab({ min: 8, K: 3, tol: 3, max: 30 })],
  ['3연속 ±3 + PASS, 최소 10, 최대 30', stab({ min: 10, K: 3, tol: 3, needPass: true, max: 30 })],
  ['3연속 ±2 + SNR≥3 + PASS, 최소 10, 최대 30', stab({ min: 10, K: 3, tol: 2, snr: 3, needPass: true, max: 30 })],
  ['5연속 ±2 + PASS, 최소 10, 최대 30', stab({ min: 10, K: 5, tol: 2, needPass: true, max: 30 })],
  ['5연속 ±2 + SNR≥3 + PASS, 최소 12, 최대 30', stab({ min: 12, K: 5, tol: 2, snr: 3, needPass: true, max: 30 })],
  ['3연속 ±2 + SNR≥3 + PASS, 최소 15, 최대 30', stab({ min: 15, K: 3, tol: 2, snr: 3, needPass: true, max: 30 })],
  ['칼만 추적 sd≤1.5 + PASS, 최소 10, 최대 30', kalman({ min: 10, max: 30 })],
  ['칼만 추적 sd≤1.0 + PASS, 최소 12, 최대 30', kalman({ min: 12, max: 30, sdStop: 1.0 })],
];
for (const key of KEYS) {
  const [label, fn] = METHODS.find(([l]) => l.startsWith(key + ' '));
  const traces = [];
  for (const [sc, lv] of CELLS) SEEDS(N).forEach((seed, i) => { const { samples, beats } = scan({ scenario: sc, seed, bpm: bpmFor(i), motionScale: lv, obs: OBS, ...EXTRA }); traces.push({ sc, tr: liveTrace(samples, beats, fn) }); });
  const evalRule = (rule, trs) => trs.map(({ tr }) => { const s = rule(tr), u = at(tr, s.t); const e = Math.abs(u.full - u.truth); return { t: s.t, early: s.early, e, pass: u.pass }; });
  const row = (name, res) => [name, f1(mean(res.map(x => x.t))), f1(q(res.map(x => x.t), 0.5)), pct(frac(res, x => !x.early)), pct(frac(res, x => x.e <= 5)), pct(frac(res, x => x.pass)), pct(frac(res, x => x.pass && x.e <= 5)), pct(frac(res, x => x.early && x.pass && x.e > 5)), pct(frac(res, x => x.pass && x.e > 5))];
  const H = ['규칙', '평균 s', '중앙 s', '최대까지 감', '±5 (멈춘 시점)', 'PASS', 'PASS∧±5', '조기 거짓 수락', '거짓 PASS 전체'];
  table(`P2b [${OBS}${process.env.EXTRA ? ' ' + process.env.EXTRA : ''}] ${label} — 전체 (${CELLS.map(c => c.join('×')).join(', ')}; n=${traces.length})`, H, RULES.map(([n, r]) => row(n, evalRule(r, traces))));
  for (const [sc, lv] of CELLS) {
    const trs = traces.filter(x => x.sc === sc);
    table(`P2b [${OBS}] ${label} — ${sc}×${lv} (n=${trs.length})`, H, RULES.filter((_, i) => [0, 3, 6, 8, 10].includes(i)).map(([n, r]) => row(n, evalRule(r, trs))));
  }
}

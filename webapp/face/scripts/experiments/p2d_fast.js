// Part 2d: 측정을 10초 아래로 내릴 수 있나.  node scripts/experiments/p2d_fast.js
//
// 지금 앱은 빨라야 10초다. 안정 조건(3연속 ±2 bpm · SNR ≥ 3)은 6초면 차는데,
// 조기 종료가 '품질 통과'를 전제로 하고 품질은 QUALITY.minSamples = 240 (8초) 미만을 'short' 로 거부하기 때문이다.
// 8초 벽을 내리면 거짓 통과를 막던 장치 하나가 빠진다. 그 자리를 무엇으로 메울지 재는 실험이다.
//
// 메우는 장치: **반쪽 합의**. [0, t] 를 겹치지 않는 두 반으로 갈라 각각 bpm 을 재고, 둘이 ±tol 안이어야 멈춘다.
//   연속 추정 3개는 창이 겹쳐 같은 잡음을 공유한다 — 서로 독립 증거가 아니다.
//   겹치지 않는 두 반은 잡음이 독립이라, 둘이 같은 bpm 을 가리키면 그건 맥박이다.
//   (구간 선택 bestWindow 의 agreeMin 과 같은 생각)
//
// 돌리는 법
//   node scripts/experiments/p2d_fast.js                 # 합성 시나리오, 걸린 시간 · 정확도
//   NOPULSE=1 node scripts/experiments/p2d_fast.js       # 맥 없는 입력에서 거짓 통과율
//   OBS=hard N=30 node scripts/experiments/p2d_fast.js
import { scan, SEEDS, bpmFor, truthIn, cut } from './motion.js';
import { analyze } from '../../src/pipeline/index.js';
import { QUALITY } from '../../src/pipeline/quality.js';
import { table, q, frac, pct, f1, mean } from '../robustness/gen.js';

const N = +process.env.N || 30;
const OBS = process.env.OBS || 'ideal';
const CELLS = (process.env.CELLS || 'still:1,tremor:1,combo:1,talk:1,nod:1').split(',')
  .map(c => c.split(':')).map(([a, b]) => [a, +b]);
const NOPULSE = !!process.env.NOPULSE;
const T0 = 4, TMAX = 30, HALF_MAX = 14;      // 반쪽 합의는 짧은 구간에서만 쓰므로 거기까지만 계산한다

// 판정 가능한 최소 길이를 6초로 내린 채 전부 돌린다 (지금 앱에 적용된 값).
// 최소 10초 규칙은 이 값에 영향받지 않으므로 (10초 = 300샘플) 바꾸기 전 숫자가 그대로 나온다.
QUALITY.minSamples = 180;

const one = s => analyze(s, { resp: false, windowRetry: false, motionRetry: false });

function trace(samples, beats) {
  const tr = [];
  for (let t = T0; t <= TMAX; t++) {
    const live = one(cut(samples, Math.max(0, t - 10), t));
    const live6 = one(cut(samples, Math.max(0, t - 6), t));
    const full = analyze(cut(samples, 0, t), { resp: false });
    let half = Infinity;
    if (t <= HALF_MAX) {
      const a = one(cut(samples, 0, t / 2)), b = one(cut(samples, t / 2, t));
      half = Math.abs(a.bpm - b.bpm);
    }
    tr.push({ t, live: live.bpm, snr: live.snrDb, live6: live6.bpm, snr6: live6.snrDb,
      full: full.bpm, pass: full.quality.pass,
      half, truth: NOPULSE ? NaN : truthIn(beats, 0, t).bpm });
  }
  return tr;
}
const at = (tr, t) => tr[t - T0];

// K연속 ±tol + 최신 SNR ≥ snr + 품질 통과 + (쓰면) 반쪽 합의 ±halfTol
// win: 안정성을 보는 실시간 창 (10초 = 지금 앱, 6초 = 더 빨리 반응하지만 더 시끄럽다)
const rule = ({ min, K = 3, tol = 2, snr = 3, halfTol = Infinity, win = 10, max = TMAX }) => tr => {
  const B = win === 6 ? 'live6' : 'live', S = win === 6 ? 'snr6' : 'snr';
  for (let t = Math.max(min, T0 + K - 1); t <= max; t++) {
    const w = []; for (let k = 0; k < K; k++) w.push(at(tr, t - k));
    if (w.some(x => !Number.isFinite(x[B]))) continue;
    const u = at(tr, t);
    if (w.every(x => Math.abs(x[B] - u[B]) <= tol) && u[S] >= snr && u.pass && u.half <= halfTol)
      return { t, early: t < max };
  }
  return { t: max, early: false };
};

const RULES = [
  ['바꾸기 전 — 3연속 ±2 · SNR≥3 · 최소 10초', rule({ min: 10, snr: 3 })],
  ['최소 시간만 6초로', rule({ min: 6, snr: 3 })],
  ['SNR 문턱만 0 dB 로', rule({ min: 10, snr: 0 })],
  ['바꾼 뒤 — 3연속 ±2 · SNR≥0 · 최소 6초', rule({ min: 6, snr: 0 })],
  ['참고: SNR 조건을 품질(−3 dB)에 맡기면', rule({ min: 6, snr: -Infinity })],
  ['참고: 안정 조건을 빼면', rule({ min: 6, K: 1, tol: Infinity, snr: 0 })],
  ['참고: 반쪽 합의 ±3 을 더하면', rule({ min: 6, snr: 0, halfTol: 3 })],
];

const traces = [];
for (const [sc, lv] of CELLS) SEEDS(N).forEach((seed, i) => {
  const { samples, beats } = scan({ scenario: sc, seed, bpm: bpmFor(i), motionScale: lv, obs: OBS, noPulse: NOPULSE });
  traces.push({ sc, tr: trace(samples, beats) });
});

const run = (r, trs) => trs.map(({ tr }) => {
  const s = r(tr), u = at(tr, s.t);
  return { t: s.t, early: s.early, e: Math.abs(u.full - u.truth), pass: u.pass };
});

if (NOPULSE) {
  const H = ['규칙', '거짓 통과', '중앙 s'];
  table(`P2d [${OBS}] 맥 없는 입력 — 멈추고 값을 낸 비율 = 거짓 통과 (${CELLS.map(c => c.join('×')).join(', ')}; n=${traces.length})`,
    H, RULES.map(([n, r]) => { const res = run(r, traces); return [n, pct(frac(res, x => x.early && x.pass)), f1(q(res.map(x => x.t), 0.5))]; }));
  for (const [sc, lv] of CELLS) {
    const trs = traces.filter(x => x.sc === sc);
    table(`P2d [${OBS}] 맥 없음 — ${sc}×${lv} (n=${trs.length})`, H,
      RULES.map(([n, r]) => { const res = run(r, trs); return [n, pct(frac(res, x => x.early && x.pass)), f1(q(res.map(x => x.t), 0.5))]; }));
  }
} else {
  const H = ['규칙', '평균 s', '중앙 s', '30초까지 감', '±5 (멈춘 시점)', 'PASS', 'PASS∧±5', '조기 거짓 수락'];
  const row = (name, res) => [name, f1(mean(res.map(x => x.t))), f1(q(res.map(x => x.t), 0.5)),
    pct(frac(res, x => !x.early)), pct(frac(res, x => x.e <= 5)), pct(frac(res, x => x.pass)),
    pct(frac(res, x => x.pass && x.e <= 5)), pct(frac(res, x => x.early && x.pass && x.e > 5))];
  table(`P2d [${OBS}] 조기 종료 — 전체 (${CELLS.map(c => c.join('×')).join(', ')}; n=${traces.length})`,
    H, RULES.map(([n, r]) => row(n, run(r, traces))));
  for (const [sc, lv] of CELLS) {
    const trs = traces.filter(x => x.sc === sc);
    table(`P2d [${OBS}] 조기 종료 — ${sc}×${lv} (n=${trs.length})`, H, RULES.map(([n, r]) => row(n, run(r, trs))));
  }
}

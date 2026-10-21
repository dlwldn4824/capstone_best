// Part 3: the quality gate itself. N=20 node scripts/experiments/p3_gate.js
//
// P1 showed the estimator is already accurate under motion (G2: 96% within ±5 bpm) while only 66% of scans PASS.
// So most rejections are false alarms, not bad measurements. This measures that gap and the two fixes:
//   (1) loosening the motion / SNR thresholds, (2) falling back to the cleanest WINDOW.sec window when the whole scan fails.
// The safety number is the last column: a fix is only acceptable if 거짓 통과 (passes with |err| > 5 bpm) stays at 0%.
import { scan, SEEDS, bpmFor, SCENARIOS } from './motion.js';
import { analyze, WINDOW } from '../../src/pipeline/index.js';
import { assessQuality, QUALITY } from '../../src/pipeline/quality.js';
import { table, frac, pct } from '../robustness/gen.js';

const N = +process.env.N || 20;
const OBS = process.env.OBS || 'hard';
const LEVELS = (process.env.LEVELS || '1,2').split(',').map(Number);
const ONLY = process.env.SC ? process.env.SC.split(',') : ['still', 'tremor', 'sway', 'nod', 'talk', 'turn', 'combo'];

// 이 변경 전의 기준
const BEFORE = { ...QUALITY, motionFrac: 0.035, motionRatioMin: 0.9, snrMinDb: 0 };

// analyze() 는 QUALITY 로만 판정하므로, 다른 기준을 보려면 결과 지표에 다시 적용한다
const withGate = (samples, r, gate) =>
  assessQuality(samples, r.snrDb, gate, { coverage: r.coverage, interference: r.interference, roiAgree: r.roiAgree });

const WAYS = [
  ['이전 기준 (이동 3.5%/90% · SNR ≥ 0), 전체 30초', (s) => { const r = analyze(s, { resp: false, windowRetry: false }); return { r, pass: withGate(s, r, BEFORE).pass }; }],
  ['지금 기준 (이동 5%/85% · SNR ≥ -3), 전체 30초', (s) => { const r = analyze(s, { resp: false, windowRetry: false }); return { r, pass: withGate(s, r, QUALITY).pass }; }],
  // 실제 코드 경로 그대로 (analyze 안에서 구간 선택까지 한다)
  ['지금 기준 + 구간 선택', (s) => { const r = analyze(s, { resp: false }); return { r, pass: r.quality.pass }; }],
];

const agg = WAYS.map(() => []);
const reasons = {};
const all = [];

for (const lv of LEVELS) for (const sc of ONLY) {
  if (!SCENARIOS[sc]) throw new Error(`알 수 없는 시나리오: ${sc}`);
  for (const [i, seed] of SEEDS(N).entries()) {
    const { samples, truth } = scan({ scenario: sc, seed, bpm: bpmFor(i), motionScale: lv, obs: OBS });
    all.push(Math.abs(analyze(samples, { resp: false, windowRetry: false }).bpm - truth.bpm));
    WAYS.forEach(([, fn], wi) => {
      const { r, pass } = fn(samples);
      agg[wi].push({ abs: Math.abs(r.bpm - truth.bpm), pass });
    });
    // 이전 기준에서 무엇 때문에 떨어졌나
    const base = analyze(samples, { resp: false, windowRetry: false });
    const qq = withGate(samples, base, BEFORE);
    if (!qq.pass) reasons[qq.reason] = (reasons[qq.reason] || 0) + 1;
  }
}

const n = agg[0].length;
console.log(`\n# P3 품질 기준 (obs=${OBS}, 시나리오 ${ONLY.join('/')} × 강도 ${LEVELS.join('/')}, n=${n})\n`);
console.log(`bpm 자체가 참값 ±5 안인 비율: **${pct(frac(all, v => v <= 5))}** — 계산은 이미 맞는다. 아래는 그중 무엇을 통과시키느냐의 문제다.\n`);

table('P3 통과율', ['방식', '통과', '통과∧±5', '거짓 통과', '맞는데 거부'],
  WAYS.map(([label], wi) => {
    const a = agg[wi];
    return [label, pct(frac(a, x => x.pass)), pct(frac(a, x => x.pass && x.abs <= 5)), pct(frac(a, x => x.pass && x.abs > 5)), pct(frac(a, x => !x.pass && x.abs <= 5))];
  }));

table('P3 이전 기준에서의 실패 이유', ['이유', '전체 대비'],
  Object.entries(reasons).sort((a, b) => b[1] - a[1]).map(([k, v]) => [k, pct(v / n)]));

console.log(`\n구간 선택은 ${WINDOW.sec}초 구간을 ${WINDOW.stepSec}초 간격으로 훑어, 통과한 것 중 SNR 이 가장 높은 것을 쓴다.`);
console.log(`같은 bpm(±3)을 내는 구간이 ${WINDOW.agreeMin}개 이상일 때만 쓴다 — 창을 여러 개 고르는 것은 우연히 걸릴 기회를 주는 일이라, 이 조건이 없으면 맥박 없는 신호가 7% 통과했다.`);
console.log('거짓 통과가 0% 로 유지되는 것이 조건이다 — 통과를 늘리려고 틀린 값을 받아들이면 안 된다.');

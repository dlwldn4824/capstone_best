// 파이프라인 공개 인터페이스. UI는 이 파일의 analyze()·quickBpm()만 호출한다.
//
// Sample = { t(ms), forehead[r,g,b], lcheek[r,g,b], rcheek[r,g,b], faceWidth, faceCenter[x,y], brightness, blink, mouthOpen }
// Result = { bpm, snrDb, rr, rmssd, sdnn, pnn50, baevskySI, meanRR, hrvReliable, hrvPairs, quality, roiBest, perRoi, method,
//            fsEstimated, fsGrid, durationSec, coverage, interference, resp, debug }
//
// 맥파 고르기 (G2, scripts/experiments/p1_motion.js): 합친 RGB · 이마 · 양 볼 맥파를 6초 창마다 SNR 가중으로 융합한다.
// 그 결과가 품질 기준에 떨어지면 한 번만, 머리 움직임 참조로 NLMS 상쇄를 한 뒤 다시 융합해 본다. 통과하면 그것을 쓴다.
// 합성 움직임 9종: ±5 bpm 81% → 96%, 품질 통과 57% → 73%, 거짓 통과 0%.
// 그래도 떨어지면 깨끗한 구간만 골라 다시 본다 (bestWindow, 아래).

import { pos } from './pos.js';
import { bandpass } from './filter.js';
import { estimateBpm, amplitudeAt } from './spectrum.js';
import { hrvFromPulse } from './hrv.js';
import { assessQuality, QUALITY, ROBUST } from './quality.js';
import { toUniform, coverageOf, observedFs, GRID_FS } from './resample.js';
import { respFromSamples } from './resp.js';
import { fuseWindows } from './fuse.js';
import { motionRefs, nlmsCancel } from './motion.js';
import { complexionOf } from './complexion.js';

export const ROIS = ['forehead', 'lcheek', 'rcheek'];
export const PULSE_FILTER = [0.5, 4.0];     // 맥파 대역통과. 하한을 0.7보다 낮춰 서맥 기본파가 깎이지 않게 한다
export const SEARCH_BAND = [0.7, 4.0];      // bpm 탐색 대역 (42–240 bpm)
// 서맥 보정: f/2 가 45–57 bpm 이고 그 세기가 기본파의 ratio 배 이상이면 f/2 를 고른다.
//
// ratio 를 0.2 에서 0.45 로 올렸다. 0.2 는 증거가 너무 약했다 — 참 90–114 bpm 이면 f/2 가 45–57 구간에
// 들어오므로 그 자리의 잡음만으로 보정이 걸려 심박이 절반으로 깎였다. 공개 데이터 MCD-rPPG
// 20명 · 20초 창 597개에서 참 90 bpm 이상 창의 18.8% 가 그렇게 읽혔다. 운동 후 · 긴장은 이 앱이 자주 만나는 상태다.
// 0.45 는 2차 고조파가 기본파만큼 센 진짜 서맥(tests/robust.test.js 의 다섯 시드)을 그대로 구하는 가장 높은 문턱이다.
// 0.5 부터는 그중 하나를 놓친다.
// 0.2 → 0.45: 고심박 절반 읽기 18.8% → 13.0%, 통과분 MAE 3.37 → 2.62 bpm, 통과분 ±5 bpm 91.0% → 92.3%
// (research/scripts/28_rppg_v3_face.py)
export const SPEC_OPTS = { harmonics: 3, subharmonic: { ratio: 0.45, minHz: 0.75, maxHz: 0.95 } };
// 10 dB: scripts/robustness/12_hrv_gate.js 에서 6–10 dB 구간 |RMSSD 오차| 중앙 19–26ms, ≥10 dB 에서 9–18ms
export const HRV_GATE = { snrDbMin: 10, pairsMin: 20 };

// 세 ROI 평균을 합친 RGB
function combinedRgb(samples) {
  return samples.map(s => [
    (s.forehead[0] + s.lcheek[0] + s.rcheek[0]) / 3,
    (s.forehead[1] + s.lcheek[1] + s.rcheek[1]) / 3,
    (s.forehead[2] + s.lcheek[2] + s.rcheek[2]) / 3,
  ]);
}

function relSeries(x) {
  let m = 0; for (const v of x) m += v; m /= x.length || 1;
  return Float32Array.from(x, v => (m ? v / m - 1 : 0));
}

// 고른 주파수 fHz에서 움직임·조명 간섭 지표
function interferenceAt(rows, rgb, fs, fHz) {
  const bp = x => bandpass(Float32Array.from(x), fs, PULSE_FILTER[0], PULSE_FILTER[1]);
  const mx = amplitudeAt(bp(rows.map(s => s.faceCenter[0] / Math.max(s.faceWidth, 1))), fs, fHz);
  const my = amplitudeAt(bp(rows.map(s => s.faceCenter[1] / Math.max(s.faceWidth, 1))), fs, fHz);
  const m = mx.amp >= my.amp ? mx : my;
  const light = amplitudeAt(bp(relSeries(rows.map(s => s.brightness))), fs, fHz);
  const green = amplitudeAt(bp(relSeries(rgb.map(c => c[1]))), fs, fHz);
  return { motionAmp: m.amp, motionFrac: m.frac, lightAmp: light.amp, lightRatio: green.amp > 0 ? light.amp / green.amp : Infinity };
}

// rows: 균일 격자 Sample[]. cancel: 움직임 참조 상쇄 여부 → { fused: {bpm, snrDb, pulse, spectrum}, perRoi, candidates }
function extractFused(rows, fs, band, cancel) {
  const candidates = { all: combinedRgb(rows) };
  for (const r of ROIS) candidates[r] = rows.map(s => s[r]);
  const refs = cancel ? motionRefs(rows, fs, PULSE_FILTER) : null;
  const perRoi = {};
  for (const [name, rgb] of Object.entries(candidates)) {
    let pulse = bandpass(pos(rgb, fs), fs, PULSE_FILTER[0], PULSE_FILTER[1]);
    if (refs) pulse = nlmsCancel(pulse, refs);
    const sp = estimateBpm(pulse, fs, band, 4096, SPEC_OPTS);
    perRoi[name] = { bpm: sp.bpm, snrDb: sp.snrDb, pulse };
  }
  const pulse = fuseWindows(['all', ...ROIS].map(k => perRoi[k].pulse), fs, band, SPEC_OPTS);
  const sp = estimateBpm(pulse, fs, band, 4096, SPEC_OPTS);
  return { fused: { bpm: sp.bpm, snrDb: sp.snrDb, pulse, spectrum: { f: sp.freqs, p: sp.power } }, perRoi, candidates };
}

function judge(samples, rows, fs, band, coverage, cancel) {
  const { fused, perRoi, candidates } = extractFused(rows, fs, band, cancel);
  const roiAgree = ROIS.filter(r => Math.abs(perRoi[r].bpm - fused.bpm) <= ROBUST.roiAgreeBpm).length;
  const interference = rows.length > 8 ? interferenceAt(rows, candidates.all, fs, fused.bpm / 60) : null;
  const quality = assessQuality(samples, fused.snrDb, undefined, { coverage, interference, roiAgree });
  return { fused, perRoi, roiAgree, interference, quality, method: cancel ? 'fused+motion' : 'fused' };
}

export function analyze(samples, opts = {}) {
  const fs = opts.fs || GRID_FS;
  const band = opts.band || SEARCH_BAND;
  const fsObserved = observedFs(samples);
  const coverage = coverageOf(samples);
  const { rows, valid } = toUniform(samples, fs);

  let j = judge(samples, rows, fs, band, coverage, false);
  if (!j.quality.pass && rows.length >= 60 && opts.motionRetry !== false) {
    const k = judge(samples, rows, fs, band, coverage, true);
    if (k.quality.pass) j = k;
  }
  // 전체로는 떨어져도 깨끗한 구간이 있으면 그것을 쓴다. 재귀 한 단계 (안에서는 windowRetry: false).
  if (!j.quality.pass && opts.windowRetry !== false) {
    const w = bestWindow(samples, opts, opts.window || WINDOW);
    if (w) return w;
  }
  const chosen = j.fused, quality = j.quality;
  const hrv = hrvFromPulse(chosen.pulse, fs, chosen.bpm, 250, valid);
  const resp = opts.resp === false ? { rate: NaN, agree: false, head: NaN, light: NaN } : respFromSamples(samples);
  // 안색은 맥박과 따로 간다 — 같은 측정에서 뽑아 기록만 하고 품질 · 점수 어디에도 넣지 않는다 (complexion.js)
  const complexion = complexionOf(samples);
  const hrvReliable = Number.isFinite(chosen.snrDb) && chosen.snrDb >= HRV_GATE.snrDbMin && hrv.pairs >= HRV_GATE.pairsMin && quality.pass;

  return {
    bpm: chosen.bpm,
    snrDb: chosen.snrDb,
    rr: hrv.rr,
    rmssd: hrv.rmssd, sdnn: hrv.sdnn, pnn50: hrv.pnn50, baevskySI: hrv.baevskySI, meanRR: hrv.meanRR,
    hrvReliable, hrvPairs: hrv.pairs,
    quality,
    method: j.method,
    roiBest: 'fused',
    perRoi: Object.fromEntries(Object.entries(j.perRoi).map(([k, v]) => [k, { bpm: v.bpm, snrDb: v.snrDb }])),
    roiAgree: j.roiAgree,
    fsEstimated: fsObserved,
    fsGrid: fs,
    durationSec: samples.length ? (samples[samples.length - 1].t - samples[0].t) / 1000 : 0,
    coverage: { ratio: coverage.ratio, maxGapSec: coverage.maxGapSec },
    interference: j.interference,
    resp: { rate: resp.rate, agree: resp.agree, head: resp.head, light: resp.light },
    complexion,
    window: null,
    debug: { pulse: chosen.pulse, spectrum: chosen.spectrum },
  };
}

// ---------- 구간 선택 ----------
// 30초를 한 덩어리로 판정하면 중간에 2초 흔들린 것 때문에 멀쩡한 28초까지 같이 버려진다.
// 전체가 품질에 떨어졌을 때만, WINDOW.sec 초짜리 구간을 stepSec 간격으로 훑어 품질을 통과하는 것 중 SNR 이 가장 높은 것을 쓴다.
// 고른 구간은 result.window = { startSec, endSec } 로 알린다 (측정 전체가 아니라 그 구간의 값이라는 뜻).
// 합성 280회(obs=hard, scripts/experiments/p3_gate.js): 기준 완화만 91% → 구간 선택까지 95%, 거짓 통과 0%.
//
// 15초라 박동 간격(HRV)은 쌍이 모자라 hrvReliable 이 꺼진다. 그게 맞다 — 심박은 살리고 HRV 는 보여 주지 않는다.
// stepSec 5 · agreeMin 2: 간격을 좁히면 창이 서로 겹쳐 합의가 독립 증거가 못 된다. 5초 간격(30초에 4개)에서
// 맥 없는 신호 통과 0%(합성 100회), 움직임 280회 통과 95%. 2.5초 간격은 같은 통과율에 맥 없음 1% 가 남았다.
export const WINDOW = { sec: 15, stepSec: 5, agreeMin: 2 };

function bestWindow(samples, opts, rule = WINDOW) {
  if (samples.length < 2) return null;
  const t0 = samples[0].t, span = (samples[samples.length - 1].t - t0) / 1000;
  if (span < rule.sec + rule.stepSec) return null;          // 고를 만큼 길지 않다
  // 창 시작점. 마지막 샘플은 30초보다 한 프레임 모자라므로(29.97초) 끝에서 한 번 더 잡아 뒷부분을 놓치지 않는다.
  const starts = [];
  for (let a = 0; a <= span - rule.sec + 1e-6; a += rule.stepSec) starts.push(a);
  const tail = span - rule.sec;
  if (tail > 0 && (!starts.length || tail - starts[starts.length - 1] > 0.5)) starts.push(tail);

  const passed = [];
  for (const a of starts) {
    const lo = t0 + a * 1000, hi = lo + rule.sec * 1000;
    const sub = samples.filter(s => s.t >= lo && s.t <= hi);
    if (sub.length < QUALITY.minSamples) continue;
    const r = analyze(sub, { ...opts, windowRetry: false });
    if (r.quality.pass) passed.push({ r, startSec: a });
  }
  if (!passed.length) return null;
  passed.sort((x, y) => y.r.snrDb - x.r.snrDb);
  const top = passed[0];
  // 구간을 여러 개 훑어 제일 좋은 것을 고르는 것은 그만큼 우연히 걸릴 기회를 주는 일이다.
  // 맥박이 없는 신호에서 한 구간이 통과하는 일이 실제로 있었다(합성 100회, 겹치는 창 7%). 맥박은 시간이 지나도 같은 자리에 있고
  // 잡음은 그렇지 않으므로, 다른 구간이 같은 bpm(±ROBUST.roiAgreeBpm)을 뒷받침할 때만 쓴다 → 0%.
  if (passed.filter(x => Math.abs(x.r.bpm - top.r.bpm) <= ROBUST.roiAgreeBpm).length < rule.agreeMin) return null;
  return { ...top.r, method: top.r.method + '+window', window: { startSec: +top.startSec.toFixed(1), endSec: +(top.startSec + rule.sec).toFixed(1) } };
}

export const QUICK = { minValidSec: 10 };

// 실시간 미리보기용: 최근 windowSec 동안의 bpm만 빠르게. 유효 데이터 10초 전, 또는 창 안 커버리지가 나쁘면 NaN.
export function quickBpm(samples, windowSec = 10) {
  const none = { bpm: NaN, snrDb: -Infinity };
  if (samples.length < 2) return none;
  const all = coverageOf(samples);
  if (all.validSec < QUICK.minValidSec - 0.1) return none;
  const tEnd = samples[samples.length - 1].t;
  const recent = samples.filter(s => s.t >= tEnd - windowSec * 1000);
  const cov = coverageOf(recent);
  if (cov.ratio < ROBUST.coverageRatioMin || cov.maxGapSec > ROBUST.maxGapSecMax) return none;
  const { rows } = toUniform(recent, GRID_FS);
  if (rows.length < 60) return none;
  const pulse = bandpass(pos(combinedRgb(rows), GRID_FS), GRID_FS, PULSE_FILTER[0], PULSE_FILTER[1]);
  const sp = estimateBpm(pulse, GRID_FS, SEARCH_BAND, 1024, SPEC_OPTS);
  return { bpm: sp.bpm, snrDb: sp.snrDb, pulse };
}

// ---------- 빠른 측정: 조기 종료 ----------
// 1초마다 최근 10초를 같은 방법(analyze)으로 잰 값을 쌓고, 최근 3개가 최신값 ±2 bpm 안이며 최신 SNR ≥ 0 dB 이고
// 최소 6초가 지났으면 "멈춰도 되는지" 후보가 된다. 실제로 멈추는 것은 그때까지 전체 샘플의 analyze() 가 품질을 통과할 때뿐이다.
// 거짓 수락을 막은 것은 안정성 조건이 아니라 품질 조건이었다 → 품질 조건을 빼지 않는다.
//
// snrDbMin 3 → 0, minSec 10 → 6 (scripts/experiments/results_p2d_fast.md, 합성 150회).
// 무엇이 시간을 잡아먹는지 하나씩 떼어 봤더니 최소 시간도, 안정 조건도 아니었다 —
// 둘 다 풀어도 중앙값이 1초밖에 안 줄었고, 안정 조건은 통째로 빼도 숫자가 그대로였다.
// 잡아먹던 것은 조기 종료만 따로 요구하던 SNR 문턱이었다. 품질 게이트는 -3 dB 면 통과시키는데 여기서 3 dB 를 받고 있었다.
//   obs=hard 중앙 10 → 7초 · 평균 14.2 → 8.9초 · 30초까지 가는 비율 9% → 2% · ±5 bpm 100%, 품질 통과 98% 그대로
// 0 dB 가 바닥이다. 한 칸 더 풀어 품질의 -3 dB 에 맡기면 맥 없는 입력이 4% 통과한다 (같은 실험, NOPULSE=1).
// 0 dB 는 옛 앱이 쓰던 선이기도 하다 (docs/research/FACE_RPPG.md 3번 표: SNR ≥ 0 통과분 MAE 5.7, ±5 bpm 87%).
export const EARLY_STOP = { minSec: 6, maxSec: 30, K: 3, tolBpm: 2, snrDbMin: 0, windowSec: 10 };

// 최근 windowSec 의 실시간 추정. 조기 종료 판단과 화면의 실시간 숫자에 같이 쓴다.
export function liveEstimate(samples, windowSec = EARLY_STOP.windowSec) {
  if (samples.length < 60) return { bpm: NaN, snrDb: -Infinity, pulse: null };
  const tEnd = samples[samples.length - 1].t;
  const recent = samples.filter(s => s.t >= tEnd - windowSec * 1000);
  const cov = coverageOf(recent);
  // 아직 windowSec 만큼 안 찍혔으면 있는 만큼으로 본다. 창 길이로 재면 10초 전에는 늘 NaN 이라 6초 종료가 불가능하다.
  const span = (tEnd - recent[0].t) / 1000;
  if (recent.length < 60 || cov.validSec < Math.min(windowSec, span) * 0.8 || cov.maxGapSec > ROBUST.maxGapSecMax) return { bpm: NaN, snrDb: -Infinity, pulse: null };
  const r = analyze(recent, { resp: false });
  return { bpm: r.bpm, snrDb: r.snrDb, pulse: r.debug.pulse };
}

// history: [{ t: 초, bpm, snrDb }] (1초마다 하나). 안정성 조건만 본다 — 품질은 호출하는 쪽이 analyze() 로 확인한다.
export function stableEnough(history, tSec, rule = EARLY_STOP) {
  if (tSec < rule.minSec || history.length < rule.K) return false;
  const w = history.slice(-rule.K);
  if (w.some(x => !Number.isFinite(x.bpm))) return false;
  const last = w[w.length - 1];
  return w.every(x => Math.abs(x.bpm - last.bpm) <= rule.tolBpm) && last.snrDb >= rule.snrDbMin;
}

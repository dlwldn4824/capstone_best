// 파이프라인 공개 인터페이스. UI는 이 파일의 analyze()·quickBpm()만 호출한다.
//
// Sample = { t(ms), forehead[r,g,b], lcheek[r,g,b], rcheek[r,g,b], faceWidth, faceCenter[x,y], brightness, blink, mouthOpen }
// Result = { bpm, snrDb, rr, rmssd, sdnn, pnn50, baevskySI, meanRR, hrvReliable, hrvPairs, quality, roiBest, perRoi,
//            fsEstimated, fsGrid, durationSec, coverage, interference, resp, debug }

import { pos } from './pos.js';
import { bandpass } from './filter.js';
import { estimateBpm, amplitudeAt } from './spectrum.js';
import { hrvFromPulse } from './hrv.js';
import { assessQuality, ROBUST } from './quality.js';
import { toUniform, coverageOf, observedFs, GRID_FS } from './resample.js';
import { respFromSamples } from './resp.js';

export const ROIS = ['forehead', 'lcheek', 'rcheek'];
export const PULSE_FILTER = [0.5, 4.0];     // 맥파 대역통과. 하한을 0.7보다 낮춰 서맥 기본파가 깎이지 않게 한다
export const SEARCH_BAND = [0.7, 4.0];      // bpm 탐색 대역 (42–240 bpm)
// 서맥 보정: f/2 가 45–57 bpm 일 때만. 2배 잠김은 실제 bpm ≤ 60 에서만 생겼고(scripts/robustness/05),
// 범위를 열어 두면 약한 신호의 120–150 bpm 이 절반으로 떨어진다(최대 45%). ratio 0.2: 신호 좋은 84–120 bpm 에서 P(f/2)/P(f) ≤ 0.11
export const SPEC_OPTS = { harmonics: 3, subharmonic: { ratio: 0.2, minHz: 0.75, maxHz: 0.95 } };
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

export function analyze(samples, opts = {}) {
  const fs = opts.fs || GRID_FS;
  const band = opts.band || SEARCH_BAND;
  const fsObserved = observedFs(samples);
  const coverage = coverageOf(samples);
  const { rows, valid } = toUniform(samples, fs);

  // ROI별 + 합성 신호 각각 계산
  const perRoi = {};
  const candidates = { all: combinedRgb(rows) };
  for (const r of ROIS) candidates[r] = rows.map(s => s[r]);

  let best = null;
  for (const [name, rgb] of Object.entries(candidates)) {
    const raw = pos(rgb, fs);
    const pulse = bandpass(raw, fs, PULSE_FILTER[0], PULSE_FILTER[1]);
    const sp = estimateBpm(pulse, fs, band, 4096, SPEC_OPTS);
    perRoi[name] = { bpm: sp.bpm, snrDb: sp.snrDb, pulse, spectrum: { f: sp.freqs, p: sp.power } };
    if (!best || sp.snrDb > perRoi[best].snrDb) best = name;
  }

  const chosen = perRoi[best];
  const hrv = hrvFromPulse(chosen.pulse, fs, chosen.bpm, 250, valid);
  const roiAgree = ROIS.filter(r => Math.abs(perRoi[r].bpm - chosen.bpm) <= ROBUST.roiAgreeBpm).length;
  const interference = rows.length > 8 ? interferenceAt(rows, candidates[best], fs, chosen.bpm / 60) : null;
  const quality = assessQuality(samples, chosen.snrDb, undefined, { coverage, interference, roiAgree });
  const resp = respFromSamples(samples);
  const hrvReliable = Number.isFinite(chosen.snrDb) && chosen.snrDb >= HRV_GATE.snrDbMin && hrv.pairs >= HRV_GATE.pairsMin && quality.pass;

  return {
    bpm: chosen.bpm,
    snrDb: chosen.snrDb,
    rr: hrv.rr,
    rmssd: hrv.rmssd, sdnn: hrv.sdnn, pnn50: hrv.pnn50, baevskySI: hrv.baevskySI, meanRR: hrv.meanRR,
    hrvReliable, hrvPairs: hrv.pairs,
    quality,
    roiBest: best,
    perRoi: Object.fromEntries(Object.entries(perRoi).map(([k, v]) => [k, { bpm: v.bpm, snrDb: v.snrDb }])),
    roiAgree,
    fsEstimated: fsObserved,
    fsGrid: fs,
    durationSec: samples.length ? (samples[samples.length - 1].t - samples[0].t) / 1000 : 0,
    coverage: { ratio: coverage.ratio, maxGapSec: coverage.maxGapSec },
    interference,
    resp: { rate: resp.rate, agree: resp.agree, head: resp.head, light: resp.light },
    debug: { pulse: chosen.pulse, spectrum: chosen.spectrum },
  };
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

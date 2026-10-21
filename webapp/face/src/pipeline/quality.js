// 품질 4조건: 얼굴 밝기 55–225 인 프레임 90% 이상 · 머리 이동 < 얼굴 폭 5% 인 프레임 85% 이상 · 깜빡임·말하기 30% 미만 · 맥박 SNR ≥ -3 dB
//
// 이동(3.5%/90% → 5%/85%)과 SNR(0 → -3 dB)은 풀어 둔 것이다. 손으로 든 폰은 이 선을 넘기 쉬운데,
// 넘었다고 bpm 이 틀리지는 않았다 (scripts/experiments/p3_gate.js, 합성 280회 obs=hard):
// 이전 기준에서 전체의 21% 가 bpm 은 참값 ±5 안인데 거부당했고, 실패 이유의 대부분이 이동(14%)이었다.
// 완화 후 통과 78% → 91%, 거짓 통과는 0% 그대로.
export const QUALITY = {
  brightnessMin: 55, brightnessMax: 225, brightnessRatioMin: 0.9,
  motionFrac: 0.05, motionRatioMin: 0.85,   // 이동이 기준 안인 프레임 비율
  blinkRatioMax: 0.3,
  snrMinDb: -3,
  minSamples: 240,                          // 8초 미만이면 판정 불가
};

// 발표 4조건과 별도로 붙는 견고성 조건. 각각 따로 보고해 UI가 이유를 설명할 수 있게 한다.
export const ROBUST = {
  coverageRatioMin: 0.85,   // 얼굴이 잡힌 시간 / 전체 시간
  maxGapSecMax: 1.5,        // 가장 긴 얼굴 놓침 (합성 실측: 1.5–2초까지 bpm 유지, scripts/robustness/01_timing.js)
  motionAmpMax: 0.005,      // 고른 bpm 주파수에서 얼굴 중심 진동 진폭 (얼굴 폭 대비) 이상이고
  motionFracMin: 0.2,       //   그 성분이 움직임 신호 분산의 20% 이상이면 → 간섭
  lightRatioMax: 0.95,      // 고른 주파수에서 (밝기 상대진폭 / 녹색 상대진폭). 맥박은 녹색이 강해 ≈0.7, 조명·화면광·그림자는 ≥1
  lightAmpMin: 0.0003,      //   밝기 상대진폭이 이보다 작으면 판단하지 않음
  roiAgreeBpm: 3, roiAgreeMin: 2,  // 단일 ROI 3개 중 2개 이상이 ±3 bpm 안
};

// samples: Sample[] (t, faceWidth, faceCenter, brightness, blink, mouthOpen) — 원래(재표본화 전) 샘플
// extra: { coverage: {ratio, maxGapSec}, interference: {motionAmp, motionFrac, lightRatio, lightAmp}, roiAgree: 맞는 ROI 수 }
//   없는 항목은 통과로 본다.
export function assessQuality(samples, snrDb, q = QUALITY, extra = {}, rq = ROBUST) {
  const n = samples.length;
  if (n < q.minSamples) {
    // 30초를 다 찍었는데 샘플이 적다면 얼굴을 놓친 것이다 → 이유를 coverage 로. short: 개별 비율은 계산하지 않았다는 표시
    const cov = extra.coverage, covBad = cov && (cov.ratio < rq.coverageRatioMin || cov.maxGapSec > rq.maxGapSecMax);
    return { pass: false, reason: covBad ? 'coverage' : 'short', short: true, brightnessOk: false, brightnessRatio: 0, motionOk: false, motionRatio: 0, blinkOk: false, blinkRatio: 1, snrOk: false, brightnessRange: 0,
      coverageOk: false, interferenceOk: false, motionInterference: false, lightInterference: false, roiAgreeOk: false };
  }
  let bright = 0, still = 0, blink = 0, bmin = 1e9, bmax = -1e9;
  let prev = null;
  for (const s of samples) {
    if (s.brightness >= q.brightnessMin && s.brightness <= q.brightnessMax) bright++;
    bmin = Math.min(bmin, s.brightness); bmax = Math.max(bmax, s.brightness);
    if (prev) {
      const dx = s.faceCenter[0] - prev.faceCenter[0], dy = s.faceCenter[1] - prev.faceCenter[1];
      if (Math.hypot(dx, dy) < q.motionFrac * s.faceWidth) still++;
    } else still++;
    if (s.blink > 0.5 || s.mouthOpen > 0.5) blink++;
    prev = s;
  }
  const brightnessRatio = bright / n, motionRatio = still / n, blinkRatio = blink / n;
  const brightnessOk = brightnessRatio >= q.brightnessRatioMin;
  const motionOk = motionRatio >= q.motionRatioMin;
  const blinkOk = blinkRatio < q.blinkRatioMax;
  const snrOk = Number.isFinite(snrDb) && snrDb >= q.snrMinDb;
  const cov = extra.coverage;
  const coverageOk = !cov || (cov.ratio >= rq.coverageRatioMin && cov.maxGapSec <= rq.maxGapSecMax);
  const itf = extra.interference;
  const motionInterference = !!itf && itf.motionAmp >= rq.motionAmpMax && itf.motionFrac >= rq.motionFracMin;
  const lightInterference = !!itf && itf.lightAmp >= rq.lightAmpMin && itf.lightRatio >= rq.lightRatioMax;
  const interferenceOk = !motionInterference && !lightInterference;
  const roiAgreeOk = extra.roiAgree == null || extra.roiAgree >= rq.roiAgreeMin;
  const pass = brightnessOk && motionOk && blinkOk && snrOk && coverageOk && interferenceOk && roiAgreeOk;
  const reason = !brightnessOk ? 'brightness' : !motionOk ? 'motion' : !blinkOk ? 'blink' : !coverageOk ? 'coverage'
    : !interferenceOk ? 'interference' : !snrOk ? 'snr' : !roiAgreeOk ? 'roi' : null;
  return { pass, reason, brightnessOk, brightnessRatio, motionOk, motionRatio, blinkOk, blinkRatio, snrOk, brightnessRange: bmax - bmin,
    coverageOk, interferenceOk, motionInterference, lightInterference, roiAgreeOk };
}

export const REASON_TEXT = {
  short: '측정 시간이 짧아요. 다시 해 주세요.',
  brightness: '얼굴이 너무 어둡거나 밝아요. 조금 더 밝은 곳에서 다시 볼까요?',
  motion: '머리가 많이 움직였어요. 가만히 있어 주세요.',
  blink: '눈 깜빡임이나 말하기가 많았어요. 편하게 앞을 봐 주세요.',
  snr: '맥박 신호가 약해요. 밝은 곳에서 가만히 다시 해 주세요.',
  coverage: '얼굴이 화면에서 자주 벗어났어요. 화면 안에 얼굴을 계속 두고 다시 해 주세요.',
  interference: '맥박과 같은 박자로 깜빡이는 빛이나 머리 움직임이 잡혔어요. 화면 밝기를 고정하고 가만히 다시 해 주세요.',
  roi: '이마와 양 볼에서 잡힌 맥박이 서로 달라요. 정면을 보고 다시 해 주세요.',
};

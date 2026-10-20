// 얼굴 움직임 지표 — MediaPipe blendshape(eyeBlink, jawOpen)와 코끝 위치로 계산한다. 맥박과 별개.
// 이 값들은 상태를 "판정"하지 않는다. 얼굴이 잡혀 있던 동안 무엇이 관측됐는지만 센다.
// 얼굴을 놓친 구간(GAP_SEC 보다 긴 프레임 간격)은 시간에도, 깜빡임 · 하품 상태에도 넣지 않는다.
import { GAP_SEC } from './resample.js';

export const FACE = {
  blinkOn: 0.5, blinkOff: 0.35,   // 깜빡임: 히스테리시스로 한 번만 센다
  closedLevel: 0.8,               // 눈 감김 비율(PERCLOS 계열): eyeBlink ≥ 0.8 인 시간 비율
  yawnLevel: 0.6, yawnMinSec: 1.5,// 하품 후보: jawOpen ≥ 0.6 이 1.5초 이상
};

// samples: Sample[] (t, blink, mouthOpen, faceCenter, faceWidth, brightness)
export function faceState(samples, q = FACE) {
  const n = samples.length;
  if (n < 2) return null;
  let blinks = 0, closed = false, closedT = 0, yawns = 0, yawnStart = null, yawnLast = null, validT = 0;
  const endYawn = () => { if (yawnStart != null && (yawnLast - yawnStart) / 1000 >= q.yawnMinSec) yawns++; yawnStart = null; };
  for (let i = 0; i < n; i++) {
    const s = samples[i], dt = i ? (s.t - samples[i - 1].t) / 1000 : 0;
    const gap = dt > GAP_SEC;
    if (gap) { closed = false; endYawn(); }                 // 놓친 동안 무슨 일이 있었는지는 모른다
    const step = gap ? 0 : dt;
    validT += step;
    if (!closed && s.blink >= q.blinkOn) { closed = true; blinks++; }
    else if (closed && s.blink < q.blinkOff) closed = false;
    if (s.blink >= q.closedLevel) closedT += step;
    if (s.mouthOpen >= q.yawnLevel) { yawnStart ??= s.t; yawnLast = s.t; }
    else endYawn();
  }
  endYawn();
  const dur = validT;                                        // 얼굴이 실제로 잡혀 있던 시간

  // 머리 움직임: 코끝 위치를 얼굴 폭으로 나눠 거리와 무관하게. 중앙값 기준 흔들림(중앙값 절대편차)
  const xs = samples.map(s => s.faceCenter[0] / s.faceWidth), ys = samples.map(s => s.faceCenter[1] / s.faceWidth);
  const med = a => { const b = [...a].sort((p, r) => p - r); return b[b.length >> 1]; };
  const cx = med(xs), cy = med(ys);
  const headMove = med(xs.map((x, i) => Math.hypot(x - cx, ys[i] - cy)));
  const br = samples.map(s => s.brightness);

  return {
    durationSec: dur,
    blinkPerMin: dur > 0 ? blinks / dur * 60 : NaN,
    blinks,
    eyeClosedRatio: dur > 0 ? closedT / dur : NaN,
    yawns,
    headMovePct: headMove * 100,            // 얼굴 폭 대비 %
    brightness: br.reduce((a, b) => a + b, 0) / n,
    fps: (n - 1) / Math.max((samples[n - 1].t - samples[0].t) / 1000, 1e-3),   // 관측 프레임 속도 (얼굴 놓친 시간 포함)
  };
}

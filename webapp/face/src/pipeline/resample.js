// 시간축 정리. 카메라 샘플은 얼굴이 잡힌 프레임에만 쌓이고(얼굴 놓침 = 구멍), 저전력 모드에서 프레임이 빠진다.
// 샘플을 균일 간격으로 취급하면 bpm이 빠진 비율만큼 낮게 나오므로, 타임스탬프 기준으로 30Hz 격자에 선형 보간한다.

export const GRID_FS = 30;        // 분석 격자 (Hz)
export const GAP_SEC = 0.25;      // 이보다 긴 프레임 간격은 '구멍'(얼굴 놓침)으로 본다

// 같은 시각(중복 프레임)은 첫 것만 남기고 시간순으로 정렬
function clean(samples) {
  const s = [...samples].sort((a, b) => a.t - b.t);
  const out = [];
  for (const x of s) if (!out.length || x.t > out[out.length - 1].t) out.push(x);
  return out;
}

// 관측 프레임 속도 (보고용): (샘플 수 - 1) / 시간
export function observedFs(samples) {
  if (samples.length < 2) return GRID_FS;
  const dur = (samples[samples.length - 1].t - samples[0].t) / 1000;
  return (samples.length - 1) / Math.max(dur, 1e-3);
}

// { ratio: 유효 시간 / 전체 시간, maxGapSec, validSec, spanSec }
export function coverageOf(samples, gapSec = GAP_SEC) {
  const s = clean(samples);
  if (s.length < 2) return { ratio: 0, maxGapSec: 0, validSec: 0, spanSec: 0 };
  const span = (s[s.length - 1].t - s[0].t) / 1000;
  let gapSum = 0, maxGap = 0;
  for (let i = 1; i < s.length; i++) {
    const dt = (s[i].t - s[i - 1].t) / 1000;
    maxGap = Math.max(maxGap, dt);
    if (dt > gapSec) gapSum += dt;
  }
  return { ratio: span > 0 ? (span - gapSum) / span : 0, maxGapSec: maxGap, validSec: span - gapSum, spanSec: span };
}

const NUM_KEYS = ['faceWidth', 'brightness', 'blink', 'mouthOpen'];
const VEC_KEYS = ['forehead', 'lcheek', 'rcheek', 'faceCenter'];

// 균일 격자 Sample[] (t는 ms) 와 valid 마스크(구멍 안이면 0)
export function toUniform(samples, fs = GRID_FS, gapSec = GAP_SEC) {
  const s = clean(samples);
  if (s.length < 2) return { rows: s.slice(), valid: new Uint8Array(s.length).fill(1) };
  const t0 = s[0].t, t1 = s[s.length - 1].t;
  const n = Math.floor((t1 - t0) / 1000 * fs) + 1;
  const rows = new Array(n), valid = new Uint8Array(n);
  let j = 0;
  for (let i = 0; i < n; i++) {
    const t = t0 + i * 1000 / fs;
    while (j < s.length - 2 && s[j + 1].t < t) j++;
    const a = s[j], b = s[j + 1];
    const f = Math.min(1, Math.max(0, (t - a.t) / (b.t - a.t)));
    const row = { t };
    for (const k of NUM_KEYS) if (a[k] != null) row[k] = a[k] + (b[k] - a[k]) * f;
    for (const k of VEC_KEYS) if (a[k]) row[k] = a[k].map((v, c) => v + (b[k][c] - v) * f);
    rows[i] = row;
    valid[i] = (b.t - a.t) / 1000 > gapSec ? 0 : 1;
  }
  return { rows, valid };
}

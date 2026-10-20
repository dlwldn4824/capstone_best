// 맥파 → 피크 → RR 간격 → HRV 지표.
import { bandpass } from "./filter.js";
// 30fps 신호는 RR 정밀도가 33ms라 부족하므로 큐빅(Catmull-Rom) 보간으로 250Hz로 올린 뒤 피크를 찾는다.

export function resampleCubic(x, fsIn, fsOut) {
  const n = x.length, dur = (n - 1) / fsIn;
  const m = Math.floor(dur * fsOut) + 1;
  const y = new Float32Array(m);
  for (let j = 0; j < m; j++) {
    const t = j / fsOut * fsIn;
    const i = Math.floor(t), f = t - i;
    const p0 = x[Math.max(0, i - 1)], p1 = x[Math.min(n - 1, i)], p2 = x[Math.min(n - 1, i + 1)], p3 = x[Math.min(n - 1, i + 2)];
    y[j] = 0.5 * ((2 * p1) + (-p0 + p2) * f + (2 * p0 - 5 * p1 + 4 * p2 - p3) * f * f + (-p0 + 3 * p1 - 3 * p2 + p3) * f * f * f);
  }
  return y;
}

// 피크 검출: 최소 간격 minDist(샘플), 프로미넌스 ≥ promFrac × 신호 표준편차
export function findPeaks(x, minDist, promFrac = 0.5) {
  let m = 0; for (const v of x) m += v; m /= x.length;
  let s = 0; for (const v of x) s += (v - m) * (v - m); s = Math.sqrt(s / x.length);
  const thr = promFrac * s;
  // 1) 프로미넌스를 넘는 국소 최대 전부 수집 (진폭 변조가 있어도 약한 박동을 놓치지 않도록)
  const cand = [];
  for (let i = 1; i < x.length - 1; i++) {
    if (x[i] <= x[i - 1] || x[i] < x[i + 1]) continue;
    let lmin = x[i], rmin = x[i];
    for (let k = Math.max(0, i - minDist); k < i; k++) lmin = Math.min(lmin, x[k]);
    for (let k = i + 1; k <= Math.min(x.length - 1, i + minDist); k++) rmin = Math.min(rmin, x[k]);
    const prom = x[i] - Math.max(lmin, rmin);
    if (prom < thr) continue;
    cand.push({ i, prom });
  }
  // 2) 프로미넌스 큰 순서로 받아들이되 minDist 안에 이미 받은 피크가 있으면 버림
  cand.sort((a, b) => b.prom - a.prom);
  const accepted = [];
  for (const c of cand) {
    if (accepted.some(p => Math.abs(p - c.i) < minDist)) continue;
    accepted.push(c.i);
  }
  return accepted.sort((a, b) => a - b);
}

// pulse: 대역통과된 맥파 (균일 격자), fs: Hz, bpmHint: FFT로 얻은 bpm(피크 간격 하한 설정에 사용)
// valid: (선택) 격자 샘플별 유효 마스크 — 얼굴 놓침 구간을 걸치는 RR은 버린다
// 반환 { rr: ms[] (정리 후), pairs: 정리 후에도 둘 다 살아 있는 이웃 RR 쌍 수, rmssd, sdnn, pnn50, baevskySI, meanRR }
// RMSSD·pNN50은 '둘 다 살아남은 이웃 쌍'으로만 계산한다 (중간 박동이 빠진 자리를 건너뛴 차이는 쓰지 않음).
export function hrvFromPulse(pulse, fs, bpmHint, fsOut = 250, valid = null) {
  // FFT로 얻은 bpm 주변(0.6~1.5배)만 남겨 2차 고조파와 잡음을 제거한 뒤 피크를 찾는다
  const f0 = (bpmHint && Number.isFinite(bpmHint) ? bpmHint : 75) / 60;
  const narrow = bandpass(pulse, fs, Math.max(0.5, f0 * 0.6), Math.min(fs / 2 - 0.5, f0 * 1.5));
  const y = resampleCubic(narrow, fs, fsOut);
  const minDist = Math.round(fsOut * 60 / Math.min(240, (bpmHint || 90) * 1.6)); // 최소 간격 = 힌트의 1.6배 bpm까지 허용
  const peaks = findPeaks(y, minDist, 0.3);
  // 원시 RR (구멍을 걸치면 null)
  const raw = [];
  for (let i = 1; i < peaks.length; i++) {
    let ok = true;
    if (valid) {
      const a = Math.floor(peaks[i - 1] / fsOut * fs), b = Math.ceil(peaks[i] / fsOut * fs);
      for (let k = Math.max(0, a); k <= Math.min(valid.length - 1, b); k++) if (!valid[k]) { ok = false; break; }
    }
    raw.push(ok ? (peaks[i] - peaks[i - 1]) / fsOut * 1000 : null);
  }
  // 이상값 제거: 중앙값 대비 ±25% 밖
  const vals = raw.filter(v => v != null);
  const med = vals.length >= 3 ? median(vals) : null;
  const keep = raw.map(v => v != null && (med == null || Math.abs(v - med) / med <= 0.25));
  const rr = raw.filter((v, i) => keep[i]);
  const diffs = [];
  for (let i = 1; i < raw.length; i++) if (keep[i] && keep[i - 1]) diffs.push(raw[i] - raw[i - 1]);
  const base = hrvFromRR(rr);
  let rmssd = NaN, pnn50 = NaN;
  if (diffs.length >= 2) {
    rmssd = Math.sqrt(diffs.reduce((a, d) => a + d * d, 0) / diffs.length);
    pnn50 = diffs.filter(d => Math.abs(d) > 50).length / diffs.length * 100;
  }
  return { rr, pairs: diffs.length, ...base, rmssd, pnn50 };
}

export function hrvFromRR(rr) {
  const n = rr.length;
  if (n < 3) return { rmssd: NaN, sdnn: NaN, pnn50: NaN, baevskySI: NaN, meanRR: NaN };
  const meanRR = rr.reduce((a, b) => a + b, 0) / n;
  let sd = 0; for (const v of rr) sd += (v - meanRR) ** 2; const sdnn = Math.sqrt(sd / (n - 1));
  let ss = 0, c50 = 0;
  for (let i = 1; i < n; i++) { const d = rr[i] - rr[i - 1]; ss += d * d; if (Math.abs(d) > 50) c50++; }
  const rmssd = Math.sqrt(ss / (n - 1));
  const pnn50 = c50 / (n - 1) * 100;
  // Baevsky SI = AMo(%) / (2 × Mo(s) × MxDMn(s)), 50ms 구간 히스토그램
  const bin = 50;
  const hist = new Map();
  for (const v of rr) { const k = Math.floor(v / bin); hist.set(k, (hist.get(k) || 0) + 1); }
  let moK = 0, moC = -1; for (const [k, c] of hist) if (c > moC) { moC = c; moK = k; }
  const Mo = (moK * bin + bin / 2) / 1000;
  const AMo = moC / n * 100;
  const MxDMn = (Math.max(...rr) - Math.min(...rr)) / 1000;
  const baevskySI = AMo / (2 * Mo * Math.max(MxDMn, 0.01));
  return { rmssd, sdnn, pnn50, baevskySI, meanRR };
}

export function median(a) { const s = [...a].sort((x, y) => x - y); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; }

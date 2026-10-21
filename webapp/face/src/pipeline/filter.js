// 2차 Butterworth 대역통과를 biquad 2개(저역+고역)로 구성하고 forward-backward(filtfilt)로 적용.
// 위상 지연이 없어 피크 위치가 보존된다.

function biquadLowpass(fc, fs) {
  const w0 = 2 * Math.PI * fc / fs, cs = Math.cos(w0), sn = Math.sin(w0);
  const alpha = sn / (2 * Math.SQRT1_2);
  const b0 = (1 - cs) / 2, b1 = 1 - cs, b2 = (1 - cs) / 2;
  const a0 = 1 + alpha, a1 = -2 * cs, a2 = 1 - alpha;
  return [b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0];
}
function biquadHighpass(fc, fs) {
  const w0 = 2 * Math.PI * fc / fs, cs = Math.cos(w0), sn = Math.sin(w0);
  const alpha = sn / (2 * Math.SQRT1_2);
  const b0 = (1 + cs) / 2, b1 = -(1 + cs), b2 = (1 + cs) / 2;
  const a0 = 1 + alpha, a1 = -2 * cs, a2 = 1 - alpha;
  return [b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0];
}
function applyBiquad(x, [b0, b1, b2, a1, a2]) {
  const y = new Float32Array(x.length);
  let x1 = 0, x2 = 0, y1 = 0, y2 = 0;
  for (let i = 0; i < x.length; i++) {
    const v = b0 * x[i] + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2;
    x2 = x1; x1 = x[i]; y2 = y1; y1 = v; y[i] = v;
  }
  return y;
}
function reverse(a) { const r = new Float32Array(a.length); for (let i = 0; i < a.length; i++) r[i] = a[a.length - 1 - i]; return r; }

export function bandpass(x, fs, lo = 0.7, hi = 4.0) {
  const hp = biquadHighpass(lo, fs), lp = biquadLowpass(hi, fs);
  // 패딩: 경계 효과 완화
  const pad = Math.min(x.length - 1, Math.round(fs * 2));
  const xp = new Float32Array(x.length + 2 * pad);
  for (let i = 0; i < pad; i++) { xp[i] = 2 * x[0] - x[pad - i]; xp[xp.length - 1 - i] = 2 * x[x.length - 1] - x[x.length - 2 - (pad - 1 - i)]; }
  xp.set(x, pad);
  let y = applyBiquad(applyBiquad(xp, hp), lp);
  y = reverse(applyBiquad(applyBiquad(reverse(y), hp), lp));
  return y.slice(pad, pad + x.length);
}

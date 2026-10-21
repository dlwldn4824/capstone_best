// 얼굴 심박 v2 + 안색 — research/src/nesy/rppg.py 의 estimate_v2 · complexion 과 한 줄씩 대응한다.
//
// 처리 순서는 rPPG-Toolbox(Liu et al., NeurIPS 2023)의 POS 평가와 같다. 그 저장소는
// Responsible AI License 라 코드를 옮기지 않고 같은 단계 · 같은 값으로 새로 썼다.
//   1. POS (Wang 2017) 1.6초 창          2. smoothness-priors 추세 제거 λ=100
//   3. 1차 버터워스 0.75–3 Hz 양방향      4. 다시 추세 제거 → 0.6–3.3 Hz 양방향
//   5. 2의 거듭제곱 FFT 최고점 = 심박     6. SNR = 1·2차 고조파 ±6 bpm / 나머지
// 공개 데이터(MCD-rPPG 100명) 20초 창: 평균 오차 3.6 bpm, SNR ≥ 0 이면 0.7 bpm (docs/research/FACE_RPPG.md)
"use strict";

const RPPG2 = (() => {
  const FS = 30, WIN = 1.6, LAMBDA = 100, POS_BAND = [0.75, 3.0], EVAL_BAND = [0.6, 3.3], SNR_DEV = 6 / 60;

  function resample(frames, key, fs = FS) {
    // frames: [{t(ms), [key]: [r,g,b]}] → {r,g,b: Float64Array} at fs
    const t0 = frames[0].t, t1 = frames[frames.length - 1].t;
    const n = Math.floor(((t1 - t0) / 1000) * fs);
    const out = [new Float64Array(n), new Float64Array(n), new Float64Array(n)];
    let j = 0;
    for (let i = 0; i < n; i++) {
      const t = t0 + (i * 1000) / fs;
      while (j < frames.length - 2 && frames[j + 1].t < t) j++;
      const a = frames[j], c = frames[j + 1];
      const u = c.t === a.t ? 0 : (t - a.t) / (c.t - a.t);
      for (let k = 0; k < 3; k++) out[k][i] = a[key][k] + u * (c[key][k] - a[key][k]);
    }
    return out;
  }

  const mean = (x, s, e) => { let m = 0; for (let i = s; i < e; i++) m += x[i]; return m / (e - s); };
  const std = (x) => { const m = mean(x, 0, x.length); let v = 0; for (let i = 0; i < x.length; i++) v += (x[i] - m) ** 2; return Math.sqrt(v / x.length); };

  // 1. POS — 창은 [n-l, n), l = ceil(1.6·fs)
  function pos([R, G, B], fs = FS) {
    const N = R.length, l = Math.ceil(WIN * fs);
    const H = new Float64Array(N);
    const s0 = new Float64Array(l), s1 = new Float64Array(l);
    for (let n = l; n < N; n++) {
      const m = n - l;
      const mr = mean(R, m, n), mg = mean(G, m, n), mb = mean(B, m, n);
      for (let k = 0; k < l; k++) {
        const r = R[m + k] / mr, g = G[m + k] / mg, b = B[m + k] / mb;
        s0[k] = g - b;               // [0, 1, -1]
        s1[k] = -2 * r + g + b;      // [-2, 1, 1]
      }
      const sd1 = std(s1), alpha = sd1 > 0 ? std(s0) / sd1 : 0;
      let hm = 0;
      for (let k = 0; k < l; k++) hm += s0[k] + alpha * s1[k];
      hm /= l;
      for (let k = 0; k < l; k++) H[m + k] += s0[k] + alpha * s1[k] - hm;
    }
    return bandpass(detrend(H), fs, POS_BAND);
  }

  // 2. smoothness-priors 추세 제거: x − (I + λ²DᵀD)⁻¹x. 5대각 대칭 행렬을 띠 Cholesky 로 푼다.
  function detrend(x, lam = LAMBDA) {
    const n = x.length;
    if (n < 3) { const m = mean(x, 0, n); return x.map((v) => v - m); }
    const L2 = lam * lam;
    const d0 = new Float64Array(n), d1 = new Float64Array(n), d2 = new Float64Array(n);
    for (let i = 0; i < n; i++) {
      // DᵀD 의 대각: 1,5,6,…,6,5,1 / 첫 비대각: -2,-4,…,-4,-2 / 둘째 비대각: 1
      const c = i === 0 || i === n - 1 ? 1 : i === 1 || i === n - 2 ? 5 : 6;
      d0[i] = 1 + L2 * c;
      if (i < n - 1) d1[i] = L2 * (i === 0 || i === n - 2 ? -2 : -4);
      if (i < n - 2) d2[i] = L2;
    }
    // 띠 Cholesky: A = L Lᵀ, L 의 대각 l0, 아래 l1, l2
    const l0 = new Float64Array(n), l1 = new Float64Array(n), l2 = new Float64Array(n);
    for (let i = 0; i < n; i++) {
      const a2 = i >= 2 ? d2[i - 2] : 0, a1 = i >= 1 ? d1[i - 1] : 0;
      l2[i] = i >= 2 ? a2 / l0[i - 2] : 0;
      l1[i] = i >= 1 ? (a1 - (i >= 2 ? l2[i] * l1[i - 1] : 0)) / l0[i - 1] : 0;
      l0[i] = Math.sqrt(d0[i] - l1[i] * l1[i] - l2[i] * l2[i]);
    }
    const y = new Float64Array(n);
    for (let i = 0; i < n; i++) y[i] = (x[i] - (i >= 1 ? l1[i] * y[i - 1] : 0) - (i >= 2 ? l2[i] * y[i - 2] : 0)) / l0[i];
    const z = new Float64Array(n);
    for (let i = n - 1; i >= 0; i--) z[i] = (y[i] - (i + 1 < n ? l1[i + 1] * z[i + 1] : 0) - (i + 2 < n ? l2[i + 2] * z[i + 2] : 0)) / l0[i];
    const out = new Float64Array(n);
    for (let i = 0; i < n; i++) out[i] = x[i] - z[i];
    return out;
  }

  // 3. 1차 버터워스 대역 통과 — scipy.signal.butter(1, …, 'bandpass') 와 같은 계수 (scripts 에서 대조함)
  function butter([lo, hi], fs) {
    const wl = 4 * Math.tan((Math.PI * (lo / fs * 2)) / 2), wh = 4 * Math.tan((Math.PI * (hi / fs * 2)) / 2);
    const bw = wh - wl, w0 = wl * wh, a0 = 16 + 4 * bw + w0;
    return { b: [4 * bw / a0, 0, -4 * bw / a0], a: [1, (2 * w0 - 32) / a0, (16 - 4 * bw + w0) / a0] };
  }

  function lfilter(b, a, x, zi) {
    const y = new Float64Array(x.length);
    let z0 = zi[0], z1 = zi[1];
    for (let i = 0; i < x.length; i++) {
      const v = b[0] * x[i] + z0;
      z0 = b[1] * x[i] - a[1] * v + z1;
      z1 = b[2] * x[i] - a[2] * v;
      y[i] = v;
    }
    return y;
  }

  // scipy.signal.filtfilt 기본값: 홀수 확장 padlen = 3·max(len a, len b) = 9, lfilter_zi 초기값
  function filtfilt({ b, a }, x) {
    const pad = 9, n = x.length;
    if (n <= pad) return Float64Array.from(x);
    const ext = new Float64Array(n + 2 * pad);
    for (let i = 0; i < pad; i++) ext[i] = 2 * x[0] - x[pad - i];
    for (let i = 0; i < n; i++) ext[pad + i] = x[i];
    for (let i = 0; i < pad; i++) ext[pad + n + i] = 2 * x[n - 1] - x[n - 2 - i];
    // lfilter_zi: (I − Aᵀ) zi = b[1:] − a[1:]·b0
    const m00 = 1 + a[1], m01 = -1, m10 = a[2], m11 = 1;
    const r0 = b[1] - a[1] * b[0], r1 = b[2] - a[2] * b[0];
    const det = m00 * m11 - m01 * m10;
    const zi = [(r0 * m11 - m01 * r1) / det, (m00 * r1 - m10 * r0) / det];
    let y = lfilter(b, a, ext, [zi[0] * ext[0], zi[1] * ext[0]]);
    y.reverse();
    y = lfilter(b, a, y, [zi[0] * y[0], zi[1] * y[0]]);
    y.reverse();
    return y.slice(pad, pad + n);
  }

  const bandpass = (x, fs, band) => filtfilt(butter(band, fs), x);

  // 5. 주기도 (0 채움 2의 거듭제곱 FFT). 크기 비교만 하므로 |X|² 로 충분하다.
  function power(x) {
    let N = 1; while (N < x.length) N <<= 1;
    const re = new Float64Array(N), im = new Float64Array(N);
    re.set(x);
    for (let i = 1, j = 0; i < N; i++) {          // 비트 뒤집기
      let bit = N >> 1;
      for (; j & bit; bit >>= 1) j ^= bit;
      j ^= bit;
      if (i < j) { [re[i], re[j]] = [re[j], re[i]]; }
    }
    for (let len = 2; len <= N; len <<= 1) {
      const ang = (-2 * Math.PI) / len;
      for (let i = 0; i < N; i += len) {
        for (let k = 0; k < len / 2; k++) {
          const wr = Math.cos(ang * k), wi = Math.sin(ang * k);
          const ur = re[i + k], ui = im[i + k];
          const vr = re[i + k + len / 2] * wr - im[i + k + len / 2] * wi;
          const vi = re[i + k + len / 2] * wi + im[i + k + len / 2] * wr;
          re[i + k] = ur + vr; im[i + k] = ui + vi;
          re[i + k + len / 2] = ur - vr; im[i + k + len / 2] = ui - vi;
        }
      }
    }
    const p = new Float64Array(N / 2 + 1);
    for (let k = 0; k <= N / 2; k++) p[k] = re[k] * re[k] + im[k] * im[k];
    return { p, N };
  }

  function hrSnr(bvp, fs = FS, [lo, hi] = EVAL_BAND) {
    const x = bandpass(detrend(bvp), fs, [lo, hi]);
    const { p, N } = power(x);
    let best = -1, bp = -1;
    for (let k = 0; k < p.length; k++) {
      const f = (k * fs) / N;
      if (f >= lo && f <= hi && p[k] > bp) { bp = p[k]; best = k; }
    }
    const hr = ((best * fs) / N) * 60, f1 = hr / 60, f2 = 2 * f1;
    let sig = 0, rest = 0;
    for (let k = 0; k < p.length; k++) {
      const f = (k * fs) / N;
      if (f < lo || f > hi) continue;
      if (Math.abs(f - f1) <= SNR_DEV || Math.abs(f - f2) <= SNR_DEV) sig += p[k]; else rest += p[k];
    }
    return { bpm: hr, snr: 10 * Math.log10(sig / Math.max(rest, 1e-12)) };
  }

  // frames: [{t: ms, rgb: [r,g,b]}] (얼굴 세 영역을 합친 평균)
  function estimate(frames, fs = FS) {
    if (frames.length < 2 || (frames[frames.length - 1].t - frames[0].t) / 1000 < 8) return null;
    return hrSnr(pos(resample(frames, "rgb", fs), fs), fs);
  }

  // 안색 — 같은 프레임 안에서 볼과 이마를 빼서 조명 세기 · 자동 화이트밸런스를 상쇄한다 (FR-07)
  function toLab(r, g, b) {
    const lin = (c) => { c /= 255; return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
    const R = lin(r), G = lin(g), B = lin(b);
    const X = (0.4124 * R + 0.3576 * G + 0.1805 * B) / 0.95047;
    const Y = 0.2126 * R + 0.7152 * G + 0.0722 * B;
    const Z = (0.0193 * R + 0.1192 * G + 0.9505 * B) / 1.08883;
    const f = (t) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
    return { L: 116 * f(Y) - 16, a: 500 * (f(X) - f(Y)), b: 200 * (f(Y) - f(Z)) };
  }

  const median = (v) => { const s = [...v].sort((a, b) => a - b); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };

  // frames: [{fh: [r,g,b], ck: [r,g,b], skip}] — skip 은 눈 깜빡임 · 말하는 프레임
  function complexion(frames) {
    const use = frames.filter((f) => !f.skip && f.fh && f.ck);
    if (use.length < 30) return null;
    const rel = [], ab = [], sat = [], rg = [];
    const S = (c) => { const mx = Math.max(...c), mn = Math.min(...c); return mx > 0 ? (mx - mn) / mx : 0; };
    for (const f of use) {
      const lf = toLab(...f.fh), lc = toLab(...f.ck);
      rel.push(lc.a - lf.a); ab.push(lc.a);
      sat.push(S(f.ck) - S(f.fh)); rg.push(f.ck[0] / f.ck[1] - f.fh[0] / f.fh[1]);
    }
    return { a_rel: median(rel), a_cheek: median(ab), s_rel: median(sat), rg_rel: median(rg) };
  }

  return { estimate, complexion, toLab, _: { pos, detrend, butter, filtfilt, power, hrSnr, resample } };
})();

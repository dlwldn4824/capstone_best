// 얼굴 영상 → 심박(rPPG) · 안색(CIELAB). 전부 브라우저 안에서 숫자로만 바꾼다. 영상은 저장하지 않는다.
//
// 심박: POS 알고리즘 (Wang et al., IEEE TBME 2017). 피부의 RGB 평균이 맥박마다
// 미세하게 흔들리는 것을 잡는다. 이마·양 볼 세 영역을 쓴다.
// HRV 는 내지 않는다 — 손목 PPG 에서도 무너진 지표다 (README 결과 8).
//
// 안색: 같은 영역의 평균 색을 Lab 으로 바꾼다. 조명에 따라 달라지므로
// 절대값이 아니라 **본인의 지난 측정과의 차이**로만 쓴다. 공개 검증 데이터가 없는
// 실험 채널이다.
"use strict";

const RPPG = (() => {
  // 얼굴 안내 타원 안에서의 영역 (영상 폭·높이 비율)
  const ROIS = [
    { x: 0.42, y: 0.20, w: 0.16, h: 0.08 },   // 이마
    { x: 0.31, y: 0.46, w: 0.11, h: 0.10 },   // 왼 볼
    { x: 0.58, y: 0.46, w: 0.11, h: 0.10 },   // 오른 볼
  ];

  function sampleFrame(ctx, w, h) {
    let r = 0, g = 0, b = 0, n = 0;
    for (const roi of ROIS) {
      const x0 = Math.round(roi.x * w), y0 = Math.round(roi.y * h);
      const rw = Math.max(1, Math.round(roi.w * w)), rh = Math.max(1, Math.round(roi.h * h));
      const px = ctx.getImageData(x0, y0, rw, rh).data;
      for (let i = 0; i < px.length; i += 4) {
        r += px[i]; g += px[i + 1]; b += px[i + 2]; n++;
      }
    }
    return { r: r / n, g: g / n, b: b / n };
  }

  // 시각이 고르지 않은 프레임을 fs Hz 로 다시 뽑는다
  function resample(frames, fs) {
    const t0 = frames[0].t, t1 = frames[frames.length - 1].t;
    const n = Math.floor(((t1 - t0) / 1000) * fs);
    const out = { r: new Float64Array(n), g: new Float64Array(n), b: new Float64Array(n) };
    let j = 0;
    for (let i = 0; i < n; i++) {
      const t = t0 + (i * 1000) / fs;
      while (j < frames.length - 2 && frames[j + 1].t < t) j++;
      const a = frames[j], c = frames[j + 1];
      const u = c.t === a.t ? 0 : (t - a.t) / (c.t - a.t);
      out.r[i] = a.r + u * (c.r - a.r);
      out.g[i] = a.g + u * (c.g - a.g);
      out.b[i] = a.b + u * (c.b - a.b);
    }
    return out;
  }

  const mean = (x, s, e) => { let m = 0; for (let i = s; i < e; i++) m += x[i]; return m / (e - s); };
  const std = (x) => { const m = mean(x, 0, x.length); let v = 0; for (const y of x) v += (y - m) * (y - m); return Math.sqrt(v / x.length); };

  function pos(sig, fs) {
    const N = sig.r.length, l = Math.round(1.6 * fs);
    const H = new Float64Array(N);
    for (let n = 0; n + l <= N; n++) {
      const mr = mean(sig.r, n, n + l), mg = mean(sig.g, n, n + l), mb = mean(sig.b, n, n + l);
      const s1 = new Float64Array(l), s2 = new Float64Array(l);
      for (let k = 0; k < l; k++) {
        const r = sig.r[n + k] / mr, g = sig.g[n + k] / mg, b = sig.b[n + k] / mb;
        s1[k] = g - b;
        s2[k] = g + b - 2 * r;
      }
      const alpha = std(s1) / (std(s2) || 1);
      const h = new Float64Array(l);
      for (let k = 0; k < l; k++) h[k] = s1[k] + alpha * s2[k];
      const hm = mean(h, 0, l);
      for (let k = 0; k < l; k++) H[n + k] += h[k] - hm;
    }
    // 1초 이동평균을 빼서 느린 흔들림(조명·자세)을 지운다
    const w = Math.round(fs), out = new Float64Array(N);
    for (let i = 0; i < N; i++) {
      const s = Math.max(0, i - w), e = Math.min(N, i + w + 1);
      out[i] = H[i] - mean(H, s, e);
    }
    return out;
  }

  // 0.7–3.0 Hz (42–180 bpm) 에서 가장 센 주파수
  function peak(x, fs) {
    const freqs = [], power = [];
    for (let f = 0.7; f <= 3.0001; f += 0.01) {
      let re = 0, im = 0;
      for (let k = 0; k < x.length; k++) {
        const ph = (2 * Math.PI * f * k) / fs;
        re += x[k] * Math.cos(ph);
        im -= x[k] * Math.sin(ph);
      }
      freqs.push(f);
      power.push(re * re + im * im);
    }
    let best = 0;
    for (let i = 1; i < power.length; i++) if (power[i] > power[best]) best = i;
    const f0 = freqs[best];
    let sig = 0, tot = 0;
    for (let i = 0; i < power.length; i++) {
      tot += power[i];
      if (Math.abs(freqs[i] - f0) <= 0.1 || Math.abs(freqs[i] - 2 * f0) <= 0.1) sig += power[i];
    }
    const snr = 10 * Math.log10(sig / Math.max(1e-12, tot - sig));
    return { bpm: f0 * 60, snr };
  }

  function estimate(frames, fs = 30) {
    if (frames.length < fs * 8) return null;                 // 8초 이상 필요
    const sig = resample(frames, fs);
    const h = pos(sig, fs);
    return peak(h, fs);
  }

  // sRGB(0–255) → CIELAB (D65)
  function toLab(r, g, b) {
    const lin = (c) => { c /= 255; return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
    const R = lin(r), G = lin(g), B = lin(b);
    const X = (0.4124 * R + 0.3576 * G + 0.1805 * B) / 0.95047;
    const Y = 0.2126 * R + 0.7152 * G + 0.0722 * B;
    const Z = (0.0193 * R + 0.1192 * G + 0.9505 * B) / 1.08883;
    const f = (t) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
    return { L: 116 * f(Y) - 16, a: 500 * (f(X) - f(Y)), b: 200 * (f(Y) - f(Z)) };
  }

  function color(frames) {
    let r = 0, g = 0, b = 0;
    for (const f of frames) { r += f.r; g += f.g; b += f.b; }
    const n = frames.length;
    return toLab(r / n, g / n, b / n);
  }

  // 조명·움직임 확인 (영역 밝기, 최근 1초 흔들림)
  function quality(frames) {
    if (frames.length < 10) return { light: "wait", still: "wait" };
    const last = frames.slice(-30);
    const lum = last.map((f) => 0.299 * f.r + 0.587 * f.g + 0.114 * f.b);
    const m = lum.reduce((a, b) => a + b, 0) / lum.length;
    const sd = Math.sqrt(lum.reduce((a, b) => a + (b - m) * (b - m), 0) / lum.length);
    return {
      light: m < 55 ? "dark" : m > 225 ? "bright" : "ok",
      still: sd > 4 ? "moving" : "ok",
    };
  }

  return { ROIS, sampleFrame, estimate, color, quality, toLab };
})();

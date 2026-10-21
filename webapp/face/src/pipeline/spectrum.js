// FFT 기반 bpm 추정과 SNR.

export function nextPow2(n) { let p = 1; while (p < n) p <<= 1; return p; }

// 반복(iterative) radix-2 FFT. re, im: Float64Array (길이 2^k)
export function fft(re, im) {
  const n = re.length;
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) { [re[i], re[j]] = [re[j], re[i]]; [im[i], im[j]] = [im[j], im[i]]; }
  }
  for (let len = 2; len <= n; len <<= 1) {
    const ang = -2 * Math.PI / len, wr = Math.cos(ang), wi = Math.sin(ang);
    for (let i = 0; i < n; i += len) {
      let cr = 1, ci = 0;
      for (let k = 0; k < len / 2; k++) {
        const ur = re[i + k], ui = im[i + k];
        const vr = re[i + k + len / 2] * cr - im[i + k + len / 2] * ci;
        const vi = re[i + k + len / 2] * ci + im[i + k + len / 2] * cr;
        re[i + k] = ur + vr; im[i + k] = ui + vi;
        re[i + k + len / 2] = ur - vr; im[i + k + len / 2] = ui - vi;
        const t = cr * wr - ci * wi; ci = cr * wi + ci * wr; cr = t;
      }
    }
  }
}

// x: 맥파, fs: Hz, band: [lo, hi] Hz
// 반환 { bpm, snrDb, freqs(bpm 단위), power(정규화), peakHz }
// opts.harmonics: SNR 신호 구간에 넣을 고조파 수 (1=기본파만, 2=+2차, 3=+3차)
// opts.subharmonic: { ratio, minHz, maxHz } — 최대 피크 f의 절반 f/2 가 [minHz, maxHz] 안이고 그 근처에 P(f/2) ≥ ratio·P(f) 인 국소 최대가 있으면 f/2를 고른다
//   (서맥이나 2차 고조파가 기본파보다 센 파형에서 2배로 잠기는 것을 막는다)
export function estimateBpm(x, fs, band = [0.7, 4.0], nfftMin = 4096, opts = {}) {
  const { harmonics = 2, subharmonic = null } = opts;
  const n = x.length;
  const nfft = Math.max(nfftMin, nextPow2(n) * 4);
  const re = new Float64Array(nfft), im = new Float64Array(nfft);
  let mean = 0; for (let i = 0; i < n; i++) mean += x[i]; mean /= n;
  for (let i = 0; i < n; i++) {
    const w = 0.5 - 0.5 * Math.cos(2 * Math.PI * i / (n - 1)); // Hanning
    re[i] = (x[i] - mean) * w;
  }
  fft(re, im);
  const half = nfft / 2;
  const freqs = [], power = [];
  let peakI = -1, peakP = -1;
  for (let k = 0; k <= half; k++) {
    const f = k * fs / nfft;
    if (f < band[0] || f > band[1]) continue;
    const p = re[k] * re[k] + im[k] * im[k];
    freqs.push(f * 60); power.push(p);
    if (p > peakP) { peakP = p; peakI = freqs.length - 1; }
  }
  if (peakI < 0) return { bpm: NaN, snrDb: -Infinity, freqs: [], power: [], peakHz: NaN };

  if (subharmonic) {
    const fHalf = freqs[peakI] / 120;
    if (fHalf >= subharmonic.minHz && fHalf <= (subharmonic.maxHz ?? Infinity)) {
      let bi = -1, bp = -1;
      for (let i = 1; i < freqs.length - 1; i++) {
        if (Math.abs(freqs[i] / 60 - fHalf) > 0.05) continue;
        if (power[i] >= power[i - 1] && power[i] >= power[i + 1] && power[i] > bp) { bp = power[i]; bi = i; }
      }
      if (bi >= 0 && bp >= subharmonic.ratio * peakP) { peakI = bi; peakP = bp; }
    }
  }
  // 포물선 보간으로 피크 정밀화
  let peakBpm = freqs[peakI];
  if (peakI > 0 && peakI < freqs.length - 1) {
    const y0 = power[peakI - 1], y1 = power[peakI], y2 = power[peakI + 1];
    const d = (y0 - y2) / (2 * (y0 - 2 * y1 + y2) || 1);
    peakBpm = freqs[peakI] + d * (freqs[1] - freqs[0]);
  }
  const peakHz = peakBpm / 60;
  // SNR: 피크 ±0.1Hz (+ 2차 고조파 ±0.1Hz) / 나머지 대역
  let sig = 0, noise = 0;
  for (let i = 0; i < freqs.length; i++) {
    const f = freqs[i] / 60;
    let inSig = false;
    for (let h = 1; h <= harmonics; h++) if (Math.abs(f - h * peakHz) <= 0.1) inSig = true;
    if (inSig) sig += power[i]; else noise += power[i];
  }
  const snrDb = 10 * Math.log10(sig / (noise + 1e-12));
  let pmax = 0; for (const p of power) if (p > pmax) pmax = p; pmax = pmax || 1;
  return { bpm: peakBpm, snrDb, freqs, power: power.map(p => p / pmax), peakHz };
}

// 주파수 f(Hz)에서의 진폭 (Hann 창 투영). 반환 { amp, frac } — frac = 그 성분 전력 / 전체 분산
export function amplitudeAt(x, fs, f) {
  const n = x.length;
  if (n < 4 || !Number.isFinite(f)) return { amp: 0, frac: 0 };
  let mean = 0; for (let i = 0; i < n; i++) mean += x[i]; mean /= n;
  let re = 0, im = 0, ws = 0, v = 0;
  for (let i = 0; i < n; i++) {
    const w = 0.5 - 0.5 * Math.cos(2 * Math.PI * i / (n - 1));
    const d = x[i] - mean, a = 2 * Math.PI * f * i / fs;
    re += w * d * Math.cos(a); im += w * d * Math.sin(a); ws += w; v += d * d;
  }
  const amp = 2 * Math.hypot(re, im) / ws;
  v /= n;
  return { amp, frac: v > 0 ? Math.min(1, amp * amp / 2 / v) : 0 };
}

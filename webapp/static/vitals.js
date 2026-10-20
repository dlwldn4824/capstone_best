// 30초 얼굴 스캔 → 심박 · 호흡 · HRV · 스트레스 지수 · 불규칙 여부 — src/nesy/vitals.py 와 한 줄씩 대응한다.
//
//   맥파       RPPG2 POS (rPPG-Toolbox 처리 순서)
//   박동       내 심박 ±0.4 Hz 로 좁힌 맥파(1차 버터워스 두 번) 극대점 + 3점 포물선 보간 + 최소 간격
//   박동 간격  0.33–1.5초 · 전체 중앙값 ±30% · 이웃 중앙값 ±20% 밖은 버림
//   HRV       RMSSD · SDNN · pNN50        스트레스  Baevsky SI = AMo / (2·Mo·MxDMn) → 0–100 (로그 눈금)
//   호흡      기저선 · 진폭 · 간격 변조의 0.1–0.5 Hz 최고점, 품질 좋은 것끼리 맞으면 평균 (참고값)
// 공개 데이터(MCD-rPPG 100명, 30초 창, 신호 좋음): 심박 0.33 bpm · RMSSD 7.5 ms · SDNN 6.1 ms · 스트레스 r 0.72 (docs/app/CHECK_DESIGN.md)
"use strict";

const VITALS = (() => {
  const FS = 30, IBI_MIN = 0.33, IBI_MAX = 1.5, GLOBAL_DEV = 0.3, LOCAL_DEV = 0.2;
  const RESP_FS = 4, RESP_BAND = [0.1, 0.5], SI_LO = 50, SI_HI = 1000, BEAT_BW = 0.4, BEAT_PASSES = 2;
  const { pos, detrend, butter, filtfilt, power, hrSnr, resample } = RPPG2._;
  const bandpass = (x, fs, band) => filtfilt(butter(band, fs), x);
  const meanOf = (v) => v.reduce((a, b) => a + b, 0) / v.length;
  const median = (v) => { const s = [...v].sort((a, b) => a - b); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
  const stdOf = (v, ddof = 0) => { const m = meanOf(v); return Math.sqrt(v.reduce((a, x) => a + (x - m) ** 2, 0) / (v.length - ddof)); };
  const r1 = (v) => (v == null ? null : Math.round(v * 10) / 10);

  function beatSignal(bvp, fs, hr) {
    const f0 = hr / 60;
    let y = detrend(bvp);
    for (let k = 0; k < BEAT_PASSES; k++) y = bandpass(y, fs, [Math.max(0.5, f0 - BEAT_BW), f0 + BEAT_BW]);
    const m = meanOf(y), s = stdOf(y) || 1;
    return Array.from(y, (v) => (v - m) / s);
  }

  function findBeats(x, fs, hr) {
    const n = x.length, cand = [];
    for (let i = 1; i < n - 1; i++) if (x[i] > x[i - 1] && x[i] >= x[i + 1] && x[i] > 0) cand.push(i);
    const d = (0.5 * 60) / Math.max(hr, 40) * fs;
    cand.sort((a, b) => x[b] - x[a]);
    const keep = [];
    for (const i of cand) if (keep.every((j) => Math.abs(i - j) >= d)) keep.push(i);
    keep.sort((a, b) => a - b);
    const t = [], a = [];
    for (const i of keep) {
      const y0 = x[i - 1], y1 = x[i], y2 = x[i + 1], den = y0 - 2 * y1 + y2;
      let off = den !== 0 ? (0.5 * (y0 - y2)) / den : 0;
      off = Math.max(-0.5, Math.min(0.5, off));
      t.push((i + off) / fs); a.push(y1 - 0.25 * (y0 - y2) * off);
    }
    return { t, a };
  }

  function cleanIbi(ibi, local = true) {
    let ok = ibi.map((v) => v >= IBI_MIN && v <= IBI_MAX);
    if (ok.filter(Boolean).length < 3) return ok;
    const med = median(ibi.filter((_, i) => ok[i]));
    ok = ok.map((o, i) => o && Math.abs(ibi[i] - med) <= GLOBAL_DEV * med);
    if (!local) return ok;
    const out = ok.slice();
    for (let i = 0; i < ibi.length; i++) {
      if (!ok[i]) continue;
      const nb = [];
      for (let j = Math.max(0, i - 2); j < Math.min(ibi.length, i + 3); j++) if (ok[j] && j !== i) nb.push(ibi[j]);
      if (nb.length >= 2) { const m = median(nb); if (Math.abs(ibi[i] - m) > LOCAL_DEV * m) out[i] = false; }
    }
    return out;
  }

  function baevsky(ibiS) {
    if (ibiS.length < 10) return null;
    const ms = ibiS.map((v) => v * 1000), cnt = new Map();
    for (const v of ms) { const k = Math.floor(v / 50); cnt.set(k, (cnt.get(k) || 0) + 1); }
    let kb = null, best = -1;
    for (const k of [...cnt.keys()].sort((a, b) => a - b)) if (cnt.get(k) > best) { best = cnt.get(k); kb = k; }
    const mo = (kb * 50 + 25) / 1000, amo = (best / ms.length) * 100;
    const mxdmn = Math.max((Math.max(...ms) - Math.min(...ms)) / 1000, 0.05);
    return amo / (2 * mo * mxdmn);
  }

  const stressScore = (si) => (si == null ? null : r1(Math.max(0, Math.min(1, (Math.log(si) - Math.log(SI_LO)) / (Math.log(SI_HI) - Math.log(SI_LO)))) * 100));
  const stressZone = (s) => (s == null ? null : s < 30 ? "편안" : s < 60 ? "보통" : s < 80 ? "높음" : "매우 높음");

  function hrv(bt) {
    const ibi = []; for (let i = 1; i < bt.length; i++) ibi.push(bt[i] - bt[i - 1]);
    const ok = cleanIbi(ibi), good = ibi.filter((_, i) => ok[i]);
    const d = []; for (let i = 0; i < ibi.length - 1; i++) if (ok[i] && ok[i + 1]) d.push((ibi[i + 1] - ibi[i]) * 1000);
    const okg = ibi.length ? cleanIbi(ibi, false) : [], dg = [];
    for (let i = 0; i < ibi.length - 1; i++) if (okg[i] && okg[i + 1]) dg.push(ibi[i + 1] - ibi[i]);
    const gOk = ibi.filter((_, i) => okg[i]), gmg = gOk.length ? meanOf(gOk) : null;
    const out = { beats: bt.length, ibi_n: ibi.length, ibi_ok: good.length, ok_ratio: ibi.length ? good.length / ibi.length : 0, ok, ibi,
      okg_ratio: ibi.length ? gOk.length / ibi.length : 0, big_jump: dg.length >= 8 ? dg.filter((v) => Math.abs(v) > 0.2 * gmg).length / dg.length : null };
    if (good.length < 10 || d.length < 8) return { ...out, hr: null, rmssd: null, sdnn: null, pnn50: null, si: null };
    const gm = meanOf(good);
    return { ...out, hr: 60 / gm, rmssd: Math.sqrt(meanOf(d.map((v) => v * v))), sdnn: stdOf(good, 1) * 1000,
      pnn50: (d.filter((v) => Math.abs(v) > 50).length / d.length) * 100, si: baevsky(good) };
  }

  // 불규칙 표본 → 4 Hz → 추세 제거(λ=10) · 0.1–0.5 Hz → 한 창(hanning) 주기도 최고점
  function interp(xs, ts, vs) {
    const out = new Float64Array(xs.length); let j = 0;
    for (let i = 0; i < xs.length; i++) {
      const x = xs[i];
      if (x <= ts[0]) { out[i] = vs[0]; continue; }
      if (x >= ts[ts.length - 1]) { out[i] = vs[vs.length - 1]; continue; }
      while (j < ts.length - 2 && ts[j + 1] < x) j++;
      const u = (x - ts[j]) / (ts[j + 1] - ts[j]); out[i] = vs[j] + u * (vs[j + 1] - vs[j]);
    }
    return out;
  }
  function respPeak(ts, vs, t0, t1) {
    if (ts.length < 6) return [null, 0];
    const n = Math.floor((t1 - t0) * RESP_FS);
    if (n < 32) return [null, 0];
    const xs = Array.from({ length: n }, (_, i) => t0 + i / RESP_FS);
    let v = interp(xs, ts, vs); const m = meanOf(v);
    v = bandpass(detrend(v.map((x) => x - m), 10), RESP_FS, RESP_BAND);
    let nfft = 1; while (nfft < n) nfft <<= 1; nfft *= 4;
    const w = new Float64Array(nfft);
    for (let i = 0; i < n; i++) w[i] = v[i] * (n > 1 ? 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (n - 1)) : 1);
    const { p, N } = power(w);
    let k = -1, bp = -1, tot = 0;
    for (let i = 0; i < p.length; i++) { const f = (i * RESP_FS) / N; if (f >= RESP_BAND[0] && f <= RESP_BAND[1]) { tot += p[i]; if (p[i] > bp) { bp = p[i]; k = i; } } }
    if (k < 0 || tot <= 0) return [null, 0];
    const fk = (k * RESP_FS) / N; let near = 0;
    for (let i = 0; i < p.length; i++) { const f = (i * RESP_FS) / N; if (f >= RESP_BAND[0] && f <= RESP_BAND[1] && Math.abs(f - fk) <= 0.03) near += p[i]; }
    return [fk * 60, near / tot];
  }

  function respiration(G, fs, bt, ba, ok) {
    const T = G.length / fs, gm = meanOf(G);
    const est = { riiv: respPeak(Array.from(G, (_, i) => i / fs), Array.from(G, (v) => v / gm), 0, T) };
    if (bt.length >= 6) {
      est.riav = respPeak(bt, ba, bt[0], bt[bt.length - 1]);
      const mid = [], iv = [];
      for (let i = 1; i < bt.length; i++) if (ok[i - 1]) { mid.push((bt[i] + bt[i - 1]) / 2); iv.push(bt[i] - bt[i - 1]); }
      if (mid.length >= 6) est.rifv = respPeak(mid, iv, mid[0], mid[mid.length - 1]);
    }
    const good = Object.entries(est).filter(([, [r, q]]) => r != null && q >= 0.3).map(([k, [r, q]]) => ({ k, r, q }))
      .sort((a, b) => b.q - a.q || b.r - a.r || (a.k < b.k ? 1 : -1));
    if (!good.length) return { rr: null, conf: "low" };
    const agree = good.filter((g) => Math.abs(g.r - good[0].r) <= 4).map((g) => g.r);
    return { rr: r1(meanOf(agree)), conf: agree.length >= 2 ? "high" : good[0].q >= 0.5 ? "mid" : "low" };
  }

  // frames: [{t: ms, rgb: [r,g,b]}]
  function analyze(frames, fs = FS) {
    if (frames.length < 2 || (frames[frames.length - 1].t - frames[0].t) / 1000 < 8) return null;
    const rgb = resample(frames, "rgb", fs), bvp = pos(rgb, fs), { bpm, snr } = hrSnr(bvp, fs);
    const x = beatSignal(bvp, fs, bpm), { t: bt, a: ba } = findBeats(x, fs, bpm);
    const h = hrv(bt), resp = respiration(rgb[1], fs, bt, ba, h.ok);
    const sig = snr >= 3 ? "high" : snr >= 0 ? "mid" : "low";
    const conf = sig === "low" || h.rmssd == null || h.ok_ratio < 0.7 ? "low" : sig === "high" && h.ok_ratio >= 0.85 ? "high" : "mid";
    const si = conf !== "low" ? h.si : null, sc = stressScore(si);
    return {
      hr: r1(bpm), snr: Math.round(snr * 100) / 100, signal: sig, hr_beats: r1(h.hr),
      rmssd: conf !== "low" ? r1(h.rmssd) : null, sdnn: conf !== "low" ? r1(h.sdnn) : null, pnn50: conf !== "low" ? r1(h.pnn50) : null,
      si: r1(si), stress: sc, stress_zone: stressZone(sc), hrv_conf: conf,
      irregular: sig === "high" && h.okg_ratio >= 0.8 && h.big_jump != null ? h.big_jump > 0.3 : null,
      rr: sig !== "low" ? resp.rr : null, rr_conf: sig !== "low" ? resp.conf : "low",
      beats: h.beats, ibi_ok_ratio: Math.round(h.ok_ratio * 100) / 100,
      _beats: bt, _wave: x,
    };
  }

  return { analyze, stressZone, _: { findBeats, cleanIbi, baevsky, hrv, respPeak, beatSignal } };
})();

// POS (Plane-Orthogonal-to-Skin) rPPG. Wang et al., IEEE TBME 2017.
// 입력: rgb — [[r,g,b], ...] ROI 평균 시계열, fs — 샘플링 주파수(Hz)
// 출력: Float32Array 맥파 신호 (길이 = rgb.length)
export function pos(rgb, fs, winSec = 1.6) {
  const n = rgb.length;
  const l = Math.max(3, Math.round(winSec * fs));
  const h = new Float32Array(n);
  if (n < l) return h;

  for (let t = 0; t + l <= n; t++) {
    // 창 평균
    let mr = 0, mg = 0, mb = 0;
    for (let i = t; i < t + l; i++) { mr += rgb[i][0]; mg += rgb[i][1]; mb += rgb[i][2]; }
    mr /= l; mg /= l; mb /= l;
    if (mr === 0 || mg === 0 || mb === 0) continue;

    // 시간 정규화 후 투영 P = [[0,1,-1],[-2,1,1]]
    const s1 = new Float32Array(l), s2 = new Float32Array(l);
    for (let i = 0; i < l; i++) {
      const r = rgb[t + i][0] / mr - 1, g = rgb[t + i][1] / mg - 1, b = rgb[t + i][2] / mb - 1;
      s1[i] = g - b;
      s2[i] = -2 * r + g + b;
    }
    const alpha = std(s1) / (std(s2) + 1e-9);
    let mean = 0;
    const p = new Float32Array(l);
    for (let i = 0; i < l; i++) { p[i] = s1[i] + alpha * s2[i]; mean += p[i]; }
    mean /= l;
    for (let i = 0; i < l; i++) h[t + i] += p[i] - mean; // overlap-add
  }
  return h;
}

export function std(a) {
  let m = 0; for (const v of a) m += v; m /= a.length;
  let s = 0; for (const v of a) s += (v - m) * (v - m);
  return Math.sqrt(s / a.length);
}

// 안색 — 볼의 붉은 기에서 이마의 붉은 기를 뺀 값.
//
// 왜 빼는가: 절대 붉기(a*)는 조명 세기 · 화이트밸런스 · 기종이 그대로 섞여 들어온다.
// 볼과 이마는 같은 렌즈 · 같은 프레임을 지나므로, 빼면 그 공통 성분이 대부분 상쇄된다.
//   MCD-rPPG 영상 1,126개에서 같은 영상 안 20초 구간끼리의 흔들림(sd 중앙):
//   원 a* 1.186 → 보정 a* 0.446 (2.7배 감소). research/scripts/30_complexion_594.py
//
// 무엇을 말할 수 있고 없는가 — 이 값은 **기록만 하고 판정에 쓰지 않는다.**
//   594명 중 안정 영상 568명에서 헤모글로빈과의 상관은 원 a* 에서 ρ = +0.187 (p < 0.001),
//   피부톤(L*) · 성별 · 나이를 뺀 뒤에도 ρ = +0.117 (p = 0.005) 로 남는다. 방향도 생리와 맞는다.
//   그런데 보정 a* 는 헤모글로빈과 무관하다 (ρ = −0.073, p = 0.081) — 헤모글로빈은 이마와 볼을
//   똑같이 붉히므로 뺄셈에서 같이 지워지기 때문이다. 빈혈 90명을 가리는 AUC 는 네 지표 모두 0.47–0.53,
//   곧 동전 던지기다. 사람 사이의 흩어짐(±3.2)이 5분위 양 끝의 차이(1.75)보다 두 배 크다.
//   → 그래서 "안색이 좋다 / 나쁘다" 를 말하지 않는다. 같은 사람 안에서 날짜별로 쌓아 둘 뿐이다.
//
// 쓰는 곳: analyze() 의 결과에 complexion 으로 실린다. 점수 · 판정 어디에도 들어가지 않는다.

export const COMPLEXION = {
  minFrames: 150,          // 5초 (30 fps). 이보다 짧으면 값을 내지 않는다
  brightnessMin: 55,       // 품질의 밝기 하한과 같다 — 너무 어두우면 색이 무너진다
  brightnessMax: 225,
};

// sRGB(0–255) → CIELAB (D65). research/src/nesy/rppg.py 의 to_lab 과 같은 식이다.
export function toLab(r, g, b) {
  const lin = c => {
    const v = c / 255;
    return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  };
  const R = lin(r), G = lin(g), B = lin(b);
  const X = (0.4124 * R + 0.3576 * G + 0.1805 * B) / 0.95047;
  const Y = 0.2126 * R + 0.7152 * G + 0.0722 * B;
  const Z = (0.0193 * R + 0.1192 * G + 0.9505 * B) / 1.08883;
  const f = v => (v > 0.008856 ? Math.cbrt(v) : 7.787 * v + 16 / 116);
  return [116 * f(Y) - 16, 500 * (f(X) - f(Y)), 200 * (f(Y) - f(Z))];
}

function meanRgb(samples, pick) {
  let r = 0, g = 0, b = 0;
  for (const s of samples) { const c = pick(s); r += c[0]; g += c[1]; b += c[2]; }
  const n = samples.length || 1;
  return [r / n, g / n, b / n];
}

// samples: Sample[] (forehead · lcheek · rcheek · brightness)
// → { delta, cheekA, foreheadA, l, frames, reliable, reason }
//   delta = 볼 a* − 이마 a*  (양수면 볼이 이마보다 붉다)
export function complexionOf(samples, rule = COMPLEXION) {
  const rows = (samples || []).filter(s => s && s.forehead && s.lcheek && s.rcheek);
  const none = { delta: NaN, cheekA: NaN, foreheadA: NaN, l: NaN, frames: rows.length, reliable: false };
  if (rows.length < rule.minFrames) return { ...none, reason: 'short' };

  // 프레임별 색을 먼저 평균 내고 한 번만 Lab 으로 옮긴다
  // (research/scripts/30_complexion_594.py 와 같은 순서 — 숫자가 그대로 이어지게)
  const fh = meanRgb(rows, s => s.forehead);
  const lc = meanRgb(rows, s => s.lcheek);
  const rc = meanRgb(rows, s => s.rcheek);
  const ck = [(lc[0] + rc[0]) / 2, (lc[1] + rc[1]) / 2, (lc[2] + rc[2]) / 2];

  const [, aF] = toLab(fh[0], fh[1], fh[2]);
  const [lCk, aCk] = toLab(ck[0], ck[1], ck[2]);

  let bright = 0;
  for (const s of rows) {
    const v = s.brightness ?? (s.forehead[0] + s.forehead[1] + s.forehead[2]) / 3;
    if (v >= rule.brightnessMin && v <= rule.brightnessMax) bright++;
  }
  const brightOk = bright / rows.length >= 0.9;

  return {
    delta: aCk - aF,
    cheekA: aCk,
    foreheadA: aF,
    l: lCk,
    frames: rows.length,
    reliable: brightOk,
    reason: brightOk ? null : 'brightness',
  };
}

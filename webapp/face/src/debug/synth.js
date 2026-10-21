// 합성 Sample[] 생성기. 카메라 없이 파이프라인을 검증하거나 데모 모드로 쓴다.
// 심박 성분 + 조명 드리프트(0.1Hz) + 호흡(0.25Hz) + 백색 잡음. RR 변동(HRV)도 넣을 수 있다.

function mulberry32(seed) {
  return function () {
    let t = (seed += 0x6D2B79F5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function gauss(rnd) { let u = 0, v = 0; while (u === 0) u = rnd(); while (v === 0) v = rnd(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); }

export function synthSamples({
  bpm = 72, fs = 30, durationSec = 30, seed = 1,
  driftAmp = 0.04, respAmp = 0.015, noise = 0.6,
  rrJitterMs = 0,          // >0 이면 박동마다 RR을 흔들어 HRV를 만든다
  brightness = 140, motion = 0, blinkRate = 0.05,
  pulseAmp = 1, h2 = 0.3,  // 맥파 세기 배수, 2차 고조파 진폭 (기본파 1 대비)
  respHeadPx = 1,          // 호흡에 따른 머리 상하 움직임 (px)
  gaps = [],               // 얼굴 놓침 구간 [[시작초, 길이초], ...] — 그 사이 샘플이 없다
  screenHz = 0, screenAmp = 0,            // 화면광 깜빡임 (채널별 세기 다름)
  nodHz = 0, nodShade = 0, nodPx = 0,     // 주기적 끄덕임: 그림자(채널별로 약간 다름) + 얼굴 중심 이동
} = {}) {
  const rnd = mulberry32(seed);
  const n = Math.round(durationSec * fs);
  const base = [150, 110, 95], gain = [0.0020, 0.0045, 0.0030];

  // 박동 위상: RR 변동을 반영해 누적
  const phase = new Float64Array(n);
  let ph = 0, rrCur = 60 / bpm;
  for (let i = 0; i < n; i++) {
    phase[i] = ph;
    ph += (1 / fs) / rrCur;
    if (ph >= 1) { ph -= 1; rrCur = 60 / bpm + (rrJitterMs ? gauss(rnd) * rrJitterMs / 1000 : 0); }
  }
  const samples = [];
  for (let i = 0; i < n; i++) {
    const t = i / fs;
    if (gaps.some(([g0, gl]) => t >= g0 && t < g0 + gl)) continue;
    // 맥파 모양: 기본파 + 약한 2차 고조파 (실제 PPG와 유사)
    const pulse = pulseAmp * (Math.sin(2 * Math.PI * phase[i]) + h2 * Math.sin(4 * Math.PI * phase[i]));
    const drift = 1 + driftAmp * Math.sin(2 * Math.PI * 0.1 * t + 1);
    const resp = respAmp * Math.sin(2 * Math.PI * 0.25 * t);
    const scr = screenAmp * Math.sin(2 * Math.PI * screenHz * t);
    const nod = Math.sin(2 * Math.PI * nodHz * t);
    const rgb = k => base.map((b, c) => b * drift * (1 + pulse * gain[c] * k + resp + scr * [1, 0.6, 1.4][c] + nodShade * nod * [1, 0.7, 1.3][c]) + gauss(rnd) * noise);
    const fh = rgb(1.0), lc = rgb(1.1), rc = rgb(1.1);
    // 얼굴 밝기: capture/roi.js 처럼 ROI 픽셀 (r+g+b)/3 평균 → 조명·화면광 변화가 그대로 들어간다
    const lum = [fh, lc, rc].reduce((a, v) => a + (v[0] + v[1] + v[2]) / 3, 0) / 3;
    samples.push({
      t: Math.round(t * 1000),
      forehead: fh, lcheek: lc, rcheek: rc,
      faceWidth: 200,
      faceCenter: [320 + motion * gauss(rnd) + nodPx * nod, 240 + motion * gauss(rnd) + nodPx * 0.5 * nod + respHeadPx * Math.sin(2 * Math.PI * 0.25 * t)],
      brightness: lum * brightness / ((base[0] + base[1] + base[2]) / 3),
      blink: rnd() < blinkRate ? 1 : 0,
      mouthOpen: 0,
    });
  }
  return samples;
}

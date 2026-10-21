// 촬영 화면 얼굴 오버레이. 타원 안쪽에만 그린다. 계산에는 쓰지 않는 그림이다.
//
//   자세 맞추기  얼굴이 잡히면 얇은 메시가 코끝에서 바깥으로 0.3초 동안 퍼진다 → "인식했다"
//   측정        메시는 그대로 두고, 메시가 "읽고 있다"는 것을 세 가지로 보여 준다
//                 빛 띠    밝은 띠가 메시를 위아래로 훑으며 지나가는 선만 밝힌다 (2.8초 주기)
//                 박동     심박을 알면 박동마다 이마 · 양 볼 부위의 선이 연한 파랑으로 한 번 밝아졌다 사라진다
//                 측정점   이마 · 양 볼 꼭짓점이 작은 점으로 하나씩 엇갈려 깜빡인다
//   완료        전체가 0.25초에 걸쳐 사라진다
// 모션 줄이기 설정이면 빛 띠 · 박동 · 깜빡임 없이 고정된 메시만 그린다.
import { ROI_INDEX } from '../capture/roi.js';

const BASE_ALIGN = 0.3, BASE_MEASURE = 0.22, SPREAD_MS = 300, DONE_FADE_MS = 250;
const SWEEP_MS = 2800, SWEEP_W = 0.14, SWEEP_BOOST = 0.5;     // 빛 띠: 주기, 폭(얼굴 높이 대비), 밝기 더함
const BEAT_DECAY_MS = 260, BEAT_BOOST = 0.65;                 // 박동: 감쇠 시간, 밝기 더함
const TWINKLE_MS = 1700;                                      // 측정점: 한 점이 다시 반짝이기까지
const LEVELS = 8;                                             // 선 밝기를 이 단계로 묶어 한 번에 그린다 (선 2,556개)
const reduced = () => typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;
const ease = x => 1 - Math.pow(1 - Math.min(1, Math.max(0, x)), 3);
const hash = i => { const s = Math.sin(i * 12.9898) * 43758.5453; return s - Math.floor(s); };

function hull(pts) {
  const p = pts.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lo = [], up = [];
  for (const q of p) { while (lo.length >= 2 && cross(lo[lo.length - 2], lo[lo.length - 1], q) <= 0) lo.pop(); lo.push(q); }
  for (let i = p.length - 1; i >= 0; i--) { const q = p[i]; while (up.length >= 2 && cross(up[up.length - 2], up[up.length - 1], q) <= 0) up.pop(); up.push(q); }
  return lo.slice(0, -1).concat(up.slice(0, -1));
}
function inside(poly, x, y) {
  let s = 0;
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i], b = poly[(i + 1) % poly.length], c = (b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0]);
    if (c !== 0) { if (!s) s = Math.sign(c); else if (Math.sign(c) !== s) return false; }
  }
  return true;
}
function rgb(hex) { const h = hex.replace('#', ''), n = parseInt(h.length === 3 ? h.replace(/./g, '$&$&') : h, 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }

export function createOverlay(canvas, { tess, brand }) {
  const st = { foundAt: 0, measureAt: 0, doneAt: 0 };
  const ctx = canvas.getContext('2d');
  const [br, bg, bb] = rgb(brand);
  const glow = [Math.round((br + 255 * 2) / 3), Math.round((bg + 255 * 2) / 3), Math.round((bb + 255 * 2) / 3)];   // 연한 파랑

  function fit() {
    const dpr = Math.min(2, window.devicePixelRatio || 1), w = Math.round(canvas.clientWidth * dpr), h = Math.round(canvas.clientHeight * dpr);
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    return dpr;
  }

  // phase: 'align' | 'measure' | 'done'. lm: 랜드마크(없으면 null). map: 정규화 → 화면 px. oval: 화면 px. bpm: 실시간 심박(없으면 NaN)
  function draw({ phase, lm, map, oval, now, bpm }) {
    const dpr = fit(), rm = reduced();
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (phase === 'measure' && !st.measureAt) st.measureAt = now;
    if (phase === 'done' && !st.doneAt) st.doneAt = now;
    if (!lm || !tess?.length) { if (phase === 'align') st.foundAt = 0; return; }
    if (!st.foundAt) st.foundAt = now;

    const pts = lm.map(p => { const [x, y] = map(p.x, p.y); return [x * dpr, y * dpr]; });
    ctx.save();
    ctx.beginPath(); ctx.ellipse(oval.cx * dpr, oval.cy * dpr, oval.rx * dpr, oval.ry * dpr, 0, 0, Math.PI * 2); ctx.clip();

    const fade = phase === 'done' ? 1 - ease((now - st.doneAt) / DONE_FADE_MS) : 1;
    const measuring = phase !== 'align' && !rm;
    const base = (phase === 'align' ? BASE_ALIGN : BASE_MEASURE) * fade;

    // 측정 영역 꼭짓점 (이번 프레임 얼굴 기준)
    const inRoi = new Uint8Array(pts.length);
    if (phase !== 'align') {
      for (const idx of Object.values(ROI_INDEX)) {
        const poly = hull(idx.map(i => pts[i]));
        let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
        for (const [x, y] of poly) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
        for (let i = 0; i < pts.length; i++) { const [x, y] = pts[i]; if (x >= x0 && x <= x1 && y >= y0 && y <= y1 && inside(poly, x, y)) inRoi[i] = 1; }
      }
    }

    // 빛 띠 위치 · 박동 세기
    let top = Infinity, bot = -Infinity;
    for (const [, y] of pts) { if (y < top) top = y; if (y > bot) bot = y; }
    const fh = bot - top || 1;
    const sweepY = measuring ? top + fh * (0.5 - 0.5 * Math.cos(2 * Math.PI * ((now - st.measureAt) / SWEEP_MS))) : null;
    const beat = measuring && Number.isFinite(bpm) ? Math.exp(-(((now / 1000) * bpm / 60) % 1) * 60000 / bpm / BEAT_DECAY_MS) : 0;

    // 자세 맞추기: 코끝에서 퍼지는 반경
    const nose = pts[1], spread = phase === 'align' && !rm ? ease((now - st.foundAt) / SPREAD_MS) : 1;
    const maxR = Math.hypot(oval.rx, oval.ry) * dpr * spread;

    // 선마다 밝기 · 색(흰/연한 파랑)을 정해 단계별로 묶는다
    const white = Array.from({ length: LEVELS }, () => []), blue = Array.from({ length: LEVELS }, () => []);
    for (const [a, b] of tess) {
      const pa = pts[a], pb = pts[b], mx = (pa[0] + pb[0]) / 2, my = (pa[1] + pb[1]) / 2;
      if (spread < 1 && Math.hypot(mx - nose[0], my - nose[1]) > maxR) continue;
      let alpha = base, isBeat = false;
      if (sweepY != null) { const d = Math.abs(my - sweepY) / (fh * SWEEP_W); if (d < 1) alpha += SWEEP_BOOST * (1 - d) * (1 - d) * fade; }
      if (beat > 0.02 && inRoi[a] && inRoi[b]) { alpha += BEAT_BOOST * beat * fade; isBeat = beat > 0.25; }
      const k = Math.min(LEVELS - 1, Math.round(Math.min(1, alpha) * (LEVELS - 1)));
      if (k <= 0) continue;
      (isBeat ? blue : white)[k].push(pa, pb);
    }
    ctx.lineWidth = 0.6 * dpr;
    const stroke = (buckets, c) => buckets.forEach((seg, k) => {
      if (!seg.length) return;
      ctx.strokeStyle = `rgba(${c[0]},${c[1]},${c[2]},${(k / (LEVELS - 1)).toFixed(3)})`;
      ctx.beginPath();
      for (let i = 0; i < seg.length; i += 2) { ctx.moveTo(seg[i][0], seg[i][1]); ctx.lineTo(seg[i + 1][0], seg[i + 1][1]); }
      ctx.stroke();
    });
    stroke(white, [255, 255, 255]);
    stroke(blue, glow);

    // 측정점: 영역 안 꼭짓점이 엇갈려 반짝인다
    if (measuring) {
      const r = 1.6 * dpr;
      for (let i = 0; i < pts.length; i++) {
        if (!inRoi[i]) continue;
        const ph = ((now / TWINKLE_MS) + hash(i)) % 1;
        const tw = Math.pow(Math.max(0, Math.sin(Math.PI * ph)), 14) * fade;   // 짧게 반짝이고 오래 쉰다
        if (tw < 0.05) continue;
        ctx.fillStyle = `rgba(255,255,255,${tw.toFixed(3)})`;
        ctx.beginPath(); ctx.arc(pts[i][0], pts[i][1], r, 0, Math.PI * 2); ctx.fill();
      }
    }
    ctx.restore();
  }

  function reset() { Object.assign(st, { foundAt: 0, measureAt: 0, doneAt: 0 }); ctx.clearRect(0, 0, canvas.width, canvas.height); }
  return { draw, reset };
}

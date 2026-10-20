// 스캔 화면 위에 얼굴 메시(MediaPipe 478점 삼각망)를 그린다 — ARKit ARFaceAnchor 메시 화면과 같은 역할.
//
//   흰 선      메시 꼭짓점 번호는 항상 같은 얼굴 위치 → 고개가 움직여도 같은 피부를 읽고 있다는 걸 보여준다
//   강조색 면  실제로 RGB 를 평균하는 영역 (facemesh.js ROI: 이마 · 양 볼). 맥박에 맞춰 밝아진다
//   빛 띠      측정 중에는 메시를 위아래로 훑는다
// 영상은 좌우 반전(거울)으로 보이므로 x 를 뒤집는다. 계산에는 쓰지 않는 그림일 뿐이다.
"use strict";

const MESH = (() => {
  const LABEL = { forehead: "이마 · 심박", cheekL: "볼 · 심박 + 안색", cheekR: "" };

  function fit(canvas) {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const w = Math.round(canvas.clientWidth * dpr), h = Math.round(canvas.clientHeight * dpr);
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    return dpr;
  }

  // 정규화 좌표(원본 영상) → 캔버스 픽셀 (object-fit: cover, 좌우 반전)
  function mapper(canvas, video) {
    const W = canvas.width, H = canvas.height, vw = video.videoWidth || 640, vh = video.videoHeight || 480;
    const sc = Math.max(W / vw, H / vh), dw = vw * sc, dh = vh * sc, ox = (W - dw) / 2, oy = (H - dh) / 2;
    return (x, y) => [W - (ox + x * dw), oy + y * dh];
  }

  // 앱 강조색(--calm) → "r,g,b" — 밝은 화면은 파랑, 다크 모드는 민트
  function accent(el) {
    const v = getComputedStyle(el).getPropertyValue("--calm").trim() || "#1A6DFF";
    const h = v.replace("#", ""), n = parseInt(h.length === 3 ? h.replace(/./g, "$&$&") : h, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255].join(",");
  }

  function clear(canvas) { const c = canvas.getContext("2d"); c.clearRect(0, 0, canvas.width, canvas.height); }

  // o: { lm, tess, polys, scanning, pulse(0–1), t(ms) }
  function draw(canvas, video, o) {
    const dpr = fit(canvas), ctx = canvas.getContext("2d"), W = canvas.width, H = canvas.height;
    ctx.clearRect(0, 0, W, H);
    if (!o.lm || !o.tess || !o.tess.length) return;
    const P = mapper(canvas, video), pts = o.lm.map((p) => P(p.x, p.y)), A = accent(canvas);
    let y0 = Infinity, y1 = -Infinity;
    for (const [, y] of pts) { if (y < y0) y0 = y; if (y > y1) y1 = y; }

    // 1) 메시 — 빛 띠와의 거리로 6단계 밝기를 나눠 한 번에 그린다 (선 2,500개)
    const band = o.scanning ? y0 + (y1 - y0) * (0.5 - 0.5 * Math.cos((o.t / 1200) * Math.PI)) : null;
    const buckets = [[], [], [], [], [], []];
    for (const [a, b] of o.tess) {
      const pa = pts[a], pb = pts[b];
      if (!pa || !pb) continue;
      let k = 0;
      if (band != null) { const d = Math.abs((pa[1] + pb[1]) / 2 - band) / ((y1 - y0) * 0.12); k = d < 1 ? 5 - Math.floor(d * 5) : 0; }
      buckets[k].push(pa, pb);
    }
    ctx.lineWidth = 0.7 * dpr;
    const base = o.scanning ? 0.28 : 0.5;
    buckets.forEach((seg, k) => {
      if (!seg.length) return;
      ctx.strokeStyle = k ? "rgba(" + A + "," + Math.min(1, base + k * 0.14).toFixed(2) + ")" : "rgba(255,255,255," + base + ")";
      ctx.beginPath();
      for (let i = 0; i < seg.length; i += 2) { ctx.moveTo(seg[i][0], seg[i][1]); ctx.lineTo(seg[i + 1][0], seg[i + 1][1]); }
      ctx.stroke();
    });

    // 2) 측정 영역 (실제로 평균하는 볼록 다각형)
    if (!o.polys) return;
    const fillA = o.scanning ? 0.16 + 0.32 * (o.pulse || 0) : 0.14;
    for (const [name, poly] of Object.entries(o.polys)) {
      const q = poly.map(([x, y]) => P(x, y));
      ctx.beginPath(); q.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.closePath();
      ctx.fillStyle = "rgba(" + A + "," + fillA.toFixed(2) + ")"; ctx.fill();
      ctx.lineWidth = 2 * dpr; ctx.strokeStyle = "rgba(255,255,255,.95)"; ctx.stroke();
      const lab = LABEL[name];
      if (!lab || o.scanning) continue;
      const cx = q.reduce((s, p) => s + p[0], 0) / q.length, top = Math.min(...q.map((p) => p[1]));
      ctx.font = "600 " + Math.round(11 * dpr) + "px Pretendard, 'Apple SD Gothic Neo', sans-serif";
      const tw = ctx.measureText(lab).width, ph = 20 * dpr, px = 8 * dpr;
      const lx = Math.max(4 * dpr, Math.min(W - tw - 2 * px - 4 * dpr, cx - tw / 2 - px)), ly = top - ph - 6 * dpr;
      ctx.fillStyle = "rgba(255,255,255,.94)";
      ctx.beginPath(); ctx.roundRect ? ctx.roundRect(lx, ly, tw + 2 * px, ph, 6 * dpr) : ctx.rect(lx, ly, tw + 2 * px, ph); ctx.fill();
      ctx.fillStyle = "rgb(" + A + ")"; ctx.textBaseline = "middle"; ctx.fillText(lab, lx + px, ly + ph / 2);
    }
  }

  return { draw, clear };
})();

// Vity 얼굴 체크 — 30초 얼굴 촬영으로 심박 · 맥파 · 박동 간격 · 호흡 · 눈 깜빡임 · 머리 흔들림을 읽어 보여 준다.
// 흐름: 홈 → 준비 시트 → 촬영(자세 맞추기 → 30초) → 결과 → 상세 시트. 기록 탭.
// 계산은 src/pipeline, 자세 판정은 src/capture/framing.js, 결과 표시 규칙은 src/ui/view.js.
// 카메라 프레임 · 랜드마크는 메모리에서만 쓰고 저장하지 않는다.
import { openCamera, closeCamera } from './capture/camera.js';
import { loadFaceMesh, detect, TESSELATION } from './capture/facemesh.js';
import { RoiSampler } from './capture/roi.js';
import { framingIssue, measureFraming } from './capture/framing.js';
import { analyze, quickBpm } from './pipeline/index.js';
import { faceState } from './pipeline/face.js';
import { synthSamples } from './debug/synth.js';
import { ic } from './ui/icons.js';
import { EVIDENCE } from './ui/evidence.js';
import { resultView } from './ui/view.js';
import { createOverlay } from './ui/overlay.js';
import { putScan, listScans, clearScans, persistStorage } from './store/db.js';

const SECS = 30, HOLD_MS = 1000, SHAKE_MS = 500;
const DEMO = new URLSearchParams(location.search).has('demo');   // 개발 확인용 합성 신호
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const ok = v => v != null && Number.isFinite(v);
const fmt = (v, d = 0) => (ok(v) ? v.toFixed(d) : '–');
const withUnit = (v, unit, d = 0) => (ok(v) ? `${v.toFixed(d)} ${unit}` : '–');
const DAY = d => `${d.getMonth() + 1}월 ${d.getDate()}일 ${'일월화수목금토'[d.getDay()]}요일`;
const HM = d => `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
const BRAND = () => getComputedStyle(document.documentElement).getPropertyValue('--brand').trim() || '#1A6DFF';
const ago = ts => { const m = Math.round((Date.now() - ts) / 60000); return m < 1 ? '방금' : m < 60 ? `${m}분 전` : m < 1440 ? `${Math.floor(m / 60)}시간 전` : DAY(new Date(ts)); };
const buzz = ms => { if (navigator.vibrate) navigator.vibrate(ms); };

function toast(m) { const t = $('toast'); t.textContent = m; t.classList.add('on'); clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove('on'), 2400); }

document.querySelectorAll('[data-ic]').forEach(el => { el.innerHTML = ic(el.dataset.ic, el.closest('.tabs') ? 24 : 22) + (el.dataset.ic === 'x' ? '' : el.innerHTML); });
document.querySelectorAll('.tabs button').forEach(b => b.addEventListener('click', () => go(b.dataset.tab)));
function go(tab) {
  document.querySelectorAll('.tabs button').forEach(x => x.setAttribute('aria-selected', x.dataset.tab === tab));
  document.querySelectorAll('.view').forEach(v => v.classList.toggle('on', v.id === 'v-' + tab));
  (tab === 'log' ? renderLog : renderHome)();
  window.scrollTo(0, 0);
}

// ---------- 홈 ----------
async function renderHome() {
  const last = (await listScans())[0];
  const lv = last ? resultView(last) : null;
  $('v-home').innerHTML = `
    <div class="hero">
      <p class="eyebrow">${DAY(new Date())}</p>
      <h1>얼굴 30초로<br><em>지금 몸 상태</em>를<br>읽어 볼게요</h1>
      <img src="/characters/coffee.png" alt="" width="136" height="136">
      <div class="reads">${['심박', '맥파', '박동 간격', '호흡', '눈 깜빡임', '머리 흔들림'].map(t => `<span class="chip">${t}</span>`).join('')}</div>
    </div>
    <div class="start">
      <button class="btn" type="button" data-act="prep">${ic('scan-face', 22)}시작하기</button>
      <p>카메라 영상은 이 휴대폰 안에서만 처리돼요</p>
    </div>
    ${last ? `<p class="sec">최근 결과</p>
    <button class="last" type="button" data-show="${last.id}">
      <span class="k">${ago(last.ts)}</span>
      <span class="v num">${lv.hr?.value ?? '–'}${lv.hr?.unit ? `<small>${lv.hr.unit}</small>` : ''}</span>
      ${ic('chevron-right', 22)}
      <span class="row">${lv.status === 'ok' ? lv.tiles.filter(t => t.state !== 'held').slice(0, 2).map(t => `<span class="chip">${t.label} ${t.value}${t.unit}</span>`).join('') : '<span class="chip warn">다시 재기 필요</span>'}</span>
    </button>` : ''}`;
}

// ---------- 준비 시트 ----------
function openPrep() {
  const row = (i, t, d) => `<li><i>${ic(i, 22)}</i><div><b>${t}</b><span>${d}</span></div></li>`;
  openSheet(`<h2>촬영 전에 확인해 주세요</h2>
    <ul class="prep-list prep">
      ${row('smartphone', '휴대폰을 세워 두세요', '책이나 컵에 기대 눈높이에 두면 30초 동안 흔들리지 않아요.')}
      ${row('scan-face', '팔 길이만큼 떨어져 앉아요', '얼굴이 원을 꽉 채우는 거리예요. 30–40cm 정도.')}
      ${row('sun', '빛은 얼굴 앞쪽에', '창문이나 조명을 등지면 얼굴이 어두워져요.')}
      ${row('mic-off', '30초 동안 말하지 않아요', '입을 움직이면 맥박 신호가 흔들려요.')}
    </ul>
    <button class="btn" type="button" data-act="scan">카메라 켜기</button>`);
}

// ---------- 촬영 ----------
// phase: 'off' → 'align'(자세 맞추기) → 'measure'(30초) → 'done'
// 화면 상태 클래스: .ready(자세 맞음, 1초 잠금) · .measuring · .warn(측정 중 문제) · .done(완료)
const cam = { stream: null, raf: 0, phase: 'off', t0: 0, readySince: 0, lastT: -1, samples: [], nose: [], mediaUp: 0, lastMedia: null };
const live = { at: 0, bpm: NaN };
const sampler = new RoiSampler(160, 120);
const overlay = createOverlay($('faceCv'), { tess: TESSELATION, brand: BRAND() });
const scanEl = () => $('scan');
const ICON_WARN = ic('triangle-alert', 22);
const SWAP_MS = 350;                          // 새 안내가 이만큼 이어져야 바꾼다 (프레임마다 흔들리는 판정이 글자를 깜빡이게 하지 않도록)
const shown = { key: null, text: '', tip: '', warn: false, pending: null, pendingSince: 0 };
let swapTimer = 0;

// 안내 한 줄(위) · 팁(아래)을 바꾼다. 다른 안내는 SWAP_MS 동안 이어질 때만 바꾸고(force 면 바로),
// 바꿀 때는 기존 문구가 위로 사라진 뒤 글자 · 색 · 아이콘 · 팁이 한꺼번에 바뀌어 아래에서 올라온다.
function say(key, text, { tip = '', warn = false, force = false } = {}) {
  const now = performance.now();
  if (key !== shown.key && !force) {
    if (shown.pending !== key) { shown.pending = key; shown.pendingSince = now; return; }
    if (now - shown.pendingSince < SWAP_MS) return;
  }
  shown.pending = null;
  if (key === shown.key && text === shown.text && tip === shown.tip && warn === shown.warn) return;
  const first = shown.key === null;
  Object.assign(shown, { key, text, tip, warn });
  const msg = $('scanMsg'), foot = $('scanFoot');
  const apply = () => {
    $('hintText').textContent = text; $('hintIc').innerHTML = warn ? ICON_WARN : ''; $('tip').textContent = tip;
    scanEl().classList.toggle('warn', warn);
    msg.classList.remove('out', 'in'); foot.classList.remove('out', 'in');
    void msg.offsetWidth;                                       // 같은 애니메이션을 다시 시작하게
    msg.classList.add('in'); foot.classList.add('in');
  };
  clearTimeout(swapTimer);
  if (first) return apply();
  msg.classList.add('out'); foot.classList.add('out');
  swapTimer = setTimeout(apply, 140);
}
function flash(cls, ms) { const el = scanEl(); el.classList.remove(cls); void el.offsetWidth; el.classList.add(cls); setTimeout(() => el.classList.remove(cls), ms); }
function ring(f) { $('ring').setAttribute('stroke-dasharray', `${Math.max(0, Math.min(100, f * 100)).toFixed(1)} 100`); }
function center(kind) { $('ovalCenter').innerHTML = kind === 'spin' ? '<span class="spinner"></span>' : kind === 'done' ? `<span class="done-ic">${ic('check', 36)}</span>` : ''; }
function setPhaseUI(phase) {
  const el = scanEl();
  el.classList.toggle('measuring', phase === 'measure');
  el.classList.toggle('done', phase === 'done');
  if (phase !== 'align') el.classList.remove('ready');
  $('scanStep').textContent = phase === 'measure' ? '측정 중' : phase === 'done' ? '분석' : '자세 맞추기';
  $('meter').hidden = phase !== 'measure';
}

async function openScan() {
  closePage(); closeSheet();
  Object.assign(cam, { phase: 'align', samples: [], nose: [], readySince: 0, badSince: 0, lastT: -1, mediaUp: 0, lastMedia: null });
  Object.assign(shown, { key: null, text: '', tip: '', warn: false, pending: null });
  clearTimeout(swapTimer);
  scanEl().className = 'scan on'; flash('entering', 520);
  setPhaseUI('align'); ring(0); center('spin'); overlay.reset(); live.bpm = NaN;
  $('live').hidden = true; $('scanRetry').hidden = true;
  say('loading', '카메라를 켜는 중', { force: true });
  if (DEMO) return demoAlign();
  if (!navigator.mediaDevices || !window.isSecureContext) return fail('카메라를 열 수 없어요', 'https 주소에서 다시 열어 주세요');
  try {
    cam.stream = (await openCamera($('video'))).stream;
    scanEl().classList.add('cam-on');                           // 영상이 실제로 재생된 뒤에 떠오르게
    say('loading', '얼굴 인식 준비 중', { force: true });
    await loadFaceMesh();
    center(null);
    schedule();
  } catch (err) {
    if (err.name === 'NotAllowedError') fail('카메라 권한이 필요해요', '설정 › Safari › 카메라에서 허용으로 바꾼 뒤 다시 시도해 주세요');
    else if (err.name === 'NotFoundError') fail('카메라를 찾지 못했어요', '');
    else fail('카메라를 열 수 없어요', '다른 앱이 카메라를 쓰고 있다면 닫고 다시 시도해 주세요');
  }
}
function fail(text, tip) { center(null); say('fail', text, { tip, warn: true, force: true }); $('scanRetry').hidden = false; }
$('scanRetry').onclick = () => { stopCam(); openScan(); };

// 정규화 랜드마크 → 화면 px (video 는 object-fit: cover, 좌우 반전)
function screenMapper(video) {
  const b = video.getBoundingClientRect(), vw = video.videoWidth || 640, vh = video.videoHeight || 480;
  const sc = Math.max(b.width / vw, b.height / vh), dw = vw * sc, dh = vh * sc, ox = (b.width - dw) / 2, oy = (b.height - dh) / 2;
  return (x, y) => [b.left + b.width - (ox + x * dw), b.top + oy + y * dh];
}
function ovalRect() { const b = $('oval').getBoundingClientRect(); return { cx: b.left + b.width / 2, cy: b.top + b.height / 2, rx: b.width / 2, ry: b.height / 2 }; }

// 최근 0.5초 코끝 흔들림 / 얼굴 폭 (가로 · 세로 모두 영상 px)
function shakeOf(now, lm, vw, vh) {
  const fw = Math.hypot((lm[454].x - lm[234].x) * vw, (lm[454].y - lm[234].y) * vh) || 1;
  cam.nose.push({ t: now, x: lm[1].x * vw / fw, y: lm[1].y * vh / fw });
  while (cam.nose.length && now - cam.nose[0].t > SHAKE_MS) cam.nose.shift();
  const mx = cam.nose.reduce((a, p) => a + p.x, 0) / cam.nose.length, my = cam.nose.reduce((a, p) => a + p.y, 0) / cam.nose.length;
  return Math.max(...cam.nose.map(p => Math.hypot(p.x - mx, p.y - my)));
}

// 새 비디오 프레임마다 한 번. requestVideoFrameCallback 이 있으면 프레임의 실제 시각(mediaTime)으로 샘플 시각을 잡는다
// (rAF 시각은 화면 갱신 시각이라 0–16ms 흔들리고, 그 흔들림이 박동 간격에 섞인다).
const RVFC = typeof HTMLVideoElement !== 'undefined' && 'requestVideoFrameCallback' in HTMLVideoElement.prototype;
function schedule() {
  const v = $('video');
  if (RVFC) cam.raf = v.requestVideoFrameCallback((now, meta) => loop(now, meta.mediaTime * 1000));
  else cam.raf = requestAnimationFrame(now => loop(now, null));
}
function loop(now, frameMs) {
  if (cam.phase !== 'align' && cam.phase !== 'measure') return;
  const v = $('video');
  if (v.readyState >= 2 && (RVFC || v.currentTime !== cam.lastT)) {   // rAF 경로에서는 새 프레임일 때만
    cam.lastT = v.currentTime;
    const vw = v.videoWidth || 640, vh = v.videoHeight || 480;
    const det = detect(v, performance.now());                  // MediaPipe 는 단조 증가 시각만 받는다
    let fr = framingIssue({ found: false }), roi = null;
    if (det) {
      roi = sampler.sample(v, det.landmarks, vw, vh);
      const pos = measureFraming(det.landmarks, screenMapper(v), ovalRect());
      fr = framingIssue({ found: true, ...pos, pose: det.pose, brightness: roi.brightness, shake: shakeOf(now, det.landmarks, vw, vh), mouthOpen: det.mouthOpen });
    } else cam.nose = [];
    const map = screenMapper(v), oval = ovalRect();
    cam.lastDraw = det ? { lm: det.landmarks, map, oval } : null;
    overlay.draw({ phase: cam.phase, lm: det?.landmarks || null, map, oval, now, bpm: live.bpm });
    // mediaTime 이 실제로 늘어나는지 자세 맞추는 동안 확인한다 (라이브 스트림에서 0에 머무는 브라우저가 있다)
    if (frameMs != null && cam.phase === 'align') { cam.mediaUp = frameMs > (cam.lastMedia ?? -1) ? cam.mediaUp + 1 : 0; cam.lastMedia = frameMs; }
    if (cam.phase === 'align') align(fr, now);
    else measure(det && roi.valid ? det : null, roi, fr, now, cam.mediaUp >= 10 && frameMs != null ? frameMs : now);
  }
  if (cam.phase === 'measure') tick(performance.now());
  if (cam.phase === 'align' || cam.phase === 'measure') schedule();
}

// 자세 맞추기: 맞으면 바로 타원이 파랗게 바뀌고 흰 링이 1초 동안 차오른다.
// 판정은 프레임마다 흔들리므로, 틀어진 상태가 RELEASE_MS 이어질 때만 해제하고 링은 부드럽게 줄어든다.
const RELEASE_MS = 300;
function align(fr, now) {
  const el = scanEl();
  if (fr.ok) cam.badSince = 0; else cam.badSince ||= now;
  const holding = cam.readySince && (fr.ok || now - cam.badSince < RELEASE_MS);
  if (!fr.ok && !holding) {
    if (cam.readySince) { cam.readySince = 0; el.classList.add('retract'); ring(0); el.classList.remove('ready'); }
    say(fr.issue, fr.text, { tip: fr.issue === 'noface' ? '휴대폰을 세워 두면 맞추기 쉬워요' : '' });
    return;
  }
  if (!cam.readySince) {
    cam.readySince = now; el.classList.remove('retract'); el.classList.add('ready');
    say('ready', '좋아요, 그대로 있어 주세요', { tip: '곧 시작해요', force: true });
  }
  if (!fr.ok) return;                                           // 잠깐 흔들리는 동안은 링을 멈춰 둔다
  ring((now - cam.readySince) / HOLD_MS);
  if (now - cam.readySince >= HOLD_MS) startMeasure();
}

function startMeasure() {
  Object.assign(cam, { phase: 'measure', samples: [], t0: performance.now(), f0: null, lastSample: performance.now() });
  live.at = 0;
  flash('locked', 420);                                          // 타원이 한 번 맥동하고 흰 링이 사라진다
  setTimeout(() => { if (cam.phase === 'measure') { ring(0); setPhaseUI('measure'); } }, 180);
  $('count').textContent = SECS;
  buzz(20);
  say('breathe', '그대로 편하게 숨 쉬세요', { tip: '말하지 말고 화면을 봐 주세요', force: true });
}

function measure(det, roi, fr, now, frameMs) {
  cam.f0 ??= frameMs;
  if (det) { cam.lastSample = now; cam.samples.push({ t: Math.round((frameMs - cam.f0) * 10) / 10, forehead: roi.forehead, lcheek: roi.lcheek, rcheek: roi.rcheek, faceWidth: roi.faceWidth, faceCenter: roi.faceCenter, brightness: roi.brightness, blink: det.blink, mouthOpen: det.mouthOpen }); }
  if (!det) say('lost', '얼굴이 원 밖으로 나갔어요', { tip: '원 안으로 돌아오면 이어서 재요', warn: true });
  else if (fr.issue === 'mouth') say('mouth', '말하지 말고 그대로 있어 주세요', { warn: true });
  else if (!fr.ok) say(fr.issue, fr.text, { warn: true });
  else say('breathe', '그대로 편하게 숨 쉬세요', { tip: '말하지 말고 화면을 봐 주세요' });
}

function tick(now) {
  const el = (now - cam.t0) / 1000;
  if (scanEl().classList.contains('measuring')) ring(el / SECS);
  $('count').textContent = Math.max(0, Math.ceil(SECS - el));
  if (now - live.at > 1000) {
    live.at = now;
    const fresh = now - (cam.lastSample ?? 0) < 1500;            // 얼굴을 놓치면 이전 숫자를 계속 보여 주지 않는다
    const q = fresh && cam.samples.length > 60 ? quickBpm(cam.samples, 10) : { bpm: NaN };
    const show = ok(q.bpm) && q.snrDb >= 0;
    $('live').hidden = !show;
    live.bpm = show ? q.bpm : NaN;
    if (show) { $('liveBpm').textContent = Math.round(q.bpm); document.querySelector('.live .heart').style.animationDuration = (60 / q.bpm).toFixed(2) + 's'; }
  }
  if (el >= SECS) finish();
}

function stopCam() {
  cancelAnimationFrame(cam.raf);
  const v = $('video'); if (RVFC && v.cancelVideoFrameCallback) v.cancelVideoFrameCallback(cam.raf);
  if (cam.stream) closeCamera(v);
  cam.stream = null;
}
function closeScan() {
  cam.phase = 'off'; stopCam(); clearTimeout(swapTimer);
  const el = scanEl(); el.classList.add('leaving');
  setTimeout(() => { if (cam.phase === 'off') { overlay.reset(); el.className = 'scan'; } }, 300);   // 그사이 다시 열었으면 건드리지 않는다
}
$('scanX').onclick = closeScan;

// 완료: 링이 다 차면 체크 표시 → 결과 화면. 계산은 그 사이에 끝난다.
async function finish() {
  if (cam.phase !== 'measure') return;                           // 두 번 불려도 한 번만
  cam.phase = 'done'; stopCam(); clearTimeout(swapTimer);
  ring(1); setPhaseUI('done'); center('done'); $('live').hidden = true;
  if (cam.lastDraw) {                                          // 측정 영역이 사라지는 0.25초
    const t0 = performance.now(), fade = () => { const n = performance.now(); overlay.draw({ phase: 'done', ...cam.lastDraw, now: n, bpm: NaN }); if (n - t0 < 300) requestAnimationFrame(fade); };
    requestAnimationFrame(fade);
  }
  say('done', '다 됐어요', { tip: '결과를 정리하고 있어요', force: true });
  buzz(30);
  const t = performance.now();
  await new Promise(r => setTimeout(r, 30));
  const samples = cam.samples;
  let scan;
  if (samples.length < 60) scan = { id: Date.now(), ts: Date.now(), r: null, f: null };
  else {
    const r = analyze(samples);
    const { debug, ...rest } = r;                                  // 그래프용 원신호는 저장하지 않는다
    scan = { id: Date.now(), ts: Date.now(), r: rest, f: faceState(samples), pulse: Array.from(debug.pulse.slice(-300), v => Math.round(v * 1e4) / 1e4) };
    await putScan(scan);
  }
  await new Promise(r => setTimeout(r, Math.max(0, 750 - (performance.now() - t))));   // 완료 표시를 볼 시간
  showResult(scan);                                               // 결과는 촬영 화면 아래에서 먼저 올라오고
  const el = scanEl(); el.classList.add('leaving');               // 촬영 화면이 그 위에서 사라진다
  setTimeout(() => { if (cam.phase === 'done') { overlay.reset(); center(null); el.className = 'scan'; } }, 300);
}

// 개발 확인용: 카메라 없이 자세 맞추기 → 30초를 합성 신호로 흉내 낸다
function demoAlign() {
  center(null);
  say('noface', '얼굴을 원 안에 맞춰 주세요', { tip: '휴대폰을 세워 두면 맞추기 쉬워요', force: true });
  setTimeout(() => {
    if (cam.phase !== 'align') return;
    scanEl().classList.add('ready'); say('ready', '좋아요, 그대로 있어 주세요', { tip: '곧 시작해요', force: true });
    const t = performance.now();
    const fill = () => { if (cam.phase !== 'align') return; const f = (performance.now() - t) / HOLD_MS; ring(f); if (f < 1) requestAnimationFrame(fill); else demoMeasure(); };
    requestAnimationFrame(fill);
  }, 900);
}
function demoMeasure() {
  startMeasure();
  const all = synthSamples({ bpm: 64 + Math.round(Math.random() * 24), durationSec: SECS, seed: Date.now() % 1000, rrJitterMs: 30, noise: 0.2, blinkRate: 0 });
  for (const s of all) s.blink = (s.t / 1000) % 4 < 0.15 ? 0.9 : 0;
  let i = 0;
  const step = () => {
    if (cam.phase !== 'measure') return;
    const now = performance.now();
    while (i < all.length && all[i].t <= now - cam.t0) { cam.samples.push(all[i++]); cam.lastSample = now; }
    tick(now);
    requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// ---------- 결과 ----------
let CUR = null, VIEW = null;
function showResult(scan) {
  CUR = scan; VIEW = resultView(scan);
  const v = VIEW, d = new Date(scan.ts);
  let h = `<div class="bar"><button class="x" type="button" data-act="close" aria-label="닫기">${ic('x', 22)}</button><span>${DAY(d)} ${HM(d)}</span><span></span></div>`;
  if (v.status !== 'ok') h += `<div class="retry"><div><h2>${esc(v.title)}</h2><p>${esc(v.message)}</p></div><img src="/characters/idle.png" alt=""></div>`;
  if (v.status === 'noface') return openPage(h);
  h += `<button class="big${v.hr.shown ? '' : ' off'}" type="button" data-detail="hr">
      <span class="k">심박 <span class="chip ${v.signal.tone}">${v.signal.label}</span></span>
      <span class="v num">${v.hr.value}${v.hr.unit ? `<small>${v.hr.unit}</small>` : ''}</span>
      ${v.wave ? '<canvas id="pulseCv" aria-label="맥파 그래프"></canvas><span class="t">얼굴 피부색에서 읽은 맥파 · 마지막 10초</span>' : ''}</button>`;
  h += `<div class="tiles">${v.tiles.map(t => `<button class="tile${t.state === 'held' ? ' off' : ''}" type="button" data-detail="${t.key}">
      <span class="k">${t.label}${t.state === 'ref' ? '<em class="ref">참고</em>' : ''}</span>
      <span class="v num">${t.value}${t.unit ? `<small>${t.unit}</small>` : ''}</span><span class="s">${esc(t.sub)}</span></button>`).join('')}</div>
    <button class="row-link" type="button" data-detail="quality"><span>측정 품질</span><span>${v.status === 'ok' ? '기준 통과' : '기준 미달'}${ic('chevron-right', 20)}</span></button>`;
  openPage(h);
  if (v.wave) drawPulse($('pulseCv'), scan.pulse);
}
function openPage(html) {
  $('result').innerHTML = `<div class="in">${html}</div>`;
  $('result').classList.remove('closing'); $('result').classList.add('on'); $('result').scrollTop = 0; $('dock').classList.add('on');
}
function closePage(animate = false) {
  const pg = $('result');
  if (!animate || !pg.classList.contains('on')) { pg.classList.remove('on', 'closing'); $('dock').classList.remove('on'); return; }
  pg.classList.add('closing'); $('dock').classList.remove('on');
  setTimeout(() => pg.classList.remove('on', 'closing'), 200);
}

function drawPulse(cv, p) {
  if (!cv || !p?.length) return;
  const dpr = Math.min(2, devicePixelRatio || 1), W = cv.width = cv.clientWidth * dpr, H = cv.height = cv.clientHeight * dpr, c = cv.getContext('2d');
  let mx = 1e-9; for (const v of p) mx = Math.max(mx, Math.abs(v));
  c.lineWidth = 2.5 * dpr; c.lineJoin = 'round'; c.strokeStyle = BRAND(); c.beginPath();
  p.forEach((v, i) => { const x = i / (p.length - 1) * W, y = H / 2 - v / mx * H * 0.42; i ? c.lineTo(x, y) : c.moveTo(x, y); });
  c.stroke();
}

// ---------- 상세 시트 ----------
function openSheet(html) { const sh = $('sheet'); sh.classList.remove('closing'); $('sheetIn').innerHTML = `<div class="grab"></div>${html}`; sh.classList.add('on'); }
function closeSheet() {
  const sh = $('sheet'); if (!sh.classList.contains('on') || sh.classList.contains('closing')) return;
  sh.classList.add('closing'); setTimeout(() => sh.classList.remove('on', 'closing'), 200);
}
$('sheet').addEventListener('click', e => { if (e.target === $('sheet')) closeSheet(); });

function detail(k) {
  const r = CUR.r, f = CUR.f, v = VIEW, e = EVIDENCE[k];
  const kv = (a, b) => `<div class="kv"><span>${a}</span><b class="num">${b}</b></div>`;
  const big = (val, unit) => `<p class="v num">${val}${unit ? `<small>${unit}</small>` : ''}</p>`;
  const t = v.tiles.find(x => x.key === k);
  let body = '';
  if (k === 'hr') body = big(v.hr.value, v.hr.unit) + `<p>${e.how}</p>` + (v.hr.shown ? `<div>${kv('신호 대 잡음', `${fmt(r.snrDb, 1)} dB`)}${['forehead', 'lcheek', 'rcheek'].map(n => kv({ forehead: '이마', lcheek: '왼쪽 볼', rcheek: '오른쪽 볼' }[n], `${fmt(r.perRoi?.[n]?.bpm)} bpm`)).join('')}</div>` : `<p>${esc(v.message)}</p>`);
  if (k === 'hrv') body = big(t.value, t.unit) + `<p>${e.how}</p><div>${kv('찾은 박동 간격', `${r.rr.length}개`)}${kv('평균 간격', withUnit(r.meanRR, 'ms'))}${kv('신호 대 잡음', withUnit(r.snrDb, 'dB', 1))}</div>${t.state === 'held' ? '<p>맥박 신호가 10 dB를 넘고 박동 간격이 20쌍 이상 잡혀야 보여 드려요. 신호가 약하면 박동 위치가 흔들려 값이 실제보다 커져요.</p>' : ''}`;
  if (k === 'resp') body = big(t.value, t.unit) + `<p>${e.how}</p><div>${kv('머리 오르내림 주기', withUnit(r.resp?.head, '회/분'))}${kv('얼굴 밝기 주기', withUnit(r.resp?.light, '회/분'))}</div>`;
  if (k === 'blink') body = big(t.value, t.unit) + `<p>${e.how}</p>${f ? `<div>${kv('얼굴이 잡힌 시간', withUnit(f.durationSec, '초'))}${kv('깜빡임', `${f.blinks}번`)}${kv('눈 감긴 시간', withUnit(f.eyeClosedRatio * 100, '%'))}</div>` : ''}`;
  if (k === 'head') body = big(t.value, t.unit) + `<p>${e.how}</p>${f ? `<div>${kv('카메라 프레임', withUnit(f.fps, 'fps'))}${kv('평균 얼굴 밝기', withUnit(f.brightness, '/ 255'))}</div>` : ''}`;
  if (k === 'quality') body = `<p>${v.status === 'ok' ? '모든 기준을 넘었어요.' : esc(v.message)}</p><div>${v.quality.map(q => `<div class="kv"><span>${q.label}</span><b class="${q.ok ? 'ok' : 'bad'} num">${q.value}</b></div>`).join('')}</div>`;
  const lit = e?.lit ? `<div class="lit"><b>연구에서는</b><p>${e.lit}</p></div>` : '';
  const src = e?.src?.length ? `<div class="src">${e.src.map(s => `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.label)}</a>`).join('')}</div>` : '';
  openSheet(`<h2>${k === 'quality' ? '측정 품질' : e.title}</h2>${body}${lit}${src}<button class="btn sub" type="button" data-act="sheetClose">닫기</button>`);
}

// ---------- 기록 ----------
async function renderLog() {
  const scans = await listScans(), by = {};
  for (const s of scans) (by[DAY(new Date(s.ts))] ||= []).push(s);
  $('v-log').innerHTML = `<h1 class="log-h">기록</h1>` + (scans.length
    ? Object.entries(by).map(([d, rs]) => `<div class="day"><h3>${d}</h3>${rs.map(s => {
        const v = resultView(s), blink = v.tiles.find(t => t.key === 'blink');
        return `<button class="rec" type="button" data-show="${s.id}"><b class="num">${v.hr?.value ?? '–'}${v.hr?.unit ? `<small>${v.hr.unit}</small>` : ''}</b>
          <span class="chip ${v.status === 'ok' ? '' : 'warn'}">${v.status === 'ok' ? '통과' : '미달'}</span>
          <span class="n">${HM(new Date(s.ts))}${blink && blink.state !== 'held' ? ` · 깜빡임 ${blink.value}회/분` : ''}</span></button>`;
      }).join('')}</div>`).join('') + '<button class="link-quiet" type="button" data-act="wipe">기록 모두 지우기</button>'
    : `<div class="empty"><img src="/characters/sleep.png" alt="" width="120" height="120"><p>아직 기록이 없어요</p><button class="btn" type="button" data-act="prep" style="max-width:240px">첫 측정 하기</button></div>`);
}

// ---------- 이벤트 ----------
document.addEventListener('click', async e => {
  const b = e.target.closest('button'); if (!b) return;
  if (b.dataset.show) { const s = (await listScans()).find(x => String(x.id) === b.dataset.show); if (s) showResult(s); return; }
  if (b.dataset.detail && CUR?.r) return detail(b.dataset.detail);
  const a = b.dataset.act;
  if (a === 'prep') openPrep();
  else if (a === 'scan') { if ($('sheet').classList.contains('on')) { closeSheet(); setTimeout(openScan, 140); } else openScan(); }
  else if (a === 'close') { closePage(true); go(document.querySelector('.tabs [aria-selected="true"]').dataset.tab); }
  else if (a === 'sheetClose') closeSheet();
  else if (a === 'wipe') { if (confirm('이 기기의 측정 기록을 모두 지울까요?')) { await clearScans(); renderLog(); toast('기록을 지웠어요'); } }
});

persistStorage();
if ('serviceWorker' in navigator && import.meta.env.PROD) navigator.serviceWorker.register('/sw.js');
renderHome();
if (!DEMO) loadFaceMesh().catch(() => { /* 촬영 화면에서 다시 불러오며 안내한다 */ });

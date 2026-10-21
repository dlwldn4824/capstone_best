// Vity 얼굴 체크 — 30초 얼굴 촬영으로 심박 · 맥파 · 박동 간격 · 호흡 · 눈 깜빡임 · 머리 흔들림을 읽어 보여 준다.
// 앱이 하려는 말은 '심박이 몇이다'가 아니라 '평소와 다른가'다 (src/pipeline/baseline.js 에 근거).
// 흐름: (첫 실행) 온보딩 → 홈 → 준비 시트 → 촬영(자세 맞추기 → 30초) → 결과 → 이유 묻기 → 상세 시트. 기록 · 내 정보 탭.
// 계산은 src/pipeline, 자세 판정은 src/capture/framing.js, 결과 표시 규칙은 src/ui/view.js.
// 카메라 프레임 · 랜드마크는 메모리에서만 쓰고 저장하지 않는다.
import { openCamera, closeCamera } from './capture/camera.js';
import { loadFaceMesh, detect, TESSELATION } from './capture/facemesh.js';
import { RoiSampler } from './capture/roi.js';
import { framingIssue, measureFraming } from './capture/framing.js';
import { analyze, liveEstimate, stableEnough, EARLY_STOP } from './pipeline/index.js';
import { faceState } from './pipeline/face.js';
import { synthSamples } from './debug/synth.js';
import { ic } from './ui/icons.js';
import { EVIDENCE } from './ui/evidence.js';
import { resultView } from './ui/view.js';
import { createOverlay } from './ui/overlay.js';
import { baselineOf, unexplained, WHY, WHY_LABEL } from './pipeline/baseline.js';
import { putScan, listScans, clearScans, persistStorage, getProfile, setProfile, wipeAll } from './store/db.js';

const SECS = 30, HOLD_MS = 1000, SHAKE_MS = 500;
// 측정 방식: quick = 맥박이 안정되고 품질을 통과하면 10초부터 끝냄(최대 30초) · full = 30초 (박동 간격 · 호흡 · 깜빡임까지)
let MODE = (() => { try { return localStorage.getItem('vity.mode') || 'quick'; } catch { return 'quick'; } })();
function setMode(m) { MODE = m; try { localStorage.setItem('vity.mode', m); } catch { /* 사생활 모드 */ } }
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
  document.body.dataset.tab = tab;                  // CSS 가 홈에서만 손잡이를 보이게 한다
  document.querySelectorAll('.tabs button').forEach(x => x.setAttribute('aria-selected', x.dataset.tab === tab));
  document.querySelectorAll('.view').forEach(v => v.classList.toggle('on', v.id === 'v-' + tab));
  ({ log: renderLog, me: renderMe }[tab] || renderHome)();
  window.scrollTo(0, 0);
}

// ---------- 평소값 ----------
// 화면 여러 곳에서 쓰므로 한 번 계산해 둔다. 측정이 끝날 때마다 다시 잡는다.
let BASE = { ready: false, n: 0, need: 0, bpm: NaN, spread: NaN };
async function refreshBase() { BASE = baselineOf(await listScans()); return BASE; }

// ---------- 홈 ----------
async function renderHome() {
  const scans = await listScans();
  BASE = baselineOf(scans);
  const last = scans[0];
  const lv = last ? resultView(last, BASE) : null;
  $('v-home').innerHTML = `
    <div class="hero">
      <p class="eyebrow">${DAY(new Date())}</p>
      <h1>얼굴 30초로<br><em>평소와 다른지</em><br>봐 드릴게요</h1>
      <img src="/assets/characters/coffee.png" alt="" width="136" height="136">
      <div class="reads">${['심박', '맥파', '박동 간격', '호흡', '눈 깜빡임', '머리 흔들림'].map(t => `<span class="chip">${t}</span>`).join('')}</div>
    </div>
    <div class="start">
      <button class="btn" type="button" data-act="prep">${ic('scan-face', 22)}시작하기</button>
      <p>카메라 영상은 이 휴대폰 안에서만 처리돼요</p>
    </div>
    ${BASE.ready
      ? `<p class="sec">내 평소</p>
    <div class="base"><span class="v num">${fmt(BASE.bpm)}<small>bpm</small></span><span class="k">최근 ${BASE.n}번의 가운데 값이에요</span></div>`
      : `<div class="base learn"><span class="k">${BASE.n ? `평소를 알려면 <b>${BASE.need}번</b> 더 재면 돼요` : '몇 번 재고 나면 평소와 비교해 드릴게요'}</span></div>`}
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
  const mode = (k, t, d) => `<button class="mode" type="button" role="radio" aria-checked="${MODE === k}" data-mode="${k}"><b>${t}</b><span>${d}</span></button>`;
  openSheet(`<h2>어떻게 잴까요?</h2>
    <div class="modes" role="radiogroup" aria-label="측정 방식">
      ${mode('quick', '빠르게', '심박 · 맥파<br>보통 10–20초')}
      ${mode('full', '전체', '박동 간격 · 호흡 · 깜빡임까지<br>30초')}
    </div>
    <ul class="prep-list prep">
      ${row('smartphone', '휴대폰을 세워 두세요', '책이나 컵에 기대 눈높이에 두면 재는 동안 흔들리지 않아요.')}
      ${row('scan-face', '팔 길이만큼 떨어져 앉아요', '얼굴이 원을 꽉 채우는 거리예요. 30–40cm 정도.')}
      ${row('sun', '빛은 얼굴 앞쪽에', '창문이나 조명을 등지면 얼굴이 어두워져요.')}
      ${row('mic-off', '재는 동안 말하지 않아요', '입을 움직이면 맥박 신호가 흔들려요.')}
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
  Object.assign(cam, { phase: 'measure', samples: [], t0: performance.now(), f0: null, lastSample: performance.now(), mode: MODE, hist: [] });
  live.at = 0;
  flash('locked', 420);                                          // 타원이 한 번 맥동하고 흰 링이 사라진다
  setTimeout(() => { if (cam.phase === 'measure') { ring(0); setPhaseUI('measure'); } }, 180);
  $('count').textContent = cam.mode === 'quick' ? 0 : SECS;
  buzz(20);
  say('breathe', '그대로 편하게 숨 쉬세요', { tip: breatheTip(), force: true });
}

function measure(det, roi, fr, now, frameMs) {
  cam.f0 ??= frameMs;
  if (det) { cam.lastSample = now; cam.samples.push({ t: Math.round((frameMs - cam.f0) * 10) / 10, forehead: roi.forehead, lcheek: roi.lcheek, rcheek: roi.rcheek, faceWidth: roi.faceWidth, faceCenter: roi.faceCenter, brightness: roi.brightness, blink: det.blink, mouthOpen: det.mouthOpen }); }
  if (!det) say('lost', '얼굴이 원 밖으로 나갔어요', { tip: '원 안으로 돌아오면 이어서 재요', warn: true });
  else if (fr.issue === 'mouth') say('mouth', '말하지 말고 그대로 있어 주세요', { warn: true });
  else if (!fr.ok) say(fr.issue, fr.text, { warn: true });
  else say('breathe', '그대로 편하게 숨 쉬세요', { tip: breatheTip() });
}
const breatheTip = () => (cam.mode === 'quick' ? '맥박이 안정되면 바로 끝나요' : '말하지 말고 화면을 봐 주세요');

function tick(now) {
  const el = (now - cam.t0) / 1000;
  if (scanEl().classList.contains('measuring')) ring(el / SECS);
  $('count').textContent = cam.mode === 'quick' ? Math.floor(el) : Math.max(0, Math.ceil(SECS - el));   // 빠르게: 지난 초 · 전체: 남은 초
  if (now - live.at > 1000) {
    live.at = now;
    const fresh = now - (cam.lastSample ?? 0) < 1500;            // 얼굴을 놓치면 이전 숫자를 계속 보여 주지 않는다
    const q = fresh ? liveEstimate(cam.samples) : { bpm: NaN, snrDb: -Infinity };
    cam.hist.push({ t: el, bpm: q.bpm, snrDb: q.snrDb });
    const show = ok(q.bpm) && q.snrDb >= 0;
    $('live').hidden = !show;
    live.bpm = show ? q.bpm : NaN;
    if (show) { $('liveBpm').textContent = Math.round(q.bpm); document.querySelector('.live .heart').style.animationDuration = (60 / q.bpm).toFixed(2) + 's'; }
    // 빠르게: 최근 3번이 ±2 bpm 안 · SNR ≥ 3 dB · 10초 이상이고, 지금까지 전체가 품질을 통과하면 끝낸다
    if (cam.mode === 'quick' && stableEnough(cam.hist, el) && analyze(cam.samples, { resp: false, windowRetry: false }).quality.pass) return finish();
  }
  if (el >= EARLY_STOP.maxSec) finish();
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
  scanEl().classList.add('retract'); ring(1);                     // 빠르게 끝나면 남은 링이 부드럽게 찬다
  setPhaseUI('done'); center('done'); $('live').hidden = true;
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
  if (samples.length < 60) scan = { id: Date.now(), ts: Date.now(), mode: cam.mode, r: null, f: null };
  else {
    const r = analyze(samples);
    const { debug, ...rest } = r;                                  // 그래프용 원신호는 저장하지 않는다
    scan = { id: Date.now(), ts: Date.now(), mode: cam.mode, r: rest, f: faceState(samples), pulse: Array.from(debug.pulse.slice(-300), v => Math.round(v * 1e4) / 1e4) };
    await putScan(scan);
  }
  await new Promise(r => setTimeout(r, Math.max(0, 750 - (performance.now() - t))));   // 완료 표시를 볼 시간
  BASE = baselineOf((await listScans()).filter(x => x.id !== scan.id));   // 이번 값은 자기 평소에 넣지 않는다
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
  CUR = scan; VIEW = resultView(scan, BASE);
  const v = VIEW, d = new Date(scan.ts);
  let h = `<div class="bar"><button class="x" type="button" data-act="close" aria-label="닫기">${ic('x', 22)}</button><span>${DAY(d)} ${HM(d)}</span><span></span></div>`;
  if (v.status !== 'ok') h += `<div class="retry"><div><h2>${esc(v.title)}</h2><p>${esc(v.message)}</p></div><img src="/assets/characters/idle.png" alt=""></div>`;
  if (v.status === 'noface') return openPage(h);
  h += `<button class="big${v.hr.shown ? '' : ' off'}" type="button" data-detail="hr">
      <span class="k">심박 <span class="chip ${v.signal.tone}">${v.signal.label}</span></span>
      <span class="v num">${v.hr.value}${v.hr.unit ? `<small>${v.hr.unit}</small>` : ''}</span>
      ${v.wave ? '<canvas id="pulseCv" aria-label="맥파 그래프"></canvas><span class="t">얼굴 피부색에서 읽은 맥파 · 마지막 10초</span>' : ''}</button>`;
  // 평소와 얼마나 다른가 — 숫자보다 이게 먼저다
  const dv = v.deviation;
  if (dv.level !== 'none') {
    const off = dv.level === 'high' || dv.level === 'low';
    h += `<div class="dev${off ? ' off' : ''}${dv.level === 'learning' ? ' learn' : ''}">
      <b>${esc(dv.text)}</b>${dv.level === 'learning' ? '' : `<span>평소 ${fmt(dv.baseBpm)} bpm</span>`}</div>`;
    if (off) h += `<div class="why"><p>왜 그런지 짚이는 게 있나요?</p><div class="chips">${WHY.map(w =>
      `<button class="chip${scan.why === w.key ? ' on' : ''}" type="button" data-why="${w.key}">${w.label}</button>`).join('')}</div>
      ${scan.why === 'none' ? '<p class="note">이유 없는 변화로 따로 모아 둘게요. 며칠 이어지면 알려 드려요.</p>' : ''}</div>`;
  }
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
  BASE = baselineOf(scans);
  for (const s of scans) (by[DAY(new Date(s.ts))] ||= []).push(s);
  const u = unexplained(scans);
  const head = u.ready && u.streak >= 2
    ? `<div class="unex on"><b>설명되지 않은 변화가 ${u.streak}일째예요</b><span>짚이는 이유 없이 평소와 다른 날이 이어지고 있어요. 계속되면 한번 쉬어 가세요.</span></div>`
    : u.ready
      ? `<div class="unex"><b>설명되지 않은 변화 ${u.recent}번</b><span>최근 3일 중, 이유를 짚지 못한 날이에요.</span></div>`
      : '';
  $('v-log').innerHTML = `<h1 class="log-h">기록</h1>` + head + (scans.length
    ? Object.entries(by).map(([d, rs]) => `<div class="day"><h3>${d}</h3>${rs.map(s => {
        const v = resultView(s, BASE), blink = v.tiles.find(t => t.key === 'blink');
        return `<button class="rec" type="button" data-show="${s.id}"><b class="num">${v.hr?.value ?? '–'}${v.hr?.unit ? `<small>${v.hr.unit}</small>` : ''}</b>
          <span class="chip ${v.status === 'ok' ? '' : 'warn'}">${v.status === 'ok' ? '통과' : '미달'}</span>
          <span class="n">${HM(new Date(s.ts))}${v.deviation?.level === 'high' || v.deviation?.level === 'low' ? ` · ${esc(v.deviation.text)}` : ''}${s.why ? ` · ${esc(WHY_LABEL[s.why] || '')}` : ''}${blink && blink.state !== 'held' ? ` · 깜빡임 ${blink.value}회/분` : ''}</span></button>`;
      }).join('')}</div>`).join('') + '<button class="link-quiet" type="button" data-act="wipe">기록 모두 지우기</button>'
    : `<div class="empty"><img src="/assets/characters/sleep.png" alt="" width="120" height="120"><p>아직 기록이 없어요</p><button class="btn" type="button" data-act="prep" style="max-width:240px">첫 측정 하기</button></div>`);
}

// ---------- 내 정보 ----------
async function renderMe() {
  const p = await getProfile();
  BASE = baselineOf(await listScans());
  const num = (id, label, val, unit, ph) =>
    `<label class="fld"><span>${label}</span><input id="${id}" inputmode="numeric" value="${val ?? ''}" placeholder="${ph}"><em>${unit}</em></label>`;
  const mode = (k, t, d) => `<button class="mode" type="button" role="radio" aria-checked="${MODE === k}" data-mode="${k}"><b>${t}</b><span>${d}</span></button>`;
  $('v-me').innerHTML = `<h1 class="log-h">내 정보</h1>
    <div class="card">
      <label class="fld"><span>이름</span><input id="pNick" maxlength="12" value="${esc(p.nick)}" placeholder="예: 하린"></label>
      ${num('pH', '키', p.height, 'cm', '170')}
      ${num('pW', '몸무게', p.weight, 'kg', '60')}
      ${num('pY', '태어난 해', p.birth_year, '년', '2004')}
      <button class="btn sub" type="button" data-act="saveMe">저장</button>
    </div>
    <div class="card">
      <p class="sec">내 평소</p>
      ${BASE.ready
        ? `<div class="base"><span class="v num">${fmt(BASE.bpm)}<small>bpm</small></span><span class="k">최근 ${BASE.n}번의 가운데 값 · 흩어짐 ±${fmt(BASE.spread, 1)}</span></div>`
        : `<div class="base learn"><span class="k">${BASE.n ? `${BASE.need}번 더 재면 잡혀요` : '아직 재지 않았어요'}</span></div>`}
    </div>
    <div class="card">
      <p class="sec">측정 방식</p>
      <div class="modes" role="radiogroup" aria-label="측정 방식">
        ${mode('quick', '빠르게', '심박 · 맥파<br>보통 10–20초')}
        ${mode('full', '전체', '박동 간격 · 호흡 · 깜빡임까지<br>30초')}
      </div>
    </div>
    <div class="card quiet">
      <p>카메라 영상 · 얼굴 랜드마크는 저장하지 않아요. 계산한 숫자만 이 휴대폰에 남아요.</p>
      <button class="link-quiet" type="button" data-act="tutorial">튜토리얼 다시 보기</button>
      <button class="link-quiet" type="button" data-act="wipeAll">모든 기록과 내 정보 지우기</button>
    </div>`;
}

// ---------- 스와이프 ----------
// 준비 시트는 홈의 '시작하기'로 열리지만, 엄지로 올리는 쪽이 빠르다. 홈에서 위로 쓸면 열고 시트에서 아래로 쓸면 닫는다.
// pointer 로 받아 마우스로도 같게 돈다. 가로로 많이 움직였거나 느린 동작은 스와이프로 보지 않는다(스크롤·탭과 섞이지 않게).
const SWIPE = { dist: 70, side: 48, ms: 700 };
let swipe = null;
addEventListener('pointerdown', e => { swipe = e.isPrimary ? { x: e.clientX, y: e.clientY, t: Date.now() } : null; }, { passive: true });
addEventListener('pointerup', e => {
  const p = swipe; swipe = null;
  if (!p || Date.now() - p.t > SWIPE.ms || Math.abs(e.clientX - p.x) > SWIPE.side) return;
  const dy = p.y - e.clientY;
  const sheetOn = $('sheet').classList.contains('on');
  if (dy <= -SWIPE.dist && sheetOn) return closeSheet();                       // 아래로 → 시트 닫기
  if (dy < SWIPE.dist) return;
  if (sheetOn || $('result').classList.contains('on') || cam.phase !== 'off') return;
  if (!$('v-home').classList.contains('on')) return;
  if (document.documentElement.scrollHeight - innerHeight - scrollY > 8) return;   // 아직 스크롤할 게 남았으면 스크롤이다
  buzz(10); openPrep();                                                        // 위로 → 준비 시트
}, { passive: true });

// ---------- 온보딩 (첫 실행) ----------
// check.html 의 캐릭터 컷씬 5단계를 글 그대로 가져왔다. 바꾼 곳은 두 군데뿐:
//   - 2단계 "심박 · 박동 간격 · 긴장도" → "심박 · 박동 간격". 이 앱은 긴장도를 계산하지 않는다 (근거 없는 말은 하지 않는다).
//   - 3단계 그룹 참여 · 만들기는 check.py 서버가 있어야 돈다. 이 앱은 백엔드가 없어 안내만 하고 넘어간다.
let OB = { step: 0, nick: '', after: null };
function renderOnb() {
  const s = OB.step, o = $('onb');
  o.classList.toggle('dark', s === 2);
  const dots = `<div class="dots">${[0, 1, 2, 3, 4].map(i => `<i class="${i === s ? 'on' : ''}"></i>`).join('')}</div>`;
  const back = s ? `<button class="back" type="button" data-ob="back" aria-label="뒤로">${ic('chevron-left', 22)}</button>` : '<span class="sp"></span>';
  let body = '', ch = 'calm', small = false;
  if (s === 0) body = `<h1>만나서 반가워요!</h1><p>저는 Vity예요. 시험기간 동안 매일 30초씩, 당신의 컨디션을 같이 지켜볼게요.</p>
    <button class="obtn" type="button" data-ob="next">시작하기</button>`;
  else if (s === 1) { ch = 'ask'; small = true; body = `<h1>이름을 알려 줄래요?</h1><p>그룹 친구들에게 이 이름으로 보여요.</p>
    <input id="obNick" maxlength="12" placeholder="예: 하린" value="${esc(OB.nick)}" aria-label="내 이름">
    <button class="obtn" type="button" data-ob="nick">좋아요</button>`; }
  else if (s === 2) { ch = 'coffee'; body = `<span class="bubble">${esc(OB.nick || '당신')}님, 30초만 저를 봐 주세요</span><h1>얼굴로 맥박을 읽어요</h1>
    <p>카메라가 이마와 볼 피부색의 아주 작은 변화를 읽어 심박 · 박동 간격을 계산해요. 밝은 곳에서, 말하지 않고 30초면 돼요.</p>
    <button class="obtn" type="button" data-ob="next">알겠어요</button>`; }
  else if (s === 3) { ch = 'sleep'; small = true; body = `<h1>같이 할 친구가 있나요?</h1><p>스터디 친구들과 기상 · 공부 시작 인증을 하면 매일 재기가 쉬워져요. 그룹엔 인증 시각만 보여요.</p>
    <div class="ochoice"><input id="obCode" maxlength="6" placeholder="초대 코드 6자리" autocapitalize="characters" aria-label="초대 코드">
    <button class="obtn" type="button" data-ob="join">코드로 참여</button>
    <button class="oghost" type="button" data-ob="make">새 그룹 만들게요</button>
    <button class="oghost" type="button" data-ob="solo">혼자 할게요</button></div>`; }
  else { small = true; body = `<h1>마지막으로 약속할게요</h1>
    <ul><li>영상 · 사진은 저장하지 않아요. 계산한 숫자만 남아요.</li>
    <li>그룹엔 이름 · 인증 시각 · 연속 일수만 보여요.</li>
    <li>의료기기가 아니에요. 진단하지 않고 내 평소와 비교해요.</li>
    <li>생체 정보라 따로 동의를 받아요 (개인정보보호법 제23조).</li></ul>
    <button class="obtn" type="button" data-ob="agree">동의하고 시작</button>`; }
  o.innerHTML = `<div class="in"><div class="top">${back}<div class="f">${dots}</div><span class="sp"></span></div>${body}</div>
    <span class="ohill${small ? ' small' : ''}"></span><img class="ochar${small ? ' small' : ''}" src="/assets/characters/${ch}.png" alt="">`;
}
function openOnb(step = 0) { OB.step = step; $('onb').classList.add('on'); renderOnb(); }
async function onb(act) {
  if (act === 'back') OB.step = Math.max(0, OB.step - 1);
  else if (act === 'next' || act === 'solo') OB.step++;
  else if (act === 'nick') { const v = ($('obNick').value || '').trim(); if (!v) return toast('이름을 적어 주세요'); OB.nick = v; await setProfile({ nick: v }); OB.step++; }
  else if (act === 'join' || act === 'make') { toast('인증 그룹은 아직 이 앱에 없어요'); OB.step++; }   // 그룹은 서버가 필요하다
  else if (act === 'agree') { await setProfile({ consent: true }); $('onb').classList.remove('on'); renderHome(); return; }
  renderOnb();
}

// ---------- 이벤트 ----------
document.addEventListener('click', async e => {
  const b = e.target.closest('button'); if (!b) return;
  if (b.dataset.show) { const s = (await listScans()).find(x => String(x.id) === b.dataset.show); if (s) showResult(s); return; }
  if (b.dataset.ob) return onb(b.dataset.ob);
  if (b.dataset.why && CUR) {                     // 이유를 고르면 그 스캔에 붙여 둔다
    CUR.why = CUR.why === b.dataset.why ? null : b.dataset.why;
    await putScan(CUR);
    showResult(CUR);
    if (CUR.why) toast(CUR.why === 'none' ? '이유 없는 변화로 모아 둘게요' : '기록했어요');
    return;
  }
  if (b.dataset.detail && CUR?.r) return detail(b.dataset.detail);
  if (b.dataset.mode) { setMode(b.dataset.mode); document.querySelectorAll('.mode').forEach(x => x.setAttribute('aria-checked', x.dataset.mode === MODE)); return; }
  const a = b.dataset.act;
  if (a === 'prep') openPrep();
  else if (a === 'scan') { if ($('sheet').classList.contains('on')) { closeSheet(); setTimeout(openScan, 140); } else openScan(); }
  else if (a === 'close') { closePage(true); go(document.querySelector('.tabs [aria-selected="true"]').dataset.tab); }
  else if (a === 'sheetClose') closeSheet();
  else if (a === 'wipe') { if (confirm('이 기기의 측정 기록을 모두 지울까요?')) { await clearScans(); await refreshBase(); renderLog(); toast('기록을 지웠어요'); } }
  else if (a === 'saveMe') {
    const n = id => { const v = ($(id).value || '').trim(); return v === '' ? null : Number(v); };
    await setProfile({ nick: ($('pNick').value || '').trim(), height: n('pH'), weight: n('pW'), birth_year: n('pY') });
    toast('저장했어요');
  }
  else if (a === 'tutorial') openOnb(0);
  else if (a === 'wipeAll') { if (confirm('기록과 내 정보를 모두 지울까요? 되돌릴 수 없어요.')) { await wipeAll(); await refreshBase(); renderMe(); toast('모두 지웠어요'); } }
});

document.body.dataset.tab = 'home';
persistStorage();
getProfile().then(p => { if (!p.consent) { OB.nick = p.nick || ''; openOnb(0); } });
if ('serviceWorker' in navigator && import.meta.env.PROD) navigator.serviceWorker.register(import.meta.env.BASE_URL + 'sw.js', { scope: import.meta.env.BASE_URL });
renderHome();
if (!DEMO) loadFaceMesh().catch(() => { /* 촬영 화면에서 다시 불러오며 안내한다 */ });

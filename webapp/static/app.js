// 폰·워치 공통: 서버 API, 실시간 동기화(SSE), 판정 문구.
"use strict";

const API = {
  async get(path) {
    const r = await fetch(path, { cache: "no-store" });
    if (!r.ok) throw new Error(path + " " + r.status);
    return r.json();
  },
  async post(path, body) {
    const r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.status);
    return j;
  },
};

// 서버가 상태를 밀어준다. 끊기면 3초 뒤 다시 붙는다.
// role: "phone" | "watch" — 서버가 지금 어떤 화면이 붙어 있는지 센다.
// h: { state, live, conn, notify, dismiss, presence }
function subscribe(role, h) {
  let es;
  const on = (name, fn) => fn && es.addEventListener(name, (e) => fn(JSON.parse(e.data)));
  const open = () => {
    es = new EventSource("/api/events?role=" + role);
    on("state", h.state); on("live", h.live); on("notify", h.notify);
    on("dismiss", h.dismiss); on("presence", h.presence);
    es.onopen = () => h.conn && h.conn(true);
    es.onerror = () => {
      h.conn && h.conn(false);
      es.close();
      setTimeout(open, 3000);
    };
  };
  open();
}

// ---------- 팝업 알람 (폰·워치 공통) ----------
// 서버가 'notify' 를 보내면 두 화면에 동시에 뜬다. 한쪽에서 확인하면 'dismiss' 로 같이 닫힌다.
const Alarm = (() => {
  let audio = null;
  const shown = new Map();          // id -> 요소
  let actions = {};                 // kind -> { label, run }
  let decorate = null;              // (n, el) => void — 화면별로 덧붙일 것

  // 브라우저는 사용자가 한 번 눌러야 소리를 허락한다. 첫 터치에 잠금을 푼다.
  function unlock() {
    if (audio) return;
    try {
      audio = new (window.AudioContext || window.webkitAudioContext)();
      if (audio.state === "suspended") audio.resume();
    } catch (e) { audio = null; }
  }
  ["pointerdown", "keydown"].forEach((ev) => window.addEventListener(ev, unlock, { once: true, capture: true }));

  function chime(urgent) {
    if (!audio) return;
    const notes = urgent ? [880, 660, 880, 660] : [660, 880];
    notes.forEach((f, i) => {
      const o = audio.createOscillator(), g = audio.createGain();
      const t = audio.currentTime + i * 0.18;
      o.frequency.value = f;
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.25, t + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.16);
      o.connect(g).connect(audio.destination);
      o.start(t); o.stop(t + 0.17);
    });
  }

  async function systemNotify(n) {
    if (!("Notification" in window) || Notification.permission !== "granted" || !navigator.serviceWorker) return;
    try {
      const reg = await navigator.serviceWorker.ready;
      await reg.showNotification(n.title, {
        body: n.body, tag: "eg-" + n.id, renotify: true,
        requireInteraction: n.kind === "ALERT",
        vibrate: n.kind === "ALERT" ? [400, 150, 400, 150, 400] : [200, 100, 200],
        data: { url: location.pathname },
      });
    } catch (e) { /* 알림창은 덤이다. 팝업은 이미 떴다. */ }
  }

  async function closeSystem(id) {
    if (!navigator.serviceWorker) return;
    try {
      const reg = await navigator.serviceWorker.ready;
      (await reg.getNotifications({ tag: "eg-" + id })).forEach((x) => x.close());
    } catch (e) { /* 무시 */ }
  }

  function show(n) {
    if (shown.has(n.id)) return;
    const urgent = n.kind === "ALERT";
    const el = document.createElement("div");
    el.className = "alarm alarm-" + n.kind.toLowerCase();
    el.setAttribute("role", "alertdialog");
    el.setAttribute("aria-modal", "true");
    el.setAttribute("aria-label", n.title);
    const act = actions[n.kind];
    el.innerHTML =
      '<div class="alarm-card">' +
      '<div class="alarm-icon" aria-hidden="true">' + (urgent
        ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3.5L21.5 20h-19z"></path><path d="M12 10v4.5M12 17.2v.3"></path></svg>'
        : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9a6 6 0 1 1 12 0c0 6 2.5 7.5 2.5 7.5h-17S6 15 6 9z"></path><path d="M10 20a2.2 2.2 0 0 0 4 0"></path></svg>') +
      "</div>" +
      '<h2 class="alarm-title"></h2><p class="alarm-body"></p>' +
      '<div class="alarm-actions">' +
      (act ? '<button type="button" class="alarm-go"></button>' : "") +
      '<button type="button" class="alarm-ok">확인</button></div></div>';
    el.querySelector(".alarm-title").textContent = n.title;
    el.querySelector(".alarm-body").textContent = n.body;
    if (act) el.querySelector(".alarm-go").textContent = act.label;
    if (decorate) decorate(n, el);
    const done = () => { API.post("/api/notify/ack", { id: n.id }).catch(() => {}); remove(n.id); };
    el.querySelector(".alarm-ok").addEventListener("click", done);
    if (act) el.querySelector(".alarm-go").addEventListener("click", () => { done(); act.run(n); });
    document.body.appendChild(el);
    shown.set(n.id, el);
    requestAnimationFrame(() => el.classList.add("on"));
    el.querySelector(act ? ".alarm-go" : ".alarm-ok").focus();
    chime(urgent);
    if (navigator.vibrate) navigator.vibrate(urgent ? [400, 150, 400, 150, 400] : [200, 100, 200]);
    if (document.hidden) systemNotify(n);
  }

  function remove(id) {
    const el = shown.get(id);
    if (el) { el.classList.remove("on"); setTimeout(() => el.remove(), 200); shown.delete(id); }
    closeSystem(id);
  }

  async function enableSystem() {
    if (!("Notification" in window)) throw new Error("이 브라우저는 알림을 지원하지 않아요");
    if (!window.isSecureContext) throw new Error("알림은 https 주소에서만 켤 수 있어요");
    if (navigator.serviceWorker) await navigator.serviceWorker.register("/sw.js");
    const p = await Notification.requestPermission();
    if (p !== "granted") throw new Error("알림이 허용되지 않았어요");
    return true;
  }

  if (navigator.serviceWorker && window.isSecureContext) navigator.serviceWorker.register("/sw.js").catch(() => {});

  return { show, remove, unlock, enableSystem, setActions: (a) => { actions = a; },
    setDecorate: (fn) => { decorate = fn; },
    permission: () => ("Notification" in window ? Notification.permission : "unsupported") };
})();

const CAUSE_KO = { alcohol: "술", exercise: "운동", sleep_debt: "짧은 잠", tense: "긴장" };
const CONTEXT_ITEMS = [
  { key: "alcohol", label: "술을 마셨어요", short: "술", hint: "다음 날 밤 심박이 오르는 가장 흔한 이유예요" },
  { key: "sleep", label: "늦게 잤어요", short: "잠", hint: "잠이 짧으면 밤 심박이 조금 올라요" },
  { key: "exercise", label: "운동을 많이 했어요", short: "운동", hint: "고강도 활동 30분 이상이면 워치가 먼저 알아봐요" },
  { key: "tense", label: "긴장되는 일이 있었어요", short: "긴장", hint: "발표·시험·다툼 같은 일" },
];

// 받침에 맞는 조사: josa("술", "으로", "로") → "술로", josa("긴장", "이", "가") → "긴장이"
function josa(word, withFinal, withoutFinal) {
  const c = word.charCodeAt(word.length - 1) - 0xac00;
  if (c < 0 || c > 11171) return word + withoutFinal;
  const fin = c % 28;
  // '로' 는 ㄹ 받침 뒤에서도 '로' 를 쓴다 (술로, 잠으로)
  if (withFinal === "으로" && fin === 8) return word + "로";
  return word + (fin ? withFinal : withoutFinal);
}

// 판정 → 화면 문구. 폰과 워치가 같은 말을 쓴다.
function verdict(s) {
  const n = s.night || {};
  const st = s.status;
  const run = (s.streak || {}).run || 0;
  const k = (s.streak || {}).k || 3;
  switch (st) {
    case "NO_DATA":
      return { tone: "muted", title: "아직 기록이 없어요", short: "기록 없음",
        body: "밴드를 차고 하룻밤 자면 시작돼요. 시연용 기록으로 먼저 둘러볼 수도 있어요." };
    case "NO_NIGHT":
      return { tone: "muted", title: "어젯밤 기록이 아직 없어요", short: "기록 대기",
        body: "밴드 기록을 보내거나 직접 넣어주세요." };
    case "BASELINE":
      return { tone: "muted", title: "평소의 나를 배우는 중", short: "배우는 중",
        body: "비교할 기준이 생길 때까지 며칠만 더 기록해 주세요." };
    case "CALM":
      return { tone: "calm", title: "평소와 같아요", short: "평소",
        body: "어젯밤 몸은 평소 범위 안에 있었어요." };
    case "ASK":
      return { tone: "left", title: "평소와 조금 달랐어요", short: "물어볼게요",
        body: "어제 있었던 일을 알려주시면 함께 따져볼게요." };
    case "EXPLAINED":
      return { tone: "calm", title: "그럴 만해요", short: "그럴 만해요",
        body: (n.explained_ko ? "어젯밤 달라진 건 " + josa(n.explained_ko, "으로", "로") + " 설명돼요. " : "") +
          "오늘은 알림 없이 기록만 해둘게요." };
    case "WATCH":
      return { tone: "left", title: "남았어요", short: run + "일째",
        body: "짚이는 이유 없이 평소와 다른 밤이 " + run + "일째예요. " + k + "일 이어지면 알려드릴게요." };
    case "ALERT":
      return { tone: "alert", title: k + "일째 설명되지 않았어요", short: k + "일째",
        body: "이유 없이 평소와 다른 상태가 " + k + "일 이어졌어요. 진단은 아니에요. 몸 상태를 한번 살펴봐 주세요." };
    default:
      return { tone: "muted", title: "", short: "", body: "" };
  }
}

function fmtDay(iso) {
  const d = new Date(iso + "T00:00:00");
  return (d.getMonth() + 1) + "월 " + d.getDate() + "일 " + "일월화수목금토"[d.getDay()] + "요일";
}

function sign(x, nd) {
  if (x === null || x === undefined) return "–";
  const v = Number(x).toFixed(nd === undefined ? 1 : nd);
  return (x > 0 ? "+" : "") + v;
}

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
      '<button type="button" class="alarm-ok">닫기</button></div></div>';
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

function _bag(key) {
  try { return JSON.parse(localStorage.getItem(key) || "{}"); } catch (e) { return {}; }
}
function _putBag(key, all) { localStorage.setItem(key, JSON.stringify(all)); }

function tracesOf(day) {
  const v = _bag("vity-traces")[day];
  return Array.isArray(v) ? v : [];
}
function setTraces(day, list) {
  const all = _bag("vity-traces");
  all[day] = list;
  _putBag("vity-traces", all);
}
function declinedOf(day) { return new Set(_bag("vity-declined")[day] || []); }
function declineTrace(day, id) {
  const all = _bag("vity-declined");
  const s = new Set(all[day] || []);
  s.add(id);
  all[day] = [...s];
  _putBag("vity-declined", all);
}
function clearDeclined(day) {
  const all = _bag("vity-declined");
  delete all[day];
  _putBag("vity-declined", all);
}
function noteOf(day) { return _bag("vity-notes")[day] || ""; }
function setDayNote(day, text) {
  const all = _bag("vity-notes");
  if (text) all[day] = text; else delete all[day];
  _putBag("vity-notes", all);
}
function openTrace(day) {
  const no = declinedOf(day);
  return tracesOf(day).find((t) => !no.has(t.id)) || null;
}

const DEMO_TRACES = {
  drink: [{ id: "dinner", ctx: "alcohol", where: "캘린더", detail: "19:00–21:00 회식", ask: "음주하셨나요?" }],
  border: [{ id: "screen", ctx: "sleep", where: "폰 사용", detail: "새벽 1시 이후에도 화면이 켜져 있었어요", ask: "평소보다 늦게 잤나요?" }],
  unexplained: [],
  calm: [],
  face_only: [],
};
const EXTRA_OPTS = [
  { key: "cold", label: "감기 기운" },
  { key: "med", label: "약 복용" },
  { key: "alcohol", label: "음주" },
  { key: "caffeine", label: "카페인" },
  { key: "tense", label: "스트레스" },
  { key: "other", label: "기타" },
];
// 원인 확인. 카페인·감기 기운·약 복용은 메모라서 밤을 끝까지 설명하지 않는다.
const CAUSE_CHIPS = [
  { label: "음주", ctx: "alcohol" },
  { label: "카페인", note: "카페인" },
  { label: "운동", ctx: "exercise" },
  { label: "감기 기운", note: "감기 기운" },
  { label: "약 복용", note: "약 복용" },
  { label: "스트레스", ctx: "tense" },
  { label: "수면 부족", ctx: "sleep" },
];

function modeOf(s) {
  return (s && s.baseline && s.baseline.mode) || "early";
}

function serverNote(s) {
  if (!s) return "";
  return String(s.note || ((s.night || {}).note) || "").trim();
}

function shownNote(s) {
  if (!s) return "";
  const server = serverNote(s);
  if (server) return server;
  const n = s.night || {};
  if ((n.causes && n.causes.length) || n.explained_by) return "";
  return noteOf(s.today) || "";
}

function adoptServerNote(s) {
  if (!s || !s.today) return;
  const server = serverNote(s);
  if ((noteOf(s.today) || "") !== server) setDayNote(s.today, server);
}

function causeRecordLabel(key) {
  const chip = CAUSE_CHIPS.find((c) => c.ctx === key || (key === "sleep_debt" && (c.ctx === "sleep" || c.ctx === "sleep_debt")));
  if (chip && chip.label) return String(chip.label).split("/")[0].replace(/\s*\(.*\)\s*/g, "").trim();
  return { alcohol: "음주", exercise: "운동", tense: "스트레스", sleep_debt: "수면 부족" }[key] || "";
}

function recordText(note, causes, explainedBy, nothing) {
  const text = (note || "").trim();
  if (text) return text;
  const keys = [];
  if (explainedBy) keys.push(explainedBy);
  (causes || []).forEach((c) => { if (keys.indexOf(c) < 0) keys.push(c); });
  const labels = keys.map(causeRecordLabel).filter(Boolean);
  if (labels.length) return labels.join(" · ");
  if (nothing) {
    const chip = CAUSE_CHIPS.find((c) => c.nothing);
    return chip ? chip.label : "";
  }
  return "";
}

function todayRecord(s) {
  if (!s) return "";
  const n = s.night || {};
  const noted = serverNote(s) || ((n.causes && n.causes.length) || n.explained_by ? "" : (noteOf(s.today) || ""));
  return recordText(noted, n.causes, n.explained_by, n.nothing);
}

function dayRecord(d) {
  if (!d) return "";
  const server = String(d.note || "").trim();
  const noted = server || ((d.causes && d.causes.length) || d.explained_by ? "" : (noteOf(d.day) || ""));
  return recordText(noted, d.causes, d.explained_by, d.nothing);
}

const NOTE_FACE = { "카페인": "coffee", "감기 기운": "cold", "약 복용": "med" };
const CAUSE_FACE = { alcohol: "drink", exercise: "move", sleep_debt: "sleep", tense: "tense" };

function chosenFace(s) {
  if (!s || s.status === "ALERT") return "";
  const noteFace = NOTE_FACE[s.choice] || NOTE_FACE[shownNote(s)];
  if (noteFace) return noteFace;
  if (CAUSE_FACE[s.choice]) return CAUSE_FACE[s.choice];
  const n = s.night || {};
  if (CAUSE_FACE[n.explained_by]) return CAUSE_FACE[n.explained_by];
  const causes = n.causes || [];
  for (const key of ["alcohol", "exercise", "sleep_debt", "tense"]) {
    if (causes.indexOf(key) >= 0) return CAUSE_FACE[key];
  }
  return "";
}

function characterName(s) {
  const chosen = chosenFace(s);
  if (chosen) return chosen;
  if (!s) return "idle";
  if (s.status === "ALERT") return "alert";
  if (s.status === "WATCH") return "left";
  if (s.status === "ASK") return "ask";
  if (s.status === "EXPLAINED") return "calm";
  if (s.status === "CALM") return "calm";
  if (s.status === "NO_NIGHT") return "sleep";
  return "idle";
}

function causeBody(key) {
  if (key === "sleep_debt") key = "sleep";
  if (key === "alcohol" || key === "sleep" || key === "exercise" || key === "tense") {
    return { [key]: true, note: "" };
  }
  return null;
}

function askTitle(s) {
  const mode = modeOf(s);
  if (mode === "early") return "어떤 일이 있었나요?";
  if (mode === "adapting") return "최근과 다른 일이 있었나요?";
  return "평소와 다른 일이 있었나요?";
}

function causeChipsHtml() {
  return CAUSE_CHIPS.map((c) => {
    const attr = c.note ? ' data-note="' + c.note + '"'
      : ' data-ctx="' + c.ctx + '"';
    return "<button type=\"button\"" + attr + ">" + c.label + "</button>";
  }).join("");
}

const CAUSE_KO = { alcohol: "술", exercise: "운동", sleep_debt: "짧은 잠", tense: "긴장" };
const OVERLAP_KO = { alcohol: "음주", exercise: "운동", sleep_debt: "짧은 잠", tense: "긴장" };
const CONTEXT_ITEMS = [
  { key: "alcohol", label: "음주하셨나요?", short: "술", hint: "회식·술 기록과 심박이 겹치는지 확인해요" },
  { key: "sleep", label: "평소보다 늦게 잤나요?", short: "잠", hint: "늦은 취침·짧은 잠과 겹치는지 확인해요" },
  { key: "exercise", label: "평소보다 많이 움직였나요?", short: "운동", hint: "고강도 운동과 겹치는지 확인해요" },
  { key: "tense", label: "긴장되는 일이 있었나요?", short: "긴장", hint: "발표·시험 같은 일과 겹치는지 확인해요" },
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

function say(tone, title, short, body, track) {
  return { tone: tone, title: title, short: short, body: body, track: !!track };
}

function recordingVerdict() {
  return say("muted", "오늘부터 기록하고 있어요", "기록 중",
    "오늘 심박을 기준으로 봐요. 최근 안정 상태보다 높게 유지되면 이유를 물어볼게요.");
}

// 판정 → 화면 문구. 폰과 워치가 같은 말을 쓴다.
// 카페인·감기 기운·약 복용은 얼굴만 바꾸고, 남음 문구는 그대로 둔다.
function verdict(s) {
  const n = s.night || {};
  const st = s.status;
  const mode = modeOf(s);
  const run = (s.streak || {}).run || 0;
  const k = (s.streak || {}).k || 3;
  switch (st) {
    case "NO_DATA":
    case "RECORDING":
      return recordingVerdict();
    case "NO_NIGHT":
      if (mode === "personal") {
        return say("muted", "어젯밤이 아직 안 들어왔어요", "대기",
          "기록이 오면, 달라진 날에만 확인을 받아요.");
      }
      if (mode === "adapting") {
        return say("muted", "오늘 밤은 아직이에요", "대기",
          "들어오면 최근 같은 기록과 비교해요.");
      }
      return recordingVerdict();
    case "BASELINE":
      if (mode === "personal") {
        return say("muted", "평소를 만드는 중", "기준",
          "내 평소가 잡히기 전에는 달라졌다고 말하지 않아요.");
      }
      return recordingVerdict();
    case "CALM":
      if (mode === "early") {
        return say("calm", "오늘 기록은 안정적이에요", "안정",
          "최근 안정 상태와 비슷해요. 달라지면 이유를 물어볼게요.");
      }
      if (mode === "adapting") {
        return say("calm", "최근 같은 기록과 비슷해요", "비슷",
          "물어볼 일이 없어요. 몸이 달라진 날에만 다시 볼게요.");
      }
      return say("calm", "오늘은 평소와 같아요", "평소",
        "물어볼 일이 없어요. 몸이 달라진 날에만 다시 볼게요.");
    case "ASK":
      if (mode === "early") {
        return say("left", "심박 변화가 감지됐어요", "변화",
          "최근 안정 상태보다 심박이 높게 유지되고 있어요.");
      }
      if (mode === "adapting") {
        return say("left", "최근 같은 기록보다 심박이 높아요", "확인",
          "겹칠 수 있는 이유만 확인할게요.");
      }
      return say("left", "심박이 평소보다 높아요", "확인",
        "이미 잡힌 기록 중에서, 겹칠 수 있는 것만 물어볼게요.");
    case "EXPLAINED": {
      const why = OVERLAP_KO[n.explained_by] || n.explained_ko;
      return say("calm", "생활 기록과 겹칩니다", "설명됨",
        (why ? josa(why, "과", "와") + " 시점이 겹칩니다. 그 이유가 보통 만드는 크기 안이에요. " : "") +
          "원인을 단정하지 않고, 오늘은 알림을 내지 않아요.");
    }
    case "WATCH":
      if (mode === "early") {
        return say("left", "이유를 적어 두었어요", "기록됨",
          "오늘은 알림으로 올리지 않아요.");
      }
      if (mode === "adapting") {
        return say("left", "최근 같은 기록보다 심박이 높아요", "남음",
          "확인된 생활 원인으로 아직 설명이 안 돼요. 알림으로 올리진 않아요.");
      }
      return say("left", "아직 설명되지 않았어요", "남음",
        "확인된 생활 원인으로 설명되지 않는 변화가 " + run + "일째예요. " + k + "일이 되면 타임라인으로 남겨요.",
        true);
    case "ALERT":
      if (mode !== "personal") {
        return say("left", "최근 같은 기록보다 심박이 높아요", "남음",
          "확인된 생활 원인으로 아직 설명이 안 돼요. 알림으로 올리진 않아요.");
      }
      return say("alert", k + "일째 이유가 남지 않아요", k + "일째",
        "최근 " + k + "일간 평소와 다른 변화가 생활 기록으로 설명되지 않습니다. 병명을 정하지 않아요.",
        true);
    default:
      return say("muted", "", "", "");
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

function speechReady() {
  return !!(window.SpeechRecognition || window.webkitSpeechRecognition);
}

// 브라우저 음성 인식만 쓴다. 말한 내용은 서버로 보내지 않는다.
function listenKo(handlers) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return null;
  const h = handlers || {};
  let rec = null;
  let listening = false;
  const api = {
    get listening() { return listening; },
    stop() {
      listening = false;
      const cur = rec;
      rec = null;
      if (cur) {
        cur.onresult = null;
        cur.onerror = null;
        cur.onend = null;
        try { cur.stop(); } catch (e) { /* 이미 끝난 인식 */ }
      }
      if (h.onstate) h.onstate(false);
    },
    start(base) {
      if (listening) api.stop();
      const prefix = String(base || "").trim();
      const cur = new SR();
      rec = cur;
      cur.lang = "ko-KR";
      cur.interimResults = true;
      cur.continuous = false;
      cur.onresult = (ev) => {
        if (rec !== cur) return;
        let said = "";
        for (let i = 0; i < ev.results.length; i++) said += ev.results[i][0].transcript;
        said = said.trim();
        const next = prefix && said ? prefix + " " + said : (said || prefix);
        if (h.ontext) h.ontext(next);
      };
      cur.onerror = (ev) => {
        if (rec !== cur) return;
        listening = false;
        if (h.onstate) h.onstate(false);
        if (h.onerror) h.onerror((ev && ev.error) || "");
      };
      cur.onend = () => {
        if (rec !== cur) return;
        listening = false;
        rec = null;
        if (h.onstate) h.onstate(false);
      };
      try {
        cur.start();
        listening = true;
        if (h.onstate) h.onstate(true);
      } catch (e) {
        listening = false;
        rec = null;
        if (h.onstate) h.onstate(false);
        if (h.onerror) h.onerror("start");
      }
    },
  };
  return api;
}

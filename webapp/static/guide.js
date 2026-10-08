// 설명되지 않는 변화가 이어질 때 — 진료를 받도록 돕는 안내.
//
// !! 의료진 검토 전 초안이다 !!
// 진단하지 않는다. "이런 증상이 함께 있으면 이런 경우일 수 있으니 어디로 언제 가라" 까지만 말한다.
// 문구는 일반적인 건강 정보 수준으로 썼다. 서비스로 내기 전에 의료진 검토를 받을 것.
// 고칠 때는 이 파일만 고치면 폰 화면이 따라 바뀐다.
"use strict";

const GUIDE = {
  // urgent: 고르면 그때만 '바로 진료' 안내를 보여준다 (처음부터 겁주지 않는다)
  symptoms: [
    { key: "fever", label: "열 · 오한" },
    { key: "cough", label: "기침 · 목 아픔 · 콧물" },
    { key: "ache", label: "몸살 · 근육통" },
    { key: "fatigue", label: "심한 피로 · 무기력" },
    { key: "dizzy", label: "어지러움 · 일어설 때 핑 돎" },
    { key: "breath", label: "조금만 움직여도 숨참" },
    { key: "palpit", label: "가만히 있어도 두근거림" },
    { key: "gut", label: "구토 · 설사 · 소변이 줄어듦" },
    { key: "pale", label: "얼굴·손톱이 창백해 보임" },
    { key: "weight", label: "체중 감소 · 더위 탐 · 손 떨림" },
    { key: "urine", label: "소변 볼 때 아프거나 자주 마려움" },
    { key: "chest", label: "가슴이 아프거나 조임", urgent: true },
    { key: "rest_breath", label: "가만히 있어도 숨이 참", urgent: true },
    { key: "faint", label: "쓰러질 것 같음 · 정신이 흐림", urgent: true },
  ],

  urgent: {
    title: "이 증상은 오늘 바로 진료가 필요해요",
    body: "기다리지 않는 게 좋아요. 가까운 응급실로 가 주세요. 혼자 움직이기 어렵다면 119에 도움을 요청하세요.",
  },

  // level: 3 오늘 진료 · 2 1–2일 안에 · 1 며칠 안에 · 0 지켜보기
  // signals: 기기가 본 변화 — hr(밤 심박 상승) · red(안색 붉어짐) · pale(안색 창백)
  conditions: [
    {
      id: "resp", name: "감기 · 독감 · 코로나19 같은 호흡기 감염",
      symptoms: ["fever", "cough", "ache", "fatigue"], signals: ["hr", "red"],
      note: "증상이 나타나기 하루이틀 전부터 잠잘 때 심박이 오르는 경우가 연구로 보고됐어요.",
      check: "열이 나는지, 주변에 아픈 사람이 있었는지 확인해 보세요. 자가검사 키트가 있으면 해보세요.",
      where: "내과 · 가정의학과", level: 2,
      escalate: { when: ["breath"], level: 3, text: "숨이 차다면 오늘 진료를 받으세요." },
    },
    {
      id: "dehyd", name: "탈수",
      symptoms: ["gut", "dizzy", "fatigue"], signals: ["hr", "pale"],
      note: "몸에 물이 부족하면 심장이 더 빨리 뛰어 혈액량을 메워요.",
      check: "물이나 이온음료를 조금씩 자주 마셔 보세요.",
      where: "내과 · 가정의학과", level: 1,
      escalate: { when: ["gut", "dizzy"], level: 3, text: "토해서 마시지 못하거나 소변이 거의 안 나오면 오늘 진료를 받으세요." },
    },
    {
      id: "anemia", name: "빈혈",
      symptoms: ["pale", "fatigue", "dizzy", "breath"], signals: ["hr", "pale"],
      note: "피가 산소를 덜 나르면 심장이 더 자주 뛰어 메워요. 얼굴이 창백해 보일 수 있어요.",
      check: "생리량이 늘었거나 변이 검게 나온 적이 있는지 떠올려 보세요.",
      where: "내과 (혈액검사)", level: 1,
    },
    {
      id: "thyroid", name: "갑상선 기능 항진",
      symptoms: ["weight", "palpit", "fatigue"], signals: ["hr"],
      note: "갑상선 호르몬이 많으면 쉬고 있어도 심박이 높게 유지돼요.",
      check: "최근 체중 변화와 땀·더위를 유난히 타는지 확인해 보세요.",
      where: "내과 · 내분비내과 (혈액검사)", level: 1,
    },
    {
      id: "rhythm", name: "심장 리듬 문제 (부정맥 등)",
      symptoms: ["palpit", "dizzy", "breath", "chest", "faint"], signals: ["hr"],
      note: "가만히 있는데 두근거리거나 맥이 불규칙하게 느껴질 수 있어요.",
      check: "두근거릴 때 손목 맥을 30초 세어 보고, 시각과 함께 적어 두세요.",
      where: "내과 · 순환기내과 (심전도)", level: 3,
    },
    {
      id: "uti", name: "호흡기 말고 다른 곳의 염증 (요로감염 등)",
      symptoms: ["fever", "urine", "fatigue"], signals: ["hr", "red"],
      note: "몸 어딘가에 염증이 있으면 열과 함께 심박이 오를 수 있어요.",
      check: "열이 나는데 기침이 없다면 다른 곳의 증상을 살펴보세요.",
      where: "내과 · 비뇨의학과", level: 2,
    },
    {
      id: "strain", name: "과로 · 수면 부족 · 스트레스가 쌓인 상태",
      symptoms: ["fatigue"], signals: ["hr"],
      note: "기록하지 않은 생활 변화가 며칠 겹쳐도 밤 심박이 오를 수 있어요.",
      check: "2–3일 일찍 자고 무리를 줄여 보세요. 그래도 이어지면 진료를 받아 보세요.",
      where: "가까운 내과 · 가정의학과", level: 0,
    },
  ],

  levels: {
    3: { label: "오늘 진료를 받으세요", tone: "alert" },
    2: { label: "1–2일 안에 진료를 받아 보세요", tone: "left" },
    1: { label: "며칠 안에 진료를 받아 보세요", tone: "left" },
    0: { label: "며칠 더 지켜봐요", tone: "calm" },
  },

  // 화면 맨 아래 작은 글씨로만
  contacts: [
    { label: "119", sub: "응급", href: "tel:119" },
    { label: "1339", sub: "감염병 상담", href: "tel:1339" },
  ],

  disclaimer: "진단이 아니에요. 기기가 본 변화와 지금 증상을 맞춰 진료를 빨리 받도록 돕는 안내예요. " +
    "이 안내는 의료진 검토 전 초안이에요.",
};

// 고른 증상 + 기기가 본 변화 → 가능성 순으로 정렬한 목록
function matchGuide(selected, signals) {
  const sel = new Set(selected);
  const out = [];
  for (const c of GUIDE.conditions) {
    const hitS = c.symptoms.filter((k) => sel.has(k));
    const hitG = c.signals.filter((k) => signals.has(k));
    if (!hitS.length && c.id !== "strain") continue;
    let level = c.level;
    let extra = "";
    if (c.escalate && c.escalate.when.some((k) => sel.has(k))) { level = Math.max(level, c.escalate.level); extra = c.escalate.text; }
    const score = hitS.length * 2 + hitG.length + (hitS.length / c.symptoms.length);
    out.push({ ...c, hitS, hitG, level, extra, score });
  }
  out.sort((a, b) => b.score - a.score);
  // 증상이 없거나 어디에도 안 맞으면 '과로·수면 부족' 하나만 보여준다
  const strain = out.filter((c) => c.id === "strain");
  const matched = out.filter((c) => c.id !== "strain");
  return sel.size && matched.length ? matched : strain;
}

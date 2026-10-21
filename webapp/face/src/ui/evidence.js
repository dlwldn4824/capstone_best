// 지표 상세 시트의 설명 · 연구 결과 · 출처. 출처는 2026-10-20 에 직접 열어 확인한 것만 넣었다.
export const EVIDENCE = {
  hr: {
    title: '심박',
    how: '이마와 양 볼의 피부색이 맥박마다 아주 조금 바뀌는 것을 읽어요 (rPPG · POS).',
    lit: '같은 방식(POS)의 평균 오차는 공개 데이터에서 3.7–4.5 bpm, 휴대폰으로 찍은 데이터에서 12.4 bpm이었어요. 피부가 어둡거나, 걷거나, 자연광일 때 오차가 커졌어요.',
    src: [
      { label: 'rPPG-Toolbox 벤치마크 (Liu 외, NeurIPS 2023)', url: 'https://arxiv.org/html/2210.00716v3' },
      { label: 'MMPD 휴대폰 데이터셋 (Tang 외, EMBC 2023)', url: 'https://arxiv.org/html/2302.03840' },
    ],
  },
  hrv: {
    title: '박동 간격 흔들림',
    how: '맥파에서 박동을 하나씩 찾아, 이웃한 간격이 얼마나 달라지는지 계산해요 (RMSSD).',
    lit: '심전도로 잴 때는 30초 RMSSD가 5분 값과 거의 같았어요(r 0.93). 카메라로 찾은 박동 간격에는 20ms 안팎의 오차가 있어서 참고로만 봐 주세요.',
    src: [
      { label: '초단기 HRV (Munoz 외, PLoS One 2015)', url: 'https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0138921' },
      { label: 'HRV 지표 개요 (Shaffer & Ginsberg, 2017)', url: 'https://www.frontiersin.org/articles/10.3389/fpubh.2017.00258/full' },
      { label: '웹캠 박동 간격 (Melchor Rodríguez 외, 2018)', url: 'https://europepmc.org/article/MED/29378598' },
    ],
  },
  resp: {
    title: '호흡',
    how: '숨 쉴 때 머리가 오르내리는 주기와 얼굴 밝기가 바뀌는 주기가 맞을 때만 보여 드려요.',
    lit: '카메라 호흡 측정 비교 연구에서 가장 좋은 방법도 실제 호흡과의 상관이 0.66이었어요. 참고로만 봐 주세요.',
    src: [
      { label: '카메라 호흡 측정 벤치마크 (ACM Computing Surveys, 2025)', url: 'https://dl.acm.org/doi/full/10.1145/3771763' },
      { label: 'PPG 호흡 추정 Smart Fusion (Karlen 외, 2013)', url: 'https://ieeexplore.ieee.org/document/6458992' },
    ],
  },
  blink: {
    title: '눈 깜빡임',
    how: '눈 감김 정도가 절반을 넘었다가 다시 뜬 횟수를 세요 (MediaPipe 얼굴 표정 값).',
    lit: '쉬고 있는 성인 100명의 깜빡임은 분당 3–48회로 사람마다 크게 달랐어요(평균 13.8회). 횟수만으로 상태를 말할 수는 없어요.',
    src: [
      { label: '졸음 지표 리뷰 (Abe, 2023)', url: 'https://europepmc.org/article/PMC/PMC10108649' },
      { label: 'MediaPipe Face Landmarker', url: 'https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker' },
    ],
  },
  head: {
    title: '머리 흔들림',
    how: '코끝 위치가 흔들린 정도를 얼굴 폭에 대한 비율로 나타내요. 크면 심박 값도 흔들려요.',
    lit: '',
    src: [],
  },
};

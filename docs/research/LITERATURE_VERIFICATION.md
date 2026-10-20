# 선행연구 수치 검증

계획 문서에 적힌 논문·데이터·수치를 원문/출판사 페이지와 대조한 결과.
검증일 2026-09-05.

범례 — **확인**: 원문 또는 출판사 페이지에서 직접 확인 · **미확인**: 논문은
존재하나 해당 수치를 확인하지 못함 · **찾지 못함**: 논문 자체를 찾지 못함

---

## 요약

| 논문 | 존재 | 인용 수치 | 조치 |
| --- | --- | --- | --- |
| Mishra 2020 (Nat Biomed Eng) | 확인 | 대부분 확인 | 그대로 사용 |
| Quer 2021 (Nat Med) | 확인 | 정확히 일치 | 그대로 사용 |
| Hongn 2025 (Sci Data) | 확인 | 확인 + **중요한 누락 발견** | 아래 참조 |
| Gabrielli (AIiM) | 확인 | F1 수치 미확인 | 원문 확인 후 인용 |
| **Li 2026 (Sensors)** | **찾지 못함** | — | **인용 보류** |
| Ibrahim 2026 (Sci Rep) | 확인 | AUC 미확인 | 원문 확인 후 인용 |
| Kim 2026 (IEEE TCE) | 확인 | 94.8% 미확인 | 원문 확인 후 인용 |
| Norman 2026 (Auton Neurosci) | 확인 | 정성 주장만 | 그대로 사용 |

---

## 1. Mishra et al. 2020 — 확인

*Pre-symptomatic detection of COVID-19 from smartwatch data*,
Nature Biomedical Engineering **4**, 1208–1220 (2020). PMID 33208926.

| 계획 문서 | 검증 결과 |
| --- | --- |
| 코호트 약 5,262명 | 확인 ("nearly 5,300") |
| COVID 감염자 32명 | 확인 |
| 26/32 (81%) 에서 변화 탐지 | 확인 |
| 25명 중 22명이 증상 발생 전/당일 | 확인 |
| 4명은 최소 9일 전 | 확인 |
| 실시간 알고리즘으로 63% 사전 탐지 | **미확인** — 원문 재확인 필요 |

## 2. Quer et al. 2021 — 확인

*Wearable sensor data and self-reported symptoms for COVID-19 detection*,
Nature Medicine (2021). PMID 33122860.

| 계획 문서 | 검증 결과 |
| --- | --- |
| 30,529명 등록 | 확인 (2020-03-25–06-07) |
| 3,811명 증상 보고 | 확인 |
| 양성 54 / 음성 279 | 확인 |
| 센서+증상 AUC 0.80 | 확인 (**IQR 0.73–0.86** — 이 구간도 함께 인용할 것) |
| 개별 AUC 0.52/0.68/0.69/0.72/0.71 | 미확인 — 표에서 재확인 |

## 3. Hongn et al. 2025 — 확인 + 계획 문서에 누락된 사항

*Wearable Physiological Signals under Acute Stress and Exercise Conditions*,
Scientific Data **12** (2025). PMID 40155406 / PMC11953403.
데이터: PhysioNet `wearable-device-dataset` v1.0.1 (Open Access,
압축 69.7 MB / 해제 247.4 MB).

확인된 것: 36 / 30 / 31명, Empatica E4, 49 feature (BVP 2 · HR 4 · HRV 20 ·
EDA 13 · ACC 10), 축소 feature 13 / 12 / 19개, XGBoost 93% / 91% / 84%,
80/20 split + 10-fold CV.

### 계획 문서가 놓친 것 (파이프라인에 직접 영향)

1. **프로토콜이 두 버전이다.**
   - v1 (S 코호트): 3분 baseline → Stroop → 5분 휴식 → TMCT → 5분 휴식 →
     Opinion → 1022에서 13씩 빼기
   - v2 (f 코호트): **Stroop 제거**, 두 번째 휴식을 Opinion 과 Subtract 사이로
     이동, 휴식에 이완 영상 추가, 원격 수행

   운동 프로토콜도 v1/v2 가 다르다 (Anaerobic: v1 = 30초 스프린트 3회 /
   v2 = 45초 4회). **하나의 태그 매핑으로 전체를 처리할 수 없다.**
   → `configs/protocol.yaml` 이 `version_by_prefix` 로 이를 처리한다.

2. **제외 대상 피험자.** 원 논문이 분류 실험에서 뺀 것은
   `f07`(손목밴드 보호 커버 미제거), `f13`(착용 불량) 두 명이다.
   → `configs/config.yaml` 의 `exclude.ml_excluded_subjects`.

3. **품질 이슈가 기록된 세션** (`data_constraints.txt`): S02 스트레스 중복,
   f14 스트레스 2분할, S03·S07 유산소 불완전, S11 유산소 2분할,
   S12 유산소 없음, S06 무산소 불완전, S16 무산소 2분할.
   → `exclude.flagged` 로 표시만 하고 제외하지는 않는다.

4. **세그먼트 선택 규칙.** 휴식 블록은 **후반부만**(잔여 스트레스 배제),
   유산소는 70·75·80·85 rpm 블록의 **중앙 1분**, 스프린트는 전체.
   → `protocol.yaml` 의 `portions` 필드.

5. **축소 feature 목록** (재현 시 그대로 쓸 것)
   - Stress/Rest 13개: `hr_mean, mean_raw_eda, mean_tonic_eda, std_tonic_eda,
     mean_recoverytime, max_ibi, ibi_mean, rmssd, ratio, LF_peak, x_std,
     y_std, z_std`
   - Aerobic/Sprint 12개: `hr_std, std_phasic_eda, tonic_ratio_down,
     peaks_density, mean_recoverytime, min_ibi, pnn50, VHF_power, LF_n,
     z_std, acc_mean, acc_ratio_down`
   - 4-class 19개: 위 둘의 합집합
   - 선택 방법: Pearson r > 0.8 상관 제거 + Sweetviz 탐색

6. **원 논문은 피험자를 분리하지 않았다.** 80/20 + 10-fold 라고만 되어 있고
   LOSO 라는 언급이 없다. 93% 를 우리 subject-independent 수치와 직접
   비교하면 안 된다.

## 4. Gabrielli et al. — 논문 확인, 수치 미확인

*Seamless Monitoring of Stress Levels Leveraging a Foundational Model for
Time Sequences*. Gabrielli, Prenkaj, Velardi (Sapienza / TU München).
arXiv:2407.03821, Artificial Intelligence in Medicine.

확인: DREAMER / MAHNOB-HCI / WESAD 세 벤치마크, UniTS 파인튜닝,
anomaly detection 으로 문제 정식화, "12개 최고 성능 방법을 상회",
침습적 신호와 경량 기기 신호에서 성능이 비슷함.

**미확인**: F1 0.869 / 0.878 / 0.834 / 0.856, 평균 0.859 ± 0.019,
피험자 수 23 / 27 / 15. → arXiv PDF 본문 표에서 직접 확인하고 인용할 것.

## 5. Li et al. 2026 (Sensors) — 찾지 못함 ⚠

*Neuro-Symbolic Class-Contrast Evidence Audit for Reliable Cross-Subject
Wearable Activity Recognition*.

제목·저자·지표(UCI HAR Accuracy 90.13%, Macro F1 90.55%, Error AUPRC
0.4238 → 0.4331)로 세 차례 검색했으나 해당 논문을 찾지 못했다.
MDPI Sensors 에서도 확인되지 않는다.

**조치**
- 이 인용은 **보류**한다. DOI 를 확보하기 전까지 발표 자료에 넣지 않는다.
- 우리 audit 구조의 근거로는 검색에서 확인된 다음을 대신 쓸 수 있다.
  - *Neuro-Symbolic Approaches for Context-Aware Human Activity Recognition*
    (arXiv:2306.05058) — semantic loss 로 context 지식을 HAR 분류기에 주입
  - *Semantic Loss: A New Neuro-Symbolic Approach for Context-Aware HAR*,
    Proc. ACM IMWUT 7(4), 2023 — 위의 저널 버전
- 다만 이 대체 논문들은 **분류 시점에 symbolic reasoning 을 쓰지 않고**
  학습 손실에 지식을 넣는 방식이라 우리 audit 구조와 다르다. 근거로 쓰려면
  차이를 명시해야 한다.

> **원 출처를 어디서 얻었는지 확인할 것.** 존재하지 않는 논문을 인용하면
> 심사에서 가장 먼저 지적된다.

## 6. Ibrahim 2026 — 논문 확인, 수치 미확인

*A causal discovery framework for digital phenotyping*,
Scientific Reports (2026), DOI `10.1038/s41598-026-55866-2`.

**미확인**: handcrafted AUC 0.497 / F1 0.438, deep embedding 최고 AUC 0.532.
StudentLife 참가자 수는 자료에 따라 48명 / 49명으로 갈린다 (원 StudentLife
논문은 48명 완료). 인용 시 원문 수치를 따를 것.

## 7. Kim et al. 2026 — 논문 확인, 수치 미확인

*Edge Neuro-Symbolic AI Framework for Privacy-Preserving Real-Time Health
Analytics in Consumer Wearable Devices*, IEEE Transactions on Consumer
Electronics (2026). IEEE Xplore 문서번호 11305223.

초록으로 확인: federated learning + 동형암호 + symbolic reasoning,
ECG / PPG / 가속도 다중모달, 자원 제약 웨어러블 대상.
**미확인**: anomaly detection accuracy 94.8%, 암호화 지연 약 35 ms.
공개 full text 가 없으므로 학교 IEEE 구독으로 확보할 것.

## 8. Norman et al. 2026 — 확인

*Wearable ANS monitoring in real life: A critical review of context-sensitive
interpretation and implications for psychophysiology*, Autonomic Neuroscience
(2026). ScienceDirect PII `S1566070225001262`.

제목이 계획 문서와 정확히 일치한다. 정성적 주장(생리신호는 맥락 의존적이며
단독 해석하면 안 된다)이 우리 연구동기의 근거이므로 정량 수치는 필요 없다.

---

## 데이터셋 접근 조건

| 데이터 | 접근 | 규모 | 비고 |
| --- | --- | --- | --- |
| Stress & Exercise (PhysioNet) | Open | 69.7 MB zip / 247.4 MB | 지금 바로 |
| WESAD (UCI) | Open | 15명 | 지금 바로 |
| ScientISST MOVE (PhysioNet) | Open | 17명 | 지금 바로 |
| **CovIdentify (PhysioNet)** | **Credentialed** | 2,887명 | **지금 신청할 것** |
| UCI HAR | Open | 30명 | 보조 |
| StudentLife | Open | 48명 | 보조 |

CovIdentify 는 PhysioNet credentialed 계정 + CITI 교육 이수 + DUA 서명이
필요하고 승인까지 수 주가 걸린다. Phase 8 은 2주 계획 밖이지만 **신청은
다른 작업과 무관하게 지금 넣어야** 나중에 병목이 되지 않는다.


---

## 추가 조사 (2026-09-05) — 계획서에 없던 선행연구

계획서 작성 후 문헌 검색에서 나온 것들. **두 편은 우리 연구와 거의 겹친다.**

### ⚠ Shahriar 2025 — 우리 1주차와 거의 동일

*Multimodal Physiological Signal Classification from Wearables: Towards
Interpretable Stress and Exercise Recognition*, IEEE SPICSCON 2025.

| | Shahriar | 우리 |
| --- | --- | --- |
| 기기 | Empatica E4 | 동일 |
| 과제 | 스트레스 vs 운동 | 동일 |
| 신호 | EDA, HR/HRV, TEMP, ACC | 동일(TEMP 제외) |
| 창 | 30초 / 15초 겹침 | 60초 / 30초 |
| 최고 모델 | XGBoost 96.1% ± 0.4% | XGBoost |
| Ablation | **ACC 가 최강 기여** | 동일 |
| LOSO | **72% ± 15%** | group_kfold 79.5% |
| 해석 | SHAP / LIME / saliency | Symbolic audit |

**데이터셋 명시는 미확인이나 Hongn 2025 일 가능성이 매우 높다.** E4 로 스트레스 +
유산소 + 무산소를 모두 담은 공개 데이터는 사실상 그것뿐이다.

**시사점.** 우리 1주차 전체(전처리 → feature → XGBoost → ablation → LOSO)는 이미
출판된 것과 같다. "ACC 가 결정적", "개인차가 문제"라는 결론까지 동일하다.
차별점을 다음과 같이 재정의해야 한다.

| | Shahriar | 우리 |
| --- | --- | --- |
| 해석 시점 | 사후 (SHAP) | 사전 지식 (규칙) |
| 모르는 상황 | 반드시 답해야 함 | **기권 가능(UNEXPLAINED)** |
| 개인차 | 문제로 지적만 | 개인 baseline 으로 대응 |
| 맥락 은닉 실험 | 없음 | 있음 |

SHAP 은 "모델이 왜 그렇게 답했는가" 를 설명하지만 **틀린 답도 설명한다.**
우리 audit 은 "이 답을 믿을 근거가 있는가" 를 판정하고 없으면 모른다고 답한다.

**조치: 전문 확보 필수.** 모르고 발표하면 첫 질문이 "이미 있는 연구 아닌가" 다.

### ⚠ Sevil 2021 — 가장 직접적인 선행연구

*Discrimination of simultaneous psychological and physical stressors using
wristband biosignals*, Computer Methods and Programs in Biomedicine.

심리 스트레스(APS)와 신체활동(PA)을 **동시 발생 상황에서** 구분. 117시간.
PA 99% / APS 92%.

| 활동 상태 | APS 탐지 정확도 |
| --- | --- |
| 좌식 | 97.3% |
| 러닝 | 94.1% |
| **자전거** | **84.5%** |

**우리 데이터가 자전거다. 84.5% 가 벤치마크가 된다.**
데이터 공개 여부는 확인되지 않음(저자 연락 필요).

### 우리 결과를 뒷받침하는 논문

**Kaya 2026** (arXiv), *Differentiating Physical and Psychological Stress Using
Wearable Physiological Signals and Salivary Cortisol* — 웨어러블만으로는 심리
스트레스와 휴식/회복 구분이 어렵다(심리 스트레스 recall 50.0%, 회복 54.2%).
타액 코르티솔 추가 시 77.8% → 94.4%.

**우리가 찾은 것과 같은 결론이다** (오류의 85% 가 휴식↔스트레스). 다른 팀, 다른
데이터에서 같은 결과가 나왔다는 것은 우리 수치가 파이프라인 결함이 아니라는
독립적 근거다. 단 n=6 으로 매우 작으므로 인용 시 명시할 것.

### 연구 동기에 인용할 논문

- **Goodday & Friend 2019**, npj Digital Medicine — 스트레스 징후가 질병으로
  전이되는 과정을 웨어러블+AI 로 예측하는 프레임워크. 우리 Phase 7-8 의 개념적 근거.
- **Ryan 2024**, Frontiers in Network Physiology — Oura Ring COVID 양성 73명.
  감염이 "정형화된 이탈" 을 일으킨다는 가정을 반박하고 발현 유형을 지도화.
  우리 "설명되지 않는 변화" 와 개념이 가장 가깝다.

### 비교 대상이 아닌 논문

Xu 2024 (Nature Electronics, e-skin + 땀 분자), Pei 2026 (Nat Commun, SQC-SAS),
Chu 2025 (ACS Nano, 코르티솔), McNaboe 2022, Marchi 2024 는 모두 **자체 제작
하드웨어**로 땀 분자나 코르티솔을 직접 측정한다. 98% 같은 수치가 눈에 띄지만
손목 PPG/EDA 와는 정보량이 달라 비교 대상이 아니며 공개 데이터도 없다.

다만 한 가지는 쓸 수 있다 — **"손목 생체신호만으로는 부족하다"** 가 이 분야의
공통 인식임을 보여준다. 우리 한계 서술의 근거가 된다.

Jambhale 2022 의 "RespiBAN 15명" 은 **WESAD** 다. 새 데이터가 아니다.

### 공개 데이터 관점 결론

조사한 12편 중 **새로 쓸 수 있는 공개 데이터는 없다.** 대부분 자체 하드웨어이거나
미공개다. 실환경 개인 baseline 검증에는 여전히 Nurse Stress Dataset(CC-BY,
즉시 다운로드)이 최선이다.


---

## 원문 확보 후 정밀 대조 (2026-09-05)

### Shahriar 2025 — **같은 데이터셋이지만 다른 문제를 푼다**

원문 참고문헌 [18] 이 `A. Hongn et al., PhysioNet, 2025, doi:10.13026/he0v-tf17`
로 **우리와 동일한 데이터셋임이 확인됐다.** 그러나 라벨 설계가 근본적으로 다르다.

> "For each subject i, the dataset yields a multivariate time series ...
> with corresponding **protocol label** y_i ∈ {S, A, An}"

**세션 단위 라벨이다.** 스트레스 세션의 모든 윈도가 `S` 로 라벨된다 — 3분 baseline 과
두 번의 5분 휴식 블록까지 포함해서. **REST 클래스가 존재하지 않는다.**

즉 그들이 실제로 푸는 문제는 "지금 어떤 상태인가" 가 아니라
**"이 윈도가 어느 세션에서 녹화됐는가"** 다.

| | Shahriar 2025 | 우리 |
| --- | --- | --- |
| 데이터 | Hongn PhysioNet v1.0.1 | 동일 |
| 라벨 | 세션 단위 {S, A, An} | 구간 단위 {REST, STRESS, EXERCISE} |
| 라벨 출처 | 폴더 이름 | `tags.csv` 프로토콜 블록 |
| 휴식 블록 | **STRESS 로 라벨** | 별도 REST 클래스 |
| feature | 16개 | 51개 (원 논문 49 재현) |
| 윈도 | 30초 / 15초 | 60초 / 30초 |
| 표준화 | 피험자별 (세션 혼합) | 피험자·세션별 (드리프트 회피) |
| 임계/스케일링 | 전체 데이터 기준 | fold train 에서만 |
| 정확도 | 96.1% / LOSO 72%±15% | group_kfold 79.5% / LOSO 80.8% |

**수치를 직접 비교하면 안 된다.** 96.1% 는 세션 식별 과제의 값이고 우리 79.5% 는
상태 식별 과제의 값이다. 후자가 훨씬 어렵다. 다만 한 가지는 기록해 둘 만하다 —
**LOSO 에서 그들의 쉬운 과제는 72% 로 떨어지는데 우리의 어려운 과제는 80.8% 를
유지한다.** 피험자별 표준화를 세션 혼합으로 한 것이 LOSO 에서 무너진 것으로 보인다.

#### 원문에서 확인된 사실 오류 두 건

1. **"43 subjects (19 male, 17 female, remainder unspecified)"**
   실제 데이터셋은 **36명**이다. 19 + 17 = 36 으로 성별 합은 맞는데 총계가 43 이다.
   `subject-info.csv` 는 데이터 행 뒤에 범례가 붙어 있어 그대로 읽으면 46행이 된다
   (우리도 처음에 46 이 나왔다). 이 파일을 걸러내지 않고 센 것으로 보인다.

2. **운동 프로토콜 서술이 실제와 다르다.**
   > "Aerobic exercise (A): **treadmill-based** endurance activity"
   > "Anaerobic exercise (An): short-burst high-intensity activities involving
   > **weight-lifting and resistance exercises**"

   실제는 **둘 다 고정식 자전거**다. 유산소는 Storer-Davis 자전거 프로토콜
   (60→110 rpm), 무산소는 Wingate 자전거 스프린트다. 트레드밀도 웨이트도 없다.
   `tags.csv` 나 원 논문 프로토콜을 확인하지 않은 것으로 보인다.

#### 우리 연구의 위치

겹치지 않는다. 오히려 **같은 데이터에서 더 정확한 라벨링과 더 엄격한 평가를 한
것 자체가 기여**가 된다. 발표에서는 다음을 명시할 것.

- 우리는 `tags.csv` 로 프로토콜 블록을 분할해 휴식과 과제를 구분한다
- 세션 간 기준선 드리프트(HR 19.4 bpm / EDA 2.01 uS)를 측정하고 회피한다
- 임계는 fold train 에서만 정한다
- Symbolic 층은 사후 설명(SHAP)이 아니라 **기권 가능한 사전 지식**이다

### Sevil 2021 — 설계 면에서 배울 점이 있다

Illinois Institute of Technology, Cinar 그룹. **34명 / 166회 실험 / 117시간**,
Empatica E4 (ACC, BVP, GSR, ST, HR) — 우리와 같은 기기다.

핵심은 **라벨이 2차원**이라는 점이다.

```
신체활동 PA  : 좌식(SS) / 트레드밀(TR) / 자전거(SB)
심리스트레스 APS: 비스트레스(NS) / 정신스트레스(MS) / 정서불안(EAS)
```

**둘을 배타적 클래스로 두지 않고 직교하는 두 축으로 둔다.** 그리고 운동 *중에*
스트레스를 유발해 동시 발생 상황을 실제로 만든다.

| 활동 상태 | APS 탐지 정확도 |
| --- | --- |
| 좌식 | 97.3% |
| 트레드밀 | 94.1% |
| **자전거** | **84.5%** |

동기는 당뇨 자동 인슐린 주입의 실시간 관리다. STAI 설문으로 유발 효과를 검증했다.

**우리에게 주는 시사점.** 우리 3분류(REST / STRESS / EXERCISE)는 세 상태가
배타적이라고 가정한다. 실제로는 "운동하면서 스트레스 받는" 상태가 존재하고
Sevil 은 그것을 실험 설계에 반영했다. **Hongn 데이터에는 동시 발생 조건이 없으므로
우리는 이 축을 검증할 수 없다.** 이것은 데이터의 한계로 명시해야 하며, Sevil 을
근거로 인용할 수 있다.

자전거에서 84.5% 로 가장 낮다는 점도 기록해 둔다. 우리 데이터가 자전거다.

데이터는 자체 수집이며 공개되지 않았다.

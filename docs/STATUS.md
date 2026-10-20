# 개발 현황 — 기준: Vity 체크 (`/check`) · 2026-10-20

```bash
python webapp/fetch_vendor.py      # 얼굴 메시(MediaPipe) 로컬에 한 번 받기 (없으면 CDN)
python webapp/server.py            # http://localhost:8000/check
python webapp/server.py --https    # 폰 카메라는 https 에서만 열린다 → https://<PC IP>:8000/check
python -m pytest -q                # 139개
```

지금 서비스의 중심은 **Vity 체크**다. 30초 얼굴 스캔으로 심박 · HRV · 스트레스 지수를 재고, 오늘의 공부 방식을 추천하고,
스터디 친구들과 기상 · 공부 시작 인증을 한다. 같은 서버의 `/` 거울 기록(루틴별 15초 · 이유 묻기 · 시험기간 리포트)은
설정에서 서로 열 수 있게만 이어져 있다. `/v1` · `/watch` 는 초기 워치 버전으로 남아 있다.

화면 캡처 전체: [`docs/check/screens/`](check/screens/) (390×844, 2배율. 스캔 화면은 카메라 대신 MediaPipe 표준 얼굴 메시를 그려 넣었다)

## 화면별 상태

✅ 웹에 구현 · 브라우저에서 확인 / 🟡 구현했지만 실기기(폰 카메라)로 끝까지 확인 안 함 / ⬜ 아직 없음

| 화면 | 기능 | 상태 | 캡처 |
| --- | --- | --- | --- |
| 인트로 | 캐릭터 컷씬 5단계: 반가워요 → 이름 → 30초 측정 방법 → 그룹 참여 · 만들기 · 혼자 → 약속 · 동의(개인정보보호법 제23조) | ✅ | [1](check/screens/01_intro_1_hello.png) [2](check/screens/02_intro_2_name.png) [3](check/screens/03_intro_3_howto.png) [4](check/screens/04_intro_4_group.png) [5](check/screens/05_intro_5_consent.png) |
| 홈 | 파란 영역(한 줄 요약 · 상태별 캐릭터) + 오늘 / 이번 주 / 내 평소 탭 + 그룹 카드(급한 순) + 공부 모드 | ✅ | [오늘](check/screens/06_home_today.png) [전체](check/screens/07_home_full.png) [이번 주](check/screens/08_home_week.png) [내 평소](check/screens/09_home_baseline.png) |
| 도움말 | 컨디션 · 심박 · 스트레스 · HRV · 호흡 · 리듬 · BMI · 공부 모드 · 신호 · 인증 옆 "?" 말풍선 | ✅ | [보기](check/screens/10_home_help_bubble.png) |
| 측정 전 질문 | 어젯밤 수면 · 커피 잔 수 · 기분 (지난 답 기억) | ✅ | [보기](check/screens/11_pre_questions.png) |
| 30초 스캔 | MediaPipe 478점 메시 · 이마 · 양 볼 측정 영역 · 자동 시작 · 실시간 맥파 · 심박 · 4단계 진행 · 품질 판정 | 🟡 | [준비](check/screens/12_scan_ready.png) [측정 중](check/screens/13_scan_measuring.png) |
| 결과 | 그룹별 인증 줄 · 종합 점수(계산식 공개) · 지표 6개 · 공부 모드 · 추천 최대 3개 | ✅ | [위](check/screens/14_result_top.png) [전체](check/screens/14_result_full.png) |
| 다시 재기 | 얼굴 · 밝기 · 움직임 · 신호 이유별 안내 | ✅ | [보기](check/screens/18_retry.png) |
| 1분 호흡 → 재측정 | 4초 들숨 · 6초 날숨 × 6 → 다시 재서 전후 비교 카드 | ✅ | [호흡](check/screens/16_breathing.png) [전후 비교](check/screens/15_breath_compare_full.png) |
| 공부 타이머 | 공부 모드의 집중 · 휴식 분 반복 · 전환 진동 · 일시정지 | ✅ | [보기](check/screens/17_study_timer.png) |
| 그룹 | 목록(최대 5개) · 상세(멤버 인증 시각 · 연속 일수) · 초대 코드 공유 · 그룹별 나가기 · 코드로 참여 | ✅ | [목록](check/screens/19_group_list.png) [상세](check/screens/20_group_detail.png) |
| 그룹 만들기 | 이름 · 캐릭터 → 인증 시간대 → 규칙 · 내 이름 → 등록 완료 | ✅ | [1](check/screens/21_group_make_1_name.png) [2](check/screens/22_group_make_2_time.png) [3](check/screens/23_group_make_3_rule.png) [완료](check/screens/24_group_make_done.png) |
| 기록 | 날짜별 점수 · 심박 · HRV · 스트레스 구간, 눌러서 결과 다시 보기 | ✅ | [보기](check/screens/25_records.png) |
| 내 정보 | 키 · 몸무게 · BMI, 재는 것 / 재지 않는 것, 정확도, 거울 기록 열기, 시연 · 지우기 | ✅ | [보기](check/screens/26_my_info.png) |

## 계산 · 검증

| 지표 | 방법 | 공개 데이터(MCD-rPPG 100명, 30초 창, 신호 좋음) |
| --- | --- | --- |
| 심박 | POS → 추세 제거 → 대역 통과 → 주기도 최고점 | 오차 0.33 bpm |
| HRV | 내 심박 ±0.4 Hz 맥파의 박동 → RMSSD · SDNN | RMSSD 7.5 ms · SDNN 6.1 ms |
| 스트레스 지수 | Baevsky SI → 0–100 | 상관 0.72 · 같은 구간 58% |
| 리듬 | 신호 좋을 때만, 박동 간격 급변 비율 | 건강한 사람 오탐 0 / 129 |
| 호흡 | 세 변조 융합 | 손끝 PPG 호흡과 상관 0.1 → 참고값, 점수 제외 |

브라우저(`vitals.js`)와 Python(`src/nesy/vitals.py`)이 같은 입력에서 같은 값을 낸다 (`tests/test_vitals.py` 기준값).
자세한 내용: [`docs/CHECK_DESIGN.md`](CHECK_DESIGN.md).

## 서버 API (`webapp/server.py` → `webapp/check.py`)

| | 경로 | 하는 일 |
| --- | --- | --- |
| GET | `/api/c/state?member=` | 프로필 · 마지막 측정 · 평소 · 최근 7일 |
| GET | `/api/c/history?member=` · `/api/c/result?id=&member=` | 측정 목록 · 측정 하나 (남의 것은 404) |
| GET | `/api/c/groups?member=` | 내 그룹 전부, 급한 순 |
| POST | `/api/c/scan` | 지표 숫자 + 세 가지 답 저장 → 점수 · 추천 · 공부 모드 · 그룹별 인증 |
| POST | `/api/c/group/create` · `join` · `leave` | 그룹 만들기 · 코드로 참여 · 나가기 (코드별) |
| POST | `/api/c/profile` · `demo` · `reset` | 키 · 몸무게 · 동의 / 시연 데이터 / 내 기록 지우기 |

서버로 가는 것은 브라우저가 계산한 숫자뿐이다. 영상 · 사진 · 얼굴 메시는 저장하지 않는다.

## 아직 안 된 것

| 항목 | 지금 | 다음 |
| --- | --- | --- |
| 실기기 측정 | 브라우저에서 가짜 맥박 신호로만 끝까지 확인 | 팀원 폰으로 2주 운용, 조명 · 기종별 오차 |
| 계정 | 브라우저마다 무작위 아이디. 아이디를 알면 기록이 보인다 | 로그인 또는 기록을 기기 안에만 |
| 배포 | 노트북 서버 + 자체 서명 https | 정식 https 호스팅 또는 홈 화면 설치(PWA) |
| 알림 | 그룹 인증 시간 알림 없음 (거울 기록엔 스케줄 배너 · 캘린더 있음) | 그룹 시간대를 캘린더(.ics) · 배너로 |
| 두 앱 합치기 | 거울 기록 ↔ Vity 체크 링크만 | 루틴별 이유 묻기 · 시험기간 리포트를 체크로 옮길지 결정 |
| 부정맥 검증 | 건강한 사람 데이터로 오탐만 확인 | '불규칙'은 다시 재기 · 보건실 안내로만 사용 |
| 캐릭터 | 기존 에셋 12개(calm = idle 같은 그림, ask · left · tense 저해상도) | 표정 에셋 추가 |

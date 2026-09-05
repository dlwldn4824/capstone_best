"""tags.csv -> 라벨된 구간(segment) 분할.

태그 N개는 구간 N-1개를 만든다. configs/protocol.yaml 의 labels 리스트가
그 구간들에 순서대로 대응한다. 실제 태그 수가 expected_segments 와 다르면
그 세션은 needs_review 로 표시하고 라벨을 붙이지 않는다 (조용한 오라벨 방지).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np


@dataclass
class Segment:
    subject: str
    session_type: str
    version: str
    seg_index: int
    name: str
    label: str          # REST / STRESS / AEROBIC / SPRINT
    start: float        # UTC epoch
    end: float
    portion: str

    def as_dict(self) -> dict:
        return asdict(self)


def subject_version(subject: str, protocol: dict) -> str:
    """S01 -> v1, f07 -> v2."""
    return protocol["version_by_prefix"].get(subject[0], "v1")


def _apply_portion(start: float, end: float, portion: str) -> tuple[float, float]:
    """원 논문의 세그먼트 선택 규칙을 반영한다."""
    if portion == "second_half":
        return (start + end) / 2.0, end
    if portion == "middle_60s":
        mid = (start + end) / 2.0
        if end - start <= 60.0:
            return start, end
        return mid - 30.0, mid + 30.0
    return start, end


def segment_session(subject, session_type, tags, protocol):
    """(segments, problem) 을 돌려준다. problem 이 None 이 아니면 사용 금지."""
    version = subject_version(subject, protocol)
    spec = protocol.get(session_type, {}).get(version)
    if spec is None:
        return [], "프로토콜 정의 없음: {}/{}".format(session_type, version)

    n_seg = len(tags) - 1
    if n_seg <= 0:
        return [], "태그 부족 (tags={})".format(len(tags))
    if n_seg != spec["expected_segments"]:
        return [], "세그먼트 수 불일치: 관측 {} != 기대 {} ({}/{})".format(
            n_seg, spec["expected_segments"], session_type, version)

    segs = []
    for i in range(n_seg):
        label = spec["labels"][i]
        if label is None:
            continue
        s, e = _apply_portion(float(tags[i]), float(tags[i + 1]),
                              spec["portions"][i])
        segs.append(Segment(subject, session_type, version, i,
                            spec["names"][i], label, s, e, spec["portions"][i]))
    return segs, None


def windows(seg, length, step):
    """세그먼트를 고정 길이 슬라이딩 윈도로 자른다.

    세그먼트가 윈도보다 짧으면 (30초 sprint 등) 세그먼트 전체를 한 윈도로 쓴다.
    이 경우 HRV 주파수영역 feature 는 신뢰할 수 없어 NaN 이 된다.
    """
    dur = seg.end - seg.start
    if dur <= 0:
        return []
    if dur < length:
        return [(seg.start, seg.end)]
    out, t = [], seg.start
    while t + length <= seg.end + 1e-9:
        out.append((t, t + length))
        t += step
    return out

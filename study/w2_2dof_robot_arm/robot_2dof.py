"""2링크 평면 로봇팔의 순기구학 / 역기구학.

각도 규약
---------
- 기저(base)는 원점. +x는 오른쪽, +y는 위.
- theta1: 링크 1이 +x축과 이루는 각. 반시계 방향이 양수.
- theta2: 링크 1에 대한 링크 2의 상대각. 반시계 방향이 양수.
- 내부 계산은 모두 라디안. 도(degree) 입력은 *_deg 함수에서만 변환한다.

자세 이름
---------
- theta2 > 0: elbow-down. 팔꿈치가 기저→목표 반직선의 시계 방향에 있다.
- theta2 < 0: elbow-up. 팔꿈치가 그 반직선의 반시계 방향에 있다.
- |theta2|가 0 또는 180도에 가까우면 singular (완전히 펴지거나 접힘).

2차원에서 기저→목표 벡터를 T, 기저→팔꿈치를 E라 하면
T × E = -L1 * L2 * sin(theta2) 이다. 부호 이름이 이 관계에서 온다.
1사분면 목표에서는 elbow-up이 시각적으로 위, elbow-down이 아래다.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass


# 부동소수점이 ±1을 아주 조금 넘는 경우만 작업공간 경계로 인정한다.
_COS_TOL = 1e-9
_ANGLE_TOL = 1e-8


@dataclass(frozen=True)
class FKResult:
    x: float
    y: float
    elbow_x: float
    elbow_y: float
    orientation: float  # 링크 2의 절대각 = theta1 + theta2

    @property
    def position(self) -> tuple[float, float]:
        return (self.x, self.y)


@dataclass(frozen=True)
class IKSolution:
    theta1: float
    theta2: float
    posture: str
    fk_x: float
    fk_y: float
    error: float
    within_limits: bool

    def to_dict(self) -> dict:
        data = asdict(self)
        data["theta1_deg"] = math.degrees(self.theta1)
        data["theta2_deg"] = math.degrees(self.theta2)
        return data


@dataclass(frozen=True)
class IKResult:
    x: float
    y: float
    L1: float
    L2: float
    distance: float
    reach_min: float
    reach_max: float
    reachable: bool
    reason: str
    solutions: tuple[IKSolution, ...]

    @property
    def valid_solutions(self) -> tuple[IKSolution, ...]:
        return tuple(sol for sol in self.solutions if sol.within_limits)


def wrap_pi(angle: float) -> float:
    """각을 (-pi, pi] 로 접는다."""
    wrapped = (angle + math.pi) % (2.0 * math.pi) - math.pi
    if wrapped <= -math.pi:
        return math.pi
    return wrapped


def _clamp_unit_interval(value: float, tol: float = _COS_TOL) -> float | None:
    """acos/asin 인자. 허용 오차 밖이면 None (도달 불가)."""
    if value > 1.0:
        return 1.0 if value <= 1.0 + tol else None
    if value < -1.0:
        return -1.0 if value >= -1.0 - tol else None
    return value


def forward_kinematics(L1: float, L2: float, theta1: float, theta2: float) -> FKResult:
    """순기구학. theta1, theta2는 라디안."""
    if L1 < 0 or L2 < 0:
        raise ValueError("링크 길이는 0 이상이어야 합니다.")
    elbow_x = L1 * math.cos(theta1)
    elbow_y = L1 * math.sin(theta1)
    absolute_2 = theta1 + theta2
    x = elbow_x + L2 * math.cos(absolute_2)
    y = elbow_y + L2 * math.sin(absolute_2)
    return FKResult(x, y, elbow_x, elbow_y, absolute_2)


def forward_kinematics_deg(L1: float, L2: float, theta1_deg: float, theta2_deg: float) -> FKResult:
    """도를 라디안으로 바꾼 뒤 순기구학을 계산한다."""
    return forward_kinematics(
        L1,
        L2,
        math.radians(theta1_deg),
        math.radians(theta2_deg),
    )


def position_error(actual: tuple[float, float], target: tuple[float, float]) -> float:
    return math.hypot(actual[0] - target[0], actual[1] - target[1])


def workspace_limits(L1: float, L2: float) -> tuple[float, float]:
    return (abs(L1 - L2), L1 + L2)


def posture_name(theta2: float) -> str:
    if abs(math.sin(theta2)) <= 1e-8:
        return "singular"
    if theta2 > 0:
        return "elbow-down"
    return "elbow-up"


def _within(angle: float, limits: tuple[float, float] | None) -> bool:
    if limits is None:
        return True
    low, high = limits
    return (low - _ANGLE_TOL) <= angle <= (high + _ANGLE_TOL)


def inverse_kinematics(
    x: float,
    y: float,
    L1: float,
    L2: float,
    theta1_limits: tuple[float, float] | None = None,
    theta2_limits: tuple[float, float] | None = None,
) -> IKResult:
    """위치 역기구학. 해는 최대 2개. 한계는 라디안, None이면 제한 없음.

    theta1 = atan2(y, x) - atan2(L2*sin(theta2), L1 + L2*cos(theta2))
    theta2 = ±acos( (x^2 + y^2 - L1^2 - L2^2) / (2*L1*L2) )
    """
    if L1 <= 0 or L2 <= 0:
        raise ValueError("역기구학 링크 길이는 양수여야 합니다.")

    distance = math.hypot(x, y)
    reach_min, reach_max = workspace_limits(L1, L2)
    cosine_theta2 = (x * x + y * y - L1 * L1 - L2 * L2) / (2.0 * L1 * L2)
    cosine = _clamp_unit_interval(cosine_theta2)

    if cosine is None or distance > reach_max + _COS_TOL or distance < reach_min - _COS_TOL:
        return IKResult(
            x=x,
            y=y,
            L1=L1,
            L2=L2,
            distance=distance,
            reach_min=reach_min,
            reach_max=reach_max,
            reachable=False,
            reason=(
                f"목표 거리 {distance:.6f}가 작업공간 "
                f"[{reach_min:.6f}, {reach_max:.6f}] 밖에 있습니다. "
                f"cos(theta2)={cosine_theta2:.6f}는 [-1, 1] 밖입니다."
            ),
            solutions=(),
        )

    theta2_candidates = (math.acos(cosine), -math.acos(cosine))
    solutions: list[IKSolution] = []
    for theta2_raw in theta2_candidates:
        theta2 = wrap_pi(theta2_raw)
        if any(abs(wrap_pi(theta2 - prev.theta2)) < 1e-8 for prev in solutions):
            continue
        k1 = L1 + L2 * math.cos(theta2)
        k2 = L2 * math.sin(theta2)
        theta1 = wrap_pi(math.atan2(y, x) - math.atan2(k2, k1))
        fk = forward_kinematics(L1, L2, theta1, theta2)
        error = position_error((fk.x, fk.y), (x, y))
        solutions.append(
            IKSolution(
                theta1=theta1,
                theta2=theta2,
                posture=posture_name(theta2),
                fk_x=fk.x,
                fk_y=fk.y,
                error=error,
                within_limits=_within(theta1, theta1_limits) and _within(theta2, theta2_limits),
            )
        )

    if not solutions:
        reason = "작업공간 경계 판정은 통과했지만 유효한 관절해를 만들지 못했습니다."
        reachable = False
    elif distance <= _COS_TOL and reach_min <= _COS_TOL:
        reason = (
            "원점으로 접어 도달 가능합니다. θ2는 ±180°이고 θ1은 아무 값이나 됩니다. "
            "반환된 해는 그중 대표 하나입니다."
        )
        reachable = True
    elif all(not sol.within_limits for sol in solutions):
        reason = "기하학적으로는 도달 가능하지만, 주어진 관절 범위 안의 해는 없습니다."
        reachable = True
    else:
        reason = f"도달 가능. 기하학 해 {len(solutions)}개."
        reachable = True

    return IKResult(
        x=x,
        y=y,
        L1=L1,
        L2=L2,
        distance=distance,
        reach_min=reach_min,
        reach_max=reach_max,
        reachable=reachable,
        reason=reason,
        solutions=tuple(solutions),
    )


def inverse_kinematics_law_of_cosines(
    x: float,
    y: float,
    L1: float,
    L2: float,
) -> list[tuple[float, float]]:
    """독립적인 검산용 역기구학.

    기저에서 본 목표 방향각 alpha에서, 링크 1이 벗어난 각 phi를 더하거나 뺀다.
    elbow-down은 alpha - phi, elbow-up은 alpha + phi.
    반환값은 (theta1, theta2) 라디안.
    """
    distance = math.hypot(x, y)
    reach_min, reach_max = workspace_limits(L1, L2)
    if distance > reach_max + _COS_TOL or distance < reach_min - _COS_TOL:
        return []
    if distance <= _COS_TOL:
        raise ValueError("목표가 원점이면 링크 1 방향이 하나로 정해지지 않습니다.")

    cos_phi = (distance * distance + L1 * L1 - L2 * L2) / (2.0 * distance * L1)
    cos_phi_unit = _clamp_unit_interval(cos_phi)
    if cos_phi_unit is None:
        return []
    alpha = math.atan2(y, x)
    phi = math.acos(cos_phi_unit)

    cos_theta2 = (distance * distance - L1 * L1 - L2 * L2) / (2.0 * L1 * L2)
    cos_theta2_unit = _clamp_unit_interval(cos_theta2)
    if cos_theta2_unit is None:
        return []
    theta2_magnitude = math.acos(cos_theta2_unit)

    candidates = (
        (wrap_pi(alpha - phi), wrap_pi(theta2_magnitude)),
        (wrap_pi(alpha + phi), wrap_pi(-theta2_magnitude)),
    )
    unique: list[tuple[float, float]] = []
    for theta1, theta2 in candidates:
        if any(
            abs(wrap_pi(theta1 - prev_1)) < 1e-7 and abs(wrap_pi(theta2 - prev_2)) < 1e-7
            for prev_1, prev_2 in unique
        ):
            continue
        unique.append((theta1, theta2))
    return unique


def run_agent(
    x: float,
    y: float,
    L1: float = 1.0,
    L2: float = 1.0,
    theta1_limits_deg: tuple[float, float] | None = None,
    theta2_limits_deg: tuple[float, float] | None = None,
    error_limit: float = 1e-6,
) -> dict:
    """목표 좌표를 받아 도달 판단 → IK → FK 검증 → 오차 → 유효성 → 요약을 수행한다."""
    theta1_limits = None if theta1_limits_deg is None else tuple(math.radians(v) for v in theta1_limits_deg)
    theta2_limits = None if theta2_limits_deg is None else tuple(math.radians(v) for v in theta2_limits_deg)
    ik = inverse_kinematics(x, y, L1, L2, theta1_limits, theta2_limits)

    lines = [
        f"[Agent] 목표 ({x:.6f}, {y:.6f}), L1={L1:g}, L2={L2:g}",
        (
            "1. 도달 판단: "
            f"거리 {ik.distance:.6f}, 작업공간 [{ik.reach_min:.6f}, {ik.reach_max:.6f}]"
        ),
        f"   {ik.reason}",
    ]

    checked = []
    for index, sol in enumerate(ik.solutions, start=1):
        fk = forward_kinematics(L1, L2, sol.theta1, sol.theta2)
        error = position_error((fk.x, fk.y), (x, y))
        valid = sol.within_limits and error <= error_limit
        limit_text = "관절 범위 안" if sol.within_limits else "관절 범위 밖"
        lines.append(
            f"2-4. 해 {index} [{sol.posture}] {limit_text}: "
            f"θ1={math.degrees(sol.theta1):.6f}°, θ2={math.degrees(sol.theta2):.6f}°"
        )
        lines.append(
            f"   FK 재계산 ({fk.x:.8f}, {fk.y:.8f}), "
            f"위치 오차 {error:.3e}, 유효={'예' if valid else '아니오'}"
        )
        checked.append(
            {
                "posture": sol.posture,
                "theta1_deg": math.degrees(sol.theta1),
                "theta2_deg": math.degrees(sol.theta2),
                "fk": [fk.x, fk.y],
                "error": error,
                "within_limits": sol.within_limits,
                "valid": valid,
            }
        )

    usable = [item for item in checked if item["valid"]]
    if not ik.reachable:
        verdict = "도달 불가. 관절각을 만들지 않습니다."
    elif not usable:
        verdict = "기하학 해는 있으나 관절 제한 또는 오차 기준을 통과하지 못했습니다."
    else:
        verdict = f"유효한 해 {len(usable)}개. 목표와의 오차가 {error_limit:g} 이하입니다."
    lines.append(f"5. 결과: {verdict}")

    return {
        "target": [x, y],
        "L1": L1,
        "L2": L2,
        "reachable": ik.reachable,
        "distance": ik.distance,
        "reach_min": ik.reach_min,
        "reach_max": ik.reach_max,
        "reason": ik.reason,
        "solutions": checked,
        "verdict": verdict,
        "report": "\n".join(lines),
    }


def fk_bug_degrees_as_radians(L1: float, L2: float, theta1_deg: float, theta2_deg: float) -> tuple[float, float]:
    """오류 예시: 도 값을 math.cos/sin에 그대로 넣는다."""
    absolute = theta1_deg + theta2_deg
    return (
        L1 * math.cos(theta1_deg) + L2 * math.cos(absolute),
        L1 * math.sin(theta1_deg) + L2 * math.sin(absolute),
    )


def fk_bug_absolute_theta2(L1: float, L2: float, theta1_deg: float, theta2_deg: float) -> tuple[float, float]:
    """오류 예시: theta2를 링크 1 기준 상대각이 아니라 +x축 절대각으로 사용한다."""
    theta1 = math.radians(theta1_deg)
    theta2 = math.radians(theta2_deg)
    return (
        L1 * math.cos(theta1) + L2 * math.cos(theta2),
        L1 * math.sin(theta1) + L2 * math.sin(theta2),
    )


def ik_bug_clamp_to_workspace(x: float, y: float, L1: float, L2: float) -> tuple[float, float, float, float]:
    """오류 예시: cos(theta2)가 1을 넘으면 1로 잘라 해를 만들어 낸다.

    반환: theta1(rad), theta2(rad), 그 자세의 x, y.
    도달 불가 점을 최대 도달 원 위로 투영한 결과가 된다.
    """
    cosine = (x * x + y * y - L1 * L1 - L2 * L2) / (2.0 * L1 * L2)
    cosine = max(-1.0, min(1.0, cosine))
    theta2 = math.acos(cosine)
    k1 = L1 + L2 * math.cos(theta2)
    k2 = L2 * math.sin(theta2)
    theta1 = math.atan2(y, x) - math.atan2(k2, k1)
    fk = forward_kinematics(L1, L2, theta1, theta2)
    return theta1, theta2, fk.x, fk.y

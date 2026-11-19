"""W2 2-DOF 로봇팔 스터디 실험.

실행:
    python3 study/w2_2dof_robot_arm/run_study.py

numpy로 순기구학을 한 번 더 계산하고, matplotlib로 그림을 저장한다.
기준 구현은 robot_2dof.py 이며, 두 번째 역기구학 식과 닫힌형 FK 식으로 검산한다.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager

sys.path.insert(0, str(Path(__file__).resolve().parent))

from robot_2dof import (
    fk_bug_absolute_theta2,
    fk_bug_degrees_as_radians,
    forward_kinematics,
    forward_kinematics_deg,
    ik_bug_clamp_to_workspace,
    inverse_kinematics,
    inverse_kinematics_law_of_cosines,
    position_error,
    run_agent,
    workspace_limits,
    wrap_pi,
)

ROOT = Path(__file__).resolve().parent
FIGURES = ROOT / "figures"
LINK_COLORS = ("#1d4e89", "#e07a3d")


def configure_font() -> str:
    preferred = ["Apple SD Gothic Neo", "AppleGothic", "NanumGothic", "Arial Unicode MS"]
    available = {font.name for font in font_manager.fontManager.ttflist}
    chosen = next((name for name in preferred if name in available), "DejaVu Sans")
    plt.rcParams["font.family"] = chosen
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.facecolor"] = "white"
    plt.rcParams["axes.facecolor"] = "#f7f8fa"
    plt.rcParams["axes.grid"] = True
    plt.rcParams["grid.color"] = "#d5dbe3"
    plt.rcParams["grid.linewidth"] = 0.6
    return chosen


def fk_numpy(L1: float, L2: float, theta1: float, theta2: float) -> np.ndarray:
    """과제에서 요구한 numpy 계산. 삼각함수 인자는 라디안이다."""
    lengths = np.array([L1, L2], dtype=float)
    absolute = np.array([theta1, theta1 + theta2], dtype=float)
    return np.array([lengths @ np.cos(absolute), lengths @ np.sin(absolute)])


def assert_close(actual: float, expected: float, tol: float, label: str) -> None:
    if abs(actual - expected) > tol:
        raise AssertionError(f"{label}: actual={actual!r}, expected={expected!r}, tol={tol}")


def check_core() -> dict:
    """닫힌형 식, numpy, 두 종류의 IK가 서로 같은지 확인한다."""
    expected_x = math.sqrt(3) / 2 + (math.sqrt(6) - math.sqrt(2)) / 4
    expected_y = 0.5 + (math.sqrt(6) + math.sqrt(2)) / 4
    fk = forward_kinematics_deg(1, 1, 30, 45)
    numpy_xy = fk_numpy(1, 1, math.radians(30), math.radians(45))
    assert_close(fk.x, expected_x, 1e-12, "FK x")
    assert_close(fk.y, expected_y, 1e-12, "FK y")
    assert_close(float(numpy_xy[0]), fk.x, 1e-12, "numpy FK x")
    assert_close(float(numpy_xy[1]), fk.y, 1e-12, "numpy FK y")

    ik = inverse_kinematics(1, 1, 1, 1)
    if len(ik.solutions) != 2:
        raise AssertionError(f"(1,1)의 해는 2개여야 합니다. 실제 {len(ik.solutions)}개")
    by_posture = {sol.posture: sol for sol in ik.solutions}
    assert_close(by_posture["elbow-down"].theta1, 0.0, 1e-12, "elbow-down theta1")
    assert_close(by_posture["elbow-down"].theta2, math.pi / 2, 1e-12, "elbow-down theta2")
    assert_close(by_posture["elbow-up"].theta1, math.pi / 2, 1e-12, "elbow-up theta1")
    assert_close(by_posture["elbow-up"].theta2, -math.pi / 2, 1e-12, "elbow-up theta2")
    for sol in ik.solutions:
        if sol.error > 1e-12:
            raise AssertionError(f"IK 재검증 오차가 큽니다: {sol.error}")

    unreachable = inverse_kinematics(1.8, 1.8, 1.0, 0.5)
    if unreachable.reachable or unreachable.solutions:
        raise AssertionError("도달 불가 점인데 해를 반환했습니다.")

    stretched = inverse_kinematics(0.0, 2.0, 1.0, 1.0)
    if len(stretched.solutions) != 1:
        raise AssertionError("완전히 편 자세는 해가 하나여야 합니다.")
    assert_close(stretched.solutions[0].theta1, math.pi / 2, 1e-12, "stretched theta1")
    assert_close(stretched.solutions[0].theta2, 0.0, 1e-12, "stretched theta2")

    origin = inverse_kinematics(0.0, 0.0, 1.0, 1.0)
    if not origin.reachable or abs(origin.solutions[0].error) > 1e-12:
        raise AssertionError("같은 길이의 팔을 접으면 원점에 도달해야 합니다.")
    another = forward_kinematics(1.0, 1.0, 0.4, math.pi)
    if position_error((another.x, another.y), (0.0, 0.0)) > 1e-12:
        raise AssertionError("접힌 팔은 θ1이 달라도 원점에 있어야 합니다.")

    compared = 0
    for L1, L2 in ((1.0, 1.0), (1.2, 0.8)):
        for x in np.linspace(-1.5, 1.5, 7):
            for y in np.linspace(-1.5, 1.5, 7):
                if math.hypot(float(x), float(y)) < 1e-9:
                    continue
                primary = inverse_kinematics(float(x), float(y), L1, L2)
                if not primary.solutions:
                    continue
                secondary = inverse_kinematics_law_of_cosines(float(x), float(y), L1, L2)
                if len(secondary) != len(primary.solutions):
                    raise AssertionError(f"해 개수 불일치 at {(x, y)} L=({L1}, {L2})")
                for sol in primary.solutions:
                    if not any(
                        abs(wrap_pi(sol.theta1 - other_1)) < 1e-8
                        and abs(wrap_pi(sol.theta2 - other_2)) < 1e-8
                        for other_1, other_2 in secondary
                    ):
                        raise AssertionError(f"두 IK 식이 불일치 at {(x, y)}")
                    back = forward_kinematics(L1, L2, sol.theta1, sol.theta2)
                    if position_error((back.x, back.y), (float(x), float(y))) > 1e-8:
                        raise AssertionError("FK 재검증 실패")
                compared += 1
    if compared < 20:
        raise AssertionError("검산 표본이 너무 적습니다.")

    return {
        "fk_x": fk.x,
        "fk_y": fk.y,
        "elbow_x": fk.elbow_x,
        "elbow_y": fk.elbow_y,
        "orientation_deg": math.degrees(fk.orientation),
        "ik_solution_count": len(ik.solutions),
        "cross_check_points": compared,
    }


def equal_link_shortcut_theta1(x: float, y: float, theta2: float) -> float:
    """L1=L2일 때만 성립하는 지름길: 링크 1은 목표 방향에서 |theta2|/2 만큼 벗어난다."""
    alpha = math.atan2(y, x)
    return wrap_pi(alpha - 0.5 * theta2)


def prepare_axes(ax, limit: float, title: str) -> None:
    ax.set_xlim(-limit, limit)
    ax.set_ylim(-limit, limit)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    ax.set_title(title)
    ax.axhline(0, color="#b7c0cc", lw=0.8)
    ax.axvline(0, color="#b7c0cc", lw=0.8)


def draw_workspace(ax, L1: float, L2: float) -> None:
    reach_min, reach_max = workspace_limits(L1, L2)
    ax.add_patch(
        plt.Circle(
            (0, 0),
            reach_max,
            facecolor="#d9e8f6",
            edgecolor="#5b7c99",
            lw=1.2,
            zorder=0,
        )
    )
    if reach_min > 1e-6:
        ax.add_patch(
            plt.Circle(
                (0, 0),
                reach_min,
                facecolor="#f7f8fa",
                edgecolor="#5b7c99",
                lw=1.0,
                ls="--",
                zorder=1,
            )
        )


def draw_arm(ax, L1: float, L2: float, theta1: float, theta2: float, colors=LINK_COLORS, alpha=1.0, lw=5.0):
    fk = forward_kinematics(L1, L2, theta1, theta2)
    ax.plot([0, fk.elbow_x], [0, fk.elbow_y], color=colors[0], lw=lw, alpha=alpha, solid_capstyle="round", zorder=3)
    ax.plot(
        [fk.elbow_x, fk.x],
        [fk.elbow_y, fk.y],
        color=colors[1],
        lw=lw,
        alpha=alpha,
        solid_capstyle="round",
        zorder=3,
    )
    ax.scatter([0], [0], s=55, c="black", zorder=4)
    ax.scatter([fk.elbow_x], [fk.elbow_y], s=45, c=colors[0], zorder=4, edgecolors="white")
    ax.scatter([fk.x], [fk.y], s=64, c="#c0392b", zorder=5, edgecolors="white")
    return fk


def save(fig, name: str) -> None:
    fig.savefig(FIGURES / name, dpi=160, bbox_inches="tight")
    plt.close(fig)


def plot_fk(fk_info: dict) -> None:
    fig, ax = plt.subplots(figsize=(6.4, 6.2))
    prepare_axes(ax, 2.15, "Forward Kinematics  θ1=30°, θ2=45°")
    draw_workspace(ax, 1, 1)
    fk = draw_arm(ax, 1, 1, math.radians(30), math.radians(45))
    ax.annotate(
        f"end-effector\n({fk.x:.4f}, {fk.y:.4f})",
        xy=(fk.x, fk.y),
        xytext=(fk.x - 1.15, fk.y + 0.28),
        arrowprops={"arrowstyle": "->", "color": "#c0392b"},
        color="#8e2f24",
        fontsize=10,
    )
    ax.text(
        0.04,
        0.04,
        "L1=1, L2=1\n링크2 절대각 = 75°\n파란 원: 최대 도달 거리 2",
        transform=ax.transAxes,
        fontsize=9,
        color="#243140",
        va="bottom",
    )
    save(fig, "01_fk_30_45.png")
    fk_info["figure_xy"] = [fk.x, fk.y]


def plot_ik() -> None:
    ik = inverse_kinematics(1, 1, 1, 1)
    fig, axes = plt.subplots(1, 2, figsize=(10.6, 5.2))
    for ax, sol in zip(axes, ik.solutions):
        prepare_axes(ax, 1.7, sol.posture)
        draw_workspace(ax, 1, 1)
        ax.plot([0, 1], [0, 1], ls=":", color="#8aa0b8", lw=1.2, zorder=2)
        draw_arm(ax, 1, 1, sol.theta1, sol.theta2)
        ax.scatter([1], [1], s=90, marker="x", c="#c0392b", zorder=6)
        ax.text(
            0.04,
            0.04,
            f"θ1={math.degrees(sol.theta1):.1f}°\nθ2={math.degrees(sol.theta2):.1f}°\n"
            f"오차={sol.error:.1e}",
            transform=ax.transAxes,
            fontsize=10,
            va="bottom",
        )
    fig.suptitle("Inverse Kinematics  목표 (1, 1), 해 2개", fontsize=14)
    save(fig, "02_ik_1_1.png")


def plot_unreachable() -> None:
    target = (1.8, 1.8)
    L1, L2 = 1.0, 0.5
    fig, ax = plt.subplots(figsize=(6.4, 6.2))
    prepare_axes(ax, 2.7, "도달 불가  L1=1, L2=0.5, 목표 (1.8, 1.8)")
    draw_workspace(ax, L1, L2)
    ax.scatter([target[0]], [target[1]], s=80, marker="x", c="#c0392b", zorder=5)
    ax.annotate(
        "목표 (1.8, 1.8)\n거리 2.55 > 최대 1.5",
        xy=target,
        xytext=(0.15, 2.15),
        arrowprops={"arrowstyle": "->", "color": "#c0392b"},
        color="#8e2f24",
        fontsize=10,
    )
    ax.text(
        0.04,
        0.04,
        "색 영역: 도달 가능\n흰 원 안(r<0.5): 너무 가까워서 불가",
        transform=ax.transAxes,
        fontsize=9,
        va="bottom",
    )
    save(fig, "03_unreachable.png")


def plot_different_links() -> dict:
    L1, L2 = 1.2, 0.8
    target = (1.0, 0.5)
    ik = inverse_kinematics(target[0], target[1], L1, L2)
    fig, axes = plt.subplots(1, 2, figsize=(10.6, 5.2))
    for ax, sol in zip(axes, ik.solutions):
        prepare_axes(ax, 2.3, f"{sol.posture}")
        draw_workspace(ax, L1, L2)
        draw_arm(ax, L1, L2, sol.theta1, sol.theta2)
        ax.scatter([target[0]], [target[1]], s=90, marker="x", c="#c0392b", zorder=6)
        ax.text(
            0.04,
            0.04,
            f"θ1={math.degrees(sol.theta1):.2f}°\nθ2={math.degrees(sol.theta2):.2f}°\n"
            f"오차={sol.error:.1e}",
            transform=ax.transAxes,
            fontsize=10,
            va="bottom",
        )
    fig.suptitle("추가 실험: L1=1.2, L2=0.8, 목표 (1.0, 0.5)", fontsize=14)
    save(fig, "04_different_links.png")
    return {
        "L1": L1,
        "L2": L2,
        "target": list(target),
        "solutions": [sol.to_dict() for sol in ik.solutions],
    }


def plot_joint_limits() -> dict:
    ik = inverse_kinematics(
        1,
        1,
        1,
        1,
        theta1_limits=(math.radians(-180), math.radians(180)),
        theta2_limits=(0.0, math.pi),
    )
    fig, ax = plt.subplots(figsize=(6.6, 6.2))
    prepare_axes(ax, 1.7, "관절 제한  θ2 ∈ [0°, 180°]")
    draw_workspace(ax, 1, 1)
    ax.plot([0, 1], [0, 1], ls=":", color="#8aa0b8", lw=1.2, zorder=2)
    for sol in ik.solutions:
        if sol.within_limits:
            draw_arm(ax, 1, 1, sol.theta1, sol.theta2)
            ax.text(
                0.04,
                0.04,
                "허용: elbow-down\nθ1=0°, θ2=90°",
                transform=ax.transAxes,
                color="#1d4e89",
                fontsize=10,
                va="bottom",
            )
        else:
            draw_arm(ax, 1, 1, sol.theta1, sol.theta2, colors=("#9aa3ad", "#c5c9ce"), alpha=0.95, lw=3.5)
            ax.text(
                0.04,
                0.96,
                "제외: elbow-up (θ2<0)\nθ1=90°, θ2=-90°",
                transform=ax.transAxes,
                color="#66707a",
                fontsize=10,
                va="top",
            )
    ax.scatter([1], [1], s=90, marker="x", c="#c0392b", zorder=6)
    save(fig, "05_joint_limits.png")
    return {"reason": ik.reason, "solutions": [sol.to_dict() for sol in ik.solutions]}


def plot_sequence() -> list[dict]:
    targets = [(1.5, 0.2), (1.0, 1.0), (0.0, 1.5), (-0.8, 0.6)]
    colors = ["#1d4e89", "#2f7d4a", "#e07a3d", "#7a4e9a"]
    fig, ax = plt.subplots(figsize=(6.8, 6.4))
    prepare_axes(ax, 2.15, "연속 목표 4개  (elbow-down 우선)")
    draw_workspace(ax, 1, 1)
    rows = []
    for index, (target, color) in enumerate(zip(targets, colors), start=1):
        agent = run_agent(target[0], target[1], 1, 1)
        chosen = next(item for item in agent["solutions"] if item["posture"] == "elbow-down")
        theta1 = math.radians(chosen["theta1_deg"])
        theta2 = math.radians(chosen["theta2_deg"])
        fk = forward_kinematics(1, 1, theta1, theta2)
        ax.plot([0, fk.elbow_x], [0, fk.elbow_y], color=color, lw=3.2, alpha=0.9, zorder=3)
        ax.plot([fk.elbow_x, fk.x], [fk.elbow_y, fk.y], color=color, lw=3.2, alpha=0.9, zorder=3)
        ax.scatter([fk.x], [fk.y], s=40, c=color, zorder=5)
        ax.text(fk.x + 0.06, fk.y + 0.06, str(index), color=color, fontsize=12, fontweight="bold")
        rows.append(
            {
                "order": index,
                "target": list(target),
                "theta1_deg": chosen["theta1_deg"],
                "theta2_deg": chosen["theta2_deg"],
                "error": chosen["error"],
            }
        )
    ax.scatter([0], [0], s=55, c="black", zorder=4)
    save(fig, "06_target_sequence.png")
    return rows


def plot_error_modes(reference: tuple[float, float]) -> dict:
    degree_bug = fk_bug_degrees_as_radians(1, 1, 30, 45)
    absolute_bug = fk_bug_absolute_theta2(1, 1, 30, 45)
    fake_theta1, fake_theta2, fake_x, fake_y = ik_bug_clamp_to_workspace(1.8, 1.8, 1.0, 0.5)
    rows = [
        ("올바른 FK", 0.0),
        ("도를 라디안으로 사용", position_error(degree_bug, reference)),
        ("θ2를 절대각으로 사용", position_error(absolute_bug, reference)),
        ("불가 점을 경계로 투영", position_error((fake_x, fake_y), (1.8, 1.8))),
    ]
    fig, ax = plt.subplots(figsize=(8.2, 4.6))
    labels = [name for name, _ in rows]
    values = [value for _, value in rows]
    bars = ax.bar(labels, values, color=["#2f7d4a", "#c0392b", "#e07a3d", "#1d4e89"])
    ax.set_ylabel("목표 또는 올바른 좌표와의 거리")
    ax.set_title("잘못된 계산을 코드로 재현했을 때의 위치 오차")
    ax.bar_label(bars, fmt="%.3f", padding=3)
    ax.set_ylim(0, max(values) * 1.25)
    fig.tight_layout()
    save(fig, "07_error_modes.png")
    return {
        "degree_bug_xy": list(degree_bug),
        "absolute_bug_xy": list(absolute_bug),
        "clamped_solution_deg": [math.degrees(fake_theta1), math.degrees(fake_theta2)],
        "clamped_xy": [fake_x, fake_y],
        "errors": {name: value for name, value in rows},
    }


def compare_models(reference_xy: tuple[float, float]) -> dict:
    """같은 문제를 받은 모델의 FINAL 수치를 numpy 기준값과 비교한다."""
    reports = {
        "GPT": {"xy": (1.124844449, 1.465925826), "decimals": 9},
        "Claude": {"xy": (1.124844, 1.465926), "decimals": 6},
        "Gemini": {"xy": (1.1248, 1.4659), "decimals": 4},
    }
    comparison = {}
    for name, item in reports.items():
        tol = 0.5 * 10 ** (-item["decimals"])
        error = position_error(item["xy"], reference_xy)
        within_rounding = all(
            abs(reported - truth) <= tol + 1e-15
            for reported, truth in zip(item["xy"], reference_xy)
        )
        comparison[name] = {
            "reported_xy": list(item["xy"]),
            "error_against_numpy": error,
            "within_reported_rounding": within_rounding,
        }

    gemini_solutions = ((-19.3263, 75.5225), (56.1962, -75.5225))
    gemini_case2 = []
    for theta1_deg, theta2_deg in gemini_solutions:
        fk = forward_kinematics_deg(1, 1, theta1_deg, theta2_deg)
        gemini_case2.append(
            {
                "theta_deg": [theta1_deg, theta2_deg],
                "fk": [fk.x, fk.y],
                "error_vs_target_1_5_0_5": position_error((fk.x, fk.y), (1.5, 0.5)),
            }
        )

    code_case2 = inverse_kinematics(1.5, 0.5, 1, 1)
    shortcut_failures = []
    for L1, L2, target in ((1.2, 0.8, (1.0, 0.5)), (1.0, 0.5, (1.2, 0.2))):
        ik = inverse_kinematics(target[0], target[1], L1, L2)
        for sol in ik.solutions:
            guessed = equal_link_shortcut_theta1(target[0], target[1], sol.theta2)
            fk = forward_kinematics(L1, L2, guessed, sol.theta2)
            shortcut_failures.append(
                {
                    "L": [L1, L2],
                    "target": list(target),
                    "true_theta1_deg": math.degrees(sol.theta1),
                    "shortcut_theta1_deg": math.degrees(guessed),
                    "shortcut_error": position_error((fk.x, fk.y), target),
                }
            )

    stated_parts = (-0.33092, 0.83092)
    theta_a = math.radians(19.3263)
    theta_b = math.radians(56.1962)
    actual_parts = (-math.sin(theta_a), math.sin(theta_b))
    return {
        "fk_main": comparison,
        "ik_main_all_models": {
            "elbow_down_deg": [0.0, 90.0],
            "elbow_up_deg": [90.0, -90.0],
            "reachable_1_8": False,
        },
        "gemini_case2_replug": gemini_case2,
        "code_case2": [sol.to_dict() for sol in code_case2.solutions],
        "gemini_stated_y_parts": list(stated_parts),
        "numpy_y_parts": list(actual_parts),
        "y_part_difference": [actual_parts[0] - stated_parts[0], actual_parts[1] - stated_parts[1]],
        "equal_link_shortcut_when_lengths_differ": shortcut_failures,
    }


def main() -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    font = configure_font()
    core = check_core()
    reference = (core["fk_x"], core["fk_y"])

    agents = [
        run_agent(1, 1, 1, 1),
        run_agent(1.8, 1.8, 1, 0.5),
        run_agent(1, 1, 1, 1, theta2_limits_deg=(0, 180)),
        run_agent(1.5, 0.5, 1, 1),
        run_agent(0.2, 1.6, 1, 1),
    ]
    for agent in agents:
        print(agent["report"])
        print()

    plot_fk(core)
    plot_ik()
    plot_unreachable()
    different_links = plot_different_links()
    joint_limits = plot_joint_limits()
    sequence = plot_sequence()
    error_modes = plot_error_modes(reference)
    model_comparison = compare_models(reference)

    payload = {
        "font": font,
        "core": core,
        "agents": [{key: value for key, value in agent.items() if key != "report"} for agent in agents],
        "different_links": different_links,
        "joint_limits": joint_limits,
        "sequence": sequence,
        "error_modes": error_modes,
        "model_comparison": model_comparison,
    }
    (ROOT / "results.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"font: {font}")
    print(f"figures: {FIGURES}")
    print(f"results: {ROOT / 'results.json'}")


if __name__ == "__main__":
    main()

import SwiftUI

// MARK: - 원인

/// 어젯밤 변화를 설명할 수 있는 원인.
/// 센서가 잡는 것(운동·긴장)과 사람만 아는 것(음주·늦은 잠)이 섞여 있다.
/// 두 종류를 같은 자료형으로 다루는 것이 이 구조의 핵심이다 —
/// 근거가 센서에서 왔든 사람에게서 왔든 "설명" 으로는 똑같이 취급한다.
enum Cause: String, CaseIterable, Identifiable {
    case exercise, stress, alcohol, sleep

    var id: String { rawValue }

    var label: String {
        switch self {
        case .exercise: return "운동했어요"
        case .stress:   return "긴장했어요"
        case .alcohol:  return "술 마셨어요"
        case .sleep:    return "늦게 잤어요"
        }
    }

    /// 게이지 범례에 쓰는 짧은 이름
    var short: String {
        switch self {
        case .exercise: return "운동"
        case .stress:   return "긴장"
        case .alcohol:  return "술"
        case .sleep:    return "늦잠"
        }
    }

    var tint: Color {
        switch self {
        case .exercise: return Color(red: 0.27, green: 0.72, blue: 0.64)
        case .stress:   return Color(red: 0.64, green: 0.53, blue: 0.87)
        case .alcohol:  return Color(red: 0.86, green: 0.64, blue: 0.33)
        case .sleep:    return Color(red: 0.42, green: 0.62, blue: 0.83)
        }
    }
}

// MARK: - 하룻밤

struct Night {
    let title: String
    let date: String
    /// 어젯밤 평소에서 벗어난 정도 (0...100)
    let deviation: Int
    /// 센서가 본 것을 사람 말로 옮긴 한 줄
    let sensorNote: String
    /// 센서만으로 설명되는 몫. 사용자가 확인하기 전에도 이미 채워져 있다.
    let auto: [Cause: Int]
    /// 사용자가 "맞다" 고 답했을 때 그 원인이 설명할 수 있는 최대 몫
    let maxShare: [Cause: Int]
    /// 지난 6일간 설명되지 않고 남은 비율. 오늘 것은 실시간으로 계산한다.
    let history: [Int]

    /// 이번 밤이 이미 여러 날 미해결로 이어지고 있는가
    var streaking: Bool { history.suffix(2).allSatisfy { $0 >= 60 } }
}

extension Night {
    /// 낮에 크게 움직인 날. 센서가 스스로 상당 부분을 설명한다.
    static let exerciseDay = Night(
        title: "운동한 날",
        date: "10월 14일 화",
        deviation: 82,
        sensorNote: "가속도가 평소의 4.1배였어요",
        auto: [.exercise: 46],
        maxShare: [.exercise: 68, .stress: 6, .alcohol: 14, .sleep: 12],
        history: [12, 18, 9, 15, 22, 14]
    )

    /// 발표가 있던 날. 피부전도가 잠든 뒤에도 가라앉지 않았다.
    static let stressDay = Night(
        title: "발표 있던 날",
        date: "10월 21일 화",
        deviation: 74,
        sensorNote: "피부전도가 잠든 뒤에도 높았어요",
        auto: [.stress: 38],
        maxShare: [.exercise: 8, .stress: 62, .alcohol: 12, .sleep: 20],
        history: [16, 11, 20, 13, 17, 12]
    )

    /// 센서에도 사람에게도 짚이는 것이 없는 날. 이것이 우리가 찾는 밤이다.
    static let unknownDay = Night(
        title: "짚이는 게 없는 날",
        date: "11월 3일 월",
        deviation: 88,
        sensorNote: "센서에서는 짚이는 게 없었어요",
        auto: [:],
        maxShare: [.exercise: 5, .stress: 8, .alcohol: 6, .sleep: 7],
        history: [14, 12, 18, 71, 78, 83]
    )

    static let all: [Night] = [.exerciseDay, .stressDay, .unknownDay]
}

// MARK: - 판정

/// 하룻밤의 설명 상태. 화면은 이 값만 보고 그린다.
struct Verdict {
    /// 원인별로 실제 차지한 몫 (게이지 세그먼트)
    let shares: [(cause: Cause, amount: Int)]
    /// 설명되지 않고 남은 비율 (0...100)
    let restPercent: Int
    /// 사흘째 미해결인가
    let alerting: Bool

    var explainedPercent: Int { 100 - restPercent }

    var headline: String {
        if restPercent <= 30 { return "그럴 만해요" }
        if alerting { return "사흘째 설명되지 않았어요" }
        return "\(restPercent)%가 남았어요"
    }

    var detail: String {
        if restPercent <= 30 {
            return "변화의 \(explainedPercent)%가 설명됐어요. 오늘은 넘어갈게요."
        }
        if alerting {
            return "컨디션을 한 번 확인해 보시는 게 좋겠어요."
        }
        return "아직 말을 걸 정도는 아니에요. 며칠 더 볼게요."
    }

    /// 진단하지 않는다는 것을 화면에서도 계속 말한다.
    var footnote: String {
        if alerting { return "어떤 진단도 하지 않아요. 설명하지 못했다는 사실만 알려드려요." }
        if restPercent <= 30 { return "설명된 밤은 쌓이지 않아요." }
        return "사흘 연속 쌓일 때만 알려드려요."
    }
}

enum Engine {
    /// 센서가 채운 몫과 사용자가 확인한 몫 중 큰 쪽을 취한다.
    /// 둘을 더하지 않는 이유: 같은 원인을 두 번 세면 안 되기 때문이다.
    static func evaluate(night: Night, picked: Set<Cause>) -> Verdict {
        var shares: [(Cause, Int)] = []
        var used = 0

        for cause in Cause.allCases {
            let sensor = night.auto[cause] ?? 0
            let confirmed = picked.contains(cause) ? (night.maxShare[cause] ?? 0) : 0
            let raw = max(sensor, confirmed)
            guard raw > 0 else { continue }
            let capped = min(raw, night.deviation - used)
            guard capped > 0 else { continue }
            used += capped
            shares.append((cause, capped))
        }

        let rest = max(0, Int((Double(night.deviation - used)
                               / Double(night.deviation) * 100).rounded()))
        return Verdict(shares: shares,
                       restPercent: rest,
                       alerting: night.streaking && rest >= 60)
    }
}

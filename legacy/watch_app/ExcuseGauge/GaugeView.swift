import SwiftUI

/// 설명 게이지.
///
/// 막대 전체가 "어젯밤 평소에서 벗어난 정도" 다.
/// 설명된 만큼 색이 채워지고 나머지는 회색으로 남는다.
///
/// 남은 부분에 경고색을 쓰지 않는 것이 의도적이다 —
/// 설명 안 된 것은 나쁜 것이 아니라 **모르는 것**이다.
/// 사흘이 쌓였을 때만 색이 바뀐다.
struct GaugeView: View {
    let deviation: Int
    let shares: [(cause: Cause, amount: Int)]
    let alerting: Bool

    private var restColor: Color {
        alerting ? Color(red: 0.88, green: 0.51, blue: 0.41)
                 : Color(white: 0.42)
    }

    var body: some View {
        GeometryReader { geo in
            HStack(spacing: 0) {
                ForEach(shares, id: \.cause) { share in
                    Rectangle()
                        .fill(share.cause.tint)
                        .frame(width: width(share.amount, in: geo.size.width))
                }
                Rectangle().fill(restColor)
            }
        }
        .frame(height: 22)
        .clipShape(RoundedRectangle(cornerRadius: 5, style: .continuous))
        .animation(.easeInOut(duration: 0.35), value: shares.map(\.amount))
    }

    private func width(_ amount: Int, in total: CGFloat) -> CGFloat {
        guard deviation > 0 else { return 0 }
        return total * CGFloat(amount) / CGFloat(deviation)
    }
}

/// 지난 이레의 미해결 비율. 회색이 쌓이는 것을 보여준다.
struct WeekStrip: View {
    let history: [Int]        // 지난 6일
    let today: Int            // 오늘 남은 비율

    private var series: [Int] { Array(history.prefix(6)) + [today] }

    var body: some View {
        HStack(alignment: .bottom, spacing: 3) {
            ForEach(Array(series.enumerated()), id: \.offset) { idx, value in
                VStack(spacing: 3) {
                    ZStack(alignment: .bottom) {
                        RoundedRectangle(cornerRadius: 2)
                            .fill(Color.white.opacity(0.10))
                        RoundedRectangle(cornerRadius: 2)
                            .fill(value >= 60
                                  ? Color(red: 0.88, green: 0.51, blue: 0.41)
                                  : Color(white: 0.42))
                            .frame(height: max(2, 34 * CGFloat(value) / 100))
                    }
                    .frame(height: 34)
                    Text(idx == series.count - 1 ? "오늘" : "·")
                        .font(.system(size: 8))
                        .foregroundStyle(idx == series.count - 1
                                         ? .primary : .tertiary)
                }
            }
        }
        .animation(.easeInOut(duration: 0.35), value: today)
    }
}

/// 원인 하나를 켜고 끄는 칩. 탭 영역을 충분히 잡는다.
struct CauseChip: View {
    let cause: Cause
    let isOn: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                Circle()
                    .fill(cause.tint)
                    .frame(width: 8, height: 8)
                    .opacity(isOn ? 1 : 0.35)
                Text(cause.label)
                    .font(.system(size: 14, weight: isOn ? .semibold : .regular))
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
                Spacer(minLength: 0)
            }
            .padding(.vertical, 9)
            .padding(.horizontal, 11)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 9, style: .continuous)
                    .fill(Color.white.opacity(isOn ? 0.14 : 0.06))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 9, style: .continuous)
                    .strokeBorder(isOn ? cause.tint : .clear, lineWidth: 1.5)
            )
        }
        .buttonStyle(.plain)
    }
}

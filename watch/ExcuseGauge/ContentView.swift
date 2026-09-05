import SwiftUI

/// 아침에 한 번 보는 화면.
///
/// 세로로 한 번 굴리면 끝나도록 구성했다. 손목에서 30초 안에 끝나야 한다.
///   1) 어젯밤 얼마나 달랐나 (게이지)
///   2) 센서가 본 것
///   3) 어제 이런 일 있었나 (탭)
///   4) 판정
///   5) 이레치 누적
///
/// 시연용으로 날짜를 탭하면 시나리오가 바뀐다.
struct ContentView: View {
    @State private var nightIndex = 0
    @State private var picked: Set<Cause> = []

    private var night: Night { Night.all[nightIndex] }
    private var verdict: Verdict { Engine.evaluate(night: night, picked: picked) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                header
                gaugeBlock
                sensorBlock
                askBlock
                verdictBlock
                weekBlock
            }
            .padding(.horizontal, 2)
            .padding(.bottom, 8)
        }
        .navigationTitle("어젯밤")
    }

    // MARK: 머리

    private var header: some View {
        Button {
            nightIndex = (nightIndex + 1) % Night.all.count
            picked.removeAll()
        } label: {
            HStack(spacing: 4) {
                Text(night.date)
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
                Image(systemName: "arrow.triangle.2.circlepath")
                    .font(.system(size: 9))
                    .foregroundStyle(.tertiary)
                Spacer()
            }
        }
        .buttonStyle(.plain)
        .accessibilityLabel("시나리오 바꾸기. 현재 \(night.title)")
    }

    // MARK: 게이지

    private var gaugeBlock: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text("평소와 다른 정도")
                .font(.system(size: 12))
                .foregroundStyle(.secondary)

            GaugeView(deviation: night.deviation,
                      shares: verdict.shares,
                      alerting: verdict.alerting)

            // 범례 — 무엇이 얼마나 설명했는지
            FlowRow(spacing: 8) {
                ForEach(verdict.shares, id: \.cause) { share in
                    legendItem(color: share.cause.tint,
                               text: share.cause.short,
                               pct: pct(share.amount))
                }
                legendItem(color: verdict.alerting
                           ? Color(red: 0.88, green: 0.51, blue: 0.41)
                           : Color(white: 0.42),
                           text: "설명 안 됨",
                           pct: verdict.restPercent)
            }
        }
    }

    private func legendItem(color: Color, text: String, pct: Int) -> some View {
        HStack(spacing: 4) {
            RoundedRectangle(cornerRadius: 1.5)
                .fill(color)
                .frame(width: 7, height: 7)
            Text("\(text) \(pct)%")
                .font(.system(size: 11))
                .foregroundStyle(.secondary)
        }
    }

    private func pct(_ amount: Int) -> Int {
        guard night.deviation > 0 else { return 0 }
        return Int((Double(amount) / Double(night.deviation) * 100).rounded())
    }

    // MARK: 센서

    private var sensorBlock: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text("센서가 본 것")
                .font(.system(size: 10, weight: .medium))
                .foregroundStyle(.tertiary)
            Text(night.sensorNote)
                .font(.system(size: 13))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 9, style: .continuous)
                .fill(Color.white.opacity(0.06))
        )
    }

    // MARK: 질문

    private var askBlock: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text("어제 이런 일 있었나요?")
                .font(.system(size: 13, weight: .semibold))

            ForEach(Cause.allCases) { cause in
                CauseChip(cause: cause, isOn: picked.contains(cause)) {
                    if picked.contains(cause) { picked.remove(cause) }
                    else { picked.insert(cause) }
                }
            }

            Button("해당 없음") { picked.removeAll() }
                .font(.system(size: 12))
                .buttonStyle(.plain)
                .foregroundStyle(.tertiary)
                .padding(.top, 2)
        }
    }

    // MARK: 판정

    private var verdictBlock: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(verdict.headline)
                .font(.system(size: 15, weight: .bold))
                .foregroundStyle(verdict.alerting
                                 ? Color(red: 0.88, green: 0.51, blue: 0.41)
                                 : .primary)
            Text(verdict.detail)
                .font(.system(size: 13))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Text(verdict.footnote)
                .font(.system(size: 10))
                .foregroundStyle(.tertiary)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 2)
        }
        .padding(11)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(Color.white.opacity(0.06))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .strokeBorder(verdict.alerting
                              ? Color(red: 0.88, green: 0.51, blue: 0.41)
                              : .clear, lineWidth: 1)
        )
    }

    // MARK: 이레

    private var weekBlock: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("설명 안 된 밤")
                .font(.system(size: 10, weight: .medium))
                .foregroundStyle(.tertiary)
            WeekStrip(history: night.history, today: verdict.restPercent)
        }
    }
}

/// 좁은 화면에서 범례를 줄바꿈해 흘려 넣는다.
/// watchOS 에는 Grid 가 부담스러워 단순 래핑을 직접 만든다.
struct FlowRow<Content: View>: View {
    let spacing: CGFloat
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            content
        }
    }
}

#Preview {
    ContentView()
}

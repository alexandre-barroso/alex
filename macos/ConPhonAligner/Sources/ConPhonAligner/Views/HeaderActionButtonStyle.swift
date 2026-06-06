import SwiftUI

struct HeaderActionButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled

    enum Tone {
        case secondary
        case primary
        case destructive
    }

    let tone: Tone

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.callout.weight(.semibold))
            .lineLimit(1)
            .minimumScaleFactor(0.82)
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .frame(minHeight: 34)
            .foregroundStyle(foreground)
            .background {
                background(configuration: configuration)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
            }
            .overlay(
                RoundedRectangle(cornerRadius: 8)
                    .strokeBorder(border, lineWidth: tone == .secondary ? 1.2 : 0)
            )
            .shadow(color: shadow, radius: configuration.isPressed ? 1 : 4, x: 0, y: configuration.isPressed ? 0 : 2)
            .scaleEffect(configuration.isPressed ? 0.98 : 1.0)
            .opacity(isEnabled ? 1.0 : 0.48)
            .animation(.snappy(duration: 0.12), value: configuration.isPressed)
    }

    private var foreground: Color {
        switch tone {
        case .secondary:
            .accentColor
        case .primary, .destructive:
            .white
        }
    }

    private var border: Color {
        switch tone {
        case .secondary:
            .accentColor.opacity(0.48)
        case .primary, .destructive:
            .clear
        }
    }

    private var shadow: Color {
        switch tone {
        case .secondary:
            .accentColor.opacity(0.12)
        case .primary:
            .accentColor.opacity(0.26)
        case .destructive:
            .red.opacity(0.22)
        }
    }

    @ViewBuilder
    private func background(configuration: Configuration) -> some View {
        switch tone {
        case .secondary:
            Color.accentColor.opacity(configuration.isPressed ? 0.18 : 0.10)
        case .primary:
            LinearGradient(
                colors: [
                    Color.accentColor.opacity(configuration.isPressed ? 0.80 : 0.95),
                    Color.accentColor.opacity(configuration.isPressed ? 0.64 : 0.78)
                ],
                startPoint: .top,
                endPoint: .bottom
            )
        case .destructive:
            LinearGradient(
                colors: [
                    Color.red.opacity(configuration.isPressed ? 0.74 : 0.90),
                    Color.red.opacity(configuration.isPressed ? 0.60 : 0.74)
                ],
                startPoint: .top,
                endPoint: .bottom
            )
        }
    }
}

import SwiftUI

struct MarkdownPopupView: View {
    @Environment(\.dismiss) private var dismiss
    let title: String
    let markdown: String

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text(title)
                    .font(.title2.weight(.semibold))
                Spacer()
                Button {
                    dismiss()
                } label: {
                    Image(systemName: "xmark")
                }
                .buttonStyle(.bordered)
                .help("Fechar")
            }
            .padding(18)
            .background(.bar)

            Divider()

            ScrollView {
                Text(attributedMarkdown)
                    .font(.body)
                    .lineSpacing(4)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(22)
            }
        }
    }

    private var attributedMarkdown: AttributedString {
        (try? AttributedString(markdown: markdown, options: AttributedString.MarkdownParsingOptions(interpretedSyntax: .full))) ?? AttributedString(markdown)
    }
}

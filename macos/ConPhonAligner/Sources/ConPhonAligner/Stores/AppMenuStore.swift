import Foundation

@MainActor
final class AppMenuStore: ObservableObject {
    @Published var isShowingHelp = false
    @Published var isShowingAbout = false

    func showHelp() {
        isShowingHelp = true
    }

    func showAbout() {
        isShowingAbout = true
    }
}

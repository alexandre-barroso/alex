import SwiftUI

enum AppLanguage: String, CaseIterable, Identifiable {
    case portuguese = "pt"
    case english = "en"

    var id: String { rawValue }

    var shortTitle: String {
        switch self {
        case .portuguese: "PT"
        case .english: "EN"
        }
    }

    static func from(_ rawValue: String) -> AppLanguage {
        AppLanguage(rawValue: rawValue) ?? .portuguese
    }
}

func L(_ language: AppLanguage, _ portuguese: String, _ english: String) -> String {
    language == .portuguese ? portuguese : english
}

private struct AppLanguageKey: EnvironmentKey {
    static let defaultValue: AppLanguage = .portuguese
}

extension EnvironmentValues {
    var appLanguage: AppLanguage {
        get { self[AppLanguageKey.self] }
        set { self[AppLanguageKey.self] = newValue }
    }
}

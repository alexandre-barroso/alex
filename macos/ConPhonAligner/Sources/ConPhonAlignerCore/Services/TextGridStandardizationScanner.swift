import Foundation

public enum TextGridStandardizationScanner {
    public static func scan(rootURL: URL) throws -> TextGridStandardizationSummary {
        var textGridCount = 0
        var counts: [String: Int] = [:]
        try enumerateTextGrids(root: rootURL.standardizedFileURL) { file in
            textGridCount += 1
            autoreleasepool {
                for name in tierNames(file) {
                    counts[name, default: 0] += 1
                }
            }
        }
        let layers = counts
            .map { TextGridLayerOccurrence(name: $0.key, count: $0.value) }
            .sorted {
                if $0.count != $1.count { return $0.count > $1.count }
                return $0.name.localizedStandardCompare($1.name) == .orderedAscending
            }
        return TextGridStandardizationSummary(textGridCount: textGridCount, layers: layers)
    }

    public static func suggestedSelection(for summary: TextGridStandardizationSummary) -> TextGridStandardizationSelection {
        TextGridStandardizationSelection(
            phonemes: firstMatch(in: summary.layerNames, aliases: ["phonemes", "phones", "phoneme", "phone", "fonemas", "fonemas-ipa"]),
            words: firstMatch(in: summary.layerNames, aliases: ["words", "word", "pal_orto", "grafemas", "hanzi", "hanzis"]),
            syllables: firstMatch(in: summary.layerNames, aliases: ["syllables", "syllable", "syl", "syll", "sylls", "sil_fon", "pinyin", "pinyins"]),
            utterance: firstMatch(in: summary.layerNames, aliases: ["utterance", "utterances", "sentence", "sentences", "frase_orto", "frase_fon"])
        )
    }

    private static func firstMatch(in names: [String], aliases: Set<String>) -> String {
        for name in names where aliases.contains(normalized(name)) {
            return name
        }
        return ""
    }

    private static func normalized(_ value: String) -> String {
        value.trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
            .replacingOccurrences(of: "-", with: "_")
            .replacingOccurrences(of: " ", with: "_")
    }

    private static func tierNames(_ url: URL) -> [String] {
        guard let text = try? String(contentsOf: url, encoding: .utf8),
              let regex = try? NSRegularExpression(pattern: #"name\s*=\s*"([^"]+)""#) else {
            return []
        }
        let range = NSRange(text.startIndex..<text.endIndex, in: text)
        return regex.matches(in: text, range: range).compactMap { match in
            guard let matchRange = Range(match.range(at: 1), in: text) else { return nil }
            return String(text[matchRange])
        }
    }

    private static func enumerateTextGrids(root: URL, visit: (URL) throws -> Void) throws {
        guard let enumerator = FileManager.default.enumerator(
            at: root,
            includingPropertiesForKeys: [.isRegularFileKey, .isDirectoryKey],
            options: [.skipsHiddenFiles]
        ) else {
            return
        }
        let skipped = Set(["original_textgrid_layers", "original_wav", "data", "dist", ".build"])
        for case let url as URL in enumerator {
            let values = try url.resourceValues(forKeys: [.isRegularFileKey, .isDirectoryKey])
            if values.isDirectory == true, skipped.contains(url.lastPathComponent) {
                enumerator.skipDescendants()
                continue
            }
            if values.isRegularFile == true, url.pathExtension.lowercased() == "textgrid" {
                try visit(url.standardizedFileURL)
            }
        }
    }
}

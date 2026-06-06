import Foundation

public enum BioEarFolderScannerError: LocalizedError, Equatable {
    case notDirectory(String)

    public var errorDescription: String? {
        switch self {
        case .notDirectory(let path): "Não é uma pasta: \(path)"
        }
    }
}

public enum BioEarFolderScanner {
    public static let requiredTiers = ["camada 1 fonemas", "camada 2 palavras", "camada 3 silabas", "camada 4 frases"]
    private static let skippedDirectoryNames = Set(["corpora", "data", "original_wav", "results", "resultados", "dist", ".build"])
    private static let knownTierNames: [String: Set<String>] = [
        "phone": ["fonemas", "fonemas_ipa", "phone", "phones", "phoneme", "phonemes"],
        "word": ["pal_orto", "grafemas", "word", "words", "ortografia", "orthography", "hanzi", "hanzis"],
        "syllable": ["sil_fon", "silabas_fonemas", "silabas_fonemas_ipa", "syllable", "syllables", "syl", "syll", "sylls", "pinyin", "pinyins"],
        "sentence": ["frase_orto", "frase_grafemas", "frase_fon", "frase_fonemas", "frase_fonemas_ipa", "sentence", "sentences", "utterance", "utterances"]
    ]
    private static let mandarinHanziTierNames: Set<String> = ["hanzi", "hanzis", "hanzi_words", "characters", "chars", "words", "汉字", "漢字"]
    private static let mandarinPinyinTierNames: Set<String> = ["pinyin", "pinyins", "pinying", "pinyings", "syllable", "syllables"]
    private static let mandarinPhoneTierNames: Set<String> = ["phone", "phones", "phoneme", "phonemes"]

    public static func scan(rootURL: URL) throws -> BioEarScanSummary {
        let root = rootURL.standardizedFileURL
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: root.path, isDirectory: &isDirectory),
              isDirectory.boolValue else {
            throw BioEarFolderScannerError.notDirectory(root.path)
        }

        let files = try regularFiles(root: root)
        let txtByKey = filesByKey(files, extensionName: "txt")
        let textGridByKey = filesByKey(files, extensionName: "textgrid")
        let audioFiles = selectedAudioFiles(files)
            .sorted { $0.path.localizedStandardCompare($1.path) == .orderedAscending }

        var pairs: [BioEarExtractionPair] = []
        var unmatchedAudio = 0
        for audio in audioFiles {
            let key = BioEarPairKey(folder: audio.deletingLastPathComponent().standardizedFileURL.path, stem: audio.deletingPathExtension().lastPathComponent)
            guard let textGrid = textGridByKey[key] else {
                unmatchedAudio += 1
                pairs.append(makePair(wav: audio, txt: txtByKey[key], textGrid: nil))
                continue
            }
            pairs.append(makePair(wav: audio, txt: txtByKey[key], textGrid: textGrid))
        }

        let pairedKeys = Set(pairs.compactMap { pair -> BioEarPairKey? in
            guard pair.textGridURL != nil else { return nil }
            return BioEarPairKey(folder: pair.wavURL.deletingLastPathComponent().standardizedFileURL.path, stem: pair.wavURL.deletingPathExtension().lastPathComponent)
        })
        let unmatchedTextGrids = textGridByKey.keys.filter { !pairedKeys.contains($0) }.count

        return BioEarScanSummary(
            rootURL: root,
            pairs: pairs,
            unmatchedWAVCount: unmatchedAudio,
            unmatchedTextGridCount: unmatchedTextGrids,
            outputState: outputState(rootURL: root, pairs: pairs)
        )
    }

    public static func datasetSlug(for rootURL: URL) -> String {
        let raw = rootURL.deletingPathExtension().lastPathComponent
        let scalars = raw.lowercased().unicodeScalars.map { scalar -> Character in
            CharacterSet.alphanumerics.contains(scalar) ? Character(scalar) : "_"
        }
        let collapsed = String(scalars)
            .split(separator: "_")
            .joined(separator: "_")
        return collapsed.isEmpty ? "conphon_custom" : collapsed
    }

    public static func outputState(rootURL: URL) -> BioEarOutputState {
        outputState(rootURL: rootURL, pairs: [])
    }

    public static func outputState(rootURL: URL, pairs: [BioEarExtractionPair]) -> BioEarOutputState {
        let root = rootURL.standardizedFileURL
        let slug = datasetSlug(for: root)
        let datasetRoot = root.appendingPathComponent("data", isDirectory: true).appendingPathComponent("corpus", isDirectory: true)
        let dataAuditory = datasetRoot
        let dataBioEar = datasetRoot.appendingPathComponent("bioear", isDirectory: true)
        let dataCandidates = [dataBioEar]
        let existingData = dataCandidates.filter { FileManager.default.fileExists(atPath: $0.path) }
        let generatedData = existingData + sidecarOutputState(pairs: pairs)
        let unmarkedData: [URL] = []
        return BioEarOutputState(
            datasetSlug: slug,
            dataAuditoryURL: dataAuditory,
            dataBioEarURL: dataBioEar,
            existingGeneratedDataOutputs: generatedData,
            existingUnmarkedDataOutputs: unmarkedData
        )
    }

    private static func sidecarOutputState(pairs: [BioEarExtractionPair]) -> [URL] {
        var generated: [URL] = []
        for pair in pairs where pair.textGridURL != nil {
            let base = pair.wavURL.deletingPathExtension()
            let output = URL(fileURLWithPath: base.path + BioEarOutputMarkers.bioearSuffix)
            if FileManager.default.fileExists(atPath: output.path) {
                generated.append(output)
            }
        }
        return generated
    }

    private static func makePair(wav: URL, txt: URL?, textGrid: URL?) -> BioEarExtractionPair {
        let presentTiers: [String]
        let missingTiers: [String]
        if let textGrid {
            let resolution = tierResolution(textGridTiers(textGrid), textGridURL: textGrid)
            presentTiers = resolution.present
            missingTiers = resolution.missing
        } else {
            presentTiers = []
            missingTiers = requiredTiers
        }

        guard AudioFileSupport.isWAV(wav) else {
            let status: BioEarPairStatus
            if textGrid == nil {
                status = .missingTextGrid
            } else if txt == nil {
                status = .missingTXT
            } else if !missingTiers.isEmpty {
                status = .missingTiers
            } else {
                status = .needsWAVConversion
            }
            return BioEarExtractionPair(
                wavURL: wav,
                txtURL: txt,
                textGridURL: textGrid,
                audioInfo: nil,
                audioError: "Will be converted to \(AudioFileSupport.targetWAVURL(for: wav).lastPathComponent) before BioEar extraction.",
                presentTiers: presentTiers,
                missingTiers: missingTiers,
                status: status
            )
        }
        do {
            let info = try AudioInspector.inspect(wav)
            let status: BioEarPairStatus
            if textGrid == nil {
                status = .missingTextGrid
            } else if txt == nil {
                status = .missingTXT
            } else if !missingTiers.isEmpty {
                status = .missingTiers
            } else if !info.isMono16kHz {
                status = .needsWAVConversion
            } else {
                status = .ready
            }
            return BioEarExtractionPair(
                wavURL: wav,
                txtURL: txt,
                textGridURL: textGrid,
                audioInfo: info,
                audioError: nil,
                presentTiers: presentTiers,
                missingTiers: missingTiers,
                status: status
            )
        } catch {
            return BioEarExtractionPair(
                wavURL: wav,
                txtURL: txt,
                textGridURL: textGrid,
                audioInfo: nil,
                audioError: error.localizedDescription,
                presentTiers: presentTiers,
                missingTiers: missingTiers,
                status: .invalidWAV
            )
        }
    }

    private static func textGridTiers(_ url: URL) -> [String] {
        guard let text = try? String(contentsOf: url, encoding: .utf8) else { return [] }
        let pattern = #"name\s*=\s*"([^"]+)""#
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return [] }
        let range = NSRange(text.startIndex..<text.endIndex, in: text)
        var tiers: [String] = []
        for match in regex.matches(in: text, range: range) {
            guard let matchRange = Range(match.range(at: 1), in: text) else { continue }
            tiers.append(String(text[matchRange]))
        }
        return tiers
    }

    private static func tierResolution(_ tiers: [String], textGridURL: URL) -> (present: [String], missing: [String]) {
        let normalized = tiers.map(normalizedTierName)
        let pathDeclaresMandarin = textGridURL.path.lowercased().contains("mandarin") || textGridURL.path.lowercased().contains("corpus_chinese")
        if normalized.count == 3,
           (pathDeclaresMandarin || (
                mandarinHanziTierNames.contains(normalized[0])
                && mandarinPinyinTierNames.contains(normalized[1])
                && mandarinPhoneTierNames.contains(normalized[2])
           )) {
            return (
                [
                    "phone: Mandarin layer 3 phones",
                    "word: Mandarin layer 1 hanzis",
                    "syllable: Mandarin layer 1 hanzis",
                    "sentence: synthesized from Mandarin pinyin tier"
                ],
                []
            )
        }

        let named = knownLevelsByTier(normalized)
        if ["phone", "word", "syllable", "sentence"].allSatisfy({ named[$0] != nil }) {
            return (
                ["phone: \(named["phone"]!)", "word: \(named["word"]!)", "syllable: \(named["syllable"]!)", "sentence: \(named["sentence"]!)"],
                []
            )
        }
        if ["phone", "word", "syllable"].allSatisfy({ named[$0] != nil }) {
            return (
                ["phone: \(named["phone"]!)", "word: \(named["word"]!)", "syllable: \(named["syllable"]!)", "sentence: synthesized from word tier"],
                []
            )
        }
        if tiers.count >= 4 {
            return (requiredTiers + tiers, [])
        }
        if tiers.count == 3 {
            return (
                ["phone: layer 1", "word: layer 2", "syllable: layer 3", "sentence: synthesized from word tier"],
                []
            )
        }
        let present = tiers.isEmpty ? [] : tiers
        return (present, requiredTiers.filter { !present.contains($0) })
    }

    private static func normalizedTierName(_ tier: String) -> String {
        tier.trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
            .replacingOccurrences(of: "-", with: "_")
            .replacingOccurrences(of: " ", with: "_")
    }

    private static func knownLevelsByTier(_ normalizedTiers: [String]) -> [String: String] {
        var result: [String: String] = [:]
        var duplicateLevels = Set<String>()
        for name in normalizedTiers {
            let matches = knownTierNames.compactMap { level, names in
                names.contains(name) ? level : nil
            }
            guard matches.count == 1 else { continue }
            let level = matches[0]
            if result[level] != nil {
                duplicateLevels.insert(level)
                continue
            }
            result[level] = name
        }
        for level in duplicateLevels {
            result.removeValue(forKey: level)
        }
        return result
    }

    private static func filesByKey(_ files: [URL], extensionName: String) -> [BioEarPairKey: URL] {
        var result: [BioEarPairKey: URL] = [:]
        for url in files where url.pathExtension.lowercased() == extensionName {
            let key = BioEarPairKey(folder: url.deletingLastPathComponent().standardizedFileURL.path, stem: url.deletingPathExtension().lastPathComponent)
            result[key] = url.standardizedFileURL
        }
        return result
    }

    private static func selectedAudioFiles(_ files: [URL]) -> [URL] {
        let audio = files
            .filter(AudioFileSupport.isSupportedAudio)
            .map(\.standardizedFileURL)
        var selectedByKey: [BioEarPairKey: URL] = [:]
        for url in audio {
            let key = BioEarPairKey(folder: url.deletingLastPathComponent().standardizedFileURL.path, stem: url.deletingPathExtension().lastPathComponent)
            if let existing = selectedByKey[key] {
                if !AudioFileSupport.isWAV(existing), AudioFileSupport.isWAV(url) {
                    selectedByKey[key] = url
                }
            } else {
                selectedByKey[key] = url
            }
        }
        return Array(selectedByKey.values)
    }

    private static func regularFiles(root: URL) throws -> [URL] {
        guard let enumerator = FileManager.default.enumerator(
            at: root,
            includingPropertiesForKeys: [.isRegularFileKey, .isDirectoryKey],
            options: [.skipsHiddenFiles]
        ) else {
            return []
        }
        var files: [URL] = []
        for case let url as URL in enumerator {
            let values = try url.resourceValues(forKeys: [.isRegularFileKey, .isDirectoryKey])
            if values.isDirectory == true, skippedDirectoryNames.contains(url.lastPathComponent) {
                enumerator.skipDescendants()
                continue
            }
            if values.isRegularFile == true {
                files.append(url)
            }
        }
        return files
    }
}

private struct BioEarPairKey: Hashable {
    let folder: String
    let stem: String
}

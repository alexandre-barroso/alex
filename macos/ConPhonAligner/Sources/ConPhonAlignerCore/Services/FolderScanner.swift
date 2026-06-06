import Foundation

public enum FolderScannerError: LocalizedError, Equatable {
    case notDirectory(String)

    public var errorDescription: String? {
        switch self {
        case .notDirectory(let path): "Não é uma pasta: \(path)"
        }
    }
}

public enum FolderScanner {
    public static func scan(rootURL: URL) throws -> FolderScanSummary {
        let root = rootURL.standardizedFileURL
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: root.path, isDirectory: &isDirectory),
              isDirectory.boolValue else {
            throw FolderScannerError.notDirectory(root.path)
        }

        let txtByFolderAndStem = try collectTextFiles(root: root)
        let audioFiles = try collectAudioFiles(root: root)

        var pairs: [AlignmentPair] = []
        var unmatchedAudio = 0
        for audio in audioFiles.sorted(by: { $0.path.localizedStandardCompare($1.path) == .orderedAscending }) {
            let key = PairKey(folder: audio.deletingLastPathComponent().standardizedFileURL.path, stem: audio.deletingPathExtension().lastPathComponent)
            guard let txt = txtByFolderAndStem[key] else {
                unmatchedAudio += 1
                continue
            }
            pairs.append(makePair(audio: audio, txt: txt))
        }

        let pairedTXTIDs = Set(pairs.map { PairKey(folder: $0.txtURL.deletingLastPathComponent().standardizedFileURL.path, stem: $0.txtURL.deletingPathExtension().lastPathComponent) })
        let unmatchedTXTs = txtByFolderAndStem.keys.filter { !pairedTXTIDs.contains($0) }.count

        return FolderScanSummary(
            rootURL: root,
            pairs: pairs,
            unmatchedWAVCount: unmatchedAudio,
            unmatchedTXTCount: unmatchedTXTs
        )
    }

    private static func makePair(audio: URL, txt: URL) -> AlignmentPair {
        let textGrid = audio.deletingPathExtension().appendingPathExtension("TextGrid")
        guard AudioFileSupport.isWAV(audio) else {
            return AlignmentPair(
                wavURL: audio,
                txtURL: txt,
                textGridURL: textGrid,
                audioInfo: nil,
                audioError: "Will be converted to \(AudioFileSupport.targetWAVURL(for: audio).lastPathComponent) before alignment.",
                status: .needsWAVConversion
            )
        }
        do {
            let info = try AudioInspector.inspect(audio)
            let status: PairStatus
            if !info.isMono16kHz {
                status = .needsWAVConversion
            } else if FileManager.default.fileExists(atPath: textGrid.path) {
                status = .textGridExists
            } else {
                status = .ready
            }
            return AlignmentPair(
                wavURL: audio,
                txtURL: txt,
                textGridURL: textGrid,
                audioInfo: info,
                audioError: nil,
                status: status
            )
        } catch {
            return AlignmentPair(
                wavURL: audio,
                txtURL: txt,
                textGridURL: textGrid,
                audioInfo: nil,
                audioError: error.localizedDescription,
                status: .invalidWAV
            )
        }
    }

    private static func collectTextFiles(root: URL) throws -> [PairKey: URL] {
        var result: [PairKey: URL] = [:]
        for url in try regularFiles(root: root) where url.pathExtension.lowercased() == "txt" {
            let key = PairKey(folder: url.deletingLastPathComponent().standardizedFileURL.path, stem: url.deletingPathExtension().lastPathComponent)
            result[key] = url.standardizedFileURL
        }
        return result
    }

    private static func collectAudioFiles(root: URL) throws -> [URL] {
        let audio = try regularFiles(root: root)
            .filter(AudioFileSupport.isSupportedAudio)
            .map(\.standardizedFileURL)
        var selectedByKey: [PairKey: URL] = [:]
        for url in audio {
            let key = PairKey(folder: url.deletingLastPathComponent().standardizedFileURL.path, stem: url.deletingPathExtension().lastPathComponent)
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
            includingPropertiesForKeys: [.isRegularFileKey],
            options: [.skipsHiddenFiles]
        ) else {
            return []
        }
        var files: [URL] = []
        for case let url as URL in enumerator {
            let values = try url.resourceValues(forKeys: [.isRegularFileKey])
            if values.isRegularFile == true {
                files.append(url)
            }
        }
        return files
    }
}

private struct PairKey: Hashable {
    let folder: String
    let stem: String
}

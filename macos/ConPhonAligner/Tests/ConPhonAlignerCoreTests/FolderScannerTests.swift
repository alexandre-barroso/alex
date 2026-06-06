import Foundation
import Testing
@testable import ConPhonAlignerCore

@Suite("Folder scanner")
struct FolderScannerTests {
    @Test("finds recursive pairs and ignores unrelated files")
    func scannerFindsRecursivePairsAndIgnoresExtraFiles() throws {
        let root = try makeTemporaryDirectory()
        let nested = root.appendingPathComponent("nested", isDirectory: true)
        try FileManager.default.createDirectory(at: nested, withIntermediateDirectories: true)
        try writeWAV(nested.appendingPathComponent("one.wav"), sampleRate: 16_000, channels: 1)
        try "text".write(to: nested.appendingPathComponent("one.txt"), atomically: true, encoding: .utf8)
        try "ignored".write(to: nested.appendingPathComponent("notes.md"), atomically: true, encoding: .utf8)

        let scan = try FolderScanner.scan(rootURL: root)

        #expect(scan.isSelectable)
        #expect(scan.pairs.count == 1)
        #expect(scan.readyCount == 1)
        #expect(scan.unmatchedWAVCount == 0)
        #expect(scan.unmatchedTXTCount == 0)
    }

    @Test("rejects folders with no same-folder same-stem pairs")
    func scannerRejectsFoldersWithNoPairs() throws {
        let root = try makeTemporaryDirectory()
        try writeWAV(root.appendingPathComponent("one.wav"), sampleRate: 16_000, channels: 1)
        try "orphan".write(to: root.appendingPathComponent("two.txt"), atomically: true, encoding: .utf8)

        let scan = try FolderScanner.scan(rootURL: root)

        #expect(!scan.isSelectable)
        #expect(scan.pairs.count == 0)
        #expect(scan.unmatchedWAVCount == 1)
        #expect(scan.unmatchedTXTCount == 1)
    }

    @Test("marks existing TextGrid pairs complete")
    func existingTextGridMarksPairComplete() throws {
        let root = try makeTemporaryDirectory()
        try writeWAV(root.appendingPathComponent("one.wav"), sampleRate: 16_000, channels: 1)
        try "text".write(to: root.appendingPathComponent("one.txt"), atomically: true, encoding: .utf8)
        try "TextGrid".write(to: root.appendingPathComponent("one.TextGrid"), atomically: true, encoding: .utf8)

        let scan = try FolderScanner.scan(rootURL: root)

        #expect(scan.pairs.first?.status == .textGridExists)
        #expect(scan.readyCount == 1)
        #expect(scan.readyToCreateCount == 0)
        #expect(scan.existingTextGridCount == 1)
        #expect(scan.isComplete)
        #expect(!scan.canCreateTextGrids)
    }

    @Test("flags non-mono or non-16 kHz WAVs for conversion")
    func nonMonoOrNon16kMarksPairForConversion() throws {
        let root = try makeTemporaryDirectory()
        try writeWAV(root.appendingPathComponent("one.wav"), sampleRate: 44_100, channels: 2)
        try "text".write(to: root.appendingPathComponent("one.txt"), atomically: true, encoding: .utf8)

        let scan = try FolderScanner.scan(rootURL: root)

        #expect(scan.pairs.first?.status == .needsWAVConversion)
        #expect(scan.conversionCount == 1)
        #expect(scan.canCreateTextGrids)
    }

    @Test("accepts non-WAV audio for Portuguese conversion before alignment")
    func nonWAVAudioMarksPortuguesePairForConversion() throws {
        let root = try makeTemporaryDirectory()
        try Data("not actually flac, scanner only preflights extension".utf8).write(to: root.appendingPathComponent("one.flac"))
        try "text".write(to: root.appendingPathComponent("one.txt"), atomically: true, encoding: .utf8)

        let scan = try FolderScanner.scan(rootURL: root)

        #expect(scan.pairs.count == 1)
        #expect(scan.pairs.first?.status == .needsWAVConversion)
        #expect(scan.pairs.first?.textGridURL.lastPathComponent == "one.TextGrid")
        #expect(scan.canCreateTextGrids)
    }

    @Test("blocks alignment when a matched WAV cannot be inspected")
    func invalidWAVBlocksAlignment() throws {
        let root = try makeTemporaryDirectory()
        try "not wav".write(to: root.appendingPathComponent("bad.wav"), atomically: true, encoding: .utf8)
        try "text".write(to: root.appendingPathComponent("bad.txt"), atomically: true, encoding: .utf8)
        try writeWAV(root.appendingPathComponent("good.wav"), sampleRate: 16_000, channels: 1)
        try "text".write(to: root.appendingPathComponent("good.txt"), atomically: true, encoding: .utf8)

        let scan = try FolderScanner.scan(rootURL: root)

        #expect(scan.invalidWAVCount == 1)
        #expect(scan.readyCount == 1)
        #expect(!scan.canCreateTextGrids)
    }

    @Test("alignment command uses mono acoustic model and skip-existing")
    func alignmentCommandUsesMonoAndSkipExisting() throws {
        let repo = URL(fileURLWithPath: "/tmp/repo")
        let folder = URL(fileURLWithPath: "/tmp/repo/corpus")
        let command = AlignerCommandBuilder.alignmentCommand(repoRoot: repo, selectedFolder: folder, pythonPath: "/usr/bin/python3")

        #expect(command.executable == "/usr/bin/python3")
        #expect(command.arguments[0] == "/tmp/repo/macos/ConPhonAligner/Tools/run_aligner.py")
        #expect(command.arguments.contains("--am-tag"))
        #expect(command.arguments.contains("mono"))
        #expect(command.arguments.contains("--skip-existing"))
        #expect(!command.arguments.contains("--no-skip-existing"))
        #expect(command.arguments.contains("--continue-on-error"))
        #expect(!command.arguments.contains("--overwrite"))
    }

    @Test("alignment command can replace existing TextGrids")
    func alignmentCommandCanReplaceExistingTextGrids() throws {
        let repo = URL(fileURLWithPath: "/tmp/repo")
        let folder = URL(fileURLWithPath: "/tmp/repo/corpus")
        let command = AlignerCommandBuilder.alignmentCommand(
            repoRoot: repo,
            selectedFolder: folder,
            pythonPath: "/usr/bin/python3",
            replaceExistingTextGrids: true
        )

        #expect(command.arguments.contains("--no-skip-existing"))
        #expect(!command.arguments.contains("--skip-existing"))
        #expect(command.arguments.contains("--continue-on-error"))
    }

    @Test("Bioear scanner finds recursive WAV TextGrid TXT triples")
    func bioearScannerFindsRecursiveTriples() throws {
        let root = try makeTemporaryDirectory()
        let nested = root.appendingPathComponent("nested", isDirectory: true)
        try FileManager.default.createDirectory(at: nested, withIntermediateDirectories: true)
        try writeWAV(nested.appendingPathComponent("one.wav"), sampleRate: 16_000, channels: 1)
        try "text".write(to: nested.appendingPathComponent("one.txt"), atomically: true, encoding: .utf8)
        try tinyTextGrid().write(to: nested.appendingPathComponent("one.TextGrid"), atomically: true, encoding: .utf8)

        let scan = try BioEarFolderScanner.scan(rootURL: root)

        #expect(scan.isSelectable)
        #expect(scan.pairs.count == 1)
        #expect(scan.readyCount == 1)
        #expect(scan.canExtract)
    }

    @Test("Bioear scanner accepts three-tier TextGrids by synthesizing sentence")
    func bioearScannerAcceptsThreeTierSentenceFallback() throws {
        let root = try makeTemporaryDirectory()
        try writeWAV(root.appendingPathComponent("three.wav"), sampleRate: 16_000, channels: 1)
        try "text".write(to: root.appendingPathComponent("three.txt"), atomically: true, encoding: .utf8)
        try threeTierTextGrid().write(to: root.appendingPathComponent("three.TextGrid"), atomically: true, encoding: .utf8)

        let scan = try BioEarFolderScanner.scan(rootURL: root)

        #expect(scan.readyCount == 1)
        #expect(scan.canExtract)
        #expect(scan.pairs.first?.presentTiers.contains("sentence: synthesized from word tier") == true)
    }

    @Test("Bioear scanner resolves named tiers in any order")
    func bioearScannerResolvesNamedTiersInAnyOrder() throws {
        let root = try makeTemporaryDirectory()
        try writeWAV(root.appendingPathComponent("named.wav"), sampleRate: 16_000, channels: 1)
        try "text".write(to: root.appendingPathComponent("named.txt"), atomically: true, encoding: .utf8)
        try shuffledNamedTextGrid().write(to: root.appendingPathComponent("named.TextGrid"), atomically: true, encoding: .utf8)

        let scan = try BioEarFolderScanner.scan(rootURL: root)

        #expect(scan.readyCount == 1)
        #expect(scan.canExtract)
        #expect(scan.pairs.first?.presentTiers.contains("phone: phonemes") == true)
        #expect(scan.pairs.first?.presentTiers.contains("syllable: syl") == true)
        #expect(scan.pairs.first?.presentTiers.contains("sentence: utterance") == true)
    }

    @Test("Bioear accepts non-WAV audio for conversion before extraction")
    func bioearScannerAcceptsNonWAVAudioForConversion() throws {
        let root = try makeTemporaryDirectory()
        try Data("not actually mp3, scanner only preflights extension".utf8).write(to: root.appendingPathComponent("voice.mp3"))
        try "text".write(to: root.appendingPathComponent("voice.txt"), atomically: true, encoding: .utf8)
        try threeTierTextGrid().write(to: root.appendingPathComponent("voice.TextGrid"), atomically: true, encoding: .utf8)

        let scan = try BioEarFolderScanner.scan(rootURL: root)

        #expect(scan.pairs.count == 1)
        #expect(scan.conversionCount == 1)
        #expect(scan.pairs.first?.status == .needsWAVConversion)
        #expect(scan.canExtract)
    }

    @Test("Bioear scanner blocks missing TXT and missing layer tiers")
    func bioearScannerBlocksMissingTXTAndTiers() throws {
        let root = try makeTemporaryDirectory()
        try writeWAV(root.appendingPathComponent("missing_txt.wav"), sampleRate: 16_000, channels: 1)
        try tinyTextGrid().write(to: root.appendingPathComponent("missing_txt.TextGrid"), atomically: true, encoding: .utf8)
        try writeWAV(root.appendingPathComponent("bad_tiers.wav"), sampleRate: 16_000, channels: 1)
        try "text".write(to: root.appendingPathComponent("bad_tiers.txt"), atomically: true, encoding: .utf8)
        try badTextGrid().write(to: root.appendingPathComponent("bad_tiers.TextGrid"), atomically: true, encoding: .utf8)

        let scan = try BioEarFolderScanner.scan(rootURL: root)

        #expect(scan.pairs.contains { $0.status == .missingTXT })
        #expect(scan.pairs.contains { $0.status == .missingTiers })
        #expect(scan.blockedCount == 2)
        #expect(!scan.canExtract)
    }

    @Test("Bioear scanner flags invalid WAVs and generated HDF5 outputs")
    func bioearScannerFlagsInvalidWAVsAndOutputMarkers() throws {
        let root = try makeTemporaryDirectory()
        try "not wav".write(to: root.appendingPathComponent("bad.wav"), atomically: true, encoding: .utf8)
        try "text".write(to: root.appendingPathComponent("bad.txt"), atomically: true, encoding: .utf8)
        try tinyTextGrid().write(to: root.appendingPathComponent("bad.TextGrid"), atomically: true, encoding: .utf8)
        let state = BioEarFolderScanner.outputState(rootURL: root)
        try FileManager.default.createDirectory(at: state.dataBioEarURL, withIntermediateDirectories: true)
        let sidecar = root.appendingPathComponent("bad_bioear.h5")
        try Data().write(to: sidecar)

        let scan = try BioEarFolderScanner.scan(rootURL: root)

        #expect(scan.invalidWAVCount == 1)
        #expect(scan.outputState.existingGeneratedDataOutputs == [state.dataBioEarURL, sidecar])
    }

    @Test("Bioear run command passes replacement flag")
    func bioearRunCommandPassesReplacementFlag() throws {
        let repo = URL(fileURLWithPath: "/tmp/repo")
        let folder = URL(fileURLWithPath: "/tmp/repo/custom")
        let settings = BioEarExtractionSettings(
            profile: .contextLite,
            jobs: 12,
            threadsPerFile: 2,
            auxiliary: BioEarAuxiliarySelection(includeIHC: true, includeSynapseDrive: true, includeRedocking: true)
        )
        let command = BioEarCommandBuilder.runCommand(
            repoRoot: repo,
            inputFolder: folder,
            replaceConfirmed: true,
            settings: settings,
            pythonPath: "/usr/bin/python3"
        )

        #expect(command.arguments[0] == "/tmp/repo/macos/ConPhonAligner/Tools/extract_bioear.py")
        #expect(command.arguments.contains("run"))
        #expect(command.arguments.contains("--replace-confirmed"))
        #expect(command.arguments.contains("--profile"))
        #expect(command.arguments.contains("context-lite"))
        #expect(command.arguments.contains("--jobs"))
        #expect(command.arguments.contains("12"))
        #expect(command.arguments.contains("--language-tag"))
        #expect(command.arguments.contains("cust"))
        #expect(!command.arguments.contains("--mfcc-sidecars"))
        #expect(!command.arguments.contains("--phonetic-details"))
    }

    @Test("Bioear rich command passes selected components and worker settings")
    func bioearRichCommandPassesSelectedComponentsAndWorkerSettings() throws {
        let repo = URL(fileURLWithPath: "/tmp/repo")
        let folder = URL(fileURLWithPath: "/tmp/repo/custom")
        let settings = BioEarExtractionSettings(
            profile: .balanced,
            jobs: 6,
            threadsPerFile: 2,
            auxiliary: BioEarAuxiliarySelection(includeIHC: false, includeSynapseDrive: true, includeRedocking: true)
        )

        let command = BioEarCommandBuilder.richAuxCommand(
            repoRoot: repo,
            inputFolder: folder,
            replaceConfirmed: true,
            settings: settings,
            pythonPath: "/usr/bin/python3"
        )

        #expect(command.arguments[0] == "/tmp/repo/macos/ConPhonAligner/Tools/append_bioear_aux.py")
        #expect(command.arguments.contains("--components"))
        #expect(command.arguments.contains("synapse,redocking"))
        #expect(command.arguments.contains("--jobs"))
        #expect(command.arguments.contains("6"))
        #expect(command.arguments.contains("--threads-per-file"))
        #expect(command.arguments.contains("2"))
        #expect(command.arguments.contains("--replace-confirmed"))
    }

    @Test("TextGrid standardizer scans layers and builds picker command")
    func textGridStandardizerScansLayersAndBuildsCommand() throws {
        let root = try makeTemporaryDirectory()
        try shuffledNamedTextGrid().write(to: root.appendingPathComponent("named.TextGrid"), atomically: true, encoding: .utf8)

        let summary = try TextGridStandardizationScanner.scan(rootURL: root)
        let selection = TextGridStandardizationScanner.suggestedSelection(for: summary)
        let command = BioEarCommandBuilder.textGridStandardizationCommand(
            repoRoot: URL(fileURLWithPath: "/tmp/repo"),
            inputFolder: root,
            selection: selection,
            pythonPath: "/usr/bin/python3"
        )

        #expect(summary.textGridCount == 1)
        #expect(selection.phonemes == "phonemes")
        #expect(selection.words == "words")
        #expect(selection.syllables == "syl")
        #expect(selection.utterance == "utterance")
        #expect(command.arguments.contains("--phone"))
        #expect(command.arguments.contains("phonemes"))
        #expect(command.arguments.contains("--syllable"))
        #expect(command.arguments.contains("syl"))
    }

    private func makeTemporaryDirectory() throws -> URL {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("ConPhonAlignerTests", isDirectory: true)
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        return root
    }

    private func writeWAV(_ url: URL, sampleRate: Int, channels: Int) throws {
        let frames = 32
        let bitsPerSample = 16
        let bytesPerSample = bitsPerSample / 8
        let dataSize = frames * channels * bytesPerSample
        var data = Data()
        data.appendASCII("RIFF")
        data.appendUInt32LE(UInt32(36 + dataSize))
        data.appendASCII("WAVE")
        data.appendASCII("fmt ")
        data.appendUInt32LE(16)
        data.appendUInt16LE(1)
        data.appendUInt16LE(UInt16(channels))
        data.appendUInt32LE(UInt32(sampleRate))
        data.appendUInt32LE(UInt32(sampleRate * channels * bytesPerSample))
        data.appendUInt16LE(UInt16(channels * bytesPerSample))
        data.appendUInt16LE(UInt16(bitsPerSample))
        data.appendASCII("data")
        data.appendUInt32LE(UInt32(dataSize))
        data.append(Data(repeating: 0, count: dataSize))
        try data.write(to: url)
    }

    private func tinyTextGrid() -> String {
        """
        File type = "ooTextFile"
        Object class = "TextGrid"

        xmin = 0.0
        xmax = 0.65
        tiers? <exists>
        size = 5
        item []:
            item [1]:
                class = "IntervalTier"
                name = "fonemas"
                xmin = 0.0
                xmax = 0.65
                intervals: size = 2
                    intervals [1]:
                        xmin = 0.0
                        xmax = 0.30
                        text = "a"
                    intervals [2]:
                        xmin = 0.30
                        xmax = 0.65
                        text = "p"
            item [2]:
                class = "IntervalTier"
                name = "pal_orto"
                xmin = 0.0
                xmax = 0.65
                intervals: size = 1
                    intervals [1]:
                        xmin = 0.0
                        xmax = 0.65
                        text = "apa"
            item [3]:
                class = "IntervalTier"
                name = "sil_fon"
                xmin = 0.0
                xmax = 0.65
                intervals: size = 1
                    intervals [1]:
                        xmin = 0.0
                        xmax = 0.65
                        text = "a p"
            item [4]:
                class = "IntervalTier"
                name = "frase_fon"
                xmin = 0.0
                xmax = 0.65
                intervals: size = 1
                    intervals [1]:
                        xmin = 0.0
                        xmax = 0.65
                        text = "a p a"
            item [5]:
                class = "IntervalTier"
                name = "frase_orto"
                xmin = 0.0
                xmax = 0.65
                intervals: size = 1
                    intervals [1]:
                        xmin = 0.0
                        xmax = 0.65
                        text = "apa"
        """
    }

    private func threeTierTextGrid() -> String {
        """
        File type = "ooTextFile"
        Object class = "TextGrid"

        xmin = 0.0
        xmax = 0.65
        tiers? <exists>
        size = 3
        item []:
            item [1]:
                class = "IntervalTier"
                name = "fonemas"
                xmin = 0.0
                xmax = 0.65
                intervals: size = 1
                    intervals [1]:
                        xmin = 0.0
                        xmax = 0.65
                        text = "a"
            item [2]:
                class = "IntervalTier"
                name = "pal_orto"
                xmin = 0.0
                xmax = 0.65
                intervals: size = 1
                    intervals [1]:
                        xmin = 0.0
                        xmax = 0.65
                        text = "apa"
            item [3]:
                class = "IntervalTier"
                name = "sil_fon"
                xmin = 0.0
                xmax = 0.65
                intervals: size = 1
                    intervals [1]:
                        xmin = 0.0
                        xmax = 0.65
                        text = "a p"
        """
    }

    private func badTextGrid() -> String {
        """
        File type = "ooTextFile"
        Object class = "TextGrid"

        item []:
            item [1]:
                class = "IntervalTier"
                name = "fonemas"
                intervals: size = 1
                    intervals [1]:
                        xmin = 0.0
                        xmax = 0.65
                        text = "a"
        """
    }

    private func shuffledNamedTextGrid() -> String {
        """
        File type = "ooTextFile"
        Object class = "TextGrid"

        xmin = 0.0
        xmax = 0.65
        tiers? <exists>
        size = 4
        item []:
            item [1]:
                class = "IntervalTier"
                name = "words"
                xmin = 0.0
                xmax = 0.65
                intervals: size = 1
                    intervals [1]:
                        xmin = 0.0
                        xmax = 0.65
                        text = "apa"
            item [2]:
                class = "IntervalTier"
                name = "utterance"
                xmin = 0.0
                xmax = 0.65
                intervals: size = 1
                    intervals [1]:
                        xmin = 0.0
                        xmax = 0.65
                        text = "apa"
            item [3]:
                class = "IntervalTier"
                name = "syl"
                xmin = 0.0
                xmax = 0.65
                intervals: size = 1
                    intervals [1]:
                        xmin = 0.0
                        xmax = 0.65
                        text = "a p"
            item [4]:
                class = "IntervalTier"
                name = "phonemes"
                xmin = 0.0
                xmax = 0.65
                intervals: size = 1
                    intervals [1]:
                        xmin = 0.0
                        xmax = 0.65
                        text = "a"
        """
    }
}

private extension Data {
    mutating func appendASCII(_ value: String) {
        append(value.data(using: .ascii)!)
    }

    mutating func appendUInt16LE(_ value: UInt16) {
        var little = value.littleEndian
        Swift.withUnsafeBytes(of: &little) { append(contentsOf: $0) }
    }

    mutating func appendUInt32LE(_ value: UInt32) {
        var little = value.littleEndian
        Swift.withUnsafeBytes(of: &little) { append(contentsOf: $0) }
    }
}

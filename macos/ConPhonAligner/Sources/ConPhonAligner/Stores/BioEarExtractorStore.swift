import AppKit
import ConPhonAlignerCore
import Foundation

@MainActor
final class BioEarExtractorStore: ObservableObject {
    @Published var selectedFolder: URL?
    @Published var summary: BioEarScanSummary?
    @Published var logText = ""
    @Published var isScanning = false
    @Published var isRunning = false
    @Published var pendingConversionPairs: [BioEarExtractionPair] = []
    @Published var pendingReplacementPaths: [URL] = []
    @Published var lastError: String?
    @Published var extractionSettings = BioEarExtractionSettings.productionDefault()
    @Published var isShowingTextGridStandardizer = false
    @Published var isPreparingTextGridStandardizer = false
    @Published var textGridStandardizationSummary: TextGridStandardizationSummary?
    @Published var textGridStandardizationSelection = TextGridStandardizationSelection()
    @Published var language: AppLanguage = .portuguese

    let repoRoot: URL
    let pythonPath: String

    private let runner = ProcessRunner()
    private var scanTask: Task<Void, Never>?

    init(
        repoRoot: URL = RepoLocator.locate(),
        pythonPath: String = PythonLocator.locate()
    ) {
        self.repoRoot = repoRoot
        self.pythonPath = pythonPath
    }

    var canExtract: Bool {
        guard let summary else { return false }
        return summary.canExtract && !isRunning && !isScanning
    }

    func statusTitle(language: AppLanguage) -> String {
        guard let summary else { return L(language, "Nenhuma pasta selecionada", "No folder selected") }
        if !summary.isSelectable { return L(language, "Nenhum trio áudio/TextGrid/TXT encontrado", "No audio/TextGrid/TXT trio found") }
        if summary.blockedCount > 0 { return L(language, "\(summary.blockedCount) trio(s) bloqueado(s)", "\(summary.blockedCount) blocked trio(s)") }
        if summary.conversionCount > 0 { return L(language, "Conversão de áudio necessária", "Audio conversion required") }
        return L(language, "\(summary.readyCount) trio(s) pronto(s)", "\(summary.readyCount) ready trio(s)")
    }

    func chooseFolder(language: AppLanguage? = nil) {
        if let language { self.language = language }
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.title = L(self.language, "Selecionar pasta com trios áudio/TextGrid/TXT", "Choose folder with audio/TextGrid/TXT trios")
        panel.prompt = L(self.language, "Selecionar pasta", "Choose folder")
        if panel.runModal() == .OK, let url = panel.url {
            scan(url)
        }
    }

    func scan(_ url: URL? = nil) {
        let target = url ?? selectedFolder
        guard let target else { return }
        scanTask?.cancel()
        selectedFolder = target
        isScanning = true
        lastError = nil
        appendLog(L(language, "\nEscaneando \(target.path)\n", "\nScanning \(target.path)\n"))

        scanTask = Task { @MainActor in
            do {
                let scan = try await Task.detached(priority: .userInitiated) {
                    try BioEarFolderScanner.scan(rootURL: target)
                }.value
                guard !Task.isCancelled else { return }
                summary = scan
                appendLog(scanDescription(scan))
                if !scan.isSelectable {
                    lastError = L(language, "ALEX não encontrou trios áudio/TXT/TextGrid de mesmo nome.", "ALEX did not find same-stem audio/TXT/TextGrid trios.")
                    appendLog(L(language, "Correção: para BioEar, coloque áudio, .txt e .TextGrid na mesma subpasta com exatamente o mesmo stem.\n", "Fix: for BioEar, put audio, .txt and .TextGrid in the same subfolder with exactly the same stem.\n"))
                } else if scan.blockedCount > 0 {
                    lastError = L(language, "\(scan.blockedCount) trio(s) bloqueado(s) por arquivos ausentes, áudio inválido ou camadas TextGrid não reconhecidas.", "\(scan.blockedCount) trio(s) blocked by missing files, invalid audio, or unrecognized TextGrid tiers.")
                    appendLog(L(language, "Correção: confira stems idênticos, áudio legível e camadas TextGrid nomeadas phonemes/phones, words, syllables/syl e sentence/utterance opcional. Cada arquivo deve conter uma única sentença.\n", "Fix: check identical stems, readable audio, and TextGrid tiers named phonemes/phones, words, syllables/syl and optional sentence/utterance. Each file must contain one sentence.\n"))
                }
            } catch {
                guard !Task.isCancelled else { return }
                summary = nil
                lastError = error.localizedDescription
                appendLog(L(language, "Escaneamento falhou: \(error.localizedDescription)\n", "Scan failed: \(error.localizedDescription)\n"))
            }
            isScanning = false
        }
    }

    func extract() {
        guard canExtract else { return }
        let conversions = summary?.pairs.filter { $0.status == .needsWAVConversion } ?? []
        if !conversions.isEmpty {
            pendingConversionPairs = conversions
            return
        }
        continueAfterPreflight()
    }

    func prepareTextGridStandardizer() {
        guard let selectedFolder else {
            lastError = L(language, "Selecione uma pasta antes de padronizar TextGrids.", "Choose a folder before standardizing TextGrids.")
            return
        }
        isPreparingTextGridStandardizer = true
        lastError = nil
        appendLog(L(language, "\nEscaneando camadas TextGrid para padronização.\n", "\nScanning TextGrid tiers for standardization.\n"))
        Task { @MainActor in
            do {
                let summary = try await Task.detached(priority: .userInitiated) {
                    try TextGridStandardizationScanner.scan(rootURL: selectedFolder)
                }.value
                textGridStandardizationSummary = summary
                textGridStandardizationSelection = TextGridStandardizationScanner.suggestedSelection(for: summary)
                isShowingTextGridStandardizer = true
                appendLog(L(language, "TextGrids encontrados: \(summary.textGridCount); camadas únicas: \(summary.layers.count).\n", "TextGrids found: \(summary.textGridCount); unique tiers: \(summary.layers.count).\n"))
                if summary.textGridCount == 0 {
                    lastError = L(language, "Nenhum TextGrid encontrado na pasta selecionada.", "No TextGrid found in the selected folder.")
                }
            } catch {
                lastError = error.localizedDescription
                appendLog(L(language, "Escaneamento de camadas falhou: \(error.localizedDescription)\n", "Tier scan failed: \(error.localizedDescription)\n"))
            }
            isPreparingTextGridStandardizer = false
        }
    }

    func cancelTextGridStandardizer() {
        isShowingTextGridStandardizer = false
    }

    func applyTextGridStandardization() {
        guard let selectedFolder, !isRunning else { return }
        isShowingTextGridStandardizer = false
        isRunning = true
        lastError = nil
        let command = BioEarCommandBuilder.textGridStandardizationCommand(
            repoRoot: repoRoot,
            inputFolder: selectedFolder,
            selection: textGridStandardizationSelection,
            pythonPath: pythonPath
        )
        appendLog(L(language, "\nPadronizando camadas TextGrid para phonemes / words / syllables / utterance.\n", "\nStandardizing TextGrid tiers to phonemes / words / syllables / utterance.\n"))
        appendLog(commandLine(command) + "\n")
        Task {
            let success = await run(command)
            isRunning = false
            if success {
                prepareTextGridStandardizer()
                scan()
            }
        }
    }

    func cancelConversion() {
        pendingConversionPairs = []
    }

    func convertAndContinue() {
        let pairs = pendingConversionPairs
        pendingConversionPairs = []
        guard !pairs.isEmpty else {
            continueAfterPreflight()
            return
        }
        runConversionThenExtraction(pairs: pairs)
    }

    func cancelReplacement() {
        pendingReplacementPaths = []
    }

    func replaceAndExtract() {
        pendingReplacementPaths = []
        runExtraction(replaceConfirmed: true)
    }

    func stop() {
        scanTask?.cancel()
        scanTask = nil
        isScanning = false
        runner.terminate()
        appendLog(L(language, "\nParada solicitada.\n", "\nStop requested.\n"))
    }

    func clearError() {
        lastError = nil
    }

    var recoverySuggestion: String {
        guard let summary else {
            return L(language, "Selecione uma pasta local acessível. ALEX pesquisará subpastas sem carregar a base inteira na interface.", "Choose an accessible local folder. ALEX will search subfolders without loading the whole dataset into the interface.")
        }
        if !summary.isSelectable {
            return L(language, "Para BioEar, cada amostra precisa de áudio, .txt e .TextGrid na mesma subpasta, todos com o mesmo stem.", "For BioEar, each sample needs audio, .txt and .TextGrid in the same subfolder, all with the same stem.")
        }
        if summary.missingTextGridCount > 0 {
            return L(language, "Crie ou mova os TextGrids correspondentes. Português pode gerar TextGrid no alinhador; outras línguas precisam trazer TextGrids prontos.", "Create or move the matching TextGrids. Portuguese can generate TextGrid in the aligner; other languages must provide ready TextGrids.")
        }
        if summary.missingTXTCount > 0 {
            return L(language, "Adicione o .txt correspondente em texto simples, com o mesmo stem do WAV e do TextGrid.", "Add the matching plain-text .txt with the same stem as the WAV and TextGrid.")
        }
        if summary.missingTierCount > 0 {
            return L(language, "Use nomes explícitos de tiers: phonemes/phones, words, syllables/syl e, se existir, sentence ou utterance. Frase é opcional: quando ausente, ALEX sintetiza uma utterance única para o arquivo. Cada arquivo deve conter só uma sentença.", "Use explicit tier names: phonemes/phones, words, syllables/syl and, if present, sentence or utterance. Sentence is optional: when absent, ALEX synthesizes one utterance for the file. Each file must contain one sentence.")
        }
        if summary.invalidWAVCount > 0 {
            return L(language, "Converta ou remova áudios corrompidos. ALEX consegue normalizar formato/taxa/canais, mas precisa conseguir abrir o áudio.", "Convert or remove corrupted audio. ALEX can normalize format/rate/channels, but it must be able to open the audio.")
        }
        return L(language, "Abra o log para ver o comando que falhou e rode novamente depois de corrigir os arquivos indicados.", "Open the log to see the failed command and run again after fixing the listed files.")
    }

    func relativePath(_ url: URL) -> String {
        guard let selectedFolder else { return url.lastPathComponent }
        let root = selectedFolder.standardizedFileURL.path
        let path = url.standardizedFileURL.path
        if path.hasPrefix(root + "/") {
            return String(path.dropFirst(root.count + 1))
        }
        return path
    }

    private func continueAfterPreflight() {
        guard let summary else { return }
        let unmarked = summary.outputState.unmarkedOutputs
        if !unmarked.isEmpty {
            let paths = unmarked.map { relativePath($0) }.joined(separator: ", ")
            lastError = L(language, "Saídas existentes sem marcador não podem ser substituídas automaticamente.", "Existing unmarked outputs cannot be replaced automatically.")
            appendLog(L(language, "\nBloqueado por saída(s) sem marcador: \(paths)\n", "\nBlocked by unmarked output(s): \(paths)\n"))
            return
        }
        let existing = summary.outputState.existingOutputs
        if !existing.isEmpty {
            pendingReplacementPaths = existing
            return
        }
        runExtraction(replaceConfirmed: false)
    }

    private func runConversionThenExtraction(pairs: [BioEarExtractionPair]) {
        guard !isRunning else { return }
        isRunning = true
        lastError = nil
        let command = AlignerCommandBuilder.normalizationCommand(
            repoRoot: repoRoot,
            wavURLs: pairs.map(\.wavURL),
            pythonPath: pythonPath
        )
        appendLog(L(language, "\nConvertendo \(pairs.count) arquivo(s) de áudio para WAV mono 16 kHz.\n", "\nConverting \(pairs.count) audio file(s) to mono 16 kHz WAV.\n"))
        appendLog(commandLine(command) + "\n")

        Task {
            let success = await run(command)
            isRunning = false
            scan()
            if success {
                continueAfterPreflight()
            }
        }
    }

    private func runExtraction(replaceConfirmed: Bool) {
        guard let selectedFolder, !isRunning else { return }
        isRunning = true
        lastError = nil
        let commands = extractionCommands(inputFolder: selectedFolder, replaceConfirmed: replaceConfirmed)
        appendLog(L(language, "\nExtração biológica auditiva ConPhon: BioEar HDF5\n", "\nConPhon biological auditory extraction: BioEar HDF5\n"))

        Task {
            for item in commands {
                appendLog("\n\(item.description)\n")
                if let config = item.configDescription {
                    appendLog("\(config)\n")
                }
                appendLog(commandLine(item.command) + "\n")
                let success = await run(item.command)
                if !success { break }
            }
            isRunning = false
            scan()
        }
    }

    private func extractionCommands(inputFolder: URL, replaceConfirmed: Bool) -> [(description: String, configDescription: String?, command: ProcessCommand)] {
        var commands: [(description: String, configDescription: String?, command: ProcessCommand)] = []
        commands.append((
            L(language, "Extração Bruce-Zilany-Carney para _bioear.h5.", "Bruce-Zilany-Carney extraction to _bioear.h5."),
            L(language, "Perfil: \(profileTitle(extractionSettings.profile)); \(extractionSettings.profile.shortSpec); tag=\(extractionSettings.languageTag); jobs=\(extractionSettings.jobs).", "Profile: \(profileTitle(extractionSettings.profile)); \(extractionSettings.profile.shortSpec); tag=\(extractionSettings.languageTag); jobs=\(extractionSettings.jobs)."),
            BioEarCommandBuilder.runCommand(
                repoRoot: repoRoot,
                inputFolder: inputFolder,
                replaceConfirmed: replaceConfirmed,
                settings: extractionSettings,
                pythonPath: pythonPath
            )
        ))
        if extractionSettings.auxiliary.hasSelection {
            commands.append((
                L(language, "Enriquecimento BioEar: \(richComponentDescription).", "BioEar enrichment: \(richComponentDescription)."),
                L(language, "Componentes=\(extractionSettings.auxiliary.componentArgument); jobs=\(extractionSettings.jobs); threads por arquivo=\(extractionSettings.threadsPerFile).", "Components=\(extractionSettings.auxiliary.componentArgument); jobs=\(extractionSettings.jobs); threads per file=\(extractionSettings.threadsPerFile)."),
                BioEarCommandBuilder.richAuxCommand(
                    repoRoot: repoRoot,
                    inputFolder: inputFolder,
                    replaceConfirmed: replaceConfirmed,
                    settings: extractionSettings,
                    pythonPath: pythonPath
                )
            ))
        }
        return commands
    }

    private var richComponentDescription: String {
        var parts: [String] = []
        if extractionSettings.auxiliary.includeIHC { parts.append("IHC") }
        if extractionSettings.auxiliary.includeSynapseDrive { parts.append("synapse drive") }
        if extractionSettings.auxiliary.includeRedocking { parts.append("redocking") }
        return parts.joined(separator: ", ")
    }

    private func profileTitle(_ profile: BioEarExtractionProfile) -> String {
        switch profile {
        case .fast: L(language, "Rápido", "Fast")
        case .balanced: L(language, "Equilibrado", "Balanced")
        case .contextLite: L(language, "Contexto leve", "Context-lite")
        }
    }

    private func run(_ command: ProcessCommand) async -> Bool {
        do {
            let output = try await runner.run(
                executable: command.executable,
                arguments: command.arguments,
                workingDirectory: command.workingDirectory,
                onOutput: { [weak self] chunk in
                    Task { @MainActor in
                        self?.appendLog(chunk)
                    }
                }
            )
            if output.exitCode != 0 {
                lastError = L(language, "Comando saiu com código \(output.exitCode).", "Command exited with code \(output.exitCode).")
                appendLog(L(language, "\nComando falhou com código \(output.exitCode).\n", "\nCommand failed with code \(output.exitCode).\n"))
                return false
            }
            appendLog(L(language, "\nComando concluído em \(String(format: "%.1f", output.duration))s.\n", "\nCommand completed in \(String(format: "%.1f", output.duration))s.\n"))
            return true
        } catch {
            lastError = error.localizedDescription
            appendLog("\n\(error.localizedDescription)\n")
            return false
        }
    }

    private func appendLog(_ text: String) {
        logText += text
        if logText.count > 100_000 {
            logText = String(logText.suffix(100_000))
        }
    }

    private func scanDescription(_ scan: BioEarScanSummary) -> String {
        if language == .english {
            return """
            Trios found: \(scan.pairs.count)
            Ready: \(scan.readyCount)
            Need audio conversion: \(scan.conversionCount)
            Missing TXT: \(scan.missingTXTCount)
            Missing TextGrid: \(scan.missingTextGridCount)
            Missing required tiers: \(scan.missingTierCount)
            Invalid audio: \(scan.invalidWAVCount)
            Audio without TextGrid pair: \(scan.unmatchedWAVCount)
            TextGrids without WAV: \(scan.unmatchedTextGridCount)
            Dataset slug: \(scan.outputState.datasetSlug)

            """
        }
        return """
        Trios encontrados: \(scan.pairs.count)
        Prontos: \(scan.readyCount)
        Precisam converter áudio: \(scan.conversionCount)
        Faltando TXT: \(scan.missingTXTCount)
        Faltando TextGrid: \(scan.missingTextGridCount)
        Faltando camadas obrigatórias: \(scan.missingTierCount)
        Áudios inválidos: \(scan.invalidWAVCount)
        Áudios sem par TextGrid: \(scan.unmatchedWAVCount)
        TextGrids sem WAV: \(scan.unmatchedTextGridCount)
        Slug do conjunto: \(scan.outputState.datasetSlug)

        """
    }

    private func commandLine(_ command: ProcessCommand) -> String {
        ([command.executable] + command.arguments)
            .map(shellQuote)
            .joined(separator: " ")
    }

    private func shellQuote(_ value: String) -> String {
        if value.range(of: #"^[A-Za-z0-9_@%+=:,./-]+$"#, options: .regularExpression) != nil {
            return value
        }
        return "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }
}

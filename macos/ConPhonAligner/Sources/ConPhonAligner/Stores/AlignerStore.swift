import AppKit
import ConPhonAlignerCore
import Foundation

@MainActor
final class AlignerStore: ObservableObject {
    @Published var selectedFolder: URL?
    @Published var summary: FolderScanSummary?
    @Published var logText = ""
    @Published var isScanning = false
    @Published var isRunning = false
    @Published var pendingConversionPairs: [AlignmentPair] = []
    @Published var isShowingExistingTextGridChoice = false
    @Published var lastError: String?
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

    var canCreateTextGrids: Bool {
        guard let summary else { return false }
        return summary.canCreateTextGrids && !isRunning && !isScanning
    }

    var canRunTextGridAction: Bool {
        guard let summary else { return false }
        return summary.isSelectable
            && summary.invalidWAVCount == 0
            && (summary.readyToCreateCount > 0 || summary.conversionCount > 0 || summary.existingTextGridCount > 0)
            && !isRunning
            && !isScanning
    }

    private var pendingConversionReplaceExistingTextGrids = false

    func statusTitle(language: AppLanguage) -> String {
        guard let summary else { return L(language, "Nenhuma pasta selecionada", "No folder selected") }
        if !summary.isSelectable { return L(language, "Nenhum par válido encontrado", "No valid pair found") }
        if summary.invalidWAVCount > 0 { return L(language, "Arquivos de áudio inválidos precisam de atenção", "Invalid audio files need attention") }
        if summary.conversionCount > 0 { return L(language, "Conversão de áudio necessária", "Audio conversion required") }
        if summary.isComplete { return L(language, "Pronto", "Ready") }
        if summary.readyToCreateCount > 0 {
            return L(language, "\(summary.readyToCreateCount) par(es) pendente(s)", "\(summary.readyToCreateCount) pending pair(s)")
        }
        return L(language, "Todos os TextGrids já existem", "All TextGrids already exist")
    }

    func chooseFolder(language: AppLanguage? = nil) {
        if let language { self.language = language }
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.title = L(self.language, "Selecionar pasta com pares áudio/TXT", "Choose folder with audio/TXT pairs")
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
                    try FolderScanner.scan(rootURL: target)
                }.value
                guard !Task.isCancelled else { return }
                summary = scan
                appendLog(scanDescription(scan))
                if !scan.isSelectable {
                    lastError = L(language, "ALEX não encontrou pares áudio/TXT de mesmo nome nesta pasta.", "ALEX did not find same-stem audio/TXT pairs in this folder.")
                    appendLog(L(language, "Correção: coloque cada arquivo de áudio e .txt correspondente na mesma subpasta e use exatamente o mesmo nome antes da extensão.\n", "Fix: put each audio file and matching .txt in the same subfolder with exactly the same name before the extension.\n"))
                } else if scan.invalidWAVCount > 0 {
                    lastError = L(language, "\(scan.invalidWAVCount) arquivo(s) de áudio não puderam ser lidos.", "\(scan.invalidWAVCount) audio file(s) could not be read.")
                    appendLog(L(language, "Correção: remova arquivos corrompidos ou converta-os para um formato de áudio legível antes de criar TextGrids.\n", "Fix: remove corrupted files or convert them to a readable audio format before creating TextGrids.\n"))
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

    func createTextGrids() {
        guard canRunTextGridAction, let summary else { return }
        if summary.existingTextGridCount > 0 {
            isShowingExistingTextGridChoice = true
            return
        }
        startTextGridCreation(replaceExistingTextGrids: false)
    }

    func continueMissingTextGrids() {
        isShowingExistingTextGridChoice = false
        startTextGridCreation(replaceExistingTextGrids: false)
    }

    func replaceExistingAndCreateTextGrids() {
        isShowingExistingTextGridChoice = false
        startTextGridCreation(replaceExistingTextGrids: true)
    }

    func cancelExistingTextGridChoice() {
        isShowingExistingTextGridChoice = false
    }

    private func startTextGridCreation(replaceExistingTextGrids: Bool) {
        guard let summary, summary.invalidWAVCount == 0 else { return }
        let conversions = summary.pairs.filter { $0.status == .needsWAVConversion }
        if !conversions.isEmpty {
            pendingConversionReplaceExistingTextGrids = replaceExistingTextGrids
            pendingConversionPairs = conversions
            return
        }
        runAlignment(replaceExistingTextGrids: replaceExistingTextGrids)
    }

    func cancelConversion() {
        pendingConversionPairs = []
        pendingConversionReplaceExistingTextGrids = false
    }

    func convertAndContinue() {
        let pairs = pendingConversionPairs
        let replaceExistingTextGrids = pendingConversionReplaceExistingTextGrids
        pendingConversionPairs = []
        pendingConversionReplaceExistingTextGrids = false
        guard !pairs.isEmpty else {
            runAlignment(replaceExistingTextGrids: replaceExistingTextGrids)
            return
        }
        runConversionThenAlignment(pairs: pairs, replaceExistingTextGrids: replaceExistingTextGrids)
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
            return L(language, "Selecione uma pasta local acessível e tente novamente.", "Choose an accessible local folder and try again.")
        }
        if !summary.isSelectable {
            return L(language, "Para português, cada amostra precisa de áudio e .txt na mesma pasta, com o mesmo stem. Exemplo: fala_001.flac e fala_001.txt.", "For Portuguese, each sample needs audio and .txt in the same folder with the same stem. Example: speech_001.flac and speech_001.txt.")
        }
        if summary.invalidWAVCount > 0 {
            return L(language, "Converta ou remova áudios corrompidos. ALEX consegue converter taxa/canais/formato, mas precisa conseguir abrir o arquivo de áudio.", "Convert or remove corrupted audio. ALEX can convert rate/channels/format, but it must be able to open the audio file.")
        }
        if summary.unmatchedWAVCount > 0 || summary.unmatchedTXTCount > 0 {
            return L(language, "Confira nomes e subpastas. ALEX não cruza arquivos entre pastas diferentes e exige stems idênticos.", "Check names and subfolders. ALEX does not match files across different folders and requires identical stems.")
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

    private func runConversionThenAlignment(pairs: [AlignmentPair], replaceExistingTextGrids: Bool) {
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
                runAlignment(replaceExistingTextGrids: replaceExistingTextGrids)
            }
        }
    }

    private func runAlignment(replaceExistingTextGrids: Bool) {
        guard let selectedFolder, !isRunning else { return }
        guard replaceExistingTextGrids || (summary?.readyToCreateCount ?? 0) > 0 else {
            appendLog(L(language, "\nNão há TextGrids pendentes para criar.\n", "\nThere are no pending TextGrids to create.\n"))
            return
        }
        isRunning = true
        lastError = nil
        let command = AlignerCommandBuilder.alignmentCommand(
            repoRoot: repoRoot,
            selectedFolder: selectedFolder,
            pythonPath: pythonPath,
            replaceExistingTextGrids: replaceExistingTextGrids
        )
        appendLog(
            replaceExistingTextGrids
                ? L(language, "\nRecriando TextGrids existentes e criando faltantes com modelo acústico mono.\n", "\nReplacing existing TextGrids and creating missing ones with the mono acoustic model.\n")
                : L(language, "\nCriando somente TextGrids faltantes com modelo acústico mono.\n", "\nCreating only missing TextGrids with the mono acoustic model.\n")
        )
        appendLog(commandLine(command) + "\n")

        Task {
            _ = await run(command)
            isRunning = false
            scan()
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
        if logText.count > 80_000 {
            logText = String(logText.suffix(80_000))
        }
    }

    private func scanDescription(_ scan: FolderScanSummary) -> String {
        if language == .portuguese {
            return """
            Pares encontrados: \(scan.pairs.count)
            Prontos para uso: \(scan.readyCount)
            Pendentes para criar: \(scan.readyToCreateCount)
            Precisam converter áudio: \(scan.conversionCount)
            TextGrids existentes: \(scan.existingTextGridCount)
            Áudios inválidos: \(scan.invalidWAVCount)
            Áudios sem TXT: \(scan.unmatchedWAVCount)
            TXTs sem WAV: \(scan.unmatchedTXTCount)

            """
        }
        return """
        Pairs found: \(scan.pairs.count)
        Ready to use: \(scan.readyCount)
        Pending creation: \(scan.readyToCreateCount)
        Need audio conversion: \(scan.conversionCount)
        Existing TextGrids: \(scan.existingTextGridCount)
        Invalid audio: \(scan.invalidWAVCount)
        Audio without TXT: \(scan.unmatchedWAVCount)
        TXT without WAV: \(scan.unmatchedTXTCount)

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

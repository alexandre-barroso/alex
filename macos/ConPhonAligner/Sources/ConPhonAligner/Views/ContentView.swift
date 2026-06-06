import ConPhonAlignerCore
import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var menuStore: AppMenuStore
    @AppStorage("alex.ui.language") private var languageRaw = AppLanguage.portuguese.rawValue

    private var language: AppLanguage {
        AppLanguage.from(languageRaw)
    }

    private var languageBinding: Binding<AppLanguage> {
        Binding(
            get: { AppLanguage.from(languageRaw) },
            set: { languageRaw = $0.rawValue }
        )
    }

    var body: some View {
        VStack(spacing: 0) {
            TabView {
                TextGridAlignerView()
                    .tabItem {
                        Label(L(language, "Alinhador", "Aligner"), systemImage: "waveform.path.badge.plus")
                    }

                BioEarExtractorView()
                    .tabItem {
                        Label("BioEar", systemImage: "waveform.path.ecg")
                    }
            }

            CopyrightFooter()
        }
        .environment(\.appLanguage, language)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Picker("", selection: languageBinding) {
                    ForEach(AppLanguage.allCases) { item in
                        Text(item.shortTitle).tag(item)
                    }
                }
                .pickerStyle(.segmented)
                .frame(width: 86)
                .help(L(language, "Idioma da interface", "Interface language"))
            }
        }
        .sheet(isPresented: $menuStore.isShowingHelp) {
            MarkdownPopupView(
                title: L(language, "Instruções", "Instructions"),
                markdown: AppMarkdownContent.help(language: language)
            )
                .frame(minWidth: 520, idealWidth: 720, maxWidth: 820, minHeight: 480, idealHeight: 620)
        }
        .sheet(isPresented: $menuStore.isShowingAbout) {
            MarkdownPopupView(
                title: L(language, "Sobre", "About"),
                markdown: AppMarkdownContent.about(language: language)
            )
                .frame(minWidth: 480, idealWidth: 620, maxWidth: 740, minHeight: 360, idealHeight: 460)
        }
    }
}

private struct CopyrightFooter: View {
    var body: some View {
        Text("© Alexandre Menezes Barroso (alexandrebaroso.com), 2006")
            .font(.system(size: 9, weight: .regular))
            .foregroundStyle(.tertiary)
            .lineLimit(1)
            .minimumScaleFactor(0.8)
            .frame(maxWidth: .infinity, alignment: .trailing)
            .padding(.horizontal, 10)
            .padding(.vertical, 2)
    }
}

private struct TextGridAlignerView: View {
    @EnvironmentObject private var store: AlignerStore
    @EnvironmentObject private var menuStore: AppMenuStore
    @Environment(\.appLanguage) private var language

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    CorpusInputPanel(
                        title: L(language, "Alinhamento em português", "Portuguese alignment"),
                        subtitle: L(language, "Áudio + TXT", "Audio + TXT"),
                        systemImage: "text.badge.checkmark",
                        rows: [
                            RequirementRow(title: L(language, "Mesmo stem", "Same stem"), value: "sample.mp3 + sample.txt", systemImage: "equal.circle"),
                            RequirementRow(title: L(language, "Subpastas", "Subfolders"), value: L(language, "Pesquisa recursiva", "Scanned recursively"), systemImage: "folder.badge.gearshape"),
                            RequirementRow(title: L(language, "Áudio", "Audio"), value: L(language, "Converte para WAV mono 16 kHz primeiro", "Converted to mono 16 kHz WAV first"), systemImage: "arrow.triangle.2.circlepath"),
                            RequirementRow(title: "TextGrid", value: L(language, "Criado com camadas canônicas", "Created with canonical tiers"), systemImage: "waveform.path.badge.plus")
                        ]
                    )
                    StatusProgressStrip(
                        isActive: store.isScanning || store.isRunning,
                        title: store.isScanning ? L(language, "Escaneando pastas", "Scanning folders") : L(language, "Executando CLI oculta", "Running hidden CLI"),
                        detail: store.isScanning
                            ? L(language, "ALEX conta pares fora da interface principal.", "ALEX counts pairs off the main thread.")
                            : L(language, "O app transmite progresso enquanto Python trabalha.", "The app streams progress while Python works.")
                    )
                    SummaryView(summary: store.summary, statusTitle: store.statusTitle(language: language))
                    PairListView(summary: store.summary)
                        .environmentObject(store)
                    LogPanel(text: store.logText)
                }
                .padding(18)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .sheet(isPresented: conversionSheetBinding) {
            ConversionConfirmationSheet(pairs: store.pendingConversionPairs)
                .environmentObject(store)
                .frame(maxWidth: 760, maxHeight: 560)
        }
        .sheet(isPresented: existingTextGridChoiceBinding) {
            ExistingTextGridChoiceSheet(summary: store.summary)
                .environmentObject(store)
                .frame(maxWidth: 720, maxHeight: 420)
        }
        .onAppear {
            store.language = language
        }
        .onChange(of: language) { _, newValue in
            store.language = newValue
        }
        .alert(L(language, "A pasta precisa de atenção", "Folder needs attention"), isPresented: errorBinding) {
            Button(L(language, "Instruções", "Instructions")) {
                store.clearError()
                menuStore.showHelp()
            }
            Button("OK", role: .cancel) {
                store.clearError()
            }
        } message: {
            Text(store.lastError.map { "\($0)\n\n\(store.recoverySuggestion)" } ?? store.recoverySuggestion)
        }
    }

    private var conversionSheetBinding: Binding<Bool> {
        Binding(
            get: { !store.pendingConversionPairs.isEmpty },
            set: { if !$0 { store.cancelConversion() } }
        )
    }

    private var existingTextGridChoiceBinding: Binding<Bool> {
        Binding(
            get: { store.isShowingExistingTextGridChoice },
            set: { if !$0 { store.cancelExistingTextGridChoice() } }
        )
    }

    private var errorBinding: Binding<Bool> {
        Binding(
            get: { store.lastError != nil },
            set: { if !$0 { store.clearError() } }
        )
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .center, spacing: 14) {
                Image(nsImage: AlignerIconFactory.makeIcon(size: 64))
                    .resizable()
                    .frame(width: 48, height: 48)
                    .clipShape(RoundedRectangle(cornerRadius: 10))

                VStack(alignment: .leading, spacing: 4) {
                    Text(L(language, "Alinhador TextGrid", "TextGrid Aligner"))
                        .font(.title.weight(.semibold))
                    Text(selectedFolderText)
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                        .truncationMode(.middle)
                        .textSelection(.enabled)
                }

                Spacer(minLength: 12)

                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 8) { actionButtons }
                    VStack(alignment: .trailing, spacing: 8) { actionButtons }
                }
            }

            if let error = store.lastError {
                Label(error, systemImage: "exclamationmark.triangle")
                    .font(.callout)
                    .foregroundStyle(.red)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(18)
        .background(.bar)
    }

    @ViewBuilder
    private var actionButtons: some View {
        Button {
            menuStore.showHelp()
        } label: {
            Label(L(language, "Instruções", "Instructions"), systemImage: "book")
        }
        .buttonStyle(HeaderActionButtonStyle(tone: .secondary))

        Button {
            store.chooseFolder(language: language)
        } label: {
            Label(L(language, "Selecionar pasta", "Choose folder"), systemImage: "folder")
        }
        .buttonStyle(HeaderActionButtonStyle(tone: .secondary))

        Button {
            store.scan()
        } label: {
            Label(L(language, "Reescanear", "Rescan"), systemImage: "arrow.clockwise")
        }
        .buttonStyle(HeaderActionButtonStyle(tone: .secondary))
        .disabled(store.selectedFolder == nil || store.isRunning || store.isScanning)

        Button {
            store.createTextGrids()
        } label: {
            Label(textGridActionTitle, systemImage: "waveform.path.badge.plus")
        }
        .buttonStyle(HeaderActionButtonStyle(tone: .primary))
        .disabled(!store.canRunTextGridAction)

        Button(role: .destructive) {
            store.stop()
        } label: {
            Label(L(language, "Parar", "Stop"), systemImage: "stop.fill")
        }
        .buttonStyle(HeaderActionButtonStyle(tone: .destructive))
        .disabled(!store.isRunning)
    }

    private var selectedFolderText: String {
        store.selectedFolder?.path ?? L(language, "Nenhuma pasta selecionada", "No folder selected")
    }

    private var textGridActionTitle: String {
        if store.summary?.isComplete == true {
            return L(language, "Recriar TextGrids", "Recreate TextGrids")
        }
        return L(language, "Criar TextGrids", "Create TextGrids")
    }
}

private struct SummaryView: View {
    @Environment(\.appLanguage) private var language
    let summary: FolderScanSummary?
    let statusTitle: String

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label(statusTitle, systemImage: "checklist")
                .font(.headline)

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 150), spacing: 10)], alignment: .leading, spacing: 10) {
                metric(L(language, "Pares", "Pairs"), "\(summary?.pairs.count ?? 0)", "waveform")
                metric(L(language, "Estado", "Status"), alignmentStatusText, "play.circle")
                metric(L(language, "Converter", "Convert"), "\(summary?.conversionCount ?? 0)", "arrow.triangle.2.circlepath")
                metric(L(language, "TextGrids", "TextGrids"), "\(summary?.existingTextGridCount ?? 0)", "doc.badge.checkmark")
                metric(L(language, "Inválidos", "Invalid"), "\(summary?.invalidWAVCount ?? 0)", "exclamationmark.triangle")
                metric(L(language, "Sem par", "Unmatched"), "\(unmatchedCount)", "questionmark.folder")
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
    }

    private var unmatchedCount: Int {
        (summary?.unmatchedWAVCount ?? 0) + (summary?.unmatchedTXTCount ?? 0)
    }

    private var alignmentStatusText: String {
        guard let summary else { return "-" }
        if summary.isComplete { return L(language, "Pronto", "Ready") }
        if summary.readyToCreateCount > 0 { return "\(summary.readyToCreateCount)" }
        if summary.conversionCount > 0 { return L(language, "Converter", "Convert") }
        return "-"
    }

    private func metric(_ title: String, _ value: String, _ image: String) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Label(title, systemImage: image)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
            Text(value)
                .font(.title3.weight(.semibold).monospacedDigit())
        }
        .padding(10)
        .frame(maxWidth: .infinity, minHeight: 74, alignment: .leading)
        .background(.quaternary.opacity(0.20), in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct PairListView: View {
    @EnvironmentObject private var store: AlignerStore
    @Environment(\.appLanguage) private var language
    let summary: FolderScanSummary?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(L(language, "Pares", "Pairs"), systemImage: "list.bullet.rectangle")
                .font(.headline)

            if let summary, !summary.pairs.isEmpty {
                LazyVStack(alignment: .leading, spacing: 8) {
                    ForEach(Array(summary.pairs.prefix(200))) { pair in
                        PairRow(pair: pair)
                            .environmentObject(store)
                    }
                    if summary.pairs.count > 200 {
                        Label(L(language, "Mostrando os primeiros 200 de \(summary.pairs.count) pares.", "Showing first 200 of \(summary.pairs.count) pairs."), systemImage: "list.bullet.rectangle.portrait")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            } else {
                Text(L(language, "Selecione uma pasta com pelo menos um par áudio/.txt de mesmo nome.", "Choose a folder with at least one same-stem audio/.txt pair."))
                    .foregroundStyle(.secondary)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct PairRow: View {
    @EnvironmentObject private var store: AlignerStore
    @Environment(\.appLanguage) private var language
    let pair: AlignmentPair

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: pair.status.systemImage)
                .foregroundStyle(pair.status.tint)
                .frame(width: 20)

            VStack(alignment: .leading, spacing: 4) {
                Text(store.relativePath(pair.wavURL))
                    .font(.callout.weight(.semibold))
                    .lineLimit(2)
                    .truncationMode(.middle)
                    .textSelection(.enabled)
                Text(detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer(minLength: 8)

            Text(pair.status.localizedTitle(language))
                .font(.caption.weight(.semibold))
                .foregroundStyle(pair.status.tint)
                .lineLimit(1)
        }
        .padding(10)
        .background(.quaternary.opacity(0.16), in: RoundedRectangle(cornerRadius: 8))
    }

    private var detail: String {
        if let info = pair.audioInfo {
            return L(language, "\(info.channels) canal(is), \(info.sampleRate) Hz -> \(store.relativePath(pair.textGridURL))", "\(info.channels) channel(s), \(info.sampleRate) Hz -> \(store.relativePath(pair.textGridURL))")
        }
        return pair.audioError ?? L(language, "O áudio não pôde ser inspecionado", "Audio could not be inspected")
    }
}

private struct LogPanel: View {
    @Environment(\.appLanguage) private var language
    let text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(L(language, "Log de execução", "Run log"), systemImage: "terminal")
                .font(.headline)
            ScrollView {
                Text(text.isEmpty ? L(language, "Selecione uma pasta para começar.", "Choose a folder to begin.") : text)
                    .font(.system(.caption, design: .monospaced))
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .textSelection(.enabled)
                    .padding(10)
            }
            .frame(minHeight: 160, maxHeight: 260)
            .background(.black.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct ConversionConfirmationSheet: View {
    @EnvironmentObject private var store: AlignerStore
    @Environment(\.appLanguage) private var language
    @Environment(\.dismiss) private var dismiss
    let pairs: [AlignmentPair]

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Label(L(language, "Converter áudio?", "Convert audio?"), systemImage: "arrow.triangle.2.circlepath")
                .font(.title2.weight(.semibold))
            Text(L(language, "ALEX criará WAVs mono 16 kHz antes do alinhamento. WAVs fora do padrão são movidos para `original_wav`; outros formatos de áudio são preservados e recebem um WAV irmão.", "ALEX will create mono 16 kHz WAVs before alignment. Non-standard WAVs move to `original_wav`; other audio formats are preserved and receive a sibling WAV."))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            ScrollView {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(pairs) { pair in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(store.relativePath(pair.wavURL))
                                .font(.caption.monospaced())
                                .textSelection(.enabled)
                                .lineLimit(2)
                                .truncationMode(.middle)
                            Text(L(language, "Pasta dos originais: \(store.relativePath(pair.wavURL.deletingLastPathComponent().appendingPathComponent("original_wav", isDirectory: true)))", "Originals folder: \(store.relativePath(pair.wavURL.deletingLastPathComponent().appendingPathComponent("original_wav", isDirectory: true)))"))
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                        .padding(8)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(.quaternary.opacity(0.18), in: RoundedRectangle(cornerRadius: 8))
                    }
                }
            }
            .frame(maxHeight: 340)

            HStack {
                Button {
                    store.convertAndContinue()
                    dismiss()
                } label: {
                    Label(L(language, "Converter e continuar", "Convert and continue"), systemImage: "play.fill")
                }
                .buttonStyle(.borderedProminent)

                Spacer()

                Button(L(language, "Cancelar", "Cancel")) {
                    store.cancelConversion()
                    dismiss()
                }
                .keyboardShortcut(.cancelAction)
            }
            .controlSize(.large)
        }
        .padding(22)
    }
}

private struct ExistingTextGridChoiceSheet: View {
    @EnvironmentObject private var store: AlignerStore
    @Environment(\.appLanguage) private var language
    @Environment(\.dismiss) private var dismiss
    let summary: FolderScanSummary?

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Label(L(language, "TextGrids existentes encontrados", "Existing TextGrids found"), systemImage: "doc.badge.checkmark")
                .font(.title2.weight(.semibold))

            Text(message)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 150), spacing: 10)], alignment: .leading, spacing: 10) {
                metric(L(language, "Pares", "Pairs"), "\(summary?.pairs.count ?? 0)", "waveform")
                metric(L(language, "Existentes", "Existing"), "\(summary?.existingTextGridCount ?? 0)", "doc.badge.checkmark")
                metric(L(language, "Faltantes", "Missing"), "\(summary?.readyToCreateCount ?? 0)", "waveform.path.badge.plus")
            }

            Spacer(minLength: 0)

            HStack {
                Button(L(language, "Cancelar", "Cancel")) {
                    store.cancelExistingTextGridChoice()
                    dismiss()
                }
                .keyboardShortcut(.cancelAction)

                Spacer()

                if (summary?.readyToCreateCount ?? 0) > 0 || (summary?.conversionCount ?? 0) > 0 {
                    Button {
                        store.continueMissingTextGrids()
                        dismiss()
                    } label: {
                        Label(L(language, "Continuar faltantes", "Continue missing"), systemImage: "forward.fill")
                    }
                }

                Button(role: .destructive) {
                    store.replaceExistingAndCreateTextGrids()
                    dismiss()
                } label: {
                    Label(L(language, "Substituir existentes", "Replace existing"), systemImage: "arrow.triangle.2.circlepath")
                }
                .buttonStyle(.borderedProminent)
            }
            .controlSize(.large)
        }
        .padding(22)
    }

    private var message: String {
        guard let summary else {
            return L(language, "ALEX encontrou TextGrids existentes.", "ALEX found existing TextGrids.")
        }
        if summary.readyToCreateCount == 0 && summary.conversionCount == 0 {
            return L(
                language,
                "Todos os pares BP já têm TextGrid. Você pode deixar tudo como está ou substituir os TextGrids existentes por novas saídas canônicas.",
                "All BP pairs already have TextGrids. You can leave everything as-is or replace existing TextGrids with new canonical outputs."
            )
        }
        return L(
            language,
            "Alguns pares BP já têm TextGrid. Você pode continuar somente onde falta TextGrid, ou substituir também os TextGrids existentes.",
            "Some BP pairs already have TextGrids. You can continue only where TextGrid is missing, or also replace existing TextGrids."
        )
    }

    private func metric(_ title: String, _ value: String, _ image: String) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Label(title, systemImage: image)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
            Text(value)
                .font(.title3.weight(.semibold).monospacedDigit())
        }
        .padding(10)
        .frame(maxWidth: .infinity, minHeight: 70, alignment: .leading)
        .background(.quaternary.opacity(0.18), in: RoundedRectangle(cornerRadius: 8))
    }
}

private extension PairStatus {
    func localizedTitle(_ language: AppLanguage) -> String {
        switch self {
        case .ready: L(language, "Pronto para criar", "Ready to create")
        case .needsWAVConversion: L(language, "Precisa converter áudio", "Needs audio conversion")
        case .textGridExists: L(language, "Pronto", "Ready")
        case .invalidWAV: L(language, "Áudio inválido", "Invalid audio")
        }
    }

    var tint: Color {
        switch self {
        case .ready: .green
        case .needsWAVConversion: .orange
        case .textGridExists: .secondary
        case .invalidWAV: .red
        }
    }

    var systemImage: String {
        switch self {
        case .ready: "checkmark.circle.fill"
        case .needsWAVConversion: "arrow.triangle.2.circlepath"
        case .textGridExists: "doc.badge.checkmark"
        case .invalidWAV: "exclamationmark.triangle.fill"
        }
    }
}

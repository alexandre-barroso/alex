import ConPhonAlignerCore
import Foundation
import SwiftUI

struct BioEarExtractorView: View {
    @EnvironmentObject private var store: BioEarExtractorStore
    @EnvironmentObject private var menuStore: AppMenuStore
    @Environment(\.appLanguage) private var language

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    CorpusInputPanel(
                        title: L(language, "Corpora BioEar", "BioEar corpora"),
                        subtitle: L(language, "Áudio + TXT + TextGrid", "Audio + TXT + TextGrid"),
                        systemImage: "waveform.path.ecg.rectangle",
                        rows: [
                            RequirementRow(title: L(language, "Mesmo stem", "Same stem"), value: "sample.flac + sample.txt + sample.TextGrid", systemImage: "equal.circle"),
                            RequirementRow(title: L(language, "Áudio", "Audio"), value: L(language, "Convertido para WAV mono 16 kHz primeiro", "Converted to mono 16 kHz WAV first"), systemImage: "arrow.triangle.2.circlepath"),
                            RequirementRow(title: L(language, "Subpastas", "Subfolders"), value: L(language, "Pesquisa recursiva", "Scanned recursively"), systemImage: "folder.badge.gearshape"),
                            RequirementRow(title: L(language, "Qualquer língua", "Any language"), value: "phonemes/phones, words, syllables/syl", systemImage: "list.bullet.clipboard"),
                            RequirementRow(title: L(language, "Português", "Portuguese"), value: L(language, "BP pode criar TextGrids aqui", "BP can create TextGrids here"), systemImage: "text.badge.checkmark")
                        ]
                    )
                    BioEarSettingsPanel()
                        .environmentObject(store)
                    BioEarTierPanel()
                    StatusProgressStrip(
                        isActive: store.isScanning || store.isRunning,
                        title: store.isScanning ? L(language, "Escaneando corpus", "Scanning corpus") : L(language, "Executando CLI oculta", "Running hidden CLI"),
                        detail: store.isScanning
                            ? L(language, "ALEX valida nomes e camadas fora da interface principal.", "ALEX validates names and tiers off the main thread.")
                            : L(language, "Extração, reamostragem, IHC, synapse e redocking rodam fora do SwiftUI.", "Extraction, resampling, IHC, synapse and redocking run outside SwiftUI.")
                    )
                    BioEarSummaryView(summary: store.summary, statusTitle: store.statusTitle(language: language))
                    BioEarOutputView(summary: store.summary)
                        .environmentObject(store)
                    BioEarPairListView(summary: store.summary)
                        .environmentObject(store)
                    BioEarLogPanel(text: store.logText)
                }
                .padding(18)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .sheet(isPresented: conversionSheetBinding) {
            BioEarConversionConfirmationSheet(pairs: store.pendingConversionPairs)
                .environmentObject(store)
                .frame(maxWidth: 760, maxHeight: 560)
        }
        .sheet(isPresented: replacementSheetBinding) {
            BioEarReplacementConfirmationSheet(paths: store.pendingReplacementPaths)
                .environmentObject(store)
                .frame(maxWidth: 760, maxHeight: 520)
        }
        .sheet(isPresented: $store.isShowingTextGridStandardizer) {
            TextGridStandardizationWizard()
                .environmentObject(store)
                .environmentObject(menuStore)
                .frame(minWidth: 720, idealWidth: 820, maxWidth: 920, minHeight: 560, idealHeight: 680)
        }
        .onAppear {
            store.language = language
        }
        .onChange(of: language) { _, newValue in
            store.language = newValue
        }
        .alert(L(language, "O corpus precisa de atenção", "Corpus needs attention"), isPresented: errorBinding) {
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

    private var replacementSheetBinding: Binding<Bool> {
        Binding(
            get: { !store.pendingReplacementPaths.isEmpty },
            set: { if !$0 { store.cancelReplacement() } }
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
                Image(systemName: "waveform.and.magnifyingglass")
                    .font(.system(size: 36, weight: .semibold))
                    .foregroundStyle(.blue)
                    .frame(width: 48, height: 48)

                VStack(alignment: .leading, spacing: 4) {
                    Text(L(language, "Extrator BioEar", "BioEar Extractor"))
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
            store.prepareTextGridStandardizer()
        } label: {
            Label(L(language, "Padronizar TextGrids", "Standardize TextGrids"), systemImage: "wand.and.stars")
        }
        .buttonStyle(HeaderActionButtonStyle(tone: .secondary))
        .disabled(store.selectedFolder == nil || store.isRunning || store.isScanning || store.isPreparingTextGridStandardizer)

        Button {
            store.extract()
        } label: {
            Label(L(language, "Extrair", "Extract"), systemImage: "waveform.path.ecg")
        }
        .buttonStyle(HeaderActionButtonStyle(tone: .primary))
        .disabled(!store.canExtract)

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
}

private struct TextGridStandardizationWizard: View {
    @EnvironmentObject private var store: BioEarExtractorStore
    @EnvironmentObject private var menuStore: AppMenuStore
    @Environment(\.appLanguage) private var language
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 5) {
                    Label(L(language, "Padronizar TextGrids", "Standardize TextGrids"), systemImage: "wand.and.stars")
                        .font(.title2.weight(.semibold))
                    Text(L(language, "Escolha qual camada detectada representa cada nível linguístico. ALEX renomeará essas camadas recursivamente e manterá backups.", "Pick which detected layer means each linguistic level. ALEX will rename those layers recursively and keep backups."))
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer()
                Button {
                    menuStore.showHelp()
                } label: {
                    Label(L(language, "Ajuda", "Help me"), systemImage: "questionmark.circle")
                }
            }

            if let summary = store.textGridStandardizationSummary {
                VStack(alignment: .leading, spacing: 10) {
                    Label(L(language, "\(summary.textGridCount) arquivos TextGrid escaneados", "\(summary.textGridCount) TextGrid files scanned"), systemImage: "doc.text.magnifyingglass")
                        .font(.headline)

                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 180), spacing: 10)], alignment: .leading, spacing: 10) {
                        ForEach(summary.layers.prefix(12)) { layer in
                            HStack {
                                Text(layer.name)
                                    .font(.caption.weight(.semibold))
                                    .lineLimit(1)
                                Spacer()
                                Text("\(layer.count)")
                                    .font(.caption.monospacedDigit())
                                    .foregroundStyle(.secondary)
                            }
                            .padding(10)
                            .background(.quaternary.opacity(0.18), in: RoundedRectangle(cornerRadius: 8))
                        }
                    }
                }

                VStack(alignment: .leading, spacing: 12) {
                    Label(L(language, "Mapear camadas", "Map layers"), systemImage: "point.3.connected.trianglepath.dotted")
                        .font(.headline)
                    Text(L(language, "Os nomes finais preferidos são `phonemes`, `words`, `syllables` e `utterance` opcional. Cada arquivo deve conter uma sentença.", "Preferred final names are `phonemes`, `words`, `syllables`, and optional `utterance`. Each file should contain one sentence."))
                        .font(.callout)
                        .foregroundStyle(.secondary)

                    layerPicker(L(language, "Fonemas / phones", "Phonemes / phones"), selection: $store.textGridStandardizationSelection.phonemes, summary: summary, allowNone: false)
                    layerPicker(L(language, "Palavras", "Words"), selection: $store.textGridStandardizationSelection.words, summary: summary, allowNone: false)
                    layerPicker(L(language, "Sílabas / syl", "Syllables / syl"), selection: $store.textGridStandardizationSelection.syllables, summary: summary, allowNone: false)
                    layerPicker(L(language, "Sentença / utterance", "Utterance / sentence"), selection: $store.textGridStandardizationSelection.utterance, summary: summary, allowNone: true)
                }
                .padding(14)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
            } else {
                ProgressView(L(language, "Escaneando camadas TextGrid...", "Scanning TextGrid layers..."))
            }

            Spacer(minLength: 0)

            HStack {
                Button(L(language, "Cancelar", "Cancel")) {
                    store.cancelTextGridStandardizer()
                    dismiss()
                }
                .keyboardShortcut(.cancelAction)

                Spacer()

                Button {
                    store.applyTextGridStandardization()
                    dismiss()
                } label: {
                    Label(L(language, "Aplicar a todos os TextGrids", "Apply to all TextGrids"), systemImage: "checkmark.circle.fill")
                }
                .buttonStyle(.borderedProminent)
                .disabled(!canApply)
            }
            .controlSize(.large)
        }
        .padding(22)
    }

    private var canApply: Bool {
        !store.textGridStandardizationSelection.phonemes.isEmpty
            && !store.textGridStandardizationSelection.words.isEmpty
            && !store.textGridStandardizationSelection.syllables.isEmpty
    }

    private func layerPicker(
        _ title: String,
        selection: Binding<String>,
        summary: TextGridStandardizationSummary,
        allowNone: Bool
    ) -> some View {
        HStack {
            Text(title)
                .font(.callout.weight(.semibold))
                .frame(width: 155, alignment: .leading)
            Picker(title, selection: selection) {
                if allowNone {
                    Text(L(language, "Sem camada - sintetizar", "No layer - synthesize")).tag("")
                }
                ForEach(summary.layers) { layer in
                    Text("\(layer.name) (\(layer.count))").tag(layer.name)
                }
            }
            .labelsHidden()
            .pickerStyle(.menu)
        }
    }
}

private struct BioEarSettingsPanel: View {
    @EnvironmentObject private var store: BioEarExtractorStore
    @Environment(\.appLanguage) private var language
    private let maxWorkers = max(1, ProcessInfo.processInfo.processorCount)

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label(L(language, "Extração BioEar", "BioEar extraction"), systemImage: "slider.horizontal.3")
                    .font(.headline)
                Spacer()
                HStack(spacing: 6) {
                    Text(L(language, "Tag", "Tag"))
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    TextField("cust", text: languageTagBinding)
                        .textFieldStyle(.roundedBorder)
                        .font(.caption.monospaced())
                        .frame(width: 64)
                        .disabled(store.isRunning)
                }
            }

            Picker(L(language, "Modo", "Mode"), selection: $store.extractionSettings.profile) {
                ForEach(BioEarExtractionProfile.allCases) { profile in
                    Text(profile.localizedTitle(language)).tag(profile)
                }
            }
            .pickerStyle(.segmented)
            .disabled(store.isRunning)

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 185), spacing: 10)], alignment: .leading, spacing: 10) {
                modeCard(.fast, "48 CF", L(language, "3 fibras", "3 fibers"))
                modeCard(.balanced, "64 CF", L(language, "10 fibras", "10 fibers"))
                modeCard(.contextLite, "80 CF", L(language, "20 fibras", "20 fibers"))
            }

            VStack(alignment: .leading, spacing: 8) {
                Label(L(language, "Matrizes ricas", "Rich arrays"), systemImage: "square.stack.3d.up")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                HStack(spacing: 10) {
                    Toggle("IHC", isOn: $store.extractionSettings.auxiliary.includeIHC)
                    Toggle(L(language, "Sinapse", "Synapse"), isOn: $store.extractionSettings.auxiliary.includeSynapseDrive)
                    Toggle("Redocking", isOn: $store.extractionSettings.auxiliary.includeRedocking)
                }
                .toggleStyle(.button)
                .disabled(store.isRunning)
            }

            HStack(spacing: 18) {
                Stepper(value: $store.extractionSettings.jobs, in: 1...maxWorkers) {
                    Label(L(language, "\(store.extractionSettings.jobs) processos", "\(store.extractionSettings.jobs) workers"), systemImage: "cpu")
                        .font(.callout.weight(.semibold))
                }
                .disabled(store.isRunning)

                Stepper(value: $store.extractionSettings.threadsPerFile, in: 1...max(1, min(4, maxWorkers))) {
                    Label(L(language, "\(store.extractionSettings.threadsPerFile) thread/arquivo", "\(store.extractionSettings.threadsPerFile) thread/file"), systemImage: "memorychip")
                        .font(.callout.weight(.semibold))
                }
                .disabled(store.isRunning)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
    }

    private func modeCard(_ profile: BioEarExtractionProfile, _ cf: String, _ fibers: String) -> some View {
        HStack(spacing: 8) {
            Image(systemName: store.extractionSettings.profile == profile ? "checkmark.circle.fill" : "circle")
                .foregroundStyle(.secondary)
                .frame(width: 18)
            VStack(alignment: .leading, spacing: 2) {
                Text(profile.localizedTitle(language))
                    .font(.caption.weight(.semibold))
                Text("\(cf), \(fibers)")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, minHeight: 58, alignment: .leading)
        .background(.quaternary.opacity(0.16), in: RoundedRectangle(cornerRadius: 8))
    }

    private var languageTagBinding: Binding<String> {
        Binding(
            get: { store.extractionSettings.languageTag },
            set: { store.extractionSettings.languageTag = BioEarExtractionSettings.normalizedLanguageTag($0) }
        )
    }
}

private struct BioEarTierPanel: View {
    @Environment(\.appLanguage) private var language

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(L(language, "Camadas TextGrid reconhecidas", "Recognized TextGrid tiers"), systemImage: "list.bullet.clipboard")
                .font(.headline)

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 210), spacing: 10)], alignment: .leading, spacing: 10) {
                tierCard(L(language, "Fonemas", "Phonemes"), L(language, "`phonemes` ou `phones`", "`phonemes` or `phones`"), "waveform")
                tierCard(L(language, "Palavras", "Words"), "`words`", "textformat")
                tierCard(L(language, "Sílabas", "Syllables"), L(language, "`syllables` ou `syl`", "`syllables` or `syl`"), "text.word.spacing")
                tierCard(L(language, "Sentença", "Utterance"), L(language, "`utterance` ou `sentence`; opcional", "`utterance` or `sentence`; optional"), "paragraphsign")
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
    }

    private func tierCard(_ title: String, _ value: String, _ image: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: image)
                .foregroundStyle(.secondary)
                .frame(width: 18)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.caption.weight(.semibold))
                Text(value)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                    .minimumScaleFactor(0.85)
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, minHeight: 58, alignment: .leading)
        .background(.quaternary.opacity(0.16), in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct BioEarSummaryView: View {
    @Environment(\.appLanguage) private var language
    let summary: BioEarScanSummary?
    let statusTitle: String

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label(statusTitle, systemImage: "waveform.path")
                .font(.headline)

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 145), spacing: 10)], alignment: .leading, spacing: 10) {
                metric(L(language, "Trios", "Triples"), "\(summary?.pairs.count ?? 0)", "doc.on.doc")
                metric(L(language, "Prontos", "Ready"), "\(summary?.readyCount ?? 0)", "play.circle")
                metric(L(language, "Converter", "Convert"), "\(summary?.conversionCount ?? 0)", "arrow.triangle.2.circlepath")
                metric(L(language, "Bloqueados", "Blocked"), "\(summary?.blockedCount ?? 0)", "exclamationmark.octagon")
                metric(L(language, "Sem TXT", "No TXT"), "\(summary?.missingTXTCount ?? 0)", "doc.badge.questionmark")
                metric(L(language, "Sem camadas", "No tiers"), "\(summary?.missingTierCount ?? 0)", "list.bullet.clipboard")
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
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

private struct BioEarOutputView: View {
    @EnvironmentObject private var store: BioEarExtractorStore
    @Environment(\.appLanguage) private var language
    let summary: BioEarScanSummary?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(L(language, "Saídas", "Outputs"), systemImage: "externaldrive")
                .font(.headline)

            if let state = summary?.outputState {
                VStack(alignment: .leading, spacing: 8) {
                    outputRow("Corpus ConPhon", state.dataAuditoryURL)
                    outputRow(L(language, "BioEar canônico", "Canonical BioEar"), state.dataBioEarURL)
                    Text(L(language, "HDF5 por trio", "HDF5 per trio"))
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    Text(L(language, "Gerado ao lado do WAV/TextGrid como <nome>_bioear.h5.", "Generated beside the WAV/TextGrid as <name>_bioear.h5."))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    Text(L(language, "Contrato biológico", "Biological contract"))
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    Text(L(language, "Somente /audio, /periphery e /labels no HDF5; labels nunca entram no modelo periférico.", "Only /audio, /periphery and /labels in HDF5; labels never enter the peripheral model."))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)

                    if !state.existingGeneratedOutputs.isEmpty {
                        Label(L(language, "Saídas geradas já existem e exigem confirmação antes da substituição.", "Generated outputs already exist and require confirmation before replacement."), systemImage: "arrow.triangle.2.circlepath")
                            .font(.caption)
                            .foregroundStyle(.orange)
                            .fixedSize(horizontal: false, vertical: true)
                    }

                    if !state.existingUnmarkedOutputs.isEmpty {
                        Label(L(language, "Saídas existentes sem marcador foram bloqueadas para proteger dados do usuário.", "Existing unmarked outputs were blocked to protect user data."), systemImage: "lock.trianglebadge.exclamationmark")
                            .font(.caption)
                            .foregroundStyle(.red)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            } else {
                Text(L(language, "As saídas serão criadas dentro da pasta selecionada.", "Outputs will be created inside the selected folder."))
                    .foregroundStyle(.secondary)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
    }

    private func outputRow(_ title: String, _ url: URL) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
            Text(store.relativePath(url))
                .font(.caption.monospaced())
                .lineLimit(2)
                .truncationMode(.middle)
                .textSelection(.enabled)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct BioEarPairListView: View {
    @EnvironmentObject private var store: BioEarExtractorStore
    @Environment(\.appLanguage) private var language
    let summary: BioEarScanSummary?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(L(language, "Trios", "Triples"), systemImage: "list.bullet.rectangle")
                .font(.headline)

            if let summary, !summary.pairs.isEmpty {
                LazyVStack(alignment: .leading, spacing: 8) {
                    ForEach(Array(summary.pairs.prefix(200))) { pair in
                        BioEarPairRow(pair: pair)
                            .environmentObject(store)
                    }
                    if summary.pairs.count > 200 {
                        Label(L(language, "Mostrando os primeiros 200 de \(summary.pairs.count) trios.", "Showing first 200 of \(summary.pairs.count) trios."), systemImage: "list.bullet.rectangle.portrait")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            } else {
                Text(L(language, "Selecione uma pasta com pelo menos um trio .wav, .TextGrid e .txt de mesmo nome.", "Choose a folder with at least one same-stem .wav, .TextGrid and .txt trio."))
                    .foregroundStyle(.secondary)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct BioEarPairRow: View {
    @EnvironmentObject private var store: BioEarExtractorStore
    @Environment(\.appLanguage) private var language
    let pair: BioEarExtractionPair

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
                .lineLimit(2)
                .multilineTextAlignment(.trailing)
        }
        .padding(10)
        .background(.quaternary.opacity(0.16), in: RoundedRectangle(cornerRadius: 8))
    }

    private var detail: String {
        if !pair.missingTiers.isEmpty {
            return L(language, "Camadas ausentes: \(pair.missingTiers.joined(separator: ", "))", "Missing tiers: \(pair.missingTiers.joined(separator: ", "))")
        }
        if pair.txtURL == nil {
            return L(language, "É obrigatório existir um .txt de mesmo nome.", "A same-stem .txt is required.")
        }
        if pair.textGridURL == nil {
            return L(language, "É obrigatório existir um .TextGrid de mesmo nome.", "A same-stem .TextGrid is required.")
        }
        if let info = pair.audioInfo {
            return L(language, "\(info.channels) canal(is), \(info.sampleRate) Hz; camadas ok", "\(info.channels) channel(s), \(info.sampleRate) Hz; tiers ok")
        }
        return pair.audioError ?? L(language, "O WAV não pôde ser inspecionado", "The WAV could not be inspected")
    }
}

private struct BioEarLogPanel: View {
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
            .frame(minHeight: 160, maxHeight: 280)
            .background(.black.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct BioEarConversionConfirmationSheet: View {
    @EnvironmentObject private var store: BioEarExtractorStore
    @Environment(\.appLanguage) private var language
    @Environment(\.dismiss) private var dismiss
    let pairs: [BioEarExtractionPair]

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Label(L(language, "Converter áudio?", "Convert audio?"), systemImage: "arrow.triangle.2.circlepath")
                .font(.title2.weight(.semibold))
            Text(L(language, "ALEX criará WAVs mono 16 kHz antes da extração. WAVs fora do padrão são movidos para `original_wav`; arquivos FLAC/MP3/M4A/AIFF/CAF etc. são preservados e recebem um WAV irmão. Cada arquivo deve conter apenas uma sentença/utterance.", "ALEX will create mono 16 kHz WAVs before extraction. Non-standard WAVs move to `original_wav`; FLAC/MP3/M4A/AIFF/CAF etc. are preserved and receive a sibling WAV. Each file must contain only one sentence/utterance."))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            ScrollView {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(pairs) { pair in
                        Text(store.relativePath(pair.wavURL))
                            .font(.caption.monospaced())
                            .textSelection(.enabled)
                            .lineLimit(2)
                            .truncationMode(.middle)
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

private struct BioEarReplacementConfirmationSheet: View {
    @EnvironmentObject private var store: BioEarExtractorStore
    @Environment(\.appLanguage) private var language
    @Environment(\.dismiss) private var dismiss
    let paths: [URL]

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Label(L(language, "Substituir saídas geradas?", "Replace generated outputs?"), systemImage: "arrow.triangle.2.circlepath")
                .font(.title2.weight(.semibold))
            Text(L(language, "Somente saídas marcadas como geradas por este extrator serão substituídas. TextGrids existentes não são modificados.", "Only outputs marked as generated by this extractor will be replaced. Existing TextGrids are not modified."))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            ScrollView {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(paths, id: \.path) { path in
                        Text(store.relativePath(path))
                            .font(.caption.monospaced())
                            .textSelection(.enabled)
                            .lineLimit(2)
                            .truncationMode(.middle)
                            .padding(8)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(.quaternary.opacity(0.18), in: RoundedRectangle(cornerRadius: 8))
                    }
                }
            }
            .frame(maxHeight: 300)

            HStack {
                Button(role: .destructive) {
                    store.replaceAndExtract()
                    dismiss()
                } label: {
                    Label(L(language, "Substituir e extrair", "Replace and extract"), systemImage: "trash")
                }
                .buttonStyle(.borderedProminent)

                Spacer()

                Button(L(language, "Cancelar", "Cancel")) {
                    store.cancelReplacement()
                    dismiss()
                }
                .keyboardShortcut(.cancelAction)
            }
            .controlSize(.large)
        }
        .padding(22)
    }
}

private extension BioEarPairStatus {
    func localizedTitle(_ language: AppLanguage) -> String {
        switch self {
        case .ready: L(language, "Pronto", "Ready")
        case .needsWAVConversion: L(language, "Precisa converter áudio", "Needs audio conversion")
        case .missingTXT: L(language, "Faltando TXT", "Missing TXT")
        case .missingTextGrid: L(language, "Faltando TextGrid", "Missing TextGrid")
        case .missingTiers: L(language, "Camadas ausentes", "Missing tiers")
        case .invalidWAV: L(language, "Áudio inválido", "Invalid audio")
        }
    }

    var tint: Color {
        switch self {
        case .ready: .green
        case .needsWAVConversion: .orange
        case .missingTXT, .missingTextGrid, .missingTiers, .invalidWAV: .red
        }
    }

    var systemImage: String {
        switch self {
        case .ready: "checkmark.circle.fill"
        case .needsWAVConversion: "arrow.triangle.2.circlepath"
        case .missingTXT: "doc.badge.questionmark"
        case .missingTextGrid: "waveform.badge.exclamationmark"
        case .missingTiers: "list.bullet.clipboard"
        case .invalidWAV: "exclamationmark.triangle.fill"
        }
    }
}

private extension BioEarExtractionProfile {
    func localizedTitle(_ language: AppLanguage) -> String {
        switch self {
        case .fast: L(language, "Rápido", "Fast")
        case .balanced: L(language, "Equilibrado", "Balanced")
        case .contextLite: L(language, "Contexto leve", "Context-lite")
        }
    }
}

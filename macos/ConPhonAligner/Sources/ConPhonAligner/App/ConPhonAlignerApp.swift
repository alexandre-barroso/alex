import AppKit
import SwiftUI

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.applicationIconImage = AlignerIconFactory.makeIcon()
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }
}

@main
struct ConPhonAlignerApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var alignerStore = AlignerStore()
    @StateObject private var bioEarStore = BioEarExtractorStore()
    @StateObject private var menuStore = AppMenuStore()
    @AppStorage("alex.ui.language") private var languageRaw = AppLanguage.portuguese.rawValue

    private var language: AppLanguage {
        AppLanguage.from(languageRaw)
    }

    var body: some Scene {
        WindowGroup(L(language, "ALEX - Alinhador TextGrid e BioEar", "ALEX - TextGrid Aligner and BioEar")) {
            ContentView()
                .environmentObject(alignerStore)
                .environmentObject(bioEarStore)
                .environmentObject(menuStore)
                .frame(minWidth: 600, idealWidth: 980, minHeight: 520, idealHeight: 720)
        }
        .commands {
            CommandGroup(after: .newItem) {
                Button(L(language, "Selecionar pasta do alinhador...", "Choose aligner folder...")) {
                    alignerStore.chooseFolder(language: language)
                }
                .keyboardShortcut("o", modifiers: [.command])

                Button(L(language, "Criar TextGrids", "Create TextGrids")) {
                    alignerStore.createTextGrids()
                }
                .keyboardShortcut("r", modifiers: [.command])
                .disabled(!alignerStore.canRunTextGridAction)

                Button(L(language, "Selecionar pasta BioEar...", "Choose BioEar folder...")) {
                    bioEarStore.chooseFolder(language: language)
                }
                .keyboardShortcut("o", modifiers: [.command, .shift])

                Button(L(language, "Extrair BioEar", "Extract BioEar")) {
                    bioEarStore.extract()
                }
                .keyboardShortcut("e", modifiers: [.command])
                .disabled(!bioEarStore.canExtract)
            }
            CommandMenu(L(language, "Ferramentas", "Tools")) {
                Button(L(language, "Reescanear alinhador", "Rescan aligner")) {
                    alignerStore.scan()
                }
                .keyboardShortcut("r", modifiers: [.command, .shift])
                .disabled(alignerStore.selectedFolder == nil || alignerStore.isRunning || alignerStore.isScanning)

                Button(L(language, "Reescanear extrator", "Rescan extractor")) {
                    bioEarStore.scan()
                }
                .keyboardShortcut("e", modifiers: [.command, .shift])
                .disabled(bioEarStore.selectedFolder == nil || bioEarStore.isRunning || bioEarStore.isScanning)

                Divider()

                Button(L(language, "Parar execução", "Stop run")) {
                    alignerStore.stop()
                    bioEarStore.stop()
                }
                .keyboardShortcut(".", modifiers: [.command])
                .disabled(!alignerStore.isRunning && !bioEarStore.isRunning)
            }
            CommandMenu(L(language, "Instruções", "Instructions")) {
                Button(L(language, "Requisitos do corpus...", "Corpus requirements...")) {
                    menuStore.showHelp()
                }
                .keyboardShortcut("i", modifiers: [.command])

                Button(L(language, "Sobre o ALEX...", "About ALEX...")) {
                    menuStore.showAbout()
                }
            }
            CommandGroup(replacing: .help) {
                Button(L(language, "Instruções do ALEX...", "ALEX Instructions...")) {
                    menuStore.showHelp()
                }
                .keyboardShortcut("?", modifiers: [.command])

                Button(L(language, "Sobre o ALEX...", "About ALEX...")) {
                    menuStore.showAbout()
                }
            }
        }
    }
}

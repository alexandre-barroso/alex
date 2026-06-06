import Foundation

public enum BioEarCommandBuilder {
    public static func scanCommand(repoRoot: URL, inputFolder: URL, pythonPath: String) -> ProcessCommand {
        ProcessCommand(
            executable: pythonPath,
            arguments: [
                repoRoot.appendingPathComponent("macos/ConPhonAligner/Tools/extract_bioear.py").path,
                "scan",
                "--input",
                inputFolder.path,
                "--json"
            ],
            workingDirectory: repoRoot
        )
    }

    public static func runCommand(
        repoRoot: URL,
        inputFolder: URL,
        replaceConfirmed: Bool,
        settings: BioEarExtractionSettings = .productionDefault(),
        pythonPath: String
    ) -> ProcessCommand {
        var arguments = [
            repoRoot.appendingPathComponent("macos/ConPhonAligner/Tools/extract_bioear.py").path,
            "run",
            "--input",
            inputFolder.path,
            "--profile",
            settings.profile.rawValue,
            "--jobs",
            String(settings.jobs),
            "--language-tag",
            settings.languageTag,
            "--json"
        ]
        if replaceConfirmed {
            arguments.append("--replace-confirmed")
        }
        return ProcessCommand(
            executable: pythonPath,
            arguments: arguments,
            workingDirectory: repoRoot
        )
    }

    public static func richAuxCommand(
        repoRoot: URL,
        inputFolder: URL,
        replaceConfirmed: Bool,
        settings: BioEarExtractionSettings = .productionDefault(),
        pythonPath: String
    ) -> ProcessCommand {
        var arguments = [
            repoRoot.appendingPathComponent("macos/ConPhonAligner/Tools/append_bioear_aux.py").path,
            "--sidecar-root",
            inputFolder.path,
            "--components",
            settings.auxiliary.componentArgument,
            "--jobs",
            String(settings.jobs),
            "--threads-per-file",
            String(settings.threadsPerFile),
            "--json"
        ]
        if replaceConfirmed {
            arguments.append("--replace-confirmed")
        }
        return ProcessCommand(
            executable: pythonPath,
            arguments: arguments,
            workingDirectory: repoRoot
        )
    }

    public static func textGridStandardizationCommand(
        repoRoot: URL,
        inputFolder: URL,
        selection: TextGridStandardizationSelection,
        pythonPath: String
    ) -> ProcessCommand {
        ProcessCommand(
            executable: pythonPath,
            arguments: [
                repoRoot.appendingPathComponent("macos/ConPhonAligner/Tools/standardize_textgrid_layers.py").path,
                "--input",
                inputFolder.path,
                "--phone",
                selection.phonemes,
                "--word",
                selection.words,
                "--syllable",
                selection.syllables,
                "--sentence",
                selection.utterance,
                "--json"
            ],
            workingDirectory: repoRoot
        )
    }
}

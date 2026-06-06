import Foundation

public enum AlignerCommandBuilder {
    public static func alignmentCommand(
        repoRoot: URL,
        selectedFolder: URL,
        pythonPath: String,
        replaceExistingTextGrids: Bool = false
    ) -> ProcessCommand {
        let existingPolicy = replaceExistingTextGrids ? "--no-skip-existing" : "--skip-existing"
        return ProcessCommand(
            executable: pythonPath,
            arguments: [
                repoRoot.appendingPathComponent("macos/ConPhonAligner/Tools/run_aligner.py").path,
                selectedFolder.path,
                "--am-tag",
                "mono",
                existingPolicy,
                "--continue-on-error",
                "--show-unmatched"
            ],
            workingDirectory: repoRoot
        )
    }

    public static func normalizationCommand(repoRoot: URL, wavURLs: [URL], pythonPath: String) -> ProcessCommand {
        ProcessCommand(
            executable: pythonPath,
            arguments: [
                repoRoot.appendingPathComponent("macos/ConPhonAligner/Tools/normalize_wavs.py").path,
                "--json"
            ] + wavURLs.map(\.path),
            workingDirectory: repoRoot
        )
    }
}

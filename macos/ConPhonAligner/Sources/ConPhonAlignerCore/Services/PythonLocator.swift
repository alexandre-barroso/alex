import Foundation

public enum PythonLocator {
    public static func locate() -> String {
        if let configured = ProcessInfo.processInfo.environment["CONPHON_PYTHON"],
           FileManager.default.isExecutableFile(atPath: configured) {
            return configured
        }
        if let bundled = ProcessInfo.processInfo.environment["ALEX_BUNDLED_PYTHON"],
           FileManager.default.isExecutableFile(atPath: bundled) {
            return bundled
        }
        let repoRoot = RepoLocator.locate()
        let bundledPython = Bundle.main.resourceURL?.appendingPathComponent("python_runtime/bin/python3.12").path
        let candidates = [
            bundledPython,
            repoRoot.appendingPathComponent(".venv/bin/python").path,
            repoRoot.appendingPathComponent("aligner/.venv/bin/python").path,
            "/usr/bin/python3"
        ].compactMap { $0 }
        for candidate in candidates where FileManager.default.isExecutableFile(atPath: candidate) {
            return candidate
        }
        return "/usr/bin/python3"
    }
}

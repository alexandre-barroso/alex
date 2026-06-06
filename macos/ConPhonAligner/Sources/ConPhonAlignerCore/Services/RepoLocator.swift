import Foundation

public enum RepoLocator {
    public static func locate(startingAt candidates: [URL] = []) -> URL {
        let environment = ProcessInfo.processInfo.environment["CONPHON_REPO_ROOT"].map(URL.init(fileURLWithPath:))
        let current = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
        let bundle = Bundle.main.bundleURL
        let bundledRepo = Bundle.main.resourceURL?.appendingPathComponent("ALEX", isDirectory: true)
        let seedURLs = ([environment, bundledRepo].compactMap { $0 } + candidates + [current, bundle]).map(\.standardizedFileURL)

        for seed in seedURLs {
            if let root = walkUp(from: seed) {
                return root
            }
        }
        return current
    }

    private static func walkUp(from seed: URL) -> URL? {
        var current = seed.hasDirectoryPath ? seed : seed.deletingLastPathComponent()
        for _ in 0..<12 {
            if FileManager.default.fileExists(atPath: current.appendingPathComponent("aligner/align_folder.py").path) {
                return current
            }
            let parent = current.deletingLastPathComponent()
            if parent.path == current.path {
                return nil
            }
            current = parent
        }
        return nil
    }
}

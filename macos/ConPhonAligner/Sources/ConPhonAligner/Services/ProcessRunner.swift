import Foundation

struct ProcessOutput {
    let exitCode: Int32
    let stdout: String
    let stderr: String
    let duration: TimeInterval

    var combinedText: String {
        if stderr.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return stdout
        }
        return stdout + "\n\nstderr:\n" + stderr
    }
}

enum ProcessRunnerError: LocalizedError {
    case missingWorkingDirectory(String)

    var errorDescription: String? {
        switch self {
        case .missingWorkingDirectory(let path): "A pasta de trabalho não existe: \(path)"
        }
    }
}

final class ProcessRunner: @unchecked Sendable {
    private let lock = NSLock()
    private var currentProcess: Process?

    func terminate() {
        lock.lock()
        let process = currentProcess
        lock.unlock()
        process?.terminate()
    }

    func run(
        executable: String,
        arguments: [String],
        workingDirectory: URL,
        onOutput: @escaping @Sendable (String) -> Void = { _ in }
    ) async throws -> ProcessOutput {
        try await Task.detached(priority: .userInitiated) { [weak self] in
            guard FileManager.default.fileExists(atPath: workingDirectory.path) else {
                throw ProcessRunnerError.missingWorkingDirectory(workingDirectory.path)
            }

            let started = Date()
            let process = Process()
            process.executableURL = URL(fileURLWithPath: executable)
            process.arguments = arguments
            process.currentDirectoryURL = workingDirectory

            var environment = ProcessInfo.processInfo.environment
            let srcPath = workingDirectory.appendingPathComponent("src").path
            var pythonPathEntries = [srcPath]
            if let bundledSitePackages = environment["ALEX_BUNDLED_SITE_PACKAGES"], !bundledSitePackages.isEmpty {
                pythonPathEntries.append(bundledSitePackages)
            } else if let resourcePath = Bundle.main.resourceURL?.path {
                let pythonEnv = URL(fileURLWithPath: resourcePath, isDirectory: true)
                    .appendingPathComponent("python_env/lib/python3.12/site-packages")
                    .path
                if FileManager.default.fileExists(atPath: pythonEnv) {
                    environment["ALEX_BUNDLED_SITE_PACKAGES"] = pythonEnv
                    pythonPathEntries.append(pythonEnv)
                }
            }
            if environment["ALEX_BUNDLED_PYTHON"] == nil,
               let resourcePath = Bundle.main.resourceURL?.path {
                let bundledPython = URL(fileURLWithPath: resourcePath, isDirectory: true)
                    .appendingPathComponent("python_runtime/bin/python3.12")
                    .path
                if FileManager.default.isExecutableFile(atPath: bundledPython) {
                    environment["ALEX_BUNDLED_PYTHON"] = bundledPython
                    environment["CONPHON_PYTHON"] = bundledPython
                    environment["PYTHONHOME"] = URL(fileURLWithPath: resourcePath, isDirectory: true)
                        .appendingPathComponent("python_runtime")
                        .path
                }
            }
            if let resourcePath = Bundle.main.resourceURL?.path {
                let javaHome = URL(fileURLWithPath: resourcePath, isDirectory: true)
                    .appendingPathComponent("java_home")
                    .path
                let javaBin = URL(fileURLWithPath: javaHome, isDirectory: true)
                    .appendingPathComponent("bin")
                    .path
                if FileManager.default.isExecutableFile(atPath: javaBin + "/java") {
                    environment["JAVA_HOME"] = javaHome
                    let previousPath = environment["PATH"] ?? "/usr/bin:/bin:/usr/sbin:/sbin"
                    environment["PATH"] = javaBin + ":" + previousPath
                }
            }
            environment["PYTHONPATH"] = pythonPathEntries.joined(separator: ":")
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            let tempRoot = URL(fileURLWithPath: NSTemporaryDirectory(), isDirectory: true)
                .appendingPathComponent("conphon-aligner-cache", isDirectory: true)
                .path
            environment["ALEX_USE_WRITABLE_SPEECH_ENGINE_RUNTIME"] = "1"
            environment["ALEX_CACHE_ROOT"] = tempRoot + "/alex-runtime"
            environment["MPLCONFIGDIR"] = tempRoot + "/matplotlib"
            environment["XDG_CACHE_HOME"] = tempRoot
            process.environment = environment

            let stdout = Pipe()
            let stderr = Pipe()
            process.standardOutput = stdout
            process.standardError = stderr

            try process.run()
            self?.setCurrentProcess(process)
            defer { self?.clearCurrentProcess(process) }

            let stdoutTask = Task.detached(priority: .utility) {
                Self.readStream(stdout.fileHandleForReading, onOutput: onOutput)
            }
            let stderrTask = Task.detached(priority: .utility) {
                Self.readStream(stderr.fileHandleForReading) { chunk in
                    onOutput("\n[stderr] " + chunk)
                }
            }

            process.waitUntilExit()

            let stdoutText = await stdoutTask.value
            let stderrText = await stderrTask.value
            return ProcessOutput(
                exitCode: process.terminationStatus,
                stdout: stdoutText,
                stderr: stderrText,
                duration: Date().timeIntervalSince(started)
            )
        }.value
    }

    private func setCurrentProcess(_ process: Process) {
        lock.lock()
        currentProcess = process
        lock.unlock()
    }

    private func clearCurrentProcess(_ process: Process) {
        lock.lock()
        if currentProcess === process {
            currentProcess = nil
        }
        currentProcess = nil
        lock.unlock()
    }

    private static func readStream(_ handle: FileHandle, onOutput: @escaping @Sendable (String) -> Void) -> String {
        var collected = ""
        while true {
            let data = handle.availableData
            if data.isEmpty {
                break
            }
            let chunk = String(data: data, encoding: .utf8) ?? ""
            collected += chunk
            if !chunk.isEmpty {
                onOutput(chunk)
            }
        }
        return collected
    }
}

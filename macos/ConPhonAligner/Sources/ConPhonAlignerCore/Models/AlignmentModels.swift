import Foundation

public struct AudioInfo: Equatable, Sendable {
    public let sampleRate: Int
    public let channels: Int
    public let bitsPerSample: Int
    public let formatCode: Int

    public init(sampleRate: Int, channels: Int, bitsPerSample: Int, formatCode: Int) {
        self.sampleRate = sampleRate
        self.channels = channels
        self.bitsPerSample = bitsPerSample
        self.formatCode = formatCode
    }

    public var isMono16kHz: Bool {
        channels == 1 && sampleRate == 16_000
    }
}

public enum PairStatus: String, Equatable, Sendable {
    case ready
    case needsWAVConversion
    case textGridExists
    case invalidWAV
}

public struct AlignmentPair: Identifiable, Equatable, Sendable {
    public let id: String
    public let wavURL: URL
    public let txtURL: URL
    public let textGridURL: URL
    public let audioInfo: AudioInfo?
    public let audioError: String?
    public let status: PairStatus

    public init(
        wavURL: URL,
        txtURL: URL,
        textGridURL: URL,
        audioInfo: AudioInfo?,
        audioError: String?,
        status: PairStatus
    ) {
        self.id = wavURL.path
        self.wavURL = wavURL
        self.txtURL = txtURL
        self.textGridURL = textGridURL
        self.audioInfo = audioInfo
        self.audioError = audioError
        self.status = status
    }
}

public struct FolderScanSummary: Equatable, Sendable {
    public let rootURL: URL
    public let pairs: [AlignmentPair]
    public let unmatchedWAVCount: Int
    public let unmatchedTXTCount: Int

    public init(rootURL: URL, pairs: [AlignmentPair], unmatchedWAVCount: Int, unmatchedTXTCount: Int) {
        self.rootURL = rootURL
        self.pairs = pairs
        self.unmatchedWAVCount = unmatchedWAVCount
        self.unmatchedTXTCount = unmatchedTXTCount
    }

    public var isSelectable: Bool { !pairs.isEmpty }
    public var readyCount: Int { pairs.filter { $0.status == .ready || $0.status == .textGridExists }.count }
    public var readyToCreateCount: Int { pairs.filter { $0.status == .ready }.count }
    public var conversionCount: Int { pairs.filter { $0.status == .needsWAVConversion }.count }
    public var existingTextGridCount: Int { pairs.filter { $0.status == .textGridExists }.count }
    public var invalidWAVCount: Int { pairs.filter { $0.status == .invalidWAV }.count }
    public var isComplete: Bool {
        !pairs.isEmpty
            && pairs.allSatisfy { $0.status == .textGridExists }
            && unmatchedWAVCount == 0
            && unmatchedTXTCount == 0
    }

    public var canCreateTextGrids: Bool {
        invalidWAVCount == 0 && (readyToCreateCount > 0 || conversionCount > 0)
    }
}

public struct ProcessCommand: Equatable, Sendable {
    public let executable: String
    public let arguments: [String]
    public let workingDirectory: URL

    public init(executable: String, arguments: [String], workingDirectory: URL) {
        self.executable = executable
        self.arguments = arguments
        self.workingDirectory = workingDirectory
    }
}

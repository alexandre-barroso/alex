import Foundation

public enum BioEarExtractionProfile: String, CaseIterable, Identifiable, Sendable {
    case fast
    case balanced
    case contextLite = "context-lite"

    public var id: String { rawValue }

    public var title: String {
        switch self {
        case .fast: "Fast"
        case .balanced: "Balanced"
        case .contextLite: "Context-lite"
        }
    }

    public var shortSpec: String {
        switch self {
        case .fast: "48 CF, 3 fibers"
        case .balanced: "64 CF, 10 fibers"
        case .contextLite: "80 CF, 20 fibers"
        }
    }
}

public struct BioEarAuxiliarySelection: Equatable, Sendable {
    public var includeIHC: Bool
    public var includeSynapseDrive: Bool
    public var includeRedocking: Bool

    public init(includeIHC: Bool, includeSynapseDrive: Bool, includeRedocking: Bool) {
        self.includeIHC = includeIHC
        self.includeSynapseDrive = includeSynapseDrive
        self.includeRedocking = includeRedocking
    }

    public static let richDefault = BioEarAuxiliarySelection(
        includeIHC: true,
        includeSynapseDrive: true,
        includeRedocking: true
    )

    public var hasSelection: Bool {
        includeIHC || includeSynapseDrive || includeRedocking
    }

    public var componentArgument: String {
        var parts: [String] = []
        if includeIHC { parts.append("ihc") }
        if includeSynapseDrive { parts.append("synapse") }
        if includeRedocking { parts.append("redocking") }
        return parts.joined(separator: ",")
    }
}

public struct BioEarExtractionSettings: Equatable, Sendable {
    public var profile: BioEarExtractionProfile
    public var jobs: Int
    public var threadsPerFile: Int
    public var auxiliary: BioEarAuxiliarySelection
    public var languageTag: String

    public init(
        profile: BioEarExtractionProfile,
        jobs: Int,
        threadsPerFile: Int,
        auxiliary: BioEarAuxiliarySelection,
        languageTag: String = "cust"
    ) {
        self.profile = profile
        self.jobs = max(1, jobs)
        self.threadsPerFile = max(1, threadsPerFile)
        self.auxiliary = auxiliary
        self.languageTag = BioEarExtractionSettings.normalizedLanguageTag(languageTag)
    }

    public static func productionDefault(processorCount: Int = ProcessInfo.processInfo.processorCount) -> BioEarExtractionSettings {
        BioEarExtractionSettings(
            profile: .balanced,
            jobs: max(1, min(8, processorCount - 2)),
            threadsPerFile: 1,
            auxiliary: .richDefault,
            languageTag: "cust"
        )
    }

    public static func normalizedLanguageTag(_ raw: String) -> String {
        let lowered = raw.lowercased().unicodeScalars.filter { CharacterSet.alphanumerics.contains($0) }
        let text = String(String.UnicodeScalarView(lowered))
        if text.isEmpty { return "cust" }
        if text.count >= 4 { return String(text.prefix(4)) }
        return text.padding(toLength: 4, withPad: "_", startingAt: 0)
    }
}

public enum BioEarPairStatus: String, Equatable, Sendable {
    case ready
    case needsWAVConversion
    case missingTXT
    case missingTextGrid
    case missingTiers
    case invalidWAV

    public var blocksExtraction: Bool {
        switch self {
        case .ready, .needsWAVConversion:
            false
        case .missingTXT, .missingTextGrid, .missingTiers, .invalidWAV:
            true
        }
    }
}

public struct BioEarExtractionPair: Identifiable, Equatable, Sendable {
    public let id: String
    public let wavURL: URL
    public let txtURL: URL?
    public let textGridURL: URL?
    public let audioInfo: AudioInfo?
    public let audioError: String?
    public let presentTiers: [String]
    public let missingTiers: [String]
    public let status: BioEarPairStatus

    public init(
        wavURL: URL,
        txtURL: URL?,
        textGridURL: URL?,
        audioInfo: AudioInfo?,
        audioError: String?,
        presentTiers: [String],
        missingTiers: [String],
        status: BioEarPairStatus
    ) {
        self.id = wavURL.path
        self.wavURL = wavURL
        self.txtURL = txtURL
        self.textGridURL = textGridURL
        self.audioInfo = audioInfo
        self.audioError = audioError
        self.presentTiers = presentTiers
        self.missingTiers = missingTiers
        self.status = status
    }
}

public struct BioEarOutputState: Equatable, Sendable {
    public let datasetSlug: String
    public let dataAuditoryURL: URL
    public let dataBioEarURL: URL
    public let existingGeneratedDataOutputs: [URL]
    public let existingUnmarkedDataOutputs: [URL]

    public init(
        datasetSlug: String,
        dataAuditoryURL: URL,
        dataBioEarURL: URL,
        existingGeneratedDataOutputs: [URL],
        existingUnmarkedDataOutputs: [URL]
    ) {
        self.datasetSlug = datasetSlug
        self.dataAuditoryURL = dataAuditoryURL
        self.dataBioEarURL = dataBioEarURL
        self.existingGeneratedDataOutputs = existingGeneratedDataOutputs
        self.existingUnmarkedDataOutputs = existingUnmarkedDataOutputs
    }

    public var existingOutputs: [URL] {
        existingGeneratedDataOutputs
    }

    public var unmarkedOutputs: [URL] {
        existingUnmarkedDataOutputs
    }

    public var existingGeneratedOutputs: [URL] {
        existingGeneratedDataOutputs
    }

    public var existingUnmarkedOutputs: [URL] {
        existingUnmarkedDataOutputs
    }
}

public struct BioEarScanSummary: Equatable, Sendable {
    public let rootURL: URL
    public let pairs: [BioEarExtractionPair]
    public let unmatchedWAVCount: Int
    public let unmatchedTextGridCount: Int
    public let outputState: BioEarOutputState

    public init(
        rootURL: URL,
        pairs: [BioEarExtractionPair],
        unmatchedWAVCount: Int,
        unmatchedTextGridCount: Int,
        outputState: BioEarOutputState
    ) {
        self.rootURL = rootURL
        self.pairs = pairs
        self.unmatchedWAVCount = unmatchedWAVCount
        self.unmatchedTextGridCount = unmatchedTextGridCount
        self.outputState = outputState
    }

    public var isSelectable: Bool { !pairs.isEmpty }
    public var readyCount: Int { pairs.filter { $0.status == .ready }.count }
    public var conversionCount: Int { pairs.filter { $0.status == .needsWAVConversion }.count }
    public var missingTXTCount: Int { pairs.filter { $0.status == .missingTXT }.count }
    public var missingTextGridCount: Int { pairs.filter { $0.status == .missingTextGrid }.count }
    public var missingTierCount: Int { pairs.filter { $0.status == .missingTiers }.count }
    public var invalidWAVCount: Int { pairs.filter { $0.status == .invalidWAV }.count }
    public var blockedCount: Int { pairs.filter { $0.status.blocksExtraction }.count }

    public var canExtract: Bool {
        blockedCount == 0 && (readyCount > 0 || conversionCount > 0)
    }
}

public enum BioEarOutputMarkers {
    public static let bioearSuffix = "_bioear.h5"
}

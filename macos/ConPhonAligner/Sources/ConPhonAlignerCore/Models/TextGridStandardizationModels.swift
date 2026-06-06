import Foundation

public struct TextGridLayerOccurrence: Identifiable, Equatable, Sendable {
    public let id: String
    public let name: String
    public let count: Int

    public init(name: String, count: Int) {
        self.id = name
        self.name = name
        self.count = count
    }
}

public struct TextGridStandardizationSummary: Equatable, Sendable {
    public let textGridCount: Int
    public let layers: [TextGridLayerOccurrence]

    public init(textGridCount: Int, layers: [TextGridLayerOccurrence]) {
        self.textGridCount = textGridCount
        self.layers = layers
    }

    public var layerNames: [String] {
        layers.map(\.name)
    }
}

public struct TextGridStandardizationSelection: Equatable, Sendable {
    public var phonemes: String
    public var words: String
    public var syllables: String
    public var utterance: String

    public init(phonemes: String = "", words: String = "", syllables: String = "", utterance: String = "") {
        self.phonemes = phonemes
        self.words = words
        self.syllables = syllables
        self.utterance = utterance
    }
}

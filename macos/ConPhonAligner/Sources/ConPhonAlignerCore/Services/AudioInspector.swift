import Foundation

public enum AudioInspectorError: LocalizedError, Equatable {
    case notRIFFWave
    case missingFormatChunk
    case malformedFormatChunk

    public var errorDescription: String? {
        switch self {
        case .notRIFFWave: "O arquivo não é um RIFF/WAVE válido."
        case .missingFormatChunk: "O bloco de formato do WAV não foi encontrado."
        case .malformedFormatChunk: "O bloco de formato do WAV está malformado."
        }
    }
}

public enum AudioInspector {
    public static func inspect(_ url: URL) throws -> AudioInfo {
        let data = try Data(contentsOf: url)
        guard data.count >= 12,
              String(data: data[0..<4], encoding: .ascii) == "RIFF",
              String(data: data[8..<12], encoding: .ascii) == "WAVE" else {
            throw AudioInspectorError.notRIFFWave
        }

        var offset = 12
        while offset + 8 <= data.count {
            let chunkID = String(data: data[offset..<offset + 4], encoding: .ascii) ?? ""
            let chunkSize = Int(data.littleEndianUInt32(at: offset + 4))
            let chunkStart = offset + 8
            let chunkEnd = chunkStart + chunkSize
            guard chunkSize >= 0, chunkEnd <= data.count else {
                throw AudioInspectorError.malformedFormatChunk
            }
            if chunkID == "fmt " {
                guard chunkSize >= 16 else { throw AudioInspectorError.malformedFormatChunk }
                let format = Int(data.littleEndianUInt16(at: chunkStart))
                let channels = Int(data.littleEndianUInt16(at: chunkStart + 2))
                let sampleRate = Int(data.littleEndianUInt32(at: chunkStart + 4))
                let bitsPerSample = Int(data.littleEndianUInt16(at: chunkStart + 14))
                return AudioInfo(
                    sampleRate: sampleRate,
                    channels: channels,
                    bitsPerSample: bitsPerSample,
                    formatCode: format
                )
            }
            offset = chunkEnd + (chunkSize % 2)
        }
        throw AudioInspectorError.missingFormatChunk
    }
}

private extension Data {
    func littleEndianUInt16(at offset: Int) -> UInt16 {
        UInt16(self[offset]) | (UInt16(self[offset + 1]) << 8)
    }

    func littleEndianUInt32(at offset: Int) -> UInt32 {
        UInt32(self[offset])
            | (UInt32(self[offset + 1]) << 8)
            | (UInt32(self[offset + 2]) << 16)
            | (UInt32(self[offset + 3]) << 24)
    }
}

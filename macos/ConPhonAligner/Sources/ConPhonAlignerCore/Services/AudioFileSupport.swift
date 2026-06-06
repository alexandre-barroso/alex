import Foundation

public enum AudioFileSupport {
    public static let supportedExtensions: Set<String> = [
        "wav", "wave",
        "flac",
        "aif", "aiff", "aifc",
        "caf",
        "mp3",
        "m4a", "mp4",
        "ogg", "opus"
    ]

    public static func isSupportedAudio(_ url: URL) -> Bool {
        supportedExtensions.contains(url.pathExtension.lowercased())
    }

    public static func isWAV(_ url: URL) -> Bool {
        let ext = url.pathExtension.lowercased()
        return ext == "wav" || ext == "wave"
    }

    public static func targetWAVURL(for audioURL: URL) -> URL {
        audioURL.deletingPathExtension().appendingPathExtension("wav")
    }
}

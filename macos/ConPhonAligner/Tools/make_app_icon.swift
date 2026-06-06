import AppKit
import Darwin
import Foundation

func makeIcon(size: CGFloat) -> NSImage {
    let image = NSImage(size: NSSize(width: size, height: size))
    image.lockFocus()
    defer { image.unlockFocus() }

    let rect = NSRect(x: 0, y: 0, width: size, height: size)
    let outer = NSBezierPath(roundedRect: rect.insetBy(dx: size * 0.055, dy: size * 0.055), xRadius: size * 0.20, yRadius: size * 0.20)
    NSGradient(
        colors: [
            NSColor(calibratedRed: 0.05, green: 0.11, blue: 0.16, alpha: 1),
            NSColor(calibratedRed: 0.10, green: 0.18, blue: 0.24, alpha: 1)
        ]
    )?.draw(in: outer, angle: 90)

    NSColor(calibratedRed: 0.16, green: 0.70, blue: 0.86, alpha: 0.20).setStroke()
    let ring = NSBezierPath(ovalIn: rect.insetBy(dx: size * 0.21, dy: size * 0.21))
    ring.lineWidth = max(1, size * 0.035)
    ring.stroke()

    NSColor(calibratedRed: 0.22, green: 0.78, blue: 0.92, alpha: 1).setStroke()
    let waveform = NSBezierPath()
    let mid = size * 0.43
    for index in 0...140 {
        let x = size * 0.16 + CGFloat(index) / 140.0 * size * 0.68
        let wave = CGFloat(sin(Double(index) * 0.25)) * size * 0.055
            + CGFloat(sin(Double(index) * 0.067)) * size * 0.028
        let y = mid + wave
        index == 0 ? waveform.move(to: NSPoint(x: x, y: y)) : waveform.line(to: NSPoint(x: x, y: y))
    }
    waveform.lineWidth = max(1.5, size * 0.027)
    waveform.lineCapStyle = .round
    waveform.stroke()

    NSColor(calibratedRed: 0.96, green: 0.73, blue: 0.23, alpha: 1).setStroke()
    for x in [size * 0.28, size * 0.50, size * 0.72] {
        let path = NSBezierPath()
        path.move(to: NSPoint(x: x, y: size * 0.18))
        path.line(to: NSPoint(x: x, y: size * 0.74))
        path.lineWidth = max(1, size * 0.014)
        path.lineCapStyle = .round
        path.stroke()
    }

    let text = "A"
    let attributes: [NSAttributedString.Key: Any] = [
        .font: NSFont.systemFont(ofSize: size * 0.29, weight: .heavy),
        .foregroundColor: NSColor.white
    ]
    let textSize = text.size(withAttributes: attributes)
    text.draw(
        at: NSPoint(x: (size - textSize.width) / 2, y: size * 0.56),
        withAttributes: attributes
    )

    if size >= 128 {
        let caption = "BioEar"
        let captionAttributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: size * 0.075, weight: .semibold),
            .foregroundColor: NSColor(calibratedRed: 0.80, green: 0.89, blue: 0.94, alpha: 1)
        ]
        let captionSize = caption.size(withAttributes: captionAttributes)
        caption.draw(
            at: NSPoint(x: (size - captionSize.width) / 2, y: size * 0.17),
            withAttributes: captionAttributes
        )
    }

    return image
}

func writePNG(size: CGFloat, to url: URL) throws {
    let image = makeIcon(size: size)
    guard
        let tiff = image.tiffRepresentation,
        let bitmap = NSBitmapImageRep(data: tiff),
        let data = bitmap.representation(using: .png, properties: [:])
    else {
        throw NSError(domain: "ALEXIcon", code: 1, userInfo: [NSLocalizedDescriptionKey: "Could not encode app icon PNG."])
    }
    try data.write(to: url)
}

guard CommandLine.arguments.count == 2 else {
    FileHandle.standardError.write(Data("usage: make_app_icon.swift <output.iconset>\n".utf8))
    exit(2)
}

let outputURL = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
try FileManager.default.createDirectory(at: outputURL, withIntermediateDirectories: true)

let icons: [(String, CGFloat)] = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024)
]

for (filename, size) in icons {
    try writePNG(size: size, to: outputURL.appendingPathComponent(filename))
}

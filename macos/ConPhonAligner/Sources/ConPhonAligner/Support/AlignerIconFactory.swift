import AppKit

enum AlignerIconFactory {
    static func makeIcon(size: CGFloat = 512) -> NSImage {
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
        ring.lineWidth = size * 0.035
        ring.stroke()

        NSColor(calibratedRed: 0.22, green: 0.78, blue: 0.92, alpha: 1).setStroke()
        let waveform = NSBezierPath()
        let mid = size * 0.43
        for index in 0...140 {
            let x = size * 0.16 + CGFloat(index) / 140.0 * size * 0.68
            let wave = sin(CGFloat(index) * 0.25) * size * 0.055 + sin(CGFloat(index) * 0.067) * size * 0.028
            let y = mid + wave
            index == 0 ? waveform.move(to: NSPoint(x: x, y: y)) : waveform.line(to: NSPoint(x: x, y: y))
        }
        waveform.lineWidth = size * 0.026
        waveform.lineCapStyle = .round
        waveform.stroke()

        NSColor(calibratedRed: 0.96, green: 0.73, blue: 0.23, alpha: 1).setStroke()
        for x in [size * 0.28, size * 0.50, size * 0.72] {
            let path = NSBezierPath()
            path.move(to: NSPoint(x: x, y: size * 0.18))
            path.line(to: NSPoint(x: x, y: size * 0.74))
            path.lineWidth = size * 0.013
            path.lineCapStyle = .round
            path.stroke()
        }

        let text = "A"
        let attrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: size * 0.29, weight: .heavy),
            .foregroundColor: NSColor.white
        ]
        let textSize = text.size(withAttributes: attrs)
        text.draw(
            at: NSPoint(x: (size - textSize.width) / 2, y: size * 0.56),
            withAttributes: attrs
        )

        if size >= 128 {
            let caption = "BioEar"
            let captionAttrs: [NSAttributedString.Key: Any] = [
                .font: NSFont.systemFont(ofSize: size * 0.075, weight: .semibold),
                .foregroundColor: NSColor(calibratedRed: 0.80, green: 0.89, blue: 0.94, alpha: 1)
            ]
            let captionSize = caption.size(withAttributes: captionAttrs)
            caption.draw(
                at: NSPoint(x: (size - captionSize.width) / 2, y: size * 0.17),
                withAttributes: captionAttrs
            )
        }

        return image
    }
}

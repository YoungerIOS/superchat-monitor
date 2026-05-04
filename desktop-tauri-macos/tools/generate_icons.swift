import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

let outDir = URL(fileURLWithPath: "desktop-tauri-macos/src-tauri/icons", isDirectory: true)
let basePath = outDir.appendingPathComponent("icon-base-1024.png")

let w = 1024
let h = 1024

guard let ctx = CGContext(
    data: nil,
    width: w,
    height: h,
    bitsPerComponent: 8,
    bytesPerRow: 0,
    space: CGColorSpaceCreateDeviceRGB(),
    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
) else {
    fputs("创建位图上下文失败\n", stderr)
    exit(1)
}

ctx.setAllowsAntialiasing(true)
ctx.setShouldAntialias(true)
ctx.interpolationQuality = .high

let bgRect = CGRect(x: 40, y: 40, width: 944, height: 944)
let bgPath = CGPath(roundedRect: bgRect, cornerWidth: 210, cornerHeight: 210, transform: nil)
ctx.saveGState()
ctx.addPath(bgPath)
ctx.clip()
let bgColors = [
    CGColor(red: 0.05, green: 0.42, blue: 0.92, alpha: 1),
    CGColor(red: 0.02, green: 0.65, blue: 0.74, alpha: 1)
] as CFArray
let bgGradient = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: bgColors, locations: [0.0, 1.0])!
ctx.drawLinearGradient(bgGradient, start: CGPoint(x: 120, y: 920), end: CGPoint(x: 940, y: 120), options: [])
ctx.restoreGState()

ctx.saveGState()
ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 0.22))
ctx.addEllipse(in: CGRect(x: 180, y: 220, width: 660, height: 660))
ctx.fillPath()
ctx.restoreGState()

let bell = CGMutablePath()
bell.move(to: CGPoint(x: 512, y: 730))
bell.addCurve(to: CGPoint(x: 348, y: 520), control1: CGPoint(x: 430, y: 720), control2: CGPoint(x: 350, y: 620))
bell.addLine(to: CGPoint(x: 332, y: 438))
bell.addCurve(to: CGPoint(x: 692, y: 438), control1: CGPoint(x: 380, y: 360), control2: CGPoint(x: 644, y: 360))
bell.addLine(to: CGPoint(x: 676, y: 520))
bell.addCurve(to: CGPoint(x: 512, y: 730), control1: CGPoint(x: 674, y: 620), control2: CGPoint(x: 594, y: 720))
bell.closeSubpath()
ctx.addPath(bell)
ctx.setFillColor(CGColor(red: 0.98, green: 0.99, blue: 1.0, alpha: 1.0))
ctx.fillPath()

let lip = CGPath(roundedRect: CGRect(x: 356, y: 405, width: 312, height: 52), cornerWidth: 24, cornerHeight: 24, transform: nil)
ctx.addPath(lip)
ctx.setFillColor(CGColor(red: 0.95, green: 0.98, blue: 1, alpha: 1))
ctx.fillPath()

ctx.setFillColor(CGColor(red: 1.0, green: 0.72, blue: 0.22, alpha: 1))
ctx.addEllipse(in: CGRect(x: 462, y: 332, width: 100, height: 100))
ctx.fillPath()

let stem = CGPath(roundedRect: CGRect(x: 486, y: 742, width: 52, height: 42), cornerWidth: 20, cornerHeight: 20, transform: nil)
ctx.addPath(stem)
ctx.setFillColor(CGColor(red: 0.95, green: 0.98, blue: 1, alpha: 1))
ctx.fillPath()

func drawWave(_ radius: CGFloat, _ alpha: CGFloat) {
    let c = CGPoint(x: 585, y: 535)
    let path = CGMutablePath()
    path.addArc(center: c, radius: radius, startAngle: -.pi/6, endAngle: .pi/6, clockwise: false)
    ctx.addPath(path)
    ctx.setStrokeColor(CGColor(red: 0.89, green: 0.98, blue: 1.0, alpha: alpha))
    ctx.setLineWidth(28)
    ctx.setLineCap(.round)
    ctx.strokePath()
}

drawWave(190, 0.90)
drawWave(240, 0.72)

ctx.setFillColor(CGColor(red: 1.0, green: 0.86, blue: 0.38, alpha: 0.9))
ctx.addEllipse(in: CGRect(x: 240, y: 660, width: 26, height: 26))
ctx.fillPath()
ctx.setFillColor(CGColor(red: 1.0, green: 0.9, blue: 0.45, alpha: 0.7))
ctx.addEllipse(in: CGRect(x: 730, y: 770, width: 20, height: 20))
ctx.fillPath()

guard let cgImage = ctx.makeImage() else {
    fputs("创建 CGImage 失败\n", stderr)
    exit(1)
}

try FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)

guard let dest = CGImageDestinationCreateWithURL(basePath as CFURL, UTType.png.identifier as CFString, 1, nil) else {
    fputs("创建输出目标失败\n", stderr)
    exit(1)
}

CGImageDestinationAddImage(dest, cgImage, nil)
if CGImageDestinationFinalize(dest) {
    print("ICON_OK \(basePath.path)")
} else {
    fputs("写出 PNG 失败\n", stderr)
    exit(1)
}

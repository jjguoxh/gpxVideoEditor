import Foundation
import AVFoundation
import QuartzCore
import AppKit

enum Exporter {
    static func export(videoURL: URL,
                       externalAudio: URL?,
                       removeOriginalAudio: Bool,
                       externalAudioOffset: Double,
                       originalVolume: Float,
                       externalVolume: Float,
                       gpxSegments: [GPXSegment],
                       gpxOffset: Double,
                       overlayMinimap: Bool = true,
                       minimapRect: CGRect = .zero,
                       minimapOpacity: Double = 0.35,
                       minimapLocalMode: Bool = false,
                       minimapLocalRadius: Double = 500,
                       minimapSmoothEnabled: Bool = true,
                       minimapSmoothWindow: Int = 5,
                       overlayTelemetry: Bool = true,
                       telemetryRect: CGRect = .zero,
                       telemetryOpacity: Double = 0.45,
                       to outputURL: URL,
                       completion: @escaping (Result<Void, Error>) -> Void) {
        let asset = AVURLAsset(url: videoURL)
        let comp = AVMutableComposition()
        guard let vTrack = asset.tracks(withMediaType: .video).first else {
            completion(.failure(NSError(domain: "no video track", code: -1)))
            return
        }
        let vComp = comp.addMutableTrack(withMediaType: .video, preferredTrackID: kCMPersistentTrackID_Invalid)!
        do {
            try vComp.insertTimeRange(CMTimeRange(start: .zero, duration: asset.duration), of: vTrack, at: .zero)
        } catch {
            completion(.failure(error))
            return
        }
        let naturalSize = vTrack.naturalSize.applying(vTrack.preferredTransform)
        let renderSize = CGSize(width: abs(naturalSize.width), height: abs(naturalSize.height))
        var audioMixParams: [AVMutableAudioMixInputParameters] = []
        if !removeOriginalAudio {
            for t in asset.tracks(withMediaType: .audio) {
                if let aComp = comp.addMutableTrack(withMediaType: .audio, preferredTrackID: kCMPersistentTrackID_Invalid) {
                    do {
                        try aComp.insertTimeRange(CMTimeRange(start: .zero, duration: asset.duration), of: t, at: .zero)
                        let p = AVMutableAudioMixInputParameters(track: aComp)
                        p.setVolume(originalVolume, at: .zero)
                        audioMixParams.append(p)
                    } catch {}
                }
            }
        }
        if let ext = externalAudio {
            let aAsset = AVURLAsset(url: ext)
            if let aTrack = aAsset.tracks(withMediaType: .audio).first {
                if let aComp = comp.addMutableTrack(withMediaType: .audio, preferredTrackID: kCMPersistentTrackID_Invalid) {
                    do {
                        let startAt = CMTimeMakeWithSeconds(max(0, externalAudioOffset), preferredTimescale: 600)
                        try aComp.insertTimeRange(CMTimeRange(start: .zero, duration: asset.duration), of: aTrack, at: startAt)
                        let p = AVMutableAudioMixInputParameters(track: aComp)
                        p.setVolume(externalVolume, at: .zero)
                        audioMixParams.append(p)
                    } catch {}
                }
            }
        }
        // 配置视频合成（用于叠加缩略图）
        let videoComp = AVMutableVideoComposition()
        videoComp.renderSize = renderSize
        videoComp.frameDuration = CMTimeMake(value: 1, timescale: 30)
        let instruction = AVMutableVideoCompositionInstruction()
        instruction.timeRange = CMTimeRange(start: .zero, duration: asset.duration)
        let layerInstruction = AVMutableVideoCompositionLayerInstruction(assetTrack: vComp)
        layerInstruction.setTransform(vTrack.preferredTransform, at: .zero)
        instruction.layerInstructions = [layerInstruction]
        videoComp.instructions = [instruction]
        
        if (overlayMinimap || overlayTelemetry), !gpxSegments.isEmpty {
            let parent = CALayer()
            parent.frame = CGRect(origin: .zero, size: renderSize)
            let videoLayer = CALayer()
            videoLayer.frame = parent.frame
            parent.addSublayer(videoLayer)
            
            if overlayMinimap {
                let mmRect = clampRect(minimapRect == .zero
                                       ? CGRect(x: renderSize.width - 220 - 14, y: 14, width: 220, height: 160)
                                       : minimapRect, into: CGRect(origin: .zero, size: renderSize))
                let bg = CALayer()
                bg.frame = mmRect
                bg.backgroundColor = NSColor.black.withAlphaComponent(min(CGFloat(minimapOpacity), 0.85)).cgColor
                bg.cornerRadius = 6
                
                if minimapLocalMode {
                    let (keyTimes, images) = buildMinimapFramesLocal(segments: gpxSegments,
                                                                     panelSize: mmRect.size,
                                                                     duration: asset.duration,
                                                                     gpxOffset: gpxOffset,
                                                                     radius: minimapLocalRadius,
                                                                     smoothEnabled: minimapSmoothEnabled,
                                                                     smoothWindow: minimapSmoothWindow)
                    let contentLayer = CALayer()
                    contentLayer.frame = bg.bounds
                    contentLayer.contentsGravity = .resizeAspectFill
                    contentLayer.masksToBounds = true
                    bg.addSublayer(contentLayer)
                    if !images.isEmpty && !keyTimes.isEmpty {
                        let anim = CAKeyframeAnimation(keyPath: "contents")
                        anim.keyTimes = keyTimes
                        anim.values = images
                        anim.calculationMode = .discrete
                        anim.duration = CMTimeGetSeconds(asset.duration)
                        anim.beginTime = AVCoreAnimationBeginTimeAtZero
                        anim.fillMode = .forwards
                        anim.isRemovedOnCompletion = false
                        contentLayer.add(anim, forKey: "contents")
                    }
                } else {
                    // 全局路径与蓝点动画（可选平滑）
                    let (pathLayer, dotLayer) = buildMinimapLayers(segments: gpxSegments,
                                                                   rect: mmRect,
                                                                   renderSize: renderSize,
                                                                   assetDuration: asset.duration,
                                                                   gpxOffset: gpxOffset,
                                                                   smoothEnabled: minimapSmoothEnabled,
                                                                   smoothWindow: minimapSmoothWindow)
                    bg.addSublayer(pathLayer)
                    bg.addSublayer(dotLayer)
                }
                parent.addSublayer(bg)
            }
            if overlayTelemetry {
                let teleRect = clampRect(telemetryRect == .zero
                                         ? CGRect(x: renderSize.width - 300 - 20, y: 20, width: 300, height: 140)
                                         : telemetryRect, into: CGRect(origin: .zero, size: renderSize))
                let bgT = CALayer()
                bgT.frame = teleRect
                bgT.backgroundColor = NSColor.black.withAlphaComponent(min(CGFloat(telemetryOpacity), 0.85)).cgColor
                bgT.cornerRadius = 8
                
                let contentLayer = CALayer()
                contentLayer.frame = bgT.bounds
                contentLayer.contentsGravity = .resizeAspect
                contentLayer.masksToBounds = true
                bgT.addSublayer(contentLayer)
                
                let (keyTimes, images) = buildTelemetryKeyframes(segments: gpxSegments, gpxOffset: gpxOffset, panelSize: bgT.bounds.size, duration: asset.duration)
                if !images.isEmpty && !keyTimes.isEmpty {
                    let anim = CAKeyframeAnimation(keyPath: "contents")
                    anim.keyTimes = keyTimes
                    anim.values = images
                    anim.calculationMode = .discrete
                    anim.duration = CMTimeGetSeconds(asset.duration)
                    anim.beginTime = AVCoreAnimationBeginTimeAtZero
                    anim.fillMode = .forwards
                    anim.isRemovedOnCompletion = false
                    contentLayer.add(anim, forKey: "contents")
                }
                
                parent.addSublayer(bgT)
            }
            
            videoComp.animationTool = AVVideoCompositionCoreAnimationTool(postProcessingAsVideoLayer: videoLayer, in: parent)
        }
        
        let exporter = AVAssetExportSession(asset: comp, presetName: AVAssetExportPresetHighestQuality)!
        exporter.outputURL = outputURL
        exporter.outputFileType = .mp4
        if !audioMixParams.isEmpty {
            let mix = AVMutableAudioMix()
            mix.inputParameters = audioMixParams
            exporter.audioMix = mix
        }
        exporter.videoComposition = videoComp
        exporter.exportAsynchronously {
            if exporter.status == .completed {
                completion(.success(()))
            } else {
                completion(.failure(exporter.error ?? NSError(domain: "export", code: -1)))
            }
        }
    }
    
    private static func buildMinimapLayers(segments: [GPXSegment], rect: CGRect, renderSize: CGSize, assetDuration: CMTime, gpxOffset: Double, smoothEnabled: Bool, smoothWindow: Int) -> (CAShapeLayer, CALayer) {
        // 收集点
        var pts: [(Double, Double)] = []
        for s in segments { pts.append((s.latStart, s.lonStart)) }
        if let last = segments.last { pts.append((last.latEnd, last.lonEnd)) }
        // 计算边界
        guard let bounds = boundsFor(pts: pts) else {
            let empty = CAShapeLayer()
            empty.frame = rect
            return (empty, CALayer())
        }
        let scale = scaleFor(bounds: bounds, w: rect.width, h: rect.height, pad: 8)
        // 路径
        let path = CGMutablePath()
        var xyPts: [CGPoint] = pts.map { toXY($0, bounds: bounds, scale: scale, w: rect.width, h: rect.height, pad: 8) }
        if smoothEnabled, xyPts.count > 3 {
            xyPts = movingAverage(xyPts, window: max(3, smoothWindow | 1))
        }
        if let first = xyPts.first {
            path.move(to: first)
            for i in 1..<xyPts.count { path.addLine(to: xyPts[i]) }
        }
        let shape = CAShapeLayer()
        shape.frame = rect
        shape.path = path
        shape.strokeColor = NSColor.systemGreen.cgColor
        shape.fillColor = NSColor.clear.cgColor
        shape.lineWidth = 2
        
        // 蓝点与动画
        let dot = CALayer()
        dot.frame = CGRect(x: 0, y: 0, width: 8, height: 8)
        dot.cornerRadius = 4
        dot.backgroundColor = NSColor.systemBlue.cgColor
        dot.borderWidth = 1
        dot.borderColor = NSColor.white.cgColor
        
        // 构建关键帧
        let total = CMTimeGetSeconds(assetDuration)
        var times: [NSNumber] = []
        var values: [NSValue] = []
        func addKey(_ vidTime: Double, _ lat: Double, _ lon: Double) {
            let t = max(0, min(total, vidTime))
            let norm = total > 0 ? t / total : 0
            let xy = toXY((lat, lon), bounds: bounds, scale: scale, w: rect.width, h: rect.height, pad: 8)
            let pos = CGPoint(x: rect.minX + xy.x, y: rect.minY + xy.y)
            times.append(NSNumber(value: norm))
            values.append(NSValue(point: pos))
        }
        for s in segments {
            let vs = s.start - gpxOffset
            let ve = s.end - gpxOffset
            addKey(vs, s.latStart, s.lonStart)
            addKey(ve, s.latEnd, s.lonEnd)
        }
        // 排序并去重
        let zipped = zip(times, values).sorted { $0.0.doubleValue < $1.0.doubleValue }
        let sortedTimes = zipped.map { $0.0 }
        let sortedValues = zipped.map { $0.1 }
        let anim = CAKeyframeAnimation(keyPath: "position")
        anim.keyTimes = sortedTimes
        anim.values = sortedValues
        anim.calculationMode = .linear
        anim.duration = total
        anim.beginTime = AVCoreAnimationBeginTimeAtZero
        anim.fillMode = .forwards
        anim.isRemovedOnCompletion = false
        dot.add(anim, forKey: "pos")
        
        return (shape, dot)
    }
    
    private static func buildMinimapFramesLocal(segments: [GPXSegment], panelSize: CGSize, duration: CMTime, gpxOffset: Double, radius: Double, smoothEnabled: Bool, smoothWindow: Int) -> ([NSNumber], [CGImage]) {
        let total = CMTimeGetSeconds(duration)
        guard total > 0 else { return ([], []) }
        let step = max(0.5, min(1.0, total / 600))
        var times: [NSNumber] = []
        var images: [CGImage] = []
        var t = 0.0
        while t <= total + 0.001 {
            let vidT = t
            if let img = renderLocalMinimapImage(segments: segments,
                                                 size: panelSize,
                                                 videoTime: vidT,
                                                 gpxOffset: gpxOffset,
                                                 radius: radius,
                                                 smoothEnabled: smoothEnabled,
                                                 smoothWindow: smoothWindow) {
                times.append(NSNumber(value: t / total))
                images.append(img)
            }
            t += step
        }
        return (times, images)
    }
    
    private static func renderLocalMinimapImage(segments: [GPXSegment], size: CGSize, videoTime: Double, gpxOffset: Double, radius: Double, smoothEnabled: Bool, smoothWindow: Int) -> CGImage? {
        let w = max(60, Int(size.width))
        let h = max(40, Int(size.height))
        let scale: CGFloat = 2.0
        let pixelW = Int(CGFloat(w) * scale)
        let pixelH = Int(CGFloat(h) * scale)
        guard let ctx = CGContext(data: nil, width: pixelW, height: pixelH, bitsPerComponent: 8, bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return nil }
        ctx.scaleBy(x: scale, y: scale)
        ctx.setFillColor(NSColor.clear.cgColor)
        ctx.fill(CGRect(x: 0, y: 0, width: CGFloat(w), height: CGFloat(h)))
        
        // 当前经纬度
        guard let cur = currentLatLon(at: videoTime, segments: segments, gpxOffset: gpxOffset) else { return ctx.makeImage() }
        // 以当前点为中心构建窗口边界
        guard let b = centeredBounds(center: cur, radiusMeters: max(50, radius)) else { return ctx.makeImage() }
        let padding: CGFloat = 6
        let scaleXY = scaleFor(bounds: b, w: CGFloat(w), h: CGFloat(h), pad: padding)
        // 使用全部轨迹点进行投影，超出窗口会被裁剪
        var allPts: [(Double, Double)] = []
        for s in segments { allPts.append((s.latStart, s.lonStart)) }
        if let last = segments.last { allPts.append((last.latEnd, last.lonEnd)) }
        var xyPts: [CGPoint] = allPts.map { toXY($0, bounds: b, scale: scaleXY, w: CGFloat(w), h: CGFloat(h), pad: padding) }
        if smoothEnabled, xyPts.count > 3 {
            xyPts = movingAverage(xyPts, window: max(3, smoothWindow|1))
        }
        // 画路径
        if xyPts.count > 1 {
            let path = CGMutablePath()
            path.addLines(between: xyPts)
            ctx.setStrokeColor(NSColor.systemGreen.withAlphaComponent(0.9).cgColor)
            ctx.setLineWidth(2)
            ctx.addPath(path)
            ctx.strokePath()
        }
        // 画当前点
        let curXY = toXY(cur, bounds: b, scale: scaleXY, w: CGFloat(w), h: CGFloat(h), pad: padding)
        ctx.setFillColor(NSColor.systemBlue.cgColor)
        ctx.fillEllipse(in: CGRect(x: curXY.x-4, y: curXY.y-4, width: 8, height: 8))
        ctx.setStrokeColor(NSColor.white.cgColor)
        ctx.setLineWidth(1)
        ctx.strokeEllipse(in: CGRect(x: curXY.x-6, y: curXY.y-6, width: 12, height: 12))
        
        return ctx.makeImage()
    }
    
    private static func centeredBounds(center: (Double, Double), radiusMeters: Double) -> (minLat: Double, minLon: Double, maxLat: Double, maxLon: Double)? {
        let lat = center.0
        let metersPerDegLat = 111_320.0
        let metersPerDegLon = 111_320.0 * cos(lat * .pi / 180.0)
        guard metersPerDegLon > 0 else { return nil }
        let dLat = radiusMeters / metersPerDegLat
        let dLon = radiusMeters / metersPerDegLon
        return (lat - dLat, center.1 - dLon, lat + dLat, center.1 + dLon)
    }
    
    private static func currentLatLon(at videoTime: Double, segments: [GPXSegment], gpxOffset: Double) -> (Double, Double)? {
        let t = videoTime + gpxOffset
        var low = 0, high = segments.count - 1, idx: Int?
        while low <= high {
            let mid = (low + high) / 2
            let s = segments[mid]
            if s.start <= t && t <= s.end { idx = mid; break }
            if t < s.start { high = mid - 1 } else { low = mid + 1 }
        }
        guard let i = idx else { return nil }
        let s = segments[i]
        let dur = s.end - s.start
        let r = dur > 0 ? (t - s.start)/dur : 0
        let la = s.latStart + (s.latEnd - s.latStart)*r
        let lo = s.lonStart + (s.lonEnd - s.lonStart)*r
        return (la, lo)
    }
    
    private static func movingAverage(_ pts: [CGPoint], window: Int) -> [CGPoint] {
        let w = max(3, window)
        let half = w / 2
        var out: [CGPoint] = []
        out.reserveCapacity(pts.count)
        for i in 0..<pts.count {
            let a = max(0, i - half)
            let b = min(pts.count - 1, i + half)
            let count = CGFloat(b - a + 1)
            var sx: CGFloat = 0
            var sy: CGFloat = 0
            var j = a
            while j <= b { sx += pts[j].x; sy += pts[j].y; j += 1 }
            out.append(CGPoint(x: sx / count, y: sy / count))
        }
        return out
    }
    
    // Helpers
    private static func boundsFor(pts: [(Double, Double)]) -> (minLat: Double, minLon: Double, maxLat: Double, maxLon: Double)? {
        guard !pts.isEmpty else { return nil }
        var minLat = pts[0].0, maxLat = pts[0].0
        var minLon = pts[0].1, maxLon = pts[0].1
        for p in pts {
            minLat = min(minLat, p.0); maxLat = max(maxLat, p.0)
            minLon = min(minLon, p.1); maxLon = max(maxLon, p.1)
        }
        return (minLat, minLon, maxLat, maxLon)
    }
    private static func scaleFor(bounds: (Double, Double, Double, Double), w: CGFloat, h: CGFloat, pad: CGFloat) -> CGFloat {
        let latRange = bounds.2 - bounds.0
        let lonRange = bounds.3 - bounds.1
        if latRange == 0 || lonRange == 0 { return 1 }
        let sx = (w - 2*pad)/CGFloat(lonRange)
        let sy = (h - 2*pad)/CGFloat(latRange)
        return min(sx, sy)
    }
    private static func toXY(_ latlon: (Double, Double), bounds: (Double, Double, Double, Double), scale: CGFloat, w: CGFloat, h: CGFloat, pad: CGFloat) -> CGPoint {
        let x = pad + CGFloat(latlon.1 - bounds.1) * scale
        let y = h - (pad + CGFloat(latlon.0 - bounds.0) * scale)
        return CGPoint(x: x, y: y)
    }
    
    private static func clampRect(_ r: CGRect, into bounds: CGRect) -> CGRect {
        var rr = r
        rr.origin.x = max(bounds.minX, min(rr.origin.x, bounds.maxX - rr.width))
        rr.origin.y = max(bounds.minY, min(rr.origin.y, bounds.maxY - rr.height))
        rr.size.width = min(rr.width, bounds.width - rr.origin.x)
        rr.size.height = min(rr.height, bounds.height - rr.origin.y)
        return rr
    }
    
    private static func buildTelemetryKeyframes(segments: [GPXSegment], gpxOffset: Double, panelSize: CGSize, duration: CMTime) -> ([NSNumber], [CGImage]) {
        let total = CMTimeGetSeconds(duration)
        guard total > 0 else { return ([], []) }
        let step = max(0.5, min(1.0, total / 600)) // 至多 ~2fps 关键帧
        var times: [NSNumber] = []
        var images: [CGImage] = []
        var t = 0.0
        while t <= total + 0.001 {
            let d = dataAt(t, segments: segments, gpxOffset: gpxOffset)
            if let img = renderTelemetryImage(size: panelSize, speed: d.speed, ele: d.ele, grade: d.grade) {
                let kt = NSNumber(value: t / total)
                times.append(kt)
                images.append(img)
            }
            t += step
        }
        return (times, images)
    }
    
    private static func dataAt(_ videoTime: Double, segments: [GPXSegment], gpxOffset: Double) -> (speed: Double, ele: Double?, grade: Double?) {
        guard !segments.isEmpty else { return (0, nil, nil) }
        let t = videoTime + gpxOffset
        var low = 0, high = segments.count - 1, idx: Int?
        while low <= high {
            let mid = (low + high) / 2
            let s = segments[mid]
            if s.start <= t && t <= s.end { idx = mid; break }
            if t < s.start { high = mid - 1 } else { low = mid + 1 }
        }
        guard let i = idx else {
            let s = (t < segments.first!.start) ? segments.first! : segments.last!
            return (s.speed, (t < segments.first!.start) ? s.eleStart : s.eleEnd, 0)
        }
        let s = segments[i]
        let dur = s.end - s.start
        let r = dur > 0 ? (t - s.start)/dur : 0
        var ele: Double?
        if let e1 = s.eleStart, let e2 = s.eleEnd { ele = e1 + (e2 - e1)*r }
        var grade: Double?
        let dist = AppModel.haversine(s.latStart, s.lonStart, s.latEnd, s.lonEnd)
        if dist > 1, let e1 = s.eleStart, let e2 = s.eleEnd { grade = (e2 - e1)/dist*100.0 } else { grade = 0 }
        return (s.speed, ele, grade)
    }
    
    private static func renderTelemetryImage(size: CGSize, speed: Double, ele: Double?, grade: Double?) -> CGImage? {
        let w = max(100, Int(size.width))
        let h = max(60, Int(size.height))
        let scale: CGFloat = 2.0
        let pixelW = Int(CGFloat(w) * scale)
        let pixelH = Int(CGFloat(h) * scale)
        guard let ctx = CGContext(data: nil, width: pixelW, height: pixelH, bitsPerComponent: 8, bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return nil }
        ctx.scaleBy(x: scale, y: scale)
        // 透明背景
        ctx.setFillColor(NSColor.clear.cgColor)
        ctx.fill(CGRect(x: 0, y: 0, width: CGFloat(w), height: CGFloat(h)))
        
        let paragraph = NSMutableParagraphStyle()
        paragraph.alignment = .left
        let fontSize = max(14, min(CGFloat(h) * 0.28, CGFloat(w) * 0.14))
        let attrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: fontSize, weight: .regular),
            .foregroundColor: NSColor.white,
            .paragraphStyle: paragraph
        ]
        let shadow = NSShadow()
        shadow.shadowBlurRadius = 2
        shadow.shadowColor = NSColor.black.withAlphaComponent(0.6)
        shadow.shadowOffset = NSSize(width: 0, height: -1)
        let attrsShadow: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: fontSize, weight: .regular),
            .foregroundColor: NSColor.white,
            .paragraphStyle: paragraph,
            .shadow: shadow
        ]
        
        func draw(text: String, at y: CGFloat) {
            let rect = CGRect(x: 12, y: y, width: CGFloat(w) - 24, height: fontSize + 6)
            (text as NSString).draw(in: rect, withAttributes: attrsShadow)
        }
        
        draw(text: String(format: "速度  %.1f km/h", speed), at: CGFloat(h) - fontSize - 12)
        var currentY = CGFloat(h) - 2*(fontSize + 12)
        if let e = ele {
            draw(text: String(format: "海拔  %.0f m", e), at: currentY)
            currentY -= (fontSize + 8)
        }
        if let g = grade {
            draw(text: String(format: "坡度  %+0.1f%%", g), at: currentY)
        }
        
        return ctx.makeImage()
    }
}

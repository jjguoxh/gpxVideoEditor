import SwiftUI

struct TrackMiniMap: View {
    let segments: [GPXSegment]
    let currentTime: Double
    let gpxOffset: Double
    let localMode: Bool
    let localRadius: Double
    let smooth: Bool
    let smoothWindow: Int
    let overrideGPXTime: Double?
    
    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width
            let h = geo.size.height
            let padding: CGFloat = 8
            let pts = allPoints()
            let curLL = currentLatLon()
            let bounds = (localMode && curLL != nil)
                ? centeredBounds(center: curLL!, radiusMeters: max(50, localRadius))
                : latLonBounds(pts: pts)
            ZStack {
                RoundedRectangle(cornerRadius: 6)
                    .fill(Color.black.opacity(0.35))
                Path { p in
                    if pts.count > 1, let b = bounds {
                        let scale = scaleFor(bounds: b, w: w, h: h, pad: padding)
                        var xyPts = pts.map { toXY($0, bounds: b, scale: scale, w: w, h: h, pad: padding) }
                        if smooth, xyPts.count > 3 {
                            xyPts = movingAverage(xyPts, window: max(3, smoothWindow|1))
                        }
                        p.addLines(xyPts)
                    }
                }
                .stroke(Color.green.opacity(0.9), lineWidth: 2)
                
                if let cur = curLL , let b = bounds {
                    let scale = scaleFor(bounds: b, w: w, h: h, pad: padding)
                    let xy = toXY(cur, bounds: b, scale: scale, w: w, h: h, pad: padding)
                    Circle()
                        .fill(Color.blue)
                        .frame(width: 8, height: 8)
                        .position(x: xy.x, y: xy.y)
                        .overlay(Circle().stroke(Color.white, lineWidth: 1).frame(width: 12, height: 12).position(x: xy.x, y: xy.y))
                } else if pts.count == 1, let b = bounds {
                    let scale = scaleFor(bounds: b, w: w, h: h, pad: padding)
                    let xy = toXY(pts[0], bounds: b, scale: scale, w: w, h: h, pad: padding)
                    Circle()
                        .fill(Color.blue)
                        .frame(width: 8, height: 8)
                        .position(x: xy.x, y: xy.y)
                        .overlay(Circle().stroke(Color.white, lineWidth: 1).frame(width: 12, height: 12).position(x: xy.x, y: xy.y))
                }
            }
        }
    }
    
    func allPoints() -> [(Double, Double)] {
        guard !segments.isEmpty else { return [] }
        var arr: [(Double, Double)] = []
        for s in segments {
            arr.append((s.latStart, s.lonStart))
        }
        if let last = segments.last {
            arr.append((last.latEnd, last.lonEnd))
        }
        return arr
    }
    
    func movingAverage(_ pts: [CGPoint], window: Int) -> [CGPoint] {
        let w = max(3, window)
        let half = w / 2
        var out: [CGPoint] = []
        for i in 0..<pts.count {
            let a = max(0, i - half)
            let b = min(pts.count - 1, i + half)
            let count = CGFloat(b - a + 1)
            var sx: CGFloat = 0
            var sy: CGFloat = 0
            for j in a...b {
                sx += pts[j].x
                sy += pts[j].y
            }
            out.append(CGPoint(x: sx / count, y: sy / count))
        }
        return out
    }
    
    func latLonBounds(pts: [(Double, Double)]) -> (minLat: Double, minLon: Double, maxLat: Double, maxLon: Double)? {
        guard !pts.isEmpty else { return nil }
        var minLat = pts[0].0, maxLat = pts[0].0
        var minLon = pts[0].1, maxLon = pts[0].1
        for p in pts {
            minLat = min(minLat, p.0)
            maxLat = max(maxLat, p.0)
            minLon = min(minLon, p.1)
            maxLon = max(maxLon, p.1)
        }
        return (minLat, minLon, maxLat, maxLon)
    }
    
    func scaleFor(bounds: (Double, Double, Double, Double), w: CGFloat, h: CGFloat, pad: CGFloat) -> CGFloat {
        let latRange = bounds.2 - bounds.0
        let lonRange = bounds.3 - bounds.1
        if latRange == 0 || lonRange == 0 { return 1 }
        let sx = (w - 2*pad)/CGFloat(lonRange)
        let sy = (h - 2*pad)/CGFloat(latRange)
        return min(sx, sy)
    }
    
    func toXY(_ latlon: (Double, Double), bounds: (Double, Double, Double, Double), scale: CGFloat, w: CGFloat, h: CGFloat, pad: CGFloat) -> CGPoint {
        let x = pad + CGFloat(latlon.1 - bounds.1) * scale
        let y = h - (pad + CGFloat(latlon.0 - bounds.0) * scale)
        return CGPoint(x: x, y: y)
    }
    
    func currentLatLon() -> (Double, Double)? {
        guard !segments.isEmpty else { return nil }
        let t = overrideGPXTime ?? (currentTime + gpxOffset)
        var low = 0
        var high = segments.count - 1
        var idx: Int?
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
    
    func centeredBounds(center: (Double, Double), radiusMeters: Double) -> (minLat: Double, minLon: Double, maxLat: Double, maxLon: Double)? {
        let lat = center.0
        let metersPerDegLat = 111_320.0
        let metersPerDegLon = 111_320.0 * cos(lat * .pi / 180.0)
        guard metersPerDegLon > 0 else { return nil }
        let dLat = radiusMeters / metersPerDegLat
        let dLon = radiusMeters / metersPerDegLon
        return (lat - dLat, center.1 - dLon, lat + dLat, center.1 + dLon)
    }
}

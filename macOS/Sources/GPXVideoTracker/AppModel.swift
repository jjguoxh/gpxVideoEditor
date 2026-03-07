import Foundation
import AVFoundation
import Combine
import SwiftUI
import CoreLocation

struct GPXSegment: Identifiable {
    let id = UUID()
    let start: Double
    let end: Double
    let latStart: Double
    let lonStart: Double
    let latEnd: Double
    let lonEnd: Double
    let eleStart: Double?
    let eleEnd: Double?
    let speed: Double
}

final class AppModel: ObservableObject {
    @Published var player: AVPlayer?
    @Published var playerItem: AVPlayerItem?
    @Published var videoURL: URL?
    @Published var gpxSegments: [GPXSegment] = []
    @Published var gpxOffset: Double = 0
    @Published var currentTime: Double = 0
    @Published var duration: Double = 0
    @Published var alignReverse: Bool = false
    @Published var externalAudioURL: URL?
    @Published var previewExternalAudio: Bool = false
    @Published var removeOriginalOnExport: Bool = false
    @Published var telemetryRect: CGRect = .zero
    @Published var minimapRect: CGRect = .zero
    @Published var telemetryOpacity: Double = 0.45
    @Published var minimapOpacity: Double = 0.35
    @Published var minimapLocalMode: Bool = true
    @Published var minimapLocalRadius: Double = 800
    @Published var minimapSmoothEnabled: Bool = true
    @Published var minimapSmoothWindow: Int = 5
    @Published var originalVolume: Float = 1.0
    @Published var externalVolume: Float = 1.0
    @Published var externalAudioOffset: Double = 0.0
    @Published var muted: Bool = false
    private var timeObserver: Any?
    private var audioPlayer: AVAudioPlayer?
    private var cancellables = Set<AnyCancellable>()
    
    func loadVideo(url: URL) {
        stopAudio()
        let asset = AVURLAsset(url: url)
        let item = AVPlayerItem(asset: asset)
        let p = AVPlayer(playerItem: item)
        player = p
        playerItem = item
        videoURL = url
        duration = CMTimeGetSeconds(asset.duration)
        addTimeObserver()
    }
    
    func addTimeObserver() {
        guard let player = player else { return }
        if let obs = timeObserver {
            player.removeTimeObserver(obs)
            timeObserver = nil
        }
        let interval = CMTimeMakeWithSeconds(0.05, preferredTimescale: 600)
        timeObserver = player.addPeriodicTimeObserver(forInterval: interval, queue: .main) { [weak self] t in
            guard let self else { return }
            let sec = CMTimeGetSeconds(t)
            self.currentTime = sec
            if self.previewExternalAudio {
                self.syncExternalAudio(to: sec)
            }
        }
    }
    
    func play() {
        player?.volume = originalVolume
        player?.play()
        if previewExternalAudio {
            startExternalAudio(at: currentTime)
        } else {
            stopAudio()
        }
    }
    
    func pause() {
        player?.pause()
        stopAudio()
    }
    
    func toggleMute() {
        muted.toggle()
        player?.volume = muted ? 0 : originalVolume
    }
    
    func seek(to seconds: Double) {
        player?.seek(to: CMTimeMakeWithSeconds(seconds, preferredTimescale: 600), toleranceBefore: .zero, toleranceAfter: .zero)
        if previewExternalAudio {
            startExternalAudio(at: seconds)
        } else {
            stopAudio()
        }
    }
    
    func jumpToStart() {
        seek(to: 0)
    }
    
    func jumpToEnd() {
        guard duration > 0 else { return }
        seek(to: max(0, duration - 0.05))
    }
    
    func rewind(_ seconds: Double = 5) {
        let t = max(0, currentTime - seconds)
        seek(to: t)
    }
    
    func forward(_ seconds: Double = 5) {
        let t = min(duration, currentTime + seconds)
        seek(to: t)
    }
    
    func setRate(_ rate: Float) {
        player?.rate = rate
        if previewExternalAudio {
            syncExternalAudio(to: currentTime)
        }
    }
    
    func loadGPX(url: URL) {
        do {
            let data = try Data(contentsOf: url)
            let parser = GPXParser()
            let pts = try parser.parse(data: data)
            let segs = AppModel.makeSegments(points: pts)
            gpxSegments = segs
        } catch {
            gpxSegments = []
        }
    }
    
    static func makeSegments(points: [GPXPoint]) -> [GPXSegment] {
        guard points.count >= 2 else { return [] }
        var segs: [GPXSegment] = []
        for i in 0..<(points.count-1) {
            let p1 = points[i]
            let p2 = points[i+1]
            let t1 = p1.time
            let t2 = p2.time
            if t2 <= t1 { continue }
            let dist = haversine(p1.lat, p1.lon, p2.lat, p2.lon)
            var spd = p1.speed ?? 0
            if spd <= 0 {
                let dt = t2 - t1
                if dt > 0 {
                    spd = (dist/1000.0)/(dt/3600.0)
                }
            }
            segs.append(GPXSegment(
                start: t1,
                end: t2,
                latStart: p1.lat,
                lonStart: p1.lon,
                latEnd: p2.lat,
                lonEnd: p2.lon,
                eleStart: p1.ele,
                eleEnd: p2.ele,
                speed: spd
            ))
        }
        return segs
    }
    
    func data(at videoTime: Double) -> (speed: Double, ele: Double?, grade: Double?, lat: Double?, lon: Double?) {
        guard !gpxSegments.isEmpty else { return (0, nil, nil, nil, nil) }
        let t = videoTime + gpxOffset
        var low = 0
        var high = gpxSegments.count - 1
        var idx: Int?
        while low <= high {
            let mid = (low + high) / 2
            let s = gpxSegments[mid]
            if s.start <= t && t <= s.end { idx = mid; break }
            if t < s.start { high = mid - 1 } else { low = mid + 1 }
        }
        guard let i = idx else {
            if t < gpxSegments.first!.start {
                let s = gpxSegments.first!
                return (s.speed, s.eleStart, 0, s.latStart, s.lonStart)
            }
            if t > gpxSegments.last!.end {
                let s = gpxSegments.last!
                return (s.speed, s.eleEnd, 0, s.latEnd, s.lonEnd)
            }
            return (0, nil, nil, nil, nil)
        }
        let s = gpxSegments[i]
        let dur = s.end - s.start
        let ratio = dur > 0 ? (t - s.start)/dur : 0
        let lat = s.latStart + (s.latEnd - s.latStart) * ratio
        let lon = s.lonStart + (s.lonEnd - s.lonStart) * ratio
        var ele: Double?
        if let e1 = s.eleStart, let e2 = s.eleEnd {
            ele = e1 + (e2 - e1) * ratio
        }
        var grade: Double?
        let dist = AppModel.haversine(s.latStart, s.lonStart, s.latEnd, s.lonEnd)
        if dist > 1, let e1 = s.eleStart, let e2 = s.eleEnd {
            grade = (e2 - e1)/dist*100.0
        } else {
            grade = 0
        }
        return (s.speed, ele, grade, lat, lon)
    }
    
    func confirmAlignment(selectedGPXTime: Double, videoTime: Double) {
        let eff = alignReverse ? (gpxSegments.last?.end ?? 0) - selectedGPXTime : selectedGPXTime
        gpxOffset = eff - videoTime
    }
    
    func selectExternalAudio(url: URL) {
        externalAudioURL = url
    }
    
    func startExternalAudio(at seconds: Double) {
        guard let url = externalAudioURL else { return }
        stopAudio()
        do {
            let ap = try AVAudioPlayer(contentsOf: url)
            audioPlayer = ap
            ap.volume = externalVolume
            let t = max(0, seconds + externalAudioOffset)
            ap.currentTime = t
            ap.prepareToPlay()
            ap.play()
        } catch {
            audioPlayer = nil
        }
    }
    
    func syncExternalAudio(to seconds: Double) {
        guard let ap = audioPlayer else { return }
        let desired = max(0, seconds + externalAudioOffset)
        ap.volume = externalVolume
        let diff = abs(ap.currentTime - desired)
        if diff > 0.15 {
            ap.currentTime = desired
        }
    }
    
    func stopAudio() {
        audioPlayer?.stop()
        audioPlayer = nil
    }
    
    func export(to url: URL, completion: @escaping (Result<Void, Error>) -> Void) {
        guard let videoURL else { completion(.failure(NSError(domain: "no video", code: -1))); return }
        Exporter.export(videoURL: videoURL,
                        externalAudio: externalAudioURL,
                        removeOriginalAudio: removeOriginalOnExport,
                        externalAudioOffset: externalAudioOffset,
                        originalVolume: originalVolume,
                        externalVolume: externalVolume,
                        gpxSegments: gpxSegments,
                        gpxOffset: gpxOffset,
                        overlayMinimap: true,
                        minimapRect: minimapRect,
                        minimapOpacity: minimapOpacity,
                        minimapLocalMode: minimapLocalMode,
                        minimapLocalRadius: minimapLocalRadius,
                        minimapSmoothEnabled: minimapSmoothEnabled,
                        minimapSmoothWindow: minimapSmoothWindow,
                        overlayTelemetry: true,
                        telemetryRect: telemetryRect,
                        telemetryOpacity: telemetryOpacity,
                        to: url,
                        completion: completion)
    }
    
    static func haversine(_ lat1: Double, _ lon1: Double, _ lat2: Double, _ lon2: Double) -> Double {
        let R = 6371000.0
        let p1 = lat1 * .pi/180
        let p2 = lat2 * .pi/180
        let dphi = (lat2-lat1) * .pi/180
        let dl = (lon2-lon1) * .pi/180
        let a = sin(dphi/2)*sin(dphi/2) + cos(p1)*cos(p2)*sin(dl/2)*sin(dl/2)
        let c = 2 * atan2(sqrt(a), sqrt(1-a))
        return R * c
    }
}

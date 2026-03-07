import SwiftUI
import AVKit

struct PlayerContainerView: NSViewRepresentable {
    let player: AVPlayer?
    func makeNSView(context: Context) -> AVPlayerView {
        let v = AVPlayerView()
        v.controlsStyle = .inline
        v.allowsPictureInPicturePlayback = false
        v.updatesNowPlayingInfoCenter = false
        v.player = player
        return v
    }
    func updateNSView(_ nsView: AVPlayerView, context: Context) {
        nsView.player = player
    }
}

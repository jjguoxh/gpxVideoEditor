import SwiftUI

struct MinimapOverlay: View {
    @EnvironmentObject var model: AppModel
    let videoSize: CGSize
    var body: some View {
        GeometryReader { geo in
            let size = geo.size
            ZStack(alignment: .topLeading) {
                RoundedRectangle(cornerRadius: 6)
                    .fill(Color.black.opacity(model.minimapOpacity))
                TrackMiniMap(segments: model.gpxSegments,
                             currentTime: model.currentTime,
                             gpxOffset: model.gpxOffset,
                             localMode: true,
                             localRadius: model.minimapLocalRadius,
                             smooth: model.minimapSmoothEnabled,
                             smoothWindow: model.minimapSmoothWindow,
                             overrideGPXTime: nil)
                    .padding(6)
                    .allowsHitTesting(false)
            }
            .frame(width: model.minimapRect.width, height: model.minimapRect.height)
            .position(x: model.minimapRect.midX, y: model.minimapRect.midY)
            .gesture(DragGesture()
                .onChanged { v in
                    var r = model.minimapRect
                    r.origin.x = min(max(0, r.origin.x + v.translation.width), size.width - r.width)
                    r.origin.y = min(max(0, r.origin.y + v.translation.height), size.height - r.height)
                    model.minimapRect = r
                }
            )
            .overlay(alignment: .bottomTrailing) {
                Rectangle()
                    .fill(Color.gray.opacity(0.6))
                    .frame(width: 14, height: 14)
                    .gesture(DragGesture()
                        .onChanged { v in
                            let w = max(140, min(model.minimapRect.width + v.translation.width, size.width - model.minimapRect.minX))
                            let h = max(100, min(model.minimapRect.height + v.translation.height, size.height - model.minimapRect.minY))
                            model.minimapRect.size = CGSize(width: w, height: h)
                        }
                    )
                    .padding(2)
            }
            .onAppear {
                if model.minimapRect == .zero {
                    let w = min(220, max(160, size.width * 0.3))
                    let h = min(160, max(120, size.height * 0.25))
                    let x = size.width - w - 14.0
                    let y: CGFloat = 14.0
                    var r = CGRect(x: x, y: y, width: w, height: h)
                    r.origin.x = min(max(0, r.origin.x), size.width - r.width)
                    r.origin.y = min(max(0, r.origin.y), size.height - r.height)
                    model.minimapRect = r
                }
            }
            .zIndex(10)
        }
    }
}

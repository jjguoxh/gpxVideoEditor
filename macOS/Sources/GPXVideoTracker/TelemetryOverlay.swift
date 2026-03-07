import SwiftUI

struct TelemetryOverlay: View {
    @EnvironmentObject var model: AppModel
    let videoSize: CGSize
    let speed: Double
    let ele: Double?
    let grade: Double?
    @State private var dragOffset: CGSize = .zero
    @State private var isResizing: Bool = false
    @State private var startRect: CGRect = .zero
    
    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .topLeading) {
                RoundedRectangle(cornerRadius: 8)
                    .fill(Color.black.opacity(model.telemetryOpacity))
                VStack(alignment: .leading, spacing: 6) {
                    Text(String(format: "速度  %.1f km/h", speed))
                    if let e = ele {
                        Text(String(format: "海拔  %.0f m", e))
                    }
                    if let g = grade {
                        Text(String(format: "坡度  %+0.1f%%", g))
                    }
                }
                .padding(10)
                .foregroundColor(.white)
                Rectangle()
                    .fill(Color.gray.opacity(0.6))
                    .frame(width: 14, height: 14)
                    .position(x: geo.size.width - 10, y: geo.size.height - 10)
                    .gesture(DragGesture()
                        .onChanged { v in
                            if !isResizing {
                                isResizing = true
                                startRect = model.telemetryRect
                            }
                            let dx = max(120, startRect.width + v.translation.width)
                            let dy = max(80, startRect.height + v.translation.height)
                            var r = startRect
                            r.size = CGSize(width: min(dx, videoSize.width - startRect.minX), height: min(dy, videoSize.height - startRect.minY))
                            model.telemetryRect = r
                        }
                        .onEnded { _ in isResizing = false }
                    )
                    .allowsHitTesting(true)
            }
            .frame(width: model.telemetryRect.width, height: model.telemetryRect.height)
            .position(x: model.telemetryRect.midX, y: model.telemetryRect.midY)
            .gesture(DragGesture()
                .onChanged { v in
                    var r = model.telemetryRect
                    r.origin.x = min(max(0, r.origin.x + v.translation.width), videoSize.width - r.width)
                    r.origin.y = min(max(0, r.origin.y + v.translation.height), videoSize.height - r.height)
                    model.telemetryRect = r
                }
            )
            .onAppear {
                if model.telemetryRect == .zero {
                    let w = max(220, videoSize.width * 0.25)
                    let h = max(120, videoSize.height * 0.22)
                    let x = videoSize.width - w - 20
                    let y = videoSize.height - h - 20
                    model.telemetryRect = CGRect(x: x, y: y, width: w, height: h)
                }
            }
        }
    }
}

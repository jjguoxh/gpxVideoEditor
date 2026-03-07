import SwiftUI
import AVKit
import UniformTypeIdentifiers

struct ContentView: View {
    @EnvironmentObject var model: AppModel
    @State private var videoSize: CGSize = CGSize(width: 1280, height: 720)
    @State private var showingExporter = false
    @State private var zoomChoice: String = "适应"
    @State private var gpxFileName: String = "未选择音轨"
    
    var body: some View {
        VStack(spacing: 8) {
            // 顶部工具栏（参考 proto/video_editor.py 排版）
            HStack(spacing: 8) {
                Button("打开视频") { openVideo() }
                Button("导入视频") { openVideo() }
                Button("导入GPX") { openGPX() }
                Button("导出视频") { export() }
                Divider().frame(height: 18)
                Button("▶ 播放") { model.play() }
                Button("⏹ 停止") { model.pause() }
                Button("⏮") { model.jumpToStart() }.frame(width: 34)
                Button("⏪") { model.rewind() }.frame(width: 34)
                Button("⏩") { model.forward() }.frame(width: 34)
                Button("⏭") { model.jumpToEnd() }.frame(width: 34)
                Divider().frame(height: 18)
                Button("分割") { }.frame(width: 60)
                Button("删除") { }.frame(width: 60)
                Button("合并") { }.frame(width: 60)
                Divider().frame(height: 18)
                Text("缩放:")
                Picker("", selection: $zoomChoice) {
                    ForEach(["适应","50%","100%","150%","200%"], id:\.self) { Text($0) }
                }.frame(width: 90)
                Spacer()
            }
            
            // 主体：左视频 + 右属性栏
            HSplitView {
                // 左侧：视频与控制
                VStack(spacing: 8) {
                    ZStack {
                        PlayerContainerView(player: model.player)
                            .frame(maxWidth: .infinity, maxHeight: .infinity)
                            .background(GeometryReader { geo in
                                Color.clear
                                    .onAppear { videoSize = geo.size }
                                    .onChange(of: geo.size) { v in videoSize = v }
                            })
                        let d = model.data(at: model.currentTime)
                        TelemetryOverlay(videoSize: videoSize, speed: d.speed, ele: d.ele, grade: d.grade)
                            .environmentObject(model)
                            .allowsHitTesting(true)
                            .zIndex(1)
                        MinimapOverlay(videoSize: videoSize)
                            .environmentObject(model)
                            .zIndex(2)
                    }
                    // 进度与时间/控制条
                    VStack(spacing: 4) {
                        Slider(value: Binding(get: { model.currentTime }, set: { model.seek(to: $0) }), in: 0...(model.duration > 0 ? model.duration : 1))
                        HStack {
                            Text(String(format: "%02d:%02d:%02d / %02d:%02d:%02d",
                                        Int(model.currentTime)/3600, (Int(model.currentTime)/60)%60, Int(model.currentTime)%60,
                                        Int(model.duration)/3600, (Int(model.duration)/60)%60, Int(model.duration)%60))
                            HStack(spacing: 6) {
                                Button("⏮") { model.jumpToStart() }.frame(width: 30)
                                Button("⏪") { model.rewind() }.frame(width: 30)
                                Button("▶") { model.play() }.frame(width: 30)
                                Button("⏩") { model.forward() }.frame(width: 30)
                                Button("⏭") { model.jumpToEnd() }.frame(width: 30)
                            }.padding(.leading, 16)
                            Spacer()
                            HStack(spacing: 8) {
                                Button(model.muted ? "🔇" : "🔊") { model.toggleMute() }.frame(width: 30)
                                Slider(value: $model.originalVolume, in: 0...1).frame(width: 100)
                            }
                            HStack(spacing: 6) {
                                Text("速度:")
                                Picker("", selection: Binding(get: {
                                    String(format: "%.2fx", model.player?.rate ?? 1.0)
                                }, set: { v in
                                    let rate = Float(v.replacingOccurrences(of: "x", with: "")) ?? 1.0
                                    model.setRate(rate)
                                })) {
                                    ForEach(["0.25x","0.5x","0.75x","1.0x","1.25x","1.5x","2.0x"], id:\.self) { Text($0) }
                                }.frame(width: 80)
                            }.padding(.leading, 12)
                        }
                    }.padding(.horizontal, 6)
                }
                // 右侧：属性栏
                ScrollView {
                    VStack(alignment: .leading, spacing: 10) {
                        GroupBox("轨迹预览") {
                            VStack(spacing: 6) {
                                // 属性栏中的轨迹预览始终显示全景
                                TrackMiniMap(segments: model.gpxSegments,
                                             currentTime: model.currentTime,
                                             gpxOffset: model.gpxOffset,
                                             localMode: false,
                                             localRadius: model.minimapLocalRadius,
                                             smooth: model.minimapSmoothEnabled,
                                             smoothWindow: model.minimapSmoothWindow,
                                             overrideGPXTime: gpxTimeSelection)
                                    .frame(minHeight: 160, maxHeight: 220)
                                    .padding(6)
                                HStack {
                                    Text("局部半径(m)")
                                    Slider(value: $model.minimapLocalRadius, in: 100...2000, step: 50).frame(width: 160)
                                    Text(String(format: "%.0f", model.minimapLocalRadius)).frame(width: 56, alignment: .trailing)
                                }
                                HStack {
                                    Toggle("平滑", isOn: $model.minimapSmoothEnabled)
                                    Text("窗口")
                                    Slider(value: Binding(get: { Double(model.minimapSmoothWindow) }, set: { model.minimapSmoothWindow = Int($0) }), in: 3...11, step: 2).frame(width: 120)
                                    Text("\(model.minimapSmoothWindow)").frame(width: 28, alignment: .trailing)
                                }
                                HStack {
                                    Text("缩略图透明度")
                                    Slider(value: $model.minimapOpacity, in: 0.2...0.9).frame(width: 160)
                                    Text(String(format: "%.2f", model.minimapOpacity)).frame(width: 56, alignment: .trailing)
                                }
                            }
                        }
                        GroupBox("对齐控制") {
                            VStack(alignment: .leading, spacing: 8) {
                                HStack {
                                    Toggle("反向", isOn: $model.alignReverse)
                                    Spacer()
                                    Button("重置视图") {
                                        model.minimapLocalMode = false
                                        model.minimapLocalRadius = 500
                                        model.minimapSmoothEnabled = true
                                        model.minimapSmoothWindow = 5
                                    }
                                }
                                Slider(value: Binding(get: {
                                    model.alignReverse ? ((model.gpxSegments.last?.end ?? 0) - gpxTimeSelection) : gpxTimeSelection
                                }, set: { val in
                                    gpxTimeSelection = model.alignReverse ? ((model.gpxSegments.last?.end ?? 0) - val) : val
                                }), in: 0...(model.gpxSegments.last?.end ?? 0))
                                HStack {
                                    Text(String(format: "GPX时间: %.1fs", gpxTimeSelection))
                                    Spacer()
                                    Button("确认对齐") { model.confirmAlignment(selectedGPXTime: gpxTimeSelection, videoTime: model.currentTime) }
                                }
                            }
                            .padding(6)
                        }
                        GroupBox("音频") {
                            HStack {
                                Button("导入音轨") { openAudio() }
                                Toggle("预览外部音轨", isOn: $model.previewExternalAudio)
                                Toggle("移除原声(导出)", isOn: $model.removeOriginalOnExport)
                            }
                            HStack {
                                Text(model.externalAudioURL?.lastPathComponent ?? "未选择音轨")
                                Spacer()
                            }
                        }
                        GroupBox("剪辑片段") {
                            Text("片段列表（待实现）").foregroundColor(.secondary)
                                .frame(maxWidth: .infinity, minHeight: 120, alignment: .topLeading)
                        }
                        GroupBox("数据分析 (GPX)") {
                            Text("速度/海拔曲线（待实现）").foregroundColor(.secondary)
                                .frame(maxWidth: .infinity, minHeight: 120, alignment: .topLeading)
                        }
                    }
                    .padding(6)
                    .frame(minWidth: 280)
                }
            }
            .frame(minHeight: 520)
        }
        .padding(8)
        .frame(minWidth: 1100, minHeight: 700)
    }
    
    @State private var gpxTimeSelection: Double = 0
    
    func openVideo() {
        let p = NSOpenPanel()
        p.allowedContentTypes = [.mpeg4Movie, .quickTimeMovie, .video]
        p.allowsMultipleSelection = false
        if p.runModal() == .OK, let url = p.url {
            model.loadVideo(url: url)
        }
    }
    
    func openGPX() {
        let p = NSOpenPanel()
        if #available(macOS 12.0, *) {
            var types: [UTType] = []
            if let g = UTType(filenameExtension: "gpx") { types.append(g) }
            if let x = UTType(filenameExtension: "xml") { types.append(x) }
            p.allowedContentTypes = types
        } else {
            p.allowedFileTypes = ["gpx", "xml"]
        }
        p.allowsMultipleSelection = false
        if p.runModal() == .OK, let url = p.url {
            model.loadGPX(url: url)
            gpxTimeSelection = 0
        }
    }
    
    func openAudio() {
        let p = NSOpenPanel()
        if #available(macOS 12.0, *) {
            let exts = ["mp3","wav","m4a","aac","flac"]
            let types = exts.compactMap { UTType(filenameExtension: $0) }
            p.allowedContentTypes = types
        } else {
            p.allowedFileTypes = ["mp3","wav","m4a","aac","flac"]
        }
        p.allowsMultipleSelection = false
        if p.runModal() == .OK, let url = p.url {
            model.selectExternalAudio(url: url)
        }
    }
    
    func export() {
        guard model.videoURL != nil else { return }
        let p = NSSavePanel()
        if #available(macOS 12.0, *) {
            p.allowedContentTypes = [.mpeg4Movie]
        } else {
            p.allowedFileTypes = ["mp4"]
        }
        if p.runModal() == .OK, let url = p.url {
            model.export(to: url) { result in
                DispatchQueue.main.async {
                    switch result {
                    case .success: NSSound.beep()
                    case .failure: NSSound.beep()
                    }
                }
            }
        }
    }
}

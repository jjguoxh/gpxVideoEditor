// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "GPXVideoTracker",
    platforms: [
        .macOS(.v12)
    ],
    products: [
        .executable(name: "GPXVideoTracker", targets: ["GPXVideoTracker"])
    ],
    dependencies: [],
    targets: [
        .executableTarget(
            name: "GPXVideoTracker",
            path: "Sources"
        )
    ]
)

// swift-tools-version: 6.0
import PackageDescription

// Three targets rather than one, and the split is the point.
//
// `DesignSystem` may not import `Tessera`. That is the same discipline import-linter
// enforces on the Python side: the reusable layer cannot reach up into the application,
// so it stays independently testable and cannot quietly acquire a dependency on a window
// or a network client.
//
// `Gallery` is a separate executable rather than a hidden window in the app, so the
// shipped binary carries no developer tool — and because the gates build every target,
// it cannot fall out of date with the components it exists to show.
let package = Package(
    name: "Tessera",
    // The *deployment* target, not the SDK. Built with the macOS 26 SDK and run on
    // anything from 14 up; 26-only API sits behind `if #available`.
    platforms: [.macOS(.v14)],
    targets: [
        .target(name: "DesignSystem", path: "Sources/DesignSystem"),
        .executableTarget(
            name: "Gallery",
            dependencies: ["DesignSystem"],
            path: "Sources/Gallery"
        ),
        .executableTarget(
            name: "Snapshot",
            dependencies: ["DesignSystem"],
            path: "Sources/Snapshot"
        ),
        .executableTarget(
            name: "Tessera",
            dependencies: ["DesignSystem"],
            path: "Sources/Tessera"
        ),
        .testTarget(
            name: "DesignSystemTests",
            dependencies: ["DesignSystem"],
            path: "Tests/DesignSystemTests"
        ),
        .testTarget(
            name: "TesseraTests",
            dependencies: ["Tessera"],
            path: "Tests/TesseraTests"
        ),
    ]
)

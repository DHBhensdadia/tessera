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
    dependencies: [
        // Apple's generator turns the committed OpenAPI document into a typed client at
        // build time. The alternative was ~4,000 hand-written lines for 109 operations,
        // and a hand-written client can fall behind the contract without anything saying
        // so — here, drift is a compile error.
        .package(url: "https://github.com/apple/swift-openapi-generator", from: "1.0.0"),
        .package(url: "https://github.com/apple/swift-openapi-runtime", from: "1.0.0"),
        .package(url: "https://github.com/apple/swift-openapi-urlsession", from: "1.0.0"),
    ],
    targets: [
        .target(name: "DesignSystem", path: "Sources/DesignSystem"),
        .target(
            name: "EngineClient",
            dependencies: [
                .product(name: "OpenAPIRuntime", package: "swift-openapi-runtime"),
                .product(name: "OpenAPIURLSession", package: "swift-openapi-urlsession"),
            ],
            // The document lives here rather than in `docs/` because SwiftPM plugins are
            // sandboxed to the package directory. `tessera-openapi` writes both copies and
            // `scripts/check.sh` fails if they differ.
            //
            // Deliberately **not** `exclude`d: the plugin discovers them as its inputs, and
            // excluding them produced a target with no sources, no generated code, and a
            // green build — an empty module compiles perfectly.
            path: "Sources/EngineClient",
            plugins: [.plugin(name: "OpenAPIGenerator", package: "swift-openapi-generator")]
        ),
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
            dependencies: ["DesignSystem", "EngineClient"],
            path: "Sources/Tessera"
        ),
        .testTarget(
            name: "DesignSystemTests",
            dependencies: ["DesignSystem"],
            path: "Tests/DesignSystemTests"
        ),
        .testTarget(
            name: "EngineClientTests",
            dependencies: ["EngineClient"],
            path: "Tests/EngineClientTests"
        ),
        .testTarget(
            name: "TesseraTests",
            dependencies: ["Tessera"],
            path: "Tests/TesseraTests"
        ),
    ]
)

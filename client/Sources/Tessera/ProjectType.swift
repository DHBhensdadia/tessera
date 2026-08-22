import UniformTypeIdentifiers

extension UTType {
    /// The `.tessera` package.
    ///
    /// Declared in the bundle's `Info.plist` as an exported type conforming to
    /// `com.apple.package`, which is what makes the Finder present the directory as one
    /// item rather than as a folder — the premise Decision #25 rests on and which the
    /// shipped bundle did not honour until 3.2.
    ///
    /// `exportedAs:` is the honest spelling even before the declaration lands: it says
    /// this application is the type's owner. Running from `swift run`, where there is no
    /// bundle to read, the system falls back to inferring from the extension, and the
    /// panels still filter correctly.
    static let tesseraProject = UTType(
        exportedAs: "com.dhbhensdadia.tessera.project",
        conformingTo: .package
    )
}

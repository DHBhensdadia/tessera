import Foundation
import os

/// How long it took to get from `main` to something the user can use.
///
/// NFR-3 says under three seconds, and a number nobody measures is a number that drifts.
/// The clock starts when the process does and stops the first time a project window has an
/// engine serving and its counts loaded — which is the honest definition of *usable*, and a
/// stricter one than "a window appeared".
///
/// Reported once, to the log and to stderr when `--time-launch` is passed, so the gate can
/// read it without a display.
///
/// **Measured from `exec`, not from this object.** The first version stored
/// `ContinuousClock.now` in a `let` on a `static let` singleton — and a `static let` in
/// Swift is lazy, so the clock started the first time anybody *read* it, which was inside
/// the method that reports the elapsed time. It printed `0.00s` three runs in a row and
/// would have passed NFR-3 for the rest of the project's life. Asking the kernel when the
/// process began cannot be fooled that way, and it also counts the dyld and runtime setup
/// that happens before any Swift code runs — which on a 76 MB bundle is a real share of
/// what the user experiences as launch.
final class LaunchClock: @unchecked Sendable {
    static let shared = LaunchClock()

    private let lock = OSAllocatedUnfairLock(initialState: false)
    private let logger = Logger(subsystem: "com.dhbhensdadia.tessera", category: "launch")

    /// When this process was `exec`ed, from the kernel's own record.
    private static func secondsSinceExec() -> Double {
        var info = kinfo_proc()
        var size = MemoryLayout<kinfo_proc>.stride
        var name: [Int32] = [CTL_KERN, KERN_PROC, KERN_PROC_PID, getpid()]
        guard sysctl(&name, UInt32(name.count), &info, &size, nil, 0) == 0 else { return -1 }

        let started = info.kp_proc.p_starttime
        var now = timeval()
        gettimeofday(&now, nil)
        return Double(now.tv_sec - started.tv_sec)
            + Double(Int(now.tv_usec) - Int(started.tv_usec)) / 1_000_000
    }

    func noteFirstUsableWindow() {
        let first = lock.withLock { reported -> Bool in
            guard !reported else { return false }
            reported = true
            return true
        }
        guard first else { return }

        let seconds = Self.secondsSinceExec()
        logger.info("launch_to_usable seconds=\(seconds, privacy: .public)")
        if CommandLine.arguments.contains("--time-launch") {
            FileHandle.standardError.write(
                Data("launch-to-usable \(String(format: "%.2f", seconds))s\n".utf8)
            )
        }
    }
}

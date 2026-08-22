# The app shell

How a project becomes a window, and how the engine that serves it lives and dies.

Everything here is lifecycle. There is no new algorithm and no new data structure in this
layer — the risk is entirely in processes, windows, and the states between "launched" and
"usable". Every defect it produced was found by counting processes or by timing a launch,
and none by reading the code.

## A project is a file, so the front door is not a document

Two scenes. A `Window` for the welcome screen, and a `WindowGroup(for: ProjectLocation.self)`
for projects.

**Not `DocumentGroup`.** That scene is built around `FileDocument`: the framework reads the
file into a value, hands it to the view and writes it back. Ours is a SQLite database inside
a package, mutated by a subprocess, with no in-memory representation and no save step at all.
Adopting it would have meant a document type that reads nothing, writes nothing and lies
about both — and it opens a file panel at launch, which is precisely what a welcome window
exists instead of.

`.tessera` is declared in the bundle as an exported type conforming to `com.apple.package`,
with `LSTypeIsPackage`. That declaration is what makes the Finder show one item rather than a
folder, and it is what Decision #25's whole argument — email it, archive it, double-click it —
depends on. It had been true on paper since Stage 0 and false in every build until 3.2.

## Opening is not the same as creating

`project.resolve` creates whatever is missing. That is right when somebody has just named a
file in a save panel and destructive when the path came from Recent Projects or from a window
macOS restored: the folder is still called "Autumn 2026", it still opens, and it is empty.

The distinction is **intent**, which only the caller knows, so it travels as a parameter all
the way down — `OpenIntent` in the client, `--must-exist` on the engine, `must_exist=` in
`tessera.project`. The engine exits **3** for a project that is not there and **4** for a path
holding something that is not ours, and the client branches on the status rather than on the
text of the message, because matching a message is a coupling that survives exactly until
somebody improves the wording.

A window restored by macOS always decodes as a reopen. That falls out of how identity is
encoded, below, and it is the behaviour you want: a restored window must never invent a
project that has gone.

## One engine per project

The engine's own rule, set in 2.9: one engine serves one project for its whole life. The
client opens a second project by launching a second engine.

Getting that right in SwiftUI took four attempts, and the three failures are more instructive
than the fix.

**`@State` in the view.** A view struct is re-initialised whenever anything upstream changes,
so `EngineController()` in `init` produced a new engine each time. One project, **six**
engines, measured on the shipped bundle.

**An `@Observable` registry.** Ownership moved to a registry keyed by project, which is
correct — but `controller(for:)` inserts on a miss, so calling it from a computed property
inside `body` mutated observed state *during body evaluation*. SwiftUI discarded the pass and
re-ran it, and the second pass built a second controller. Two projects, **four** engines,
exactly two each. The registry is a lookup table, not view state; it is a plain class behind
an `EnvironmentKey` now, and views observe the controller they were handed rather than the
mapping.

**Teardown on `.onDisappear`.** SwiftUI fires that whenever a view leaves a hierarchy, which
is not the same as a window closing. A spurious release dropped a live controller, the next
lookup built a new one, and the old Python process survived with nothing attached to it.
Teardown hangs off `NSWindow.willCloseNotification` now — an event that means one thing.

`start()` is also guarded so it launches at most once, with the flag set before the first
`await`; on the main actor that is atomic without a lock. And the process handle lives in a
small non-isolated box that terminates on `deinit`, so a controller dropped by a path nobody
intended still takes its subprocess with it.

## Identity, and the thing SwiftUI does not do

`WindowGroup(for:)` is documented around one window per value. **It does not focus an existing
window when asked to open a value it already has one for** — measured: re-opening two open
projects took the engine count from two to four. So the application checks first.

Two parts to that check, and the second replaced a worse version of itself.

`ProjectLocation` encodes **only its URL**. The synthesised `Codable` included the intent, so
the same project arriving from a launch argument and from a Finder double-click encoded
differently and got two windows. The test guarding this originally asserted `==`, passed, and
was aimed at the wrong mechanism — SwiftUI keys windows on the encoded value.

And "is this project already open" is answered by asking AppKit which visible window has this
`representedURL`, which `.navigationDocument(url)` sets. The first version kept its own map
and registered from an `NSViewRepresentable`; windows created from launch arguments were never
recorded, so the first re-open still made a second pair. **Every version that kept its own
copy of something the system already tracked had a moment where the copy was not yet true.**

## Launch, measured

NFR-3 asks for under three seconds from cold launch to a usable window. `LaunchClock` reports
it once, from the kernel's record of when the process was `exec`ed to the moment a project
window has an engine serving *and* its counts loaded — a stricter definition than "a window
appeared".

It is measured from `exec` rather than from a stored timestamp because the first version
stored `ContinuousClock.now` on a `static let`, and a `static let` in Swift is lazy: the clock
started the first time anything read it, which was inside the method reporting elapsed time.
It printed `0.00s` three runs running and would have passed for the rest of the project's
life. Measuring from `exec` also counts the dyld and runtime setup before any Swift code runs,
which on a 76 MB bundle is a real share of what a person experiences as launch.

Current: **2.06 s** cold, 1.35–1.50 s warm, on the shipped `.app`.

## Counting without fetching

Every list endpoint answers with a page carrying a `total`, so the sidebar's counts are one
request each with `limit=1`. Decoding uses a type with only `total` on it — the first version
reused `Page<Term>`, which asks the decoder to read a room as a term, throws, and turns into a
count that never arrives. Every number rendered as `…`.

That was visible **only** because "not asked yet" is drawn differently from zero. The
distinction was made for the checklist, on the grounds that a screen briefly claiming you have
no rooms is one people learn to distrust, and it caught an unrelated bug for free.

## What the shell does not do

It renders no entity screen — 3.4 owns those, and what stands in their place is the empty
state each will keep. It carries a deliberately small slice of the engine's HTTP surface,
named as a seed: health, institutions, time-grids, terms, and counts. 3.3 extends it into the
typed client checked against the OpenAPI snapshot.

## See also

- [Packaging and the sidecar](packaging.md) — how the client and engine ship together
- [The design system](design-system.md) — the language the shell is drawn in

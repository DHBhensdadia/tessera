# Packaging and the sidecar

How a Python engine and a SwiftUI application become one `.dmg`, and how they find each
other at runtime.

```bash
./packaging/build.sh        # → packaging/out/Tessera-<version>-arm64.dmg
./packaging/smoke-test.sh   # installs it and verifies it actually works
```

## Shape

```
Tessera.app/Contents/
├── MacOS/Tessera              SwiftUI client
└── Resources/engine/          PyInstaller-frozen engine, ~44 MB
```

One application to the user; a client and a server to us ([ADR-0001](../adr/0001-engine-client-sidecar.md)).
The same engine also ships as a Docker image and a CLI, so it must never assume the
client exists.

## The handshake

Neither the port nor the token can be agreed in advance. A fixed port collides with
whatever else is using it and prevents two projects being open at once; a fixed token is
not a secret. Both are invented at startup and announced over the pipe that already
connects parent and child:

```json
{"port": 52141, "token": "…", "pid": 4823, "project": "/path/to/file.tessera"}
```

The engine binds the socket **before** starting uvicorn, because otherwise the port only
exists once the server is already accepting requests nobody knows how to address.

**stdout carries this line and nothing else.** Everything — ours, uvicorn's,
SQLAlchemy's, and Alembic's — is logged to **stderr**. This is not tidiness: Alembic
runs migrations moments before the handshake is written, and while its output went to
stdout the client read a log line where it expected JSON and reported a broken engine.
The client also scans lines for one that parses, rather than trusting the first, so a
stray print degrades into "keep looking".

## Token

Generated per launch and required on every request except `/docs` and `/openapi.json`.
The API shape is public knowledge; a project's staffing and room data is not. Any process
on the machine can open the loopback port — only the one that read the handshake gets
anywhere.

Compared with `secrets.compare_digest`, since a plain `==` returns as soon as it finds a
difference and leaks how much of the token was right. Overkill for a loopback socket,
and the correct habit.

## Migrations on startup

`tessera.engine.migrate` runs `alembic upgrade head` every time, not only on creation.
That is how an existing project file survives the user updating the application; a
project already at head is a no-op.

The Alembic `Config` is built in code rather than read from `alembic.ini`, which is a
development convenience that is not shipped. The migration scripts travel as **data**
in the PyInstaller spec and are located under `sys._MEIPASS` once frozen — resolving
relative to `__file__` finds nothing in a shipped build.

## Dying with the parent

macOS has no equivalent of Linux's `PR_SET_PDEATHSIG`, so the engine polls
`os.getppid()` and exits when it changes. Without it, force-quitting leaves a stray
process holding the project file open.

> **Keep that path free of I/O.** A `logger.info` call between the check and the exit
> made the engine outlive the application three launches out of three; removing it made
> three out of three clean. The mechanism is unconfirmed — it reproduces only with the
> SwiftUI application as parent, not with a Python parent, frozen or otherwise, and the
> engine writes far too little to stderr for pipe saturation to explain it. What is
> established is that writing to a pipe whose far end has just died is unsafe here, and
> that nobody is left to read the message anyway.

This is also why `packaging/smoke-test.sh` exists. The unit suite spawns the engine from
Python and **passes whether or not a shipped bundle leaks a process** — the failure is
only observable in the real thing.

**Twenty-six checks, and the ones that grow fastest are about data that travels.** Anything
read from disk at render time — the migrations, the sixteen templates, and since 4.8 one
script — makes a spec that forgets it build cleanly, pass every unit test, and serve a stack
trace to the first person who opens that page. So the script drives the whole of the
console's route to a timetable on the installed bundle: the Generate form, pressing it, the
watch page *carrying its script*, the solve settling, and the week grid with teaching drawn in
it. Verified sensitive rather than assumed to be — take `templates/solve/watch.js` out of an
installed `.app` and the script check fails; take `templates/timetables/` out and the form and
the grid checks fail with it.

## Signing, inside out

Nested Mach-O binaries first (85 of them), then the bundle. A signature seals the
contents it covers, so signing the bundle first and a nested dylib afterwards
invalidates the outer seal and macOS refuses to launch it.

Signing uses `--options=runtime` with the entitlements frozen Python needs —
`allow-unsigned-executable-memory`, `allow-jit`, `disable-library-validation`. Harmless
under ad-hoc signing, and proving them now means notarization changes only the identity
([ADR-0010](../adr/0010-ship-unnotarized-first.md)).

Set `CODESIGN_IDENTITY` to sign with a Developer ID instead of ad-hoc.

## Architecture

**Apple Silicon only** ([ADR-0011](../adr/0011-arm64-only.md)). PyInstaller cannot
cross-compile — it freezes against the host's installed wheels — so the runner
architecture *is* the artefact's architecture, and CI uses a single `macos-14` runner.

## Releasing

Push a `v*` tag. `.github/workflows/release.yml` builds the `.dmg`, **runs the smoke
test**, computes checksums and publishes a GitHub release. A build that fails the smoke
test never becomes a release.

Until notarization, the release notes carry the first-launch workaround:

```bash
xattr -dr com.apple.quarantine /Applications/Tessera.app
```

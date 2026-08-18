"""The sidecar entry point.

Started by the desktop application as a child process, never by the user. It binds a
loopback port the kernel chooses, prints one line of JSON describing how to reach it,
and serves until its parent goes away.

The handshake exists because neither the port nor the token can be agreed in advance: a
fixed port collides with whatever else is using it and prevents two projects being open
at once, and a fixed token is not a secret. Both are invented at startup and announced
over the pipe that already connects parent and child.

    {"port": 52141, "token": "…", "pid": 4823, "project": "/path/to/file.tessera"}
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import sys
import threading
import time
from pathlib import Path

import structlog
import uvicorn

from tessera import paths, project
from tessera.api.app import create_app
from tessera.api.logging import configure_logging
from tessera.repository.database import create_project_engine

logger = structlog.get_logger(__name__)


def default_project() -> Path:
    """Where a project lives when none is named.

    The desktop application always passes an explicit path, so this only matters for the
    Docker image and the CLI — which run on Linux, where an Application Support
    directory does not exist.
    """
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Tessera"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "tessera"
    return base / "default.tessera"


def watch_parent(poll_seconds: float = 1.0) -> None:
    """Exit when the process that started us does.

    macOS has no equivalent of Linux's ``PR_SET_PDEATHSIG``, so the child polls instead.
    A process whose parent dies is reparented to init and reports a different ppid,
    which is the signal.

    Without this, force-quitting the application leaves the engine running. Do that a
    few times and the user has several stray Python processes holding their project
    file open — the kind of detail that makes software feel unfinished.

    **Nothing is logged on the way out, and that is deliberate.** A ``logger.info`` call
    sat between the check and the exit, and with it the engine reliably outlived the
    desktop application — three launches out of three. Removing it made three out of
    three clean.

    The precise mechanism is unconfirmed: the failure reproduces only when the parent is
    the SwiftUI application, not when it is another Python process, frozen or otherwise,
    and the engine writes far too little to stderr for pipe saturation to explain it.
    What is established is that the parent owns the other end of this process's stderr,
    that writing to it at the moment the parent dies is unsafe, and that there is nobody
    left to read the message anyway.

    Keep this path free of I/O.
    """
    original = os.getppid()
    while True:
        time.sleep(poll_seconds)
        if os.getppid() != original:
            os._exit(0)


def migrations_directory() -> Path:
    """Where the migration scripts live, frozen or not.

    Kept as a name here because callers and tests import it from this module; the
    resolution itself moved to `tessera.paths` in 2.5, when the console's templates
    turned out to need exactly the same treatment and one copy of the rule was better
    than two.
    """
    return paths.migrations_directory()


def migrate(project_path: Path) -> None:
    """Bring a project file up to the current schema.

    Run on every start rather than only on creation: this is how an existing project
    survives the user updating the application. A project already at head is a no-op.

    The Config is built in code rather than read from ``alembic.ini``, which is a
    development convenience that is not shipped. env.py skips its logging setup when no
    file is configured.
    """
    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(migrations_directory()))
    config.attributes["database_url"] = f"sqlite:///{project_path}"
    command.upgrade(config, "head")


def serve(project_path: Path, *, host: str = "127.0.0.1", port: int = 0) -> None:
    project_path.parent.mkdir(parents=True, exist_ok=True)
    # `--project` names the project; where the database sits inside it is this module's
    # business and nobody else's. A bare file from v0.1.0 becomes a package here.
    database = project.resolve(project_path)
    migrate(database)

    # Bind before starting uvicorn, so the chosen port is knowable in time to be
    # announced. Letting uvicorn bind would mean the port only exists after the server
    # is already accepting requests nobody knows how to address.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    # Listen before announcing, not after. Binding alone does not accept connections,
    # so a client that dialled the moment it read the handshake was refused until
    # uvicorn got around to listening — a race wide enough to fail reliably on a Linux
    # runner and never once on this machine. With the socket listening, the kernel
    # queues the connection and uvicorn serves it when it starts.
    sock.listen(128)
    chosen = sock.getsockname()[1]

    token = secrets.token_urlsafe(32)
    handshake = {
        "port": chosen,
        "token": token,
        "pid": os.getpid(),
        "project": str(project_path),
    }
    sys.stdout.write(json.dumps(handshake) + "\n")
    sys.stdout.flush()

    threading.Thread(target=watch_parent, daemon=True).start()

    engine = create_project_engine(database)
    app = create_app(engine=engine, project_path=project_path, token=token, configure_logs=False)
    uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False)).run(sockets=[sock])


def main() -> None:
    parser = argparse.ArgumentParser(prog="tessera-engine", description=__doc__)
    parser.add_argument(
        "--project",
        type=Path,
        default=None,
        help="Project file to open. Created if it does not exist.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="0 lets the kernel choose, which is what the desktop application wants.",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    configure_logging(level=args.log_level)
    if args.host != "127.0.0.1":
        # Deliberately noisy. An institution's staffing and room data has no business
        # on a network interface, and this is the only way it gets there.
        logger.warning("binding_beyond_loopback", host=args.host)

    serve(args.project or default_project(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()

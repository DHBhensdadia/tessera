"""The HTTP surface.

Contract frozen in Phase 1.4 ahead of the handlers, so later phases plug into a known
shape and the client can be built against it. See docs/internals/api-contract.md.
"""

from tessera.api.app import create_app

__all__ = ["create_app"]

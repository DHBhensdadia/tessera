"""Measuring the solver against somebody else's published numbers.

**A leaf.** Nothing in `tessera/` imports this, and `import-linter` says so, because it exists
to hold one thing the product must never acquire: a formulation that is not Tessera's. CB-CTT
prices room capacity at a point per standing student where Tessera refuses the room outright
(#213), and a benchmark that quietly relaxed the product's invariants would be measuring
something nobody ships.

The split 4.5's D1 rests on: **the search is the product, the objective is the problem
statement.** Everything here is a problem statement. The Fix-and-Optimize loop that reads it is
the one in `tessera/solver/`, unchanged and unaware.
"""

from tessera.bench.cbctt import Competition

__all__ = ["Competition"]

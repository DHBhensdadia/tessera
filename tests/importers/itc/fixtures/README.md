# Vendored ITC-2019 instances

Two instances from the [International Timetabling Competition 2019](https://www.itc2019.org/),
unmodified, so the parser's tests need no 279 MiB download and no network.

| file | instance | why this one |
|---|---|---|
| `bet-sum18.xml` | Test Instance 3 | weeks that vary, classes needing no room, parent classes, eight distribution types |
| `pu-cs-fal07.xml` | Test Instance 4 | 2,002 students and travel times between rooms |

Between them every branch in `tessera/importers/itc/format.py` is taken. Neither alone is
enough — `bet-sum18` has no students and no travel times, `pu-cs-fal07` has no roomless
classes.

They are real competition files rather than constructed ones on purpose: an invented fixture
tests the parser against one reading of the format specification, and that reading is the part
most likely to be wrong.

The remaining 34 instances are read by the `benchmark` tests, which need the download —
see the repository README. `scripts/itc-instances.sha256` covers all 36, these two included.

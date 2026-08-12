# Student groups and the conflict relation

Who can be taught opposite whom. The single most consequential question in the data
model, because the solver builds one constraint per conflicting pair — a wrong answer is
either a clash it permits or a timetable it wrongly calls impossible.

## Two kinds of group, one rule

You schedule groups, not students. Groups nest: an intake of 120 splits into three lab
batches of 40, and a lecture for the whole intake clashes with anything scheduled for a
batch inside it. That much is a tree.

**Electives break the tree.** A module drawing students from three different intakes is
nobody's child; it cuts across. Modelling it as a tree node would be a lie.

So there are two kinds:

| | |
|---|---|
| `STRUCTURAL` | a node in the programme tree — a programme, an intake, a lab batch. Has a parent |
| `COHORT` | a cross-cutting set — an elective — that *names* its constituent groups |

Both then reduce to one rule:

> **Two groups conflict when their leaf sets intersect.**

Containment falls out of it rather than needing separate handling: an intake's leaves are
its lab batches, so intake and batch intersect automatically. Sibling batches do not,
which is what lets three labs run in parallel.

Resolution always bottoms out at structural groups. A cohort drawing from another cohort
is rejected at construction, because it would double-count the same students.

## Where the rules live — and why nowhere else

All of it is in [`tessera/domain/groups.py`](../../tessera/domain/groups.py): leaf
resolution, cycle rejection, `conflicts`, `conflict_map`, `headcount`.

**`repository/groups.py` contains none of it.** Every write builds the *prospective*
`GroupSet` — the world as it would be after the change — and lets the domain object:

```python
_validated([*_load_all(session), candidate])  # raises → 409
```

Re-parenting a group onto its own descendant is refused because `GroupSet.__init__`
rejects cycles, not because the repository re-derives the rule.

The obvious alternative is a recursive CTE. That would be a second implementation of the
hierarchy, in a second language, obliged to agree with the first forever — and the two
would drift, silently, because nothing checks them against each other.

`test_the_repository_does_not_reimplement_the_hierarchy` parses the repository's AST and
fails if `cte()` or `union_all()` appears. *(The first version grepped for the word
"recursive" and tripped on the docstring explaining why there is no recursive query. A
guard that fires on its own documentation gets deleted rather than heeded.)*

Cost: O(groups) per write. Hundreds of rows.

## Two sizes, and they differ

| | |
|---|---|
| `size` | what the user typed — this group's own students |
| `headcount` | what the solver must seat |

`headcount` falls back to the **sum of the leaves** when a group's own size is zero,
because a parent left at zero almost always means "nobody filled this in" rather than
"this intake has no students". An intake with three labs of 40 reports `size: 0,
headcount: 120`.

Both are returned. Returning only one would look like a simplification and would quietly
break either editing or capacity checking.

## The tree endpoint

`GET /student-groups/tree` returns the hierarchy already resolved, so the client never
rebuilds the parent/child rules — a second implementation is a second place for them to
be wrong.

**Cohorts appear as additional roots with no children**, distinguished by `kind`. They
have no parent by definition, and omitting them would hide exactly the groups most
likely to cause conflicts. The interface renders them in their own section (P7 Act 5).

## Deletion refuses rather than cascading

`student_group.parent_id` is `ON DELETE CASCADE`. Left alone, deleting an intake would
silently take its three lab batches, and deleting a programme root would take the entire
tree.

So the repository refuses while anything hangs off a group, naming the counts:

```
"2024 CSE still has dependants" → {"sub_groups": 3}
```

Blocked by sub-groups, by cohorts drawing from it, or by sessions it attends. The user
deletes bottom-up, which is explicit.

**The cascade stays as a backstop**, not as a feature: its job is preventing dangling
rows if something ever bypasses this module, not performing the deletion.

Programmes behave the same way — refused while groups belong to them, even though
`program_id` is `SET NULL` and they would technically survive. An intake with no
programme is meaningless, and silently producing a pile of them is worse than making the
caller detach them first.

## Verified by properties, not examples

`tests/domain/test_groups_properties.py` runs seven invariants over **250 randomly
generated hierarchies each** — varying depth, branching, and which groups an elective
draws from.

Example-based tests can only assert what someone thought to write down. The space of
tree shapes is large, the relation must hold across all of it, and this is the phase
Hypothesis was chosen for.

"""Constraints over HTTP.

The rules live in `tests/domain/test_constraints.py` and the storage in
`tests/repository/test_constraints.py`. What only appears at the edge is the contract
extension: a target set that the 1.4 surface could not express, alongside the session-only
spelling it froze, and the refusal to accept both at once.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tessera.domain.constraints import INVARIANTS, SPECS, ConstraintKind, TargetKind
from tessera.repository import calendar as calendar_repo
from tessera.repository import create_all, session_factory
from tessera.repository import models as m


@pytest.fixture
def project(engine: Engine) -> dict[str, int]:
    """A term made through the repository, so it arrives with its default preferences."""
    create_all(engine)
    with session_factory(engine)() as db:
        institution = m.Institution(name="Test University")
        db.add(institution)
        db.flush()
        grid = m.TimeGrid(
            institution_id=institution.id,
            days=5,
            slots_per_day=10,
            slot_minutes=60,
            day_start_minute=540,
        )
        shah = m.Instructor(name="Prof. Shah")
        db.add_all([grid, shah])
        db.flush()
        term = calendar_repo.create_term(
            db,
            institution_id=institution.id,
            time_grid_id=grid.id,
            academic_year="2026-27",
            name="Autumn",
        )
        db.commit()
        return {"term_id": int(term.id or 0), "instructor_id": int(shah.id)}


class TestTheContractExtension:
    def test_a_constraint_can_name_an_instructor(
        self, client: TestClient, project: dict[str, int]
    ) -> None:
        """The interaction the 1.4 surface could describe and not express."""
        response = client.post(
            f"/api/v1/terms/{project['term_id']}/constraints",
            json={
                "kind": "limit_consecutive_slots",
                "targets": [{"kind": "instructor", "id": project["instructor_id"]}],
                "params": {"slots": 3},
                "is_hard": True,
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["targets"] == [{"kind": "instructor", "id": project["instructor_id"]}]
        # Not "everyone": a rule about one person that says everyone is worse than one
        # that says nothing. Names need the database, which the console has and the wire
        # response does not, so ids are the honest fallback.
        assert body["summary"] == "Give instructor 1 at most 3 hour(s) in a row"
        assert body["target_ids"] == []

    def test_target_ids_still_works_and_still_means_sessions(
        self, client: TestClient, project: dict[str, int]
    ) -> None:
        """A 1.4 consumer keeps working unchanged, which is why the field survives."""
        response = client.post(
            f"/api/v1/terms/{project['term_id']}/constraints",
            json={"kind": "same_room", "target_ids": [1]},
        )
        assert response.status_code == 422, response.text
        assert "targets[session]" in response.text

    def test_sending_both_spellings_is_refused(
        self, client: TestClient, project: dict[str, int]
    ) -> None:
        """Merging them would make "clear the targets" ambiguous under PATCH."""
        response = client.post(
            f"/api/v1/terms/{project['term_id']}/constraints",
            json={
                "kind": "same_room",
                "target_ids": [1],
                "targets": [{"kind": "session", "id": 1}],
            },
        )
        assert response.status_code == 422
        assert "not both" in response.text

    def test_a_scope_is_reported_for_every_constraint(
        self, client: TestClient, project: dict[str, int]
    ) -> None:
        listed = client.get(f"/api/v1/terms/{project['term_id']}/constraints").json()
        assert {item["scope"] for item in listed["items"]} == {"global"}


class TestTheDefaultsAreThere:
    def test_a_new_term_lists_seven_preferences(
        self, client: TestClient, project: dict[str, int]
    ) -> None:
        listed = client.get(f"/api/v1/terms/{project['term_id']}/constraints").json()
        assert listed["total"] == 7

    def test_each_one_arrives_with_a_sentence(
        self, client: TestClient, project: dict[str, int]
    ) -> None:
        """The console renders this rather than composing its own copy of the rule."""
        listed = client.get(f"/api/v1/terms/{project['term_id']}/constraints").json()
        for item in listed["items"]:
            assert item["summary"] and "{" not in item["summary"]


class TestRetuning:
    def test_the_weight_slider_writes_here(
        self, client: TestClient, project: dict[str, int]
    ) -> None:
        listed = client.get(f"/api/v1/terms/{project['term_id']}/constraints").json()
        first = listed["items"][0]

        response = client.patch(f"/api/v1/constraints/{first['id']}", json={"weight": 20})
        assert response.status_code == 200, response.text
        assert response.json()["weight"] == 20

    def test_a_field_left_out_is_left_alone(
        self, client: TestClient, project: dict[str, int]
    ) -> None:
        listed = client.get(f"/api/v1/terms/{project['term_id']}/constraints").json()
        first = listed["items"][0]

        updated = client.patch(f"/api/v1/constraints/{first['id']}", json={"enabled": False})
        assert updated.json()["weight"] == first["weight"]
        assert updated.json()["enabled"] is False

    def test_narrowing_a_preference_to_one_person(
        self, client: TestClient, project: dict[str, int]
    ) -> None:
        listed = client.get(f"/api/v1/terms/{project['term_id']}/constraints").json()
        gaps = next(item for item in listed["items"] if item["kind"] == "minimise_instructor_gaps")

        response = client.patch(
            f"/api/v1/constraints/{gaps['id']}",
            json={"targets": [{"kind": "instructor", "id": project["instructor_id"]}]},
        )
        assert response.status_code == 200, response.text
        assert response.json()["targets"] == [
            {"kind": "instructor", "id": project["instructor_id"]}
        ]

    def test_a_rule_that_does_not_exist(self, client: TestClient, project: dict[str, int]) -> None:
        assert client.patch("/api/v1/constraints/999", json={"weight": 2}).status_code == 404


class TestRemoving:
    def test_a_preference_can_be_withdrawn(
        self, client: TestClient, project: dict[str, int]
    ) -> None:
        listed = client.get(f"/api/v1/terms/{project['term_id']}/constraints").json()
        first = listed["items"][0]

        assert client.delete(f"/api/v1/constraints/{first['id']}").status_code == 204
        after = client.get(f"/api/v1/terms/{project['term_id']}/constraints").json()
        assert after["total"] == 6

    def test_deleting_one_that_is_gone(self, client: TestClient, project: dict[str, int]) -> None:
        assert client.delete("/api/v1/constraints/999").status_code == 404


class TestRefusals:
    def test_a_kind_may_not_target_what_it_is_not_about(
        self, client: TestClient, project: dict[str, int]
    ) -> None:
        response = client.post(
            f"/api/v1/terms/{project['term_id']}/constraints",
            json={
                "kind": "same_room",
                "targets": [{"kind": "instructor", "id": project["instructor_id"]}],
            },
        )
        assert response.status_code == 422
        assert "applies to session" in response.text

    def test_a_missing_parameter_is_named(
        self, client: TestClient, project: dict[str, int]
    ) -> None:
        response = client.post(
            f"/api/v1/terms/{project['term_id']}/constraints",
            json={
                "kind": "limit_consecutive_slots",
                "targets": [{"kind": "instructor", "id": project["instructor_id"]}],
            },
        )
        assert response.status_code == 422
        assert "slots" in response.text

    def test_a_term_that_does_not_exist(self, client: TestClient, project: dict[str, int]) -> None:
        response = client.get("/api/v1/terms/999/constraints")
        assert response.status_code == 404


class TestAvailabilityCarriesItsStrength:
    def test_an_hour_someone_would_rather_not_teach(
        self, client: TestClient, project: dict[str, int]
    ) -> None:
        """Decision #78: the grid is three-state, and this is where the middle one lands."""
        response = client.post(
            f"/api/v1/terms/{project['term_id']}/unavailability",
            json={
                "kind": "instructor",
                "subject_id": project["instructor_id"],
                "slots": [34],
                "reason": "Friday afternoon",
                "is_hard": False,
                "weight": 5,
            },
        )
        assert response.status_code == 201, response.text
        blocked = response.json()["items"][0]
        assert blocked["is_hard"] is False
        assert blocked["weight"] == 5

    def test_an_hour_blocked_the_old_way_is_still_a_refusal(
        self, client: TestClient, project: dict[str, int]
    ) -> None:
        """Every caller written before 2.8 sends neither field and must not change."""
        response = client.post(
            f"/api/v1/terms/{project['term_id']}/unavailability",
            json={"kind": "instructor", "subject_id": project["instructor_id"], "slots": [12]},
        )
        assert response.json()["items"][0]["is_hard"] is True


class TestTheCatalogue:
    """That what the engine publishes about constraints is what the domain actually holds.

    `SPECS` lives in `tessera.domain.constraints` and the console reads it by importing it,
    which works only because the console runs inside the engine. A native client had no way
    to learn which kinds exist, what each may be attached to, or what parameters it takes —
    so it could not offer to create a constraint without a hand-written copy of `SPECS` in
    Swift, which is what Decision #5 forbids and what `ConstraintSpec` warns about in its
    own docstring.

    The catalogue is derived from `SPECS` rather than restated, so these tests are not
    checking a transcription. They are checking that the derivation stays total — that a
    kind added to the domain appears on the wire without anybody remembering to add it, and
    that nothing on the wire says something the domain does not.
    """

    def test_every_kind_is_published_exactly_once(self, client: TestClient) -> None:
        body = client.get("/api/v1/constraint-catalogue").json()
        published = [k["kind"] for k in body["kinds"]]

        assert sorted(published) == sorted(k.value for k in ConstraintKind)
        assert len(published) == len(set(published))

    def test_each_kind_carries_what_the_domain_says_about_it(self, client: TestClient) -> None:
        body = client.get("/api/v1/constraint-catalogue").json()

        for entry in body["kinds"]:
            spec = SPECS[ConstraintKind(entry["kind"])]
            assert entry["scope"] == spec.scope.value
            assert sorted(entry["targets"]) == sorted(t.value for t in spec.targets)
            assert entry["summary_template"] == spec.summary
            assert entry["unnarrowed"] == spec.unnarrowed

            published = {p["name"]: p for p in entry["params"]}
            assert published.keys() == spec.params.keys()
            for name, param in spec.params.items():
                assert published[name]["label"] == param.label
                assert published[name]["minimum"] == param.minimum
                assert published[name]["maximum"] == param.maximum
                assert published[name]["default"] == param.default

    def test_placeholders_are_bare_so_a_client_can_fill_them_in(self, client: TestClient) -> None:
        """The promise the summary template makes, enforced where the templates live.

        A client renders the sentence as a form is typed — asking the engine per keystroke
        would be absurd — so it substitutes the placeholders itself. That is only safe while
        every placeholder is a bare `{name}`: a format spec like `{slots:>3}` would need a
        second implementation of Python's format mini-language in Swift, and would be
        discovered as a rendering bug rather than as a contract change.

        So the constraint is stated here rather than assumed there.
        """
        import re

        body = client.get("/api/v1/constraint-catalogue").json()

        for entry in body["kinds"]:
            placeholders = set(re.findall(r"\{([^}]*)\}", entry["summary_template"]))
            allowed = {p["name"] for p in entry["params"]} | {"targets"}

            assert placeholders <= allowed, (
                f"{entry['kind']} names {placeholders - allowed} in its summary, which is "
                "neither one of its parameters nor 'targets'"
            )
            for placeholder in placeholders:
                assert re.fullmatch(r"\w+", placeholder), (
                    f"{entry['kind']} uses a format spec in {{{placeholder}}} — a client "
                    "fills these in by name and cannot interpret one"
                )

    def test_the_example_is_the_template_filled_in(self, client: TestClient) -> None:
        """A menu of sixteen kinds is unreadable as templates, so each carries a rendering."""
        body = client.get("/api/v1/constraint-catalogue").json()

        for entry in body["kinds"]:
            spec = SPECS[ConstraintKind(entry["kind"])]
            assert entry["example"] == spec.describe({}, "…")
            assert "{" not in entry["example"]

    def test_the_invariants_are_published_and_none_of_them_is_a_kind(
        self, client: TestClient
    ) -> None:
        """The rules that cannot be switched off, and the line between the two lists.

        An invariant appearing as a configurable kind would be the worst possible bug on
        this screen: a control offering to disable something that cannot be disabled.
        """
        body = client.get("/api/v1/constraint-catalogue").json()

        assert [i["key"] for i in body["invariants"]] == [i.key for i in INVARIANTS]
        assert all(i["statement"] and i["because"] for i in body["invariants"])

        keys = {i["key"] for i in body["invariants"]}
        kinds = {k["kind"] for k in body["kinds"]}
        assert not keys & kinds

    def test_it_needs_no_project_and_no_term(self, client: TestClient) -> None:
        """It describes the build, not the file — so it answers before anything is set up,
        and a client can fetch it once per engine and keep it."""
        assert client.get("/api/v1/constraint-catalogue").status_code == 200

    def test_an_unnarrowed_rule_says_what_it_applies_to(self, client: TestClient) -> None:
        """The fallback word is per kind, and "everyone" is wrong for two of them.

        `unnarrowed` defaulted to "everyone" for every kind, which reads correctly for the
        five about people and groups and produced "Avoid teaching everyone twice in one day"
        for the one about courses. It has been on the console page since 2.5 and on the wire
        since 2.8; nothing displayed the sentence beside the rule it describes until the
        native screen did.

        So: no global kind may describe itself as applying to people when it can only be
        attached to courses.
        """
        body = client.get("/api/v1/constraint-catalogue").json()

        for entry in body["kinds"]:
            if entry["scope"] != "global":
                continue
            spec = SPECS[ConstraintKind(entry["kind"])]
            rendered = spec.describe({})

            assert "{" not in rendered
            if spec.targets == {TargetKind.COURSE}:
                assert "everyone" not in rendered, (
                    f"{entry['kind']} may only be attached to courses and describes itself "
                    f"as applying to people: {rendered!r}"
                )

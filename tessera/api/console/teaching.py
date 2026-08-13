"""The catalogue, and what a term does with it.

Three pages that mirror the three-level split rather than flattening it:

* **Courses** — the catalogue, which outlives every term
* **A term** — which courses are offered in it
* **An offering** — its weekly pattern, and the sessions that pattern generates

The last one is the page the whole product is about. "3 lectures + 1 lab split three
ways" is what a timetabler actually knows, and *expand* is where that becomes the six
blocks a solver can place. Showing the count next to the pattern is what makes the model
explain itself without documentation.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Form, Request, Response
from fastapi.responses import HTMLResponse

from tessera.api.console.base import describe, page, redirect, router
from tessera.api.deps import Db
from tessera.domain.entities import SessionKind
from tessera.repository import calendar as calendar_repo
from tessera.repository import expansion
from tessera.repository import groups as groups_repo
from tessera.repository import models as m
from tessera.repository import sessions as sessions_repo
from tessera.repository import structure as structure_repo
from tessera.repository import teaching as repo
from tessera.repository.errors import RepositoryError


@dataclass(frozen=True)
class CourseRow:
    id: int
    code: str
    name: str
    credits: int
    department: str


def _render_courses(
    request: Request, db: Db, *, problem: str | None = None, **extra: object
) -> HTMLResponse:
    departments = {int(d.id or 0): d.name for d in structure_repo.list_departments(db)}
    rows = [
        CourseRow(
            id=int(course.id or 0),
            code=course.code,
            name=course.name,
            credits=course.credits,
            department=departments.get(int(course.department_id or 0), "—"),
        )
        for course in repo.list_courses(db)
    ]
    return page(
        request,
        "teaching/courses.html",
        courses=rows,
        departments=structure_repo.list_departments(db),
        problem=problem,
        **extra,
    )


@router.get("/courses", include_in_schema=False)
def list_courses(request: Request, db: Db) -> HTMLResponse:
    return _render_courses(request, db)


@router.post("/courses", include_in_schema=False)
def create_course(
    request: Request,
    db: Db,
    code: str = Form(...),
    name: str = Form(...),
    credits: int = Form(0),
    department_id: str = Form(""),
) -> Response:
    try:
        repo.create_course(
            db,
            code=code,
            name=name,
            credits=credits,
            department_id=int(department_id) if department_id else None,
        )
    except RepositoryError as error:
        return _render_courses(
            request, db, problem=describe(error), submitted={"code": code, "name": name}
        )
    return redirect("/console/courses")


@router.post("/courses/{course_id}/delete", include_in_schema=False)
def delete_course(request: Request, db: Db, course_id: int) -> Response:
    try:
        repo.delete_course(db, course_id)
    except RepositoryError as error:
        return _render_courses(request, db, problem=describe(error))
    return redirect("/console/courses")


# -- one term, and what it offers ----------------------------------------------


def _render_term(
    request: Request, db: Db, term_id: int, *, problem: str | None = None
) -> HTMLResponse:
    term = calendar_repo.get_term(db, term_id)
    offered = calendar_repo.list_offerings(db, term_id=term_id)
    courses = {int(c.id or 0): c for c in repo.list_courses(db)}
    rows = [
        {
            "id": int(o.id or 0),
            "label": f"{courses[int(o.course_id or 0)].code} {courses[int(o.course_id or 0)].name}",
            "sessions": calendar_repo.session_count(db, int(o.id or 0)),
        }
        for o in offered
        if int(o.course_id or 0) in courses
    ]
    return page(
        request,
        "teaching/term.html",
        term=term,
        offerings=rows,
        available=[
            c
            for c in courses.values()
            if int(c.id or 0) not in {int(o.course_id or 0) for o in offered}
        ],
        problem=problem,
    )


@router.get("/terms/{term_id}/offerings", include_in_schema=False)
def term_detail(request: Request, db: Db, term_id: int) -> HTMLResponse:
    return _render_term(request, db, term_id)


@router.post("/terms/{term_id}/offerings", include_in_schema=False)
def offer_course(request: Request, db: Db, term_id: int, course_id: int = Form(...)) -> Response:
    try:
        calendar_repo.create_offering(db, term_id=term_id, course_id=course_id)
    except RepositoryError as error:
        return _render_term(request, db, term_id, problem=describe(error))
    return redirect(f"/console/terms/{term_id}/offerings")


@router.post("/offerings/{offering_id}/delete", include_in_schema=False)
def withdraw_offering(request: Request, db: Db, offering_id: int) -> Response:
    offering = calendar_repo.get_offering(db, offering_id)
    term_id = int(offering.term_id or 0)
    try:
        calendar_repo.delete_offering(db, offering_id)
    except RepositoryError as error:
        return _render_term(request, db, term_id, problem=describe(error))
    return redirect(f"/console/terms/{term_id}/offerings")


# -- one offering: the weekly pattern, and what it expands to -------------------


def _render_offering(
    request: Request, db: Db, offering_id: int, *, problem: str | None = None
) -> HTMLResponse:
    offering = calendar_repo.get_offering(db, offering_id)
    course = repo.get_course(db, int(offering.course_id or 0))
    term = calendar_repo.get_term(db, int(offering.term_id or 0))

    known = groups_repo.group_set(db)
    names = {int(g.id or 0): g.name for g in known.all}
    instructors = {int(i.id or 0): i.name for i in db.query(m.Instructor).all()}
    features = {int(f.id or 0): f.name for f in structure_repo.list_features(db)}

    patterns = [
        {
            "id": int(t.id or 0),
            "kind": t.kind.value,
            "per_week": t.per_week,
            "duration_slots": t.duration_slots,
            "split": t.split_per_attendee,
            "attendees": ", ".join(sorted(names.get(int(a), "?") for a in t.attendee_ids)),
            "instructors": ", ".join(sorted(instructors.get(int(i), "?") for i in t.instructor_ids))
            or "—",
            "features": ", ".join(sorted(features.get(int(f), "?") for f in t.required_features))
            or "—",
            # What it *would* produce, from the domain. The generated count next to it is
            # what it has produced — the two differing is exactly what expand reconciles.
            "expects": t.session_count,
            "generated": sessions_repo.template_session_count(db, int(t.id or 0)),
        }
        for t in sessions_repo.list_templates(db, offering_id=offering_id)
    ]

    blocks = [
        {
            "kind": s.kind.value,
            "occurrence": s.occurrence + 1,
            "duration_slots": s.duration_slots,
            "attendees": ", ".join(sorted(names.get(int(a), "?") for a in s.attendee_ids)),
            "headcount": sessions_repo.headcount_of(db, sorted(s.attendee_ids)),
        }
        for s in sessions_repo.list_sessions(
            db, term_id=int(offering.term_id or 0), offering_id=offering_id
        )
    ]

    return page(
        request,
        "teaching/offering.html",
        offering=offering,
        course=course,
        term=term,
        patterns=patterns,
        sessions=blocks,
        groups=sorted(known.all, key=lambda g: g.name),
        instructors=sorted(instructors.items(), key=lambda kv: kv[1]),
        features=structure_repo.list_features(db),
        kinds=[k.value for k in SessionKind],
        problem=problem,
    )


@router.get("/offerings/{offering_id}/templates", include_in_schema=False)
def offering_detail(request: Request, db: Db, offering_id: int) -> HTMLResponse:
    return _render_offering(request, db, offering_id)


@router.post("/offerings/{offering_id}/templates", include_in_schema=False)
def add_pattern(
    request: Request,
    db: Db,
    offering_id: int,
    kind: str = Form("lecture"),
    duration_slots: int = Form(...),
    per_week: int = Form(...),
    split_per_attendee: bool = Form(False),
    attendee_ids: list[int] | None = Form(None),
    instructor_ids: list[int] | None = Form(None),
    required_feature_ids: list[int] | None = Form(None),
) -> Response:
    try:
        sessions_repo.create_template(
            db,
            offering_id=offering_id,
            kind=SessionKind(kind),
            duration_slots=duration_slots,
            per_week=per_week,
            split_per_attendee=split_per_attendee,
            attendee_ids=attendee_ids or [],
            instructor_ids=instructor_ids or [],
            required_feature_ids=required_feature_ids or [],
        )
    except RepositoryError as error:
        return _render_offering(request, db, offering_id, problem=describe(error))
    return redirect(f"/console/offerings/{offering_id}/templates")


@router.post("/templates/{template_id}/repeat", include_in_schema=False)
def set_repeats(request: Request, db: Db, template_id: int, per_week: int = Form(...)) -> Response:
    """Change how many of a component there are per week.

    Nothing happens to the sessions until *expand* is pressed — which is the point.
    Separating the edit from the reconciliation is what lets someone see what a change
    would cost before paying for it.
    """
    template = sessions_repo.get_template(db, template_id)
    offering_id = int(template.offering_id or 0)
    try:
        sessions_repo.update_template(db, template_id, changes={"per_week": per_week})
    except RepositoryError as error:
        return _render_offering(request, db, offering_id, problem=describe(error))
    return redirect(f"/console/offerings/{offering_id}/templates")


@router.post("/templates/{template_id}/delete", include_in_schema=False)
def remove_pattern(request: Request, db: Db, template_id: int) -> Response:
    template = sessions_repo.get_template(db, template_id)
    offering_id = int(template.offering_id or 0)
    try:
        sessions_repo.delete_template(db, template_id)
    except RepositoryError as error:
        return _render_offering(request, db, offering_id, problem=describe(error))
    return redirect(f"/console/offerings/{offering_id}/templates")


@router.post("/offerings/{offering_id}/expand", include_in_schema=False)
def expand_offering(request: Request, db: Db, offering_id: int) -> Response:
    """Reconcile the sessions against the pattern.

    Safe to press twice: it adds what is missing, removes what is no longer wanted, and
    leaves everything else alone. It refuses outright rather than removing a session
    somebody has already placed in a timetable.
    """
    try:
        expansion.expand(db, offering_id)
    except RepositoryError as error:
        return _render_offering(request, db, offering_id, problem=describe(error))
    return redirect(f"/console/offerings/{offering_id}/templates")

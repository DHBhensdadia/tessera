"""Timetable generation: a CP-SAT model driven by a Fix-and-Optimize search.

Feasibility and optimisation are separate phases. Finding *a* valid timetable is fast;
finding a good one is not, and the outer search is what closes that gap (ADR-002).
"""

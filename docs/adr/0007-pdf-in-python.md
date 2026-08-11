# ADR-0007: Generate PDFs in Python with ReportLab, not native PDFKit

**Status:** Accepted · **Date:** 2026-08-07

## Context

macOS has excellent native PDF generation. Using it would mean the exporter only works
inside the macOS app, cannot be tested in CI without a Mac, and does not exist for
Docker or CLI users.

WeasyPrint would allow HTML/CSS layout but depends on Pango, cairo and GDK-PixBuf,
which are not pip-installable and make PyInstaller bundling fragile.

## Decision

Generate PDFs in the engine with **ReportLab**, whose table layout suits grid reports
and which has effectively no native dependencies.

## Consequences

- All three deployments export PDFs from one implementation.
- Export is testable in CI on Linux.
- Page layout is built programmatically rather than in CSS, which is more work for
  complex designs.
- This reverses an earlier inclination toward PDFKit, taken before the sidecar
  architecture made a Python-side exporter obviously better.

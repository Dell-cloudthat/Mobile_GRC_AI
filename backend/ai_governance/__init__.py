"""
Shadow AI governance — v1.

Discovers which AI apps a client's people use, scores the risk of each one,
explains what it is and why the team is probably using it, and records the
business's decision (approve, move to a business plan, block, accept risk).

Modules:
  catalog     — curated AI app knowledge (ai_apps.json): what it is, data
                handling by plan, matching keys, likely business reasons.
  matcher     — turns a raw app name / domain / Entra app ID into a catalog app.
  importers   — CSV import (Entra, Defender for Cloud Apps, generic exports).
  observations— merges discovery records into one observation per app.
  risk        — explainable 0–100 risk score from catalog facts + evidence.
  intel       — product intelligence: likely use by department, alternatives,
                recommended action, MSP opportunity.
"""

# Shadow AI (v1)

SecurityOS finds the AI tools a client's people use, scores the risk of each,
explains what it is and why the team is probably using it, and records the
executive's decision. MSPs get a rollup across clients with the service
conversations each pattern points to.

## Where things live

| Piece | Location |
|---|---|
| AI app catalog (what each app is, data terms by plan, matching keys) | `backend/ai_governance/ai_apps.json` |
| Matching, CSV import, risk score, intelligence | `backend/ai_governance/` |
| API | `backend/api/ai_usage.py` |
| Microsoft 365 scanner | `backend/integrations/m365_ai_discovery.py` |
| Database tables (migration 0002) | `ai_app_observations` (current state), `ai_app_decisions` (append-only) |
| Screens | `apps/web/src/views/securityos/ai/` |
| Demo data (generated) | `apps/web/src/data/aiDemo.json` ← `python -m backend.scripts.build_ai_demo` |

## Getting data in

Upload a CSV on the client's **AI** tab (admin, engineer or MSP technician).
Columns are recognised by name; only an app name **or** domain column is
required. User and department columns make the "why they use it" much better.

Works with:
- the SecurityOS Microsoft 365 scanner (below), the most complete source
- Entra admin center → Enterprise applications → Download
- Defender for Cloud Apps → Cloud discovery → Discovered apps → Export
- firewall / DNS filter exports of domains visited

Non-AI apps are skipped. Unknown apps that look like AI ("AI Meeting Notes Pro")
are kept as *possible AI apps* and scored as untrusted until reviewed.

## Microsoft 365 scanner

Read-only. Lists every third-party app people signed into with their work
account, who consented, their department and the permissions granted.

1. In the client tenant (or as a multi-tenant app with admin consent), register
   an app and grant these Microsoft Graph **application** permissions, then
   grant admin consent:
   - `DelegatedPermissionGrant.Read.All`
   - `Application.Read.All`
   - `User.Read.All`
2. Create a client secret.
3. Run:
   ```bash
   export M365_CLIENT_SECRET='...'
   python -m backend.integrations.m365_ai_discovery \
     --tenant-id contoso.onmicrosoft.com --client-id <app id> --out contoso-ai.csv
   ```
4. Upload `contoso-ai.csv` on the client's AI tab.

v1 deliberately stores no client secrets. A scheduled scan with secrets in
Azure Key Vault comes with the Microsoft 365 integration step of the roadmap.

## Risk score

0–100, higher is riskier. Every point is a named factor shown on screen:
data used for training (by plan), admin controls, business plan available,
data jurisdiction, SOC 2, real Microsoft 365 permissions granted (or the
category's typical exposure when we have no permissions data), number of users,
and the client's regulated data (PHI, card data, CMMC...). Unknown facts score
as a gap, never as safe.

Apps are scored as the free/personal plan by default because we can't see
billing. Approving the business plan rescores against it. Microsoft 365
Copilot Chat and Gemini seen through a work-account consent are scored as
the business version.

Levels: critical ≥ 70, high ≥ 50, medium ≥ 30, low below that.

## Decisions (executive only)

| Decision | Rule |
|---|---|
| Approve business plan | Only for apps with a business plan; rescores the app |
| Approve as used | High/critical apps need a 20+ character reason |
| Block | Then revoke consent; if it appears in a later import it's flagged "still in use" |
| Accept risk | Reason (20+ chars) and end date required: ≤ 90 days for critical, ≤ 365 otherwise |
| Under review | Marks it as being looked at |

Every import and decision is written to the org's hash-chained audit log.
Decision history can't be edited (database triggers block UPDATE and DELETE).

## Keeping the catalog accurate

Vendor terms change. When editing `ai_apps.json`:
- use `"unknown"` / `null` when you haven't verified a fact; the score treats it as a gap
- update `reviewed_at`
- run `python -m backend.scripts.build_ai_demo` and `pytest backend/tests/test_shadow_ai.py`

Priority for the next review: confirm the `unknown` training terms for the
meeting notetakers (Read AI, Fathom, tl;dv, Granola), since they score high.

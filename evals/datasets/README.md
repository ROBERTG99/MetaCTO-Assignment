# Eval datasets

Each line in a `.jsonl` file is one case: a new incoming request, judged against the seeded Brightboard backlog (`backlog: "seed_v1"` = the 17 needs and 62 requests in `backend/seed/`). The schema is `case.schema.json`.

| File | What | Status |
|---|---|---|
| `test_handwritten.jsonl` | Robert's hard cases (`H001`...), `reviewed_by_human: true`. The pattern for the generated hard cases. | waiting for cases |
| `test.jsonl` | About 150 cases: the handwritten ones plus generated ones (`T001`..., `reviewed_by_human: false`). Frozen. | after the handwritten cases |
| `FROZEN` | SHA-256 of `test.jsonl`. The runner refuses to run if they disagree. | after test.jsonl |
| dev | Not a file: the seed stream replayed in arrival order, scored against `ground_truth.json`. | |

**Label rule:** same need = same problem for the same persona or job, whatever the solution. `expected.need: null` means a new need.

**Need ids:** alerts, audit_log, chart_comments, csv_import, dark_mode, data_portability, embedded, excel_finance, localization, mobile, onboarding_templates, performance, permissions, scim, share_kpis, snowflake, sso.

**Personas** (from the seed): account_manager, analyst, cs_leader, data_engineer, end_user, exec, finance, it_admin, ops_manager, product_manager, security_compliance, smb_owner, team_lead.

**Example line** (one line per case in the file; shown wrapped here):

```json
{"id": "H001", "slice": "same_solution_different_need", "backlog": "seed_v1",
 "request": {"title": "Export the KPI table to Excel", "description": "Our auditors want every month's revenue table as .xlsx so they can tick the numbers.", "requester_role": "Group Financial Controller", "segment": "enterprise", "source": "portal"},
 "expected": {"need": "excel_finance", "persona": "finance", "must_not_link": ["data_portability"]},
 "rationale": "Excel for a finance review pack, not for leaving or backing up.", "author": "robert", "reviewed_by_human": true}
```

# Dummy data for manual frontend testing — Target flow

Three CSVs (all verified to import with zero errors) + the script that regenerates them.
World: the current `seed_haleon` dev DB. **Node ids change on every re-seed** — after
`seed_haleon --reset`, regenerate before uploading:

```powershell
cd backend
venv\Scripts\python.exe manage.py shell -c "exec(open(r'..\dummy_data\generate_dummy_data.py', encoding='utf-8').read())"
```

| File | What's in it | Where it goes |
|---|---|---|
| `sales_history_aug2025.csv` | 128 sale rows dated **Aug 2025** across the 6 GT towns + 2 MT districts, 4 SKUs, deliberately uneven per territory | UI: **KPIs → Sales Data → Import** |
| `sales_actuals_jul2026.csv` | 61 rows dated **Jul 1–16, 2026**: town sales, one row per partner outlet, and one **return** | UI: **KPIs → Sales Data → Import** |
| `sales_actuals_aug2026.csv` | 114 rows dated **Aug 2026** (towns + MT districts) — the actuals behind the August targets | UI: **KPIs → Sales Data → Import** |
| `targets_aug2026_india.csv` | 3 plan-less **India-level** targets (`FY2026-M08`: CORE_VALUE 600000, FOCUS_NPI_VALUE 150000, EC_OVERALL 60) | API only — no UI screen (below) |

All rows use `source=manual_entry` and `DUMMY-…` external refs — re-uploading the same file
is a harmless idempotent upsert, and everything is deletable by that prefix.

---

## Test flow A — full plan lifecycle (August 2026)

The Aug-2025 history is the fuel: it drives the baseline suggestion and the
contribution-based territory split for a **new August 2026 plan**.

1. **Upload** `sales_history_aug2025.csv` (KPIs → Sales Data → Import). Expect 128 ok.
2. **Targets → New plan** (wizard): Scope = name "Aug 2026 Test Plan", plan year FY 2026-27,
   month **Aug 2026**, top territory **India**, grain *town*. KPIs = **Core Value** with the
   `HAL_VALUE_SPLIT` recipe + baseline *Last year, same period*. Step 3: pick
   review level **region** if you want the cascade, and optionally a small **payout budget**
   (e.g. 25000) to see the over-budget publish dialog. Create.
3. **Top numbers stage** → **Calculate suggestion** → a suggested top appears (≈ the Aug-2025
   total × growth). Type your own number (e.g. 600000), Save.
4. **Territory split stage** → **Generate split** → review the staged diff in the panel
   (shares should be *uneven* — Whitefield weighs more than Karol Bagh by construction) →
   **Apply to plan**. Check the grid: ⓘ explain on any row shows the blend.
5. Edit one town's number with the pencil (within/beyond the change cap to see
   auto-approve vs escalate), re-generate the split → the **keep or replace** collision
   panel appears.
6. **Field review stage** → Send for review → log in as an RSM (`rsm.north@haleon.com`,
   password from the seed cheat sheet) to accept/adjust from the reviewer screen → back as
   admin: Send a reminder / Close remaining reviews.
7. **Publish stage** → gate checklist → Publish (over-budget dialog if you set a tiny
   budget → "Publish anyway", audited).
8. Actuals: upload `sales_actuals_aug2026.csv` now (KPIs → Sales Data → Import; 114 ok) —
   the rows sit ready, but **achievement compute clips at today's date**, so August
   actuals appear once August starts (Run compute on the Actuals tab then, or let the
   nightly job pick them up). For a same-day actuals loop use flow B.

## Test flow B — actuals moving this month (July 2026)

July already has a published plan (the seeded AOP) and sales. This file adds more.

1. Note the current numbers: plan **Jul 2026 AOP** → Actuals tab (Core Value).
2. **Upload** `sales_actuals_jul2026.csv`. Expect 61 ok.
3. On the Actuals tab press **Run compute** → actuals/achievement % rise, and the
   Karol Bagh **return** row subtracts from value.
4. Achievement dashboard (OPERATIONS → Achievement) shows the same movement per person.

## Test flow C — plan-less India-level targets (API)

There is no UI screen for allocation CSVs — push it with PowerShell:

```powershell
$login = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/auth/login/" -Method Post -ContentType "application/json" -Body '{"identifier":"admin@thriive.com","password":"Admin@1234"}'
$tok = $login.data.tokens.access; if (-not $tok) { $tok = $login.access }
$body = @{ data = (Get-Content D:\thriive\dummy_data\targets_aug2026_india.csv -Raw) } | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/targets/allocations/bulk/" -Method Post -ContentType "application/json" -Headers @{Authorization="Bearer $tok"} -Body $body
```

Expect `created: 3` — the AOP trio at the India root, live immediately (plan-less rows).
See them in **Targets → By person** for the NSM (owns India). All of
`sales_actuals_aug2026.csv` falls under India, so once an August compute runs these
targets get their actuals (CORE_VALUE ≈ the file's net total rolled up the tree). Two caveats: an August plan
that later splits the same KPIs from the India root lands on this same dimension — its
applied numbers take over the row (your import shows up as the "manual" history on it);
and re-importing over an existing row lands *pending* (maker-checker) — that's governance,
not a failure.

## Cleanup

```powershell
cd backend
venv\Scripts\python.exe manage.py shell -c "from apps.kpi_engine.models import Transaction; from apps.targets.models import TargetAllocation; print(Transaction.objects.filter(source='manual_entry', external_ref__startswith='DUMMY-').delete()); print(TargetAllocation.objects.filter(target_period__code='FY2026-M08', plan__isnull=True, source='bulk_import').delete())"
```

(Then delete any test plan from its workspace while it's still a draft, or re-seed.)

# Building the Tableau Public dashboard

Everything is done in the browser (Tableau Public web authoring); nothing is installed.
Tableau occasionally renames buttons, so if a label differs slightly, look for the closest match.

## 0. Produce the data (in the codespace)

```bash
source .venv/bin/activate
dbt build
python scripts/markov_forecast.py
python scripts/export_for_tableau.py
```

This writes four files to `exports/`. In the codespace Explorer, right-click each one and choose **Download**:

| File | One row per | Used for |
|---|---|---|
| `vintage_curves.csv` | vintage, credit band, month on book, default measure | View 1: vintage default curves |
| `roll_rates.csv` | period, scope, from-bucket, to-bucket | View 2: roll-rate heatmap |
| `episode_outcomes.csv` | scope, peak bucket, outcome | View 3: how delinquency ends |
| `forecast_backtest.csv` | cut-off month, series | View 4: forecast vs actual |

These files hold only aggregated counts and rates: no loan-level Freddie Mac records, so they can be published.

## 1. Start a workbook

1. Go to **public.tableau.com**, sign in (personal account), click **Create → Web Authoring**.
2. Upload **vintage_curves.csv**.
3. Add the other three files as **separate data sources** (**Data → New Data Source**). Each view uses one file; no joins.

## 2. View 1 — "Vintage default curves" (data source: vintage_curves)

1. Rename the sheet: **Vintage Default Curves**.
2. Create a calculated field (**Analysis → Create Calculated Field**), name **Cumulative Default Rate**:
   ```
   SUM([Defaults]) / SUM([Loans Observable])
   ```
   Right-click it in the Data pane → **Default Properties → Number Format → Percentage**, 1 decimal.
   (Sum first, then divide: this stays correct when several credit bands are selected.)
3. Drag **Months on Book** to **Columns**. Click its dropdown and make it **Dimension** and **Continuous** (green).
4. Drag **Cumulative Default Rate** to **Rows**.
5. Drag **Vintage** to **Color**. Colors: 2006 = orange, 2007 = red, 2012 = teal, 2019 = blue.
6. Drag **Default Measure** to **Filters**, choose **Raw**, then right-click → **Show Filter** →
   set it to **Single Value (list)**. This is the "with / without forbearance" switch: watch the 2019 curve fall.
7. Drag **Credit Band** to **Filters**, select all, right-click → **Show Filter** (multiple values).
8. Title: *Share of loans defaulted, by months since first payment*.

## 3. View 2 — "Roll rates" (data source: roll_rates)

1. New sheet, rename it **Roll-Rate Matrix**.
2. Drag **From Bucket** to **Rows** and **To Bucket** to **Columns**.
3. Sort them in credit order, not alphabetically: click the **From Bucket** pill → **Sort** → **Sort By: Field**,
   **Field Name: From Order**, **Aggregation: Minimum**, Ascending. Do the same for **To Bucket** with **To Order**.
4. Marks card: set the mark type to **Square**. Drag **Share of From Bucket** to **Color** and to **Label**.
   Set its number format to **Percentage**, 1 decimal. Edit colors: a single-hue sequential palette (e.g. Blue).
5. Drag **Period** to **Filters**, choose **All years**, then **Show Filter** as **Single Value (dropdown)**.
6. Drag **Scope** to **Filters**, choose **Outside forbearance**, **Show Filter** as **Single Value (list)**.
7. Title: *Where loans go next month (row = this month, column = next month)*.

Try: Period 2009 vs 2016 (crisis vs calm), and 2020 with Scope "All months" vs "Outside forbearance".

## 4. View 3 — "How delinquency ends" (data source: episode_outcomes)

1. New sheet, rename it **How Delinquency Ends**.
2. Drag **Peak Bucket** to **Rows**; sort by **Peak Order** (Minimum), as in View 2.
3. Drag **Share of Peak Bucket** to **Columns**. Use **SUM**.
4. Drag **Outcome** to **Color**. Colors: Cured = green, Paid off = light green, REO = dark red, Loss exit = red,
   Still delinquent = orange, everything else = grey.
5. Drag **Share of Peak Bucket** to **Label** too; percentage format, 0 decimals.
6. Drag **Scope** to **Filters**, choose **All episodes**, **Show Filter** as **Single Value (list)**.
7. Title: *Outcome of each delinquency episode, by how far behind it got*.

## 5. View 4 — "Forecast vs actual" (data source: forecast_backtest)

1. New sheet, rename it **Forecast Back-Test**.
2. Drag **Cutoff Month** to **Columns**; choose **YEAR** (discrete is fine).
3. Drag **Defaults** to **Rows** (SUM).
4. Drag **Series** to **Color**. Colors: Actual = black, Forecast v1 = grey, Forecast v2 = blue.
5. Marks: **Line**. Click **Shape**/**Detail** if needed so each series is its own line; turn on markers.
6. Drag **Error Pct** to **Tooltip**.
7. Title: *12-month defaults: forecast at each December vs what happened*.

## 6. The dashboard

1. **New Dashboard**. Size: **Fixed, 1400 × 1000** (or Automatic).
2. Text at the top:
   - Title: **Mortgage Credit Risk: Vintages, Roll Rates and a Back-Tested Forecast**
   - Subtitle: *200,000 Freddie Mac loans (2006, 2007, 2012, 2019 vintages), tracked monthly to March 2026.*
3. Layout: **Vintage Default Curves** top-left, **Roll-Rate Matrix** top-right,
   **How Delinquency Ends** bottom-left, **Forecast Back-Test** bottom-right.
4. Make each filter apply only to its own sheet (the default, as each comes from its own data source).
5. Footer text: *Built with Python, dbt and DuckDB. Code and methodology:
   github.com/rajib-k-das/loan-credit-risk-analytics. Source: Freddie Mac Single-Family Loan-Level Dataset.*

## 7. Publish

1. **File → Save** (or **Publish**). Name: **Mortgage Credit Risk Analytics**. Make sure the **dashboard** tab is the
   active tab when you publish, so the link opens on it.
2. Open the published viz from your profile and check it in a private browser window.
3. Copy its link (the `/app/profile/.../viz/...` address) and send it over: it goes in the README, and a screenshot
   saved as `docs/dashboard.png` goes at the top of the README.

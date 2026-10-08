"""
Export the dashboard data from the warehouse to CSV files for Tableau Public.

Run after `dbt build` and `python scripts/markov_forecast.py`. Writes four files to exports/:

  vintage_curves.csv     Cumulative defaults and prepayments by vintage, credit band and month on book, in long format
                         (one row per default measure: "Raw" or "Excluding forbearance"). Only months where at least
                         90% of the vintage is observable are kept, so curve tails rest on most of the cohort.
  roll_rates.csv         Roll-rate matrix with percentages per from-bucket, for every year and for all years combined,
                         outside forbearance and including it.
  episode_outcomes.csv   How delinquency episodes ended, by their deepest bucket, for all / forbearance / other episodes.
  forecast_backtest.csv  Forecast (v1, v2) and actual 12-month defaults at each December cut-off, in long format.

Sort columns (from_order, to_order, peak_order) let Tableau show buckets in credit order, not alphabetically.

Usage:
    python scripts/export_for_tableau.py
"""

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "warehouse.duckdb"
EXPORT_DIR = ROOT / "exports"

BUCKET_ORDER = """
    case {col} when 'Current' then 1 when '30' then 2 when '60' then 3 when '90' then 4 when '120+' then 5
               when 'REO' then 6 when 'Prepaid' then 7 when 'Defaulted' then 8 when 'Removed' then 9 else 10 end
"""

QUERIES = {
    "vintage_curves": """
        with vintage_coverage as (
            select vintage_year, months_on_book, sum(loans_observable) / sum(cohort_loans) as share_observable
            from marts.fct_vintage_curves group by all
        ),
        curves as (
            select c.*
            from marts.fct_vintage_curves as c
            inner join vintage_coverage as v using (vintage_year, months_on_book)
            where v.share_observable >= 0.9
        )
        select cast(vintage_year as varchar) as "Vintage", credit_score_band as "Credit Band",
               months_on_book as "Months on Book", 'Raw' as "Default Measure",
               cohort_loans as "Cohort Loans", loans_observable as "Loans Observable",
               cumulative_defaults as "Defaults", cumulative_prepayments as "Prepayments"
        from curves
        union all
        select cast(vintage_year as varchar), credit_score_band, months_on_book, 'Excluding forbearance',
               cohort_loans, loans_observable, cumulative_defaults_excl_forbearance, cumulative_prepayments
        from curves
        order by 1, 2, 4, 3
    """,
    "roll_rates": f"""
        with base as (
            select cast(year(from_month) as varchar) as period, is_in_forbearance, from_bucket, to_bucket, loans
            from marts.fct_roll_rates
            where from_bucket in ('Current', '30', '60', '90', '120+')
        ),
        periods as (
            select period, from_bucket, to_bucket, is_in_forbearance, loans from base
            union all
            select 'All years', from_bucket, to_bucket, is_in_forbearance, loans from base
        ),
        scoped as (
            select period, 'Outside forbearance' as scope, from_bucket, to_bucket, sum(loans) as loans
            from periods where not is_in_forbearance group by all
            union all
            select period, 'All months', from_bucket, to_bucket, sum(loans)
            from periods group by all
        )
        select period as "Period", scope as "Scope", from_bucket as "From Bucket", to_bucket as "To Bucket",
               {BUCKET_ORDER.format(col='from_bucket')} as "From Order",
               {BUCKET_ORDER.format(col='to_bucket')} as "To Order",
               loans as "Loans",
               round(loans / sum(loans) over (partition by period, scope, from_bucket), 5) as "Share of From Bucket"
        from scoped
        order by 1, 2, 5, 6
    """,
    "episode_outcomes": """
        with scoped as (
            select 'All episodes' as scope, peak_bucket, outcome from marts.fct_delinquency_episodes
            union all
            select case when had_forbearance then 'In forbearance' else 'Not in forbearance' end,
                   peak_bucket, outcome
            from marts.fct_delinquency_episodes
        )
        select scope as "Scope", peak_bucket as "Peak Bucket",
               case peak_bucket when '30' then 1 when '60' then 2 when '90' then 3 else 4 end as "Peak Order",
               outcome as "Outcome", count(*) as "Episodes",
               round(count(*) / sum(count(*)) over (partition by scope, peak_bucket), 5) as "Share of Peak Bucket"
        from scoped
        group by scope, peak_bucket, outcome
        order by 1, 3, 5 desc
    """,
    "forecast_backtest": """
        select cast(cutoff_month as date) as "Cutoff Month", run_type as "Run Type", loans_at_cutoff as "Loans at Cutoff",
               'Actual' as "Series", actual_defaults as "Defaults", null as "Error Pct"
        from marts.markov_backtest where run_type = 'back-test'
        union all
        select cast(cutoff_month as date), run_type, loans_at_cutoff, 'Forecast v1 (pooled)',
               forecast_defaults_v1, error_pct_v1
        from marts.markov_backtest
        union all
        select cast(cutoff_month as date), run_type, loans_at_cutoff, 'Forecast v2 (by vintage, ex-forbearance)',
               forecast_defaults_v2, error_pct_v2
        from marts.markov_backtest
        order by 1, 4
    """,
}


def main() -> None:
    EXPORT_DIR.mkdir(exist_ok=True)
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        for name, sql in QUERIES.items():
            target = EXPORT_DIR / f"{name}.csv"
            con.sql(sql).write_csv(str(target))
            rows = con.sql(f"select count(*) from read_csv_auto('{target}')").fetchone()[0]
            print(f"  wrote {target.relative_to(ROOT)}  ({rows:,} rows)")


if __name__ == "__main__":
    main()

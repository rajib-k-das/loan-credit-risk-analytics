"""
Print the headline findings from the marts, for the README and the dashboard narrative.

Run after `dbt build`:
    python scripts/summarize_findings.py
"""

from pathlib import Path

import duckdb

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "warehouse.duckdb"

BUCKETS = "('Current', '30', '60', '90', '120+')"

CHECKS = {
    "1. Cumulative default rate (%) by vintage and month on book, raw / excluding forbearance": """
        with curve as (
            select vintage_year, months_on_book,
                   100.0 * sum(cumulative_defaults) / sum(loans_observable) as raw,
                   100.0 * sum(cumulative_defaults_excl_forbearance) / sum(loans_observable) as excl,
                   100.0 * sum(loans_observable) / sum(cohort_loans) as pct_observable
            from marts.fct_vintage_curves group by all
        )
        select vintage_year,
               round(any_value(raw)  filter (where months_on_book = 12), 2)  as m12,
               round(any_value(raw)  filter (where months_on_book = 24), 2)  as m24,
               round(any_value(raw)  filter (where months_on_book = 36), 2)  as m36,
               round(any_value(excl) filter (where months_on_book = 36), 2)  as m36_excl_fb,
               round(any_value(raw)  filter (where months_on_book = 60), 2)  as m60,
               round(any_value(excl) filter (where months_on_book = 60), 2)  as m60_excl_fb,
               max(months_on_book) filter (where pct_observable >= 99)       as fully_observed_to_month
        from curve group by 1 order by 1
    """,
    "2. Cumulative default rate (%) at month 36 by credit score band": """
        pivot (
            select vintage_year, credit_score_band,
                   round(100.0 * cumulative_defaults / loans_observable, 2) as rate
            from marts.fct_vintage_curves where months_on_book = 36
        ) on credit_score_band
          in ('<620', '620-679', '680-719', '720-759', '760+')
          using any_value(rate) group by vintage_year order by vintage_year
    """,
    "3. Roll-rate matrix (% of loans moving next month), all months, outside forbearance": f"""
        with t as (
            select from_bucket, to_bucket, sum(loans) as loans
            from marts.fct_roll_rates
            where not is_in_forbearance and from_bucket in {BUCKETS}
            group by all
        ),
        pct as (
            select from_bucket, to_bucket, 100.0 * loans / sum(loans) over (partition by from_bucket) as pct from t
        )
        pivot (select from_bucket, to_bucket, round(pct, 2) as pct from pct)
        on to_bucket in ('Current', '30', '60', '90', '120+', 'REO', 'Prepaid', 'Defaulted', 'Removed', 'Unknown')
        using any_value(pct)
        order by case from_bucket when 'Current' then 1 when '30' then 2 when '60' then 3 when '90' then 4 else 5 end
    """,
    "4. Roll rates by year (%): 30 -> 60 days, 30 -> cured, 60 -> 90 days": """
        with t as (
            select year(from_month) as year, from_bucket, to_bucket, sum(loans) as loans
            from marts.fct_roll_rates where from_bucket in ('30', '60') group by all
        )
        select year,
               round(100.0 * sum(loans) filter (where from_bucket = '30' and to_bucket = '60')
                     / sum(loans) filter (where from_bucket = '30'), 1)                      as roll_30_to_60,
               round(100.0 * sum(loans) filter (where from_bucket = '30' and to_bucket = 'Current')
                     / sum(loans) filter (where from_bucket = '30'), 1)                      as cure_30,
               round(100.0 * sum(loans) filter (where from_bucket = '60' and to_bucket = '90')
                     / sum(loans) filter (where from_bucket = '60'), 1)                      as roll_60_to_90,
               sum(loans) filter (where from_bucket = '30')                                   as loans_at_30
        from t group by year order by year
    """,
    "5. Delinquency episodes: outcome by forbearance": """
        select had_forbearance, count(*) as episodes,
               round(100.0 * count(*) filter (where outcome = 'Cured') / count(*), 1)          as cured_pct,
               round(100.0 * count(*) filter (where reached_default) / count(*), 1)            as reached_default_pct,
               round(100.0 * count(*) filter (where reached_default_excl_forbearance) / count(*), 1)
                                                                                                as default_excl_fb_pct,
               round(avg(months_delinquent_in_episode), 1)                                      as avg_months
        from marts.fct_delinquency_episodes group by 1 order by 1
    """,
    "6. Delinquency episodes: what happens after the deepest point": """
        select peak_bucket, count(*) as episodes,
               round(100.0 * count(*) filter (where outcome = 'Cured') / count(*), 1)     as cured_pct,
               round(100.0 * count(*) filter (where outcome = 'Paid off') / count(*), 1)  as paid_off_pct,
               round(100.0 * count(*) filter (where outcome in ('REO', 'Loss exit')) / count(*), 1) as reo_or_loss_pct,
               round(100.0 * count(*) filter (where outcome = 'Still delinquent') / count(*), 1)    as still_delinquent_pct
        from marts.fct_delinquency_episodes group by 1
        order by case peak_bucket when '30' then 1 when '60' then 2 when '90' then 3 else 4 end
    """,
    "7. Repeat delinquency: loans by number of episodes": """
        select episodes, count(*) as loans,
               round(100.0 * count(*) / sum(count(*)) over (), 1) as pct_of_delinquent_loans
        from (select loan_id, least(count(*), 5) as episodes from marts.fct_delinquency_episodes group by 1)
        group by 1 order by 1
    """,
}


def main() -> None:
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        for title, sql in CHECKS.items():
            print(f"\n== {title} ==")
            con.sql(sql).show(max_rows=60, max_width=250)


if __name__ == "__main__":
    main()

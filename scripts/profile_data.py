"""
Profile the loaded data so the modeling assumptions can be checked against what Freddie Mac actually sends.

Run after `dbt build`. Prints, per vintage:
  - loans, loan-months, and the reporting window
  - every delinquency status value and zero balance code, with counts
  - borrower assistance codes and disaster / deferral flags (decision 004 assumes 'F' = forbearance)
  - default rates under both definitions

Usage:
    python scripts/profile_data.py
"""

from pathlib import Path

import duckdb

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "warehouse.duckdb"

CHECKS = {
    "Loans and months by vintage": """
        select vintage_year, count(distinct loan_id) as loans, count(*) as loan_months,
               min(reporting_month) as first_month, max(reporting_month) as last_month
        from intermediate.int_loan_months group by 1 order by 1
    """,
    "Delinquency status values (top 15)": """
        select delinquency_status_code, count(*) as rows
        from staging.stg_freddie__performance group by 1 order by 2 desc limit 15
    """,
    "Zero balance codes": """
        select zero_balance_code, count(*) as loans
        from staging.stg_freddie__performance where zero_balance_code is not null group by 1 order by 1
    """,
    "Borrower assistance codes": """
        select borrower_assistance_status, count(*) as rows,
               count(*) filter (where is_disaster_delinquency) as with_disaster_flag,
               count(*) filter (where months_delinquent > 0)   as delinquent_rows
        from staging.stg_freddie__performance group by 1 order by 2 desc
    """,
    "Raw values of the hardship and modification flags": """
        select 'payment_deferral_flag' as field, payment_deferral_flag as value, count(*) as rows
        from raw.loan_performance group by 1, 2
        union all
        select 'delinquency_due_to_disaster', delinquency_due_to_disaster, count(*) from raw.loan_performance group by 1, 2
        union all
        select 'modification_flag', modification_flag, count(*) from raw.loan_performance group by 1, 2
        order by 1, 3 desc
    """,
    "REO: months between REO acquisition and sale": """
        with reo as (
            select loan_id,
                   count(*) filter (where delinquency_status_code = 'RA') as reo_months,
                   max(zero_balance_code) as exit_code
            from intermediate.int_loan_months group by 1 having reo_months > 0
        )
        select exit_code, count(*) as loans, round(avg(reo_months), 1) as avg_reo_months, max(reo_months) as max_reo_months
        from reo group by 1 order by 2 desc
    """,
    "Forbearance months by year": """
        select year(reporting_month) as year, count(*) filter (where is_in_forbearance) as forbearance_months,
               count(*) filter (where is_deferral_month) as deferrals_granted, count(*) filter (where has_payment_deferral) as months_with_deferral
        from intermediate.int_loan_months group by 1 having forbearance_months > 0 or months_with_deferral > 0
        order by 1
    """,
    "Default rate by vintage (raw vs. excluding forbearance)": """
        select vintage_year, count(*) as loans,
               round(100.0 * count(default_month) / count(*), 2) as default_pct,
               round(100.0 * count(default_month_excl_forbearance) / count(*), 2) as default_pct_excl_forbearance
        from (select distinct loan_id, vintage_year, default_month, default_month_excl_forbearance
              from intermediate.int_loan_months)
        group by 1 order by 1
    """,
}


def main() -> None:
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        for title, sql in CHECKS.items():
            print(f"\n== {title} ==")
            con.sql(sql).show(max_rows=50)


if __name__ == "__main__":
    main()

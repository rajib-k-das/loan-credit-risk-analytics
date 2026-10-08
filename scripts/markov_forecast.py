"""
12-month Markov-chain default forecast, back-tested (decision 005).

Method
  1. At a cut-off month T, estimate a monthly transition matrix between credit states from all loan transitions
     in the 12 months up to T (marts.fct_credit_state_transitions).
  2. Start from the loans that are active and not defaulted at T (Current, 30 or 60 days late).
  3. Apply the matrix 12 times. The share that ends in Defaulted is the forecast default count; same for Prepaid.
  4. Compare with what actually happened to those same loans in the 12 months after T.

The back-test runs at every December with a full 12 months of history before it and 12 months of outcomes after it.
A forward forecast from the last reporting month is added with no actuals.

Writes marts.markov_backtest (and exports/markov_backtest.csv) and prints the results.

Usage:
    python scripts/markov_forecast.py
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "warehouse.duckdb"
EXPORT_DIR = ROOT / "exports"

TRANSIENT = ["Current", "30", "60"]
ABSORBING = ["Defaulted", "Prepaid", "Removed"]
STATES = TRANSIENT + ABSORBING
HORIZON = 12
COLUMNS = [
    "cutoff_month", "run_type", "loans_at_cutoff", "monthly_roll_current_to_30", "monthly_roll_60_to_default",
    "forecast_defaults", "actual_defaults", "forecast_default_rate", "actual_default_rate",
    "default_forecast_error_pct", "forecast_prepays", "actual_prepays",
]


def transition_matrix(con: duckdb.DuckDBPyConnection, cutoff: str) -> np.ndarray:
    """Monthly transition probabilities from transitions observed in the 12 months ending at the cut-off."""
    counts = con.execute(
        """
        select from_state, to_state, sum(loans) as loans
        from marts.fct_credit_state_transitions
        where from_month >= cast(? as date) - interval 12 month
          and from_month <  cast(? as date)
          and from_state in ('Current', '30', '60')
          and to_state <> 'Unknown'          -- decision 007: unknown months are left out, not guessed
        group by all
        """,
        [cutoff, cutoff],
    ).df()

    matrix = np.zeros((len(STATES), len(STATES)))
    for row in counts.itertuples():
        matrix[STATES.index(row.from_state), STATES.index(row.to_state)] = row.loans
    for i, state in enumerate(STATES):
        total = matrix[i].sum()
        if state in ABSORBING or total == 0:
            matrix[i] = 0
            matrix[i, i] = 1.0          # absorbing (or no data): stays put
        else:
            matrix[i] /= total
    assert np.allclose(matrix.sum(axis=1), 1.0), "every row of a transition matrix must sum to 1"
    return matrix


def starting_loans(con: duckdb.DuckDBPyConnection, cutoff: str) -> pd.DataFrame:
    """Loans active and not yet defaulted at the cut-off, with what happened to them in the next 12 months."""
    return con.execute(
        """
        select
            credit_state,
            count(*)                                                                   as loans,
            count(*) filter (where default_month >  cast(? as date)
                               and default_month <= cast(? as date) + interval 12 month) as actual_defaults,
            count(*) filter (where prepaid_month >  cast(? as date)
                               and prepaid_month <= cast(? as date) + interval 12 month) as actual_prepays
        from (
            select months.credit_state, months.default_month,
                   case when loans.zero_balance_code = '01' then loans.exit_month end as prepaid_month
            from intermediate.int_loan_months as months
            inner join marts.dim_loan as loans using (loan_id)
            where months.reporting_month = cast(? as date)
              and months.credit_state in ('Current', '30', '60')
              and not loans.is_default_before_first_payment
        )
        group by credit_state
        """,
        [cutoff] * 5,
    ).df()


def forecast(matrix: np.ndarray, start: pd.DataFrame) -> tuple[float, float]:
    vector = np.zeros(len(STATES))
    for row in start.itertuples():
        vector[STATES.index(row.credit_state)] = row.loans
    projected = vector @ np.linalg.matrix_power(matrix, HORIZON)
    return projected[STATES.index("Defaulted")], projected[STATES.index("Prepaid")]


def main() -> None:
    with duckdb.connect(str(DB_PATH)) as con:
        first_month, last_month = con.execute(
            "select min(reporting_month), max(reporting_month) from intermediate.int_loan_months"
        ).fetchone()

        cutoffs = [
            str(d.date())
            for d in pd.date_range(f"{first_month.year}-12-01", last_month, freq="12MS")
            if d - pd.DateOffset(months=HORIZON) >= pd.Timestamp(first_month)
            and d + pd.DateOffset(months=HORIZON) <= pd.Timestamp(last_month)
        ]

        rows = []
        for cutoff in cutoffs + [str(last_month)]:
            is_backtest = cutoff != str(last_month)
            matrix = transition_matrix(con, cutoff)
            start = starting_loans(con, cutoff)
            if start.empty:
                continue
            forecast_defaults, forecast_prepays = forecast(matrix, start)
            loans = int(start["loans"].sum())
            actual_defaults = int(start["actual_defaults"].sum()) if is_backtest else None
            actual_prepays = int(start["actual_prepays"].sum()) if is_backtest else None
            rows.append(
                {
                    "cutoff_month": cutoff,
                    "run_type": "back-test" if is_backtest else "forward forecast",
                    "loans_at_cutoff": loans,
                    "monthly_roll_current_to_30": round(matrix[0, 1], 5),
                    "monthly_roll_60_to_default": round(matrix[2, 3], 4),
                    "forecast_defaults": round(forecast_defaults, 1),
                    "actual_defaults": actual_defaults,
                    "forecast_default_rate": round(forecast_defaults / loans, 5),
                    "actual_default_rate": round(actual_defaults / loans, 5) if is_backtest else None,
                    "default_forecast_error_pct": (
                        round(100 * (forecast_defaults - actual_defaults) / actual_defaults, 1)
                        if is_backtest and actual_defaults else None
                    ),
                    "forecast_prepays": round(forecast_prepays, 1),
                    "actual_prepays": actual_prepays,
                }
            )

        results = pd.DataFrame(rows, columns=COLUMNS)
        con.register("results_df", results)
        con.execute("create schema if not exists marts")
        con.execute("create or replace table marts.markov_backtest as select * from results_df")

    EXPORT_DIR.mkdir(exist_ok=True)
    results.to_csv(EXPORT_DIR / "markov_backtest.csv", index=False)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 20)
    print(results.drop(columns=["forecast_prepays", "actual_prepays"]).to_string(index=False))
    backtests = results[results["run_type"] == "back-test"]
    if not backtests.empty:
        errors = backtests["default_forecast_error_pct"].dropna().abs()
        print(f"\nBack-tests: {len(backtests)}. Median absolute error in 12-month defaults: {errors.median():.1f}%")
    print("Wrote marts.markov_backtest and exports/markov_backtest.csv")


if __name__ == "__main__":
    main()

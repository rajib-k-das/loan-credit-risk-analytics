"""
12-month Markov-chain default forecast, back-tested (decisions 005, 012 and 013).

Method
  1. At a cut-off month T, estimate a monthly transition matrix between credit states from loan transitions
     in the 12 months up to T (marts.fct_credit_state_transitions).
  2. Start from the loans that are active and not defaulted at T (Current, 30 or 60 days late).
  3. Apply the matrix 12 times. The share that ends in Defaulted is the forecast default count.
  4. Compare with what actually happened to those same loans in the 12 months after T.

Two versions are run side by side:
  v1  one pooled matrix for the whole portfolio, from all transitions.
  v2  one matrix per vintage, estimated without months spent in forbearance. A row with too few
      observations falls back to the pooled (forbearance-excluded) row.
Both forecast the same target: raw 12-month defaults, forbearance included.

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
MIN_ROW_OBSERVATIONS = 50   # v2: below this, a vintage's row uses the pooled row instead
COLUMNS = [
    "cutoff_month", "run_type", "loans_at_cutoff", "actual_defaults",
    "forecast_defaults_v1", "error_pct_v1", "forecast_defaults_v2", "error_pct_v2",
    "monthly_roll_60_to_default_v1", "monthly_roll_60_to_default_v2",
    "forecast_prepays_v1", "actual_prepays",
]


def transition_counts(con: duckdb.DuckDBPyConnection, cutoff: str) -> pd.DataFrame:
    """Transitions observed in the 12 months ending at the cut-off."""
    return con.execute(
        """
        select vintage_year, is_in_forbearance, from_state, to_state, sum(loans) as loans
        from marts.fct_credit_state_transitions
        where from_month >= cast(? as date) - interval 12 month
          and from_month <  cast(? as date)
          and from_state in ('Current', '30', '60')
          and to_state <> 'Unknown'          -- decision 007: unknown months are left out, not guessed
        group by all
        """,
        [cutoff, cutoff],
    ).df()


def count_matrix(counts: pd.DataFrame) -> np.ndarray:
    matrix = np.zeros((len(STATES), len(STATES)))
    for row in counts.itertuples():
        matrix[STATES.index(row.from_state), STATES.index(row.to_state)] += row.loans
    return matrix


def normalise(matrix: np.ndarray, fallback: np.ndarray | None = None) -> np.ndarray:
    """Turn counts into probabilities. Absorbing rows stay put; thin rows use the fallback row if given."""
    out = np.zeros_like(matrix, dtype=float)
    for i, state in enumerate(STATES):
        total = matrix[i].sum()
        if state in ABSORBING:
            out[i, i] = 1.0
        elif total >= MIN_ROW_OBSERVATIONS or (fallback is None and total > 0):
            out[i] = matrix[i] / total
        elif fallback is not None:
            out[i] = fallback[i]
        else:
            out[i, i] = 1.0
    assert np.allclose(out.sum(axis=1), 1.0), "every row of a transition matrix must sum to 1"
    return out


def starting_loans(con: duckdb.DuckDBPyConnection, cutoff: str) -> pd.DataFrame:
    """Loans active and not yet defaulted at the cut-off, with what happened to them in the next 12 months."""
    return con.execute(
        """
        select
            vintage_year,
            credit_state,
            count(*)                                                                   as loans,
            count(*) filter (where default_month >  cast(? as date)
                               and default_month <= cast(? as date) + interval 12 month) as actual_defaults,
            count(*) filter (where prepaid_month >  cast(? as date)
                               and prepaid_month <= cast(? as date) + interval 12 month) as actual_prepays
        from (
            select months.vintage_year, months.credit_state, months.default_month,
                   case when loans.zero_balance_code = '01' then loans.exit_month end as prepaid_month
            from intermediate.int_loan_months as months
            inner join marts.dim_loan as loans using (loan_id)
            where months.reporting_month = cast(? as date)
              and months.credit_state in ('Current', '30', '60')
              and not loans.is_default_before_first_payment
        )
        group by all
        """,
        [cutoff] * 5,
    ).df()


def project(matrix: np.ndarray, start: pd.DataFrame) -> np.ndarray:
    vector = np.zeros(len(STATES))
    for row in start.itertuples():
        vector[STATES.index(row.credit_state)] += row.loans
    return vector @ np.linalg.matrix_power(matrix, HORIZON)


def error_pct(forecast: float, actual: int | None) -> float | None:
    return round(100 * (forecast - actual) / actual, 1) if actual else None


def main() -> None:
    defaulted, prepaid = STATES.index("Defaulted"), STATES.index("Prepaid")
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
            start = starting_loans(con, cutoff)
            if start.empty:
                continue
            counts = transition_counts(con, cutoff)

            # v1: one pooled matrix from all transitions.
            matrix_v1 = normalise(count_matrix(counts))
            projected_v1 = project(matrix_v1, start)

            # v2: a matrix per vintage, forbearance months left out, thin rows from the pooled matrix.
            outside_forbearance = counts[~counts["is_in_forbearance"]]
            pooled_v2 = normalise(count_matrix(outside_forbearance))
            forecast_v2 = 0.0
            for vintage, vintage_start in start.groupby("vintage_year"):
                vintage_counts = outside_forbearance[outside_forbearance["vintage_year"] == vintage]
                matrix = normalise(count_matrix(vintage_counts), fallback=pooled_v2)
                forecast_v2 += project(matrix, vintage_start)[defaulted]

            actual_defaults = int(start["actual_defaults"].sum()) if is_backtest else None
            rows.append(
                {
                    "cutoff_month": cutoff,
                    "run_type": "back-test" if is_backtest else "forward forecast",
                    "loans_at_cutoff": int(start["loans"].sum()),
                    "actual_defaults": actual_defaults,
                    "forecast_defaults_v1": round(projected_v1[defaulted], 1),
                    "error_pct_v1": error_pct(projected_v1[defaulted], actual_defaults),
                    "forecast_defaults_v2": round(forecast_v2, 1),
                    "error_pct_v2": error_pct(forecast_v2, actual_defaults),
                    "monthly_roll_60_to_default_v1": round(matrix_v1[2, defaulted], 4),
                    "monthly_roll_60_to_default_v2": round(pooled_v2[2, defaulted], 4),
                    "forecast_prepays_v1": round(projected_v1[prepaid], 1),
                    "actual_prepays": int(start["actual_prepays"].sum()) if is_backtest else None,
                }
            )

        results = pd.DataFrame(rows, columns=COLUMNS)
        con.register("results_df", results)
        con.execute("create schema if not exists marts")
        con.execute("create or replace table marts.markov_backtest as select * from results_df")

    EXPORT_DIR.mkdir(exist_ok=True)
    results.to_csv(EXPORT_DIR / "markov_backtest.csv", index=False)

    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)
    print(results[["cutoff_month", "loans_at_cutoff", "actual_defaults", "forecast_defaults_v1", "error_pct_v1",
                   "forecast_defaults_v2", "error_pct_v2"]].to_string(index=False))

    backtests = results[results["run_type"] == "back-test"]
    if not backtests.empty:
        shocks = {"2007-12-01", "2008-12-01", "2019-12-01"}
        print(f"\nBack-tests: {len(backtests)}. Median absolute error in 12-month defaults:")
        for label, subset in [("all years", backtests),
                              ("excluding the 3 shock years (Dec 2007, 2008, 2019)",
                               backtests[~backtests["cutoff_month"].isin(shocks)])]:
            print(f"  {label:<52} v1 {subset['error_pct_v1'].abs().median():6.1f}%   "
                  f"v2 {subset['error_pct_v2'].abs().median():6.1f}%")
    print("Wrote marts.markov_backtest and exports/markov_backtest.csv")


if __name__ == "__main__":
    main()

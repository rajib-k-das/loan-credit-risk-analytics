"""
Load the Freddie Mac Single-Family Loan-Level Dataset (sample files) into DuckDB.

Input: the yearly sample zips downloaded from Freddie Mac (sample_2006.zip, ...), placed in data/raw/.
Each zip holds two pipe-delimited text files with no header row:

    sample_orig_YYYY.txt                      one row per loan, 31 fields, at origination
    sample_svcg_YYYY.txt (or sample_perf_)    one row per loan per month, 35 fields

Output: two DuckDB tables, every column kept as text (typing happens in dbt staging):

    raw.loan_origination   + vintage_year, source_file
    raw.loan_performance   + vintage_year, source_file

Freddie Mac's terms allow non-commercial use only and do not allow redistribution,
so these files are git-ignored and never committed.

Usage:
    python ingest/load_freddie_mac.py                          # zips or .txt files in data/raw
    python ingest/load_freddie_mac.py --raw-dir tests/fixtures # synthetic test loans (used in CI)
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "warehouse.duckdb"
DEFAULT_RAW_DIR = ROOT / "data" / "raw"
EXTRACT_DIR = ROOT / "data" / "extracted"

# Field order from Freddie Mac's file layout (File Layout, effective July 2026).
ORIGINATION_COLUMNS = [
    "credit_score", "first_payment_date", "first_time_homebuyer_flag", "maturity_date", "msa",
    "mi_pct", "number_of_units", "occupancy_status", "orig_cltv", "orig_dti",
    "orig_upb", "orig_ltv", "orig_interest_rate", "channel", "prepayment_penalty_flag",
    "amortization_type", "property_state", "property_type", "postal_code", "loan_id",
    "loan_purpose", "orig_loan_term", "number_of_borrowers", "seller_name", "super_conforming_flag",
    "pre_harp_loan_id", "program_indicator", "harp_indicator", "property_valuation_method",
    "interest_only_flag", "vantage_score",
]
PERFORMANCE_COLUMNS = [
    "loan_id", "reporting_period", "current_upb", "delinquency_status", "loan_age",
    "remaining_months_to_maturity", "defect_settlement_date", "modification_flag",
    "zero_balance_code", "zero_balance_date", "current_interest_rate", "current_non_interest_bearing_upb",
    "last_paid_installment_date", "mi_recoveries", "net_sales_proceeds", "non_mi_recoveries",
    "total_expenses", "legal_costs", "maintenance_costs", "taxes_and_insurance", "miscellaneous_expenses",
    "actual_loss", "cumulative_modification_cost", "interest_rate_step_flag", "payment_deferral_flag",
    "estimated_ltv", "zero_balance_removal_upb", "delinquent_accrued_interest",
    "delinquency_due_to_disaster", "borrower_assistance_status", "current_month_modification_cost",
    "interest_bearing_upb", "mi_cancellation_flag", "servicer_name", "bankruptcy_cramdown_costs",
]

ORIG_PATTERN = re.compile(r"sample_orig_(\d{4})\.txt$", re.IGNORECASE)
PERF_PATTERN = re.compile(r"sample_(?:svcg|perf)_(\d{4})\.txt$", re.IGNORECASE)


def extract_zips(raw_dir: Path) -> list[Path]:
    """Unzip every sample zip once (skipped if already extracted). Returns the folders to search."""
    folders = [raw_dir]
    for archive in sorted(raw_dir.glob("*.zip")):
        target = EXTRACT_DIR / archive.stem
        folders.append(target)
        if target.exists() and any(target.iterdir()):
            print(f"  already extracted  {archive.name}")
            continue
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                name = Path(member).name
                if ORIG_PATTERN.search(name) or PERF_PATTERN.search(name):
                    with zf.open(member) as src, open(target / name, "wb") as dst:
                        while chunk := src.read(1 << 20):
                            dst.write(chunk)
        print(f"  extracted          {archive.name}")
    return folders


def find_files(folders: list[Path], pattern: re.Pattern) -> dict[int, Path]:
    found: dict[int, Path] = {}
    for folder in folders:
        for path in folder.glob("*.txt"):
            match = pattern.search(path.name)
            if match:
                found[int(match.group(1))] = path
    return dict(sorted(found.items()))


def check_field_count(path: Path, expected: int) -> None:
    """Stop with a clear message if the file doesn't match the layout this loader was written for."""
    with open(path, encoding="latin-1") as f:
        first_line = f.readline().rstrip("\r\n")
    actual = first_line.count("|") + 1
    if actual != expected:
        sys.exit(
            f"{path.name}: expected {expected} pipe-delimited fields, found {actual}.\n"
            "Freddie Mac may have changed the file layout. Compare the file with the latest "
            "File Layout spreadsheet and update the column lists in this script."
        )


def load_table(con: duckdb.DuckDBPyConnection, table: str, files: dict[int, Path], columns: list[str]) -> None:
    column_spec = "{" + ", ".join(f"'{c}': 'VARCHAR'" for c in columns) + "}"
    selects = []
    for vintage, path in files.items():
        check_field_count(path, len(columns))
        selects.append(f"""
            select *, {vintage} as vintage_year, '{path.name}' as source_file
            from read_csv('{path.as_posix()}', delim='|', header=false, quote='', escape='',
                          columns={column_spec}, encoding='latin-1')
        """)
    con.execute(f"create or replace table {table} as " + " union all ".join(selects))
    count = con.execute(f"select count(*) from {table}").fetchone()[0]
    print(f"  {table:<24} {count:>12,} rows  (vintages {', '.join(map(str, files))})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR, help="folder with sample zips or .txt files")
    args = parser.parse_args()

    if not args.raw_dir.exists():
        sys.exit(f"{args.raw_dir} does not exist. Put the Freddie Mac sample zips there first.")

    print("Finding files...")
    folders = extract_zips(args.raw_dir)
    orig_files = find_files(folders, ORIG_PATTERN)
    perf_files = find_files(folders, PERF_PATTERN)
    if not orig_files or not perf_files:
        sys.exit(f"No sample_orig_YYYY.txt / sample_svcg_YYYY.txt files found in {args.raw_dir}")
    if set(orig_files) != set(perf_files):
        sys.exit(f"Vintages don't match: origination {sorted(orig_files)}, performance {sorted(perf_files)}")

    print("Loading into DuckDB...")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(DB_PATH)) as con:
        con.execute("create schema if not exists raw")
        load_table(con, "raw.loan_origination", orig_files, ORIGINATION_COLUMNS)
        load_table(con, "raw.loan_performance", perf_files, PERFORMANCE_COLUMNS)


if __name__ == "__main__":
    main()

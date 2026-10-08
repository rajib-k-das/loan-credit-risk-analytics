"""
Write four synthetic test loans in Freddie Mac's file layout (31 origination fields, 35 performance fields).

The loans are invented and hand-checkable. Their expected results are asserted in
tests/data_tests/assert_fixture_known_answers.sql:

    FIXTURE00001  prepays     current for three months, pays off in 2019-06            -> Prepaid, no default
    FIXTURE00002  defaults    0, 0, 30, 60, 90, 120 days late, REO for 2 months, sold   -> default 2019-07
    FIXTURE00003  forbearance 30/60/90 days late in COVID forbearance, then deferral   -> raw default 2020-06,
                                                                                          no default excluding forbearance
    FIXTURE00004  removed     an unknown (XX) month, a 30-day episode that cures,
                              then removed for a defect (code 96: censored, not a default)  -> Removed, no default

Usage:
    python tests/fixtures/make_fixtures.py
"""

from pathlib import Path

HERE = Path(__file__).resolve().parent


def origination(loan_id, credit_score, first_payment, dti, upb, ltv, rate, state):
    fields = [""] * 31
    fields[0] = credit_score          # Credit Score (9999 = not available)
    fields[1] = first_payment         # First Payment Date
    fields[2] = "N"                   # First Time Homebuyer Flag
    fields[3] = "204902"              # Maturity Date
    fields[4] = "41940"               # MSA
    fields[5] = "000"                 # MI %
    fields[6] = "1"                   # Number of Units
    fields[7] = "P"                   # Occupancy Status
    fields[8] = ltv                   # Original CLTV
    fields[9] = dti                   # Original DTI (999 = not available)
    fields[10] = upb                  # Original UPB
    fields[11] = ltv                  # Original LTV
    fields[12] = rate                 # Original Interest Rate
    fields[13] = "R"                  # Channel
    fields[14] = "N"                  # Prepayment Penalty Flag
    fields[15] = "FRM"                # Amortization Type
    fields[16] = state                # Property State
    fields[17] = "SF"                 # Property Type
    fields[18] = "95100"              # Postal Code (first 3 digits + 00)
    fields[19] = loan_id              # Loan Sequence Number
    fields[20] = "P"                  # Loan Purpose
    fields[21] = "360"                # Original Loan Term
    fields[22] = "2"                  # Number of Borrowers
    fields[23] = "TEST SELLER"        # Seller Name
    fields[24] = ""                   # Super Conforming Flag
    fields[25] = ""                   # Pre-HARP Loan Sequence Number
    fields[26] = "9"                  # Program Indicator
    fields[27] = ""                   # HARP Indicator
    fields[28] = "9"                  # Property Valuation Method
    fields[29] = "N"                  # Interest Only Indicator
    fields[30] = "9999"               # VantageScore (9999 = not available)
    return "|".join(fields)


def performance(loan_id, period, upb, status, age, zero_balance_code="", zero_balance_date="",
                assistance="", disaster="", deferral="", actual_loss=""):
    fields = [""] * 35
    fields[0] = loan_id
    fields[1] = period
    fields[2] = upb
    fields[3] = status
    fields[4] = str(age)
    fields[5] = str(360 - age)
    fields[7] = "N"
    fields[8] = zero_balance_code
    fields[9] = zero_balance_date
    fields[10] = "4.000"
    fields[11] = "0"
    fields[21] = actual_loss
    fields[24] = deferral             # Payment Deferral
    fields[28] = disaster             # Delinquency Due to Disaster
    fields[29] = assistance           # Borrower Assistance Status Code
    fields[31] = upb                  # Interest Bearing UPB
    fields[33] = "TEST SERVICER"
    return "|".join(fields)


def months(start: str, count: int) -> list[str]:
    year, month = int(start[:4]), int(start[4:])
    out = []
    for _ in range(count):
        out.append(f"{year}{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return out


orig_rows = [
    origination("FIXTURE00001", "760", "201903", "999", "300000", "80", "4.250", "CA"),
    origination("FIXTURE00002", "640", "201903", "45", "250000", "95", "4.875", "FL"),
    origination("FIXTURE00003", "700", "201912", "38", "400000", "90", "3.875", "NY"),
    origination("FIXTURE00004", "9999", "201903", "30", "200000", "75", "4.500", "TX"),
]

perf_rows = []

# 1. Prepays in June 2019.
for i, period in enumerate(months("201903", 4)):
    last = period == "201906"
    perf_rows.append(performance("FIXTURE00001", period, "0" if last else "299000", "0", i,
                                 zero_balance_code="01" if last else "", zero_balance_date="201906" if last else ""))

# 2. Rolls 0 -> 0 -> 1 -> 2 -> 3 -> 4, then REO (RA) for two months; the property sells in 2019-10 with a loss.
for i, (period, status) in enumerate(zip(months("201903", 8), ["0", "0", "1", "2", "3", "4", "RA", "RA"])):
    last = period == "201910"
    perf_rows.append(performance("FIXTURE00002", period, "0" if last else "249000", status, i,
                                 zero_balance_code="09" if last else "", zero_balance_date="201910" if last else "",
                                 actual_loss="-61000" if last else ""))

# 3. COVID forbearance: three missed payments while in forbearance, then a payment deferral cures it.
statuses = ["0", "0", "0", "0", "1", "2", "3", "0", "0"]
for i, (period, status) in enumerate(zip(months("201912", 9), statuses)):
    in_forbearance = period in ("202004", "202005", "202006")
    perf_rows.append(performance("FIXTURE00003", period, "398000", status, i,
                                 assistance="F" if in_forbearance else "",
                                 disaster="Y" if in_forbearance else "",
                                 deferral="C" if period == "202007" else "P" if period > "202007" else ""))

# 4. An unknown month, a 30-day episode that cures, then removed for a defect (code 96 = censored, not a default).
for i, (period, status) in enumerate(zip(months("201903", 5), ["0", "XX", "1", "0", "0"])):
    last = period == "201907"
    perf_rows.append(performance("FIXTURE00004", period, "0" if last else "199000", status, i,
                                 zero_balance_code="96" if last else "", zero_balance_date="201907" if last else ""))

(HERE / "sample_orig_2019.txt").write_text("\n".join(orig_rows) + "\n")
(HERE / "sample_svcg_2019.txt").write_text("\n".join(perf_rows) + "\n")
print(f"Wrote {len(orig_rows)} origination rows and {len(perf_rows)} performance rows to {HERE}")

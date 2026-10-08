# Design decisions

Each entry records a modeling choice, the alternatives considered, and why this one won.

## 001 — Vintages: 2006, 2007, 2012, 2019

**Choice:** load the Freddie Mac yearly samples (50,000 loans each) for four origination years.
**Why:** they span the full credit cycle. 2006–2007 are the pre-crisis vintages that defaulted heavily;
2012 is a post-crisis vintage underwritten to tighter standards; 2019 runs straight into COVID forbearance.
Comparing them is the point of a vintage analysis. Four samples (about 200,000 loans) fit comfortably in DuckDB in a codespace.
**Rejected:** the full dataset (tens of millions of loans; too large for a free codespace and adds nothing to the method).

## 002 — Default definition: 90+ days delinquent, or a loss-type exit

**Choice:** a loan defaults in the first month it is 3 or more payments behind (`default_delinquency_months`),
or exits through a loss-type zero balance code: 02 third-party sale, 03 short sale or charge-off, 09 REO disposition,
or the REO-acquisition status `RA`.
**Why:** 90 days past due is the standard serious-delinquency threshold in mortgage credit and in Basel's default definition.
Loss exits are included because some loans go to a short sale or foreclosure sale without a 90-day record in the sample.
**Configurable:** change the dbt var to test sensitivity (the known-answer test fails at 60 days, as it should).

## 003 — States: Current, 30, 60, 90, 120+, Prepaid, Defaulted (absorbing)

**Choice:** two state columns on `int_loan_months`:
- `delinquency_bucket`: the bucket reported that month. Not absorbing: a loan can roll 90 → 60 → Current.
  Used for **roll-rate matrices**, which must show cures.
- `credit_state`: the same, except that once the default definition is met the loan stays `Defaulted`.
  Used for **default rates, vintage curves and the Markov forecast**.

**Why two:** found while building. With 90+ as the default trigger, an absorbing state model would never show the 90 or 120+
buckets, so a single column would either lose the roll-rate detail or break the default rate. Two columns keep both honest.

## 004 — Flag COVID forbearance; report results with and without it

**Choice:** a month is in forbearance when the Borrower Assistance Status Code is `F`, or Delinquency Due to Disaster is `Y`.
Every default measure has a second version (`*_excl_forbearance`) in which delinquency during forbearance does not count.
Loss exits always count.
**Why:** in 2020 servicers reported forborne loans as delinquent even though borrowers were permitted to skip payments.
Counting them as defaults overstates 2019-vintage credit losses; ignoring them hides real stress. Showing both lets the reader judge.
**To verify on real data:** the code values. `scripts/profile_data.py` lists every assistance code and flag count by year.

## 005 — Forecast: a 12-month Markov chain, back-tested

**Choice:** estimate monthly transition probabilities between credit states, project 12 months ahead, and back-test
by fitting on data up to a cut-off date and comparing the forecast with what actually happened.
**Why:** transition-matrix (roll-rate) forecasting is the standard approach for consumer credit loss forecasting and CECL;
the back-test shows whether its assumptions hold, rather than presenting a forecast without evidence.

## 006 — Removals are censored, not defaults

**Choice:** zero balance codes 15 (whole-loan sale), 16 (reperforming securitization), 96 (repurchase) and any
unrecognized code put the loan in `Removed`. The loan leaves the analysis without a credit outcome.
**Why:** these loans left the sample for reasons unrelated to the borrower paying or not paying. Counting them as
defaults would inflate losses; counting them as performing would hide that we stopped observing them.

## 007 — Unknown status stays unknown

**Choice:** delinquency status `XX` (or any unexpected value) maps to `Unknown`, never to Current.
A warning test lists unexpected values.
**Why:** assuming a missing month is current would quietly understate delinquency.

## 008 — Text in, types in staging

**Choice:** the loader stores every field as text and checks the field count (31 / 35) before loading;
all typing and "not available" codes (9, 99, 999, 9999) are handled in dbt staging.
**Why:** a layout change then fails loudly at load time with a clear message, and every conversion rule is in SQL where it is reviewable and tested.

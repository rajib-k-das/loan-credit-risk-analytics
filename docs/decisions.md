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
the property is taken into REO (status `RA`), or the loan exits through a loss-type zero balance code:
02 third-party sale, 03 short sale or charge-off, 09 REO disposition.
**Why:** 90 days past due is the standard serious-delinquency threshold in mortgage credit and in Basel's default definition.
Loss exits are included because some loans go to a short sale or foreclosure sale without a 90-day record in the sample.
**Configurable:** change the dbt var to test sensitivity (the known-answer test fails at 60 days, as it should).

## 003 — States: Current, 30, 60, 90, 120+, REO, Prepaid, Defaulted (absorbing)

**Choice:** two state columns on `int_loan_months`:
- `delinquency_bucket`: the bucket reported that month. Not absorbing: a loan can roll 90 → 60 → Current.
  Used for **roll-rate matrices**, which must show cures.
- `credit_state`: the same, except that once the default definition is met the loan stays `Defaulted`.
  Used for **default rates, vintage curves and the Markov forecast**.

**REO is a state, not an exit** (found on the real data): after the lender takes the property (`RA`), the loan
keeps reporting every month until the property is sold and the loan exits with code 09. The first build treated `RA` as
an exit and a test caught 36,660 "rows after exit". REO months now have their own bucket, and a loan in REO counts as defaulted.

**Why two:** found while building. With 90+ as the default trigger, an absorbing state model would never show the 90 or 120+
buckets, so a single column would either lose the roll-rate detail or break the default rate. Two columns keep both honest.

## 004 — Flag COVID forbearance; report results with and without it

**Choice:** a month is in forbearance when the Borrower Assistance Status Code is `F`, or Delinquency Due to Disaster is `Y`.
Every default measure has a second version (`*_excl_forbearance`) in which delinquency during forbearance does not count.
Loss exits always count.
**Why:** in 2020 servicers reported forborne loans as delinquent even though borrowers were permitted to skip payments.
Counting them as defaults overstates 2019-vintage credit losses; ignoring them hides real stress. Showing both lets the reader judge.
**Verified on real data:** assistance codes are F (forbearance), T (trial period) and R (repayment plan); F carries most of
the disaster flags. The disaster flag also appears without F in 2017–2018 (hurricane years), so pre-COVID disaster
hardship is caught too. Payment deferral is coded C (granted this month) and P (deferred in a prior month), not Y.

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

## 009 — Loans that default before their first payment: flag, don't drop

**Found on the real data:** two 2006-vintage loans (F06Q10088508, F06Q40224814) have first payment dates in 2011 and 2012,
start reporting a month earlier, and are already 90+ days delinquent in their first reported month. A delinquency before
any payment was due is impossible, so these records are inconsistent, most likely because the loan's terms (and first
payment date) were reset after a modification while the delinquency count carried over.
**Choice:** keep them, flag them (`is_default_before_first_payment`) and exclude them from vintage curves and forecasts.
The test warns while there are a few and fails above 20 loans, which would mean a load or logic problem rather than a quirk.
**Rejected:** silently dropping them (hides the issue) or failing the build on 2 loans in 200,000 (blocks everything over noise).

## 010 — Vintage curves: cumulative rate of loans originated, censored by calendar

**Choice:** the cumulative default rate at month on book *m* is defaults by *m* divided by loans originated, counting only
loans the data can see that far (first payment month + *m* − 1 on or before the last reporting month). Loans that prepay
stay in the denominator. Counts are stored with the rates so a BI tool can combine segments correctly (sum, then divide).
**Why:** this is the standard cumulative default rate used to compare vintages. Counting only observable loans keeps the
youngest loans from dragging the tail of a curve down. `fully_observed_to_month` in the findings script shows where each
curve is complete; past it, curves rest on fewer loans and should be read with care.
**Rejected:** a hazard-rate (survival) curve, which divides by loans still active. It answers a different question
("of loans still alive, how many default next month") and belongs in the forecast, not the vintage comparison.

## 011 — Roll rates and episodes use consecutive months only

**Choice:** a transition is counted only between two consecutive reporting months for the same loan; a delinquency
episode is an unbroken run of 30+ day months (gaps and islands). A missing or unknown month ends a run.
**Why:** pairing across a gap would invent a one-month transition that took longer. Unknown months are rare, so
breaking runs at them costs little and keeps every transition real.

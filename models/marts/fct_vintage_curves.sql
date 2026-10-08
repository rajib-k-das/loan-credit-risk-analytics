-- Cumulative default and prepayment curves: for each vintage and credit-score band, the share of loans that had
-- defaulted (or prepaid) by each month on book.
--
-- Right-censoring (decision 010): a loan counts at month on book m only if the data reaches that far for it,
-- i.e. its first payment month + m - 1 is on or before the last reporting month. Loans that prepay stay in the
-- denominator: the rate is "of the loans originated", the standard cumulative default rate.
-- Counts are stored alongside rates so a BI tool can re-aggregate (sum counts, then divide).

with data_end as (

    select max(reporting_month) as last_reporting_month from {{ ref('int_loan_months') }}

),

loans as (

    select
        dim_loan.loan_id,
        dim_loan.vintage_year,
        dim_loan.credit_score_band,
        dim_loan.orig_upb,
        date_diff('month', dim_loan.first_payment_month, data_end.last_reporting_month) + 1    as months_observable,
        date_diff('month', dim_loan.first_payment_month, dim_loan.default_month) + 1           as default_mob,
        date_diff('month', dim_loan.first_payment_month, dim_loan.default_month_excl_forbearance) + 1
                                                                                               as default_mob_excl_forbearance,
        case when dim_loan.zero_balance_code = '01'
             then date_diff('month', dim_loan.first_payment_month, dim_loan.exit_month) + 1 end as prepay_mob
    from {{ ref('dim_loan') }} as dim_loan
    cross join data_end
    where not dim_loan.is_default_before_first_payment     -- decision 009

),

months_on_book as (

    select range as months_on_book from range(1, 361)

),

loan_months as (

    select loans.*, months_on_book.months_on_book
    from loans
    inner join months_on_book on months_on_book.months_on_book <= loans.months_observable

),

cohorts as (

    select vintage_year, credit_score_band, count(*) as cohort_loans
    from loans
    group by all

)

select
    loan_months.vintage_year,
    loan_months.credit_score_band,
    loan_months.months_on_book,
    any_value(cohorts.cohort_loans)                                                         as cohort_loans,
    count(*)                                                                                as loans_observable,
    sum(loan_months.orig_upb)                                                               as orig_upb_observable,
    count(*) filter (where loan_months.default_mob <= loan_months.months_on_book)           as cumulative_defaults,
    count(*) filter (where loan_months.default_mob_excl_forbearance <= loan_months.months_on_book)
                                                                                            as cumulative_defaults_excl_forbearance,
    coalesce(sum(loan_months.orig_upb) filter (where loan_months.default_mob <= loan_months.months_on_book), 0)
                                                                                            as cumulative_default_upb,
    count(*) filter (where loan_months.prepay_mob <= loan_months.months_on_book)            as cumulative_prepayments,

    cumulative_defaults / loans_observable                                                  as cumulative_default_rate,
    cumulative_defaults_excl_forbearance / loans_observable                                 as cumulative_default_rate_excl_forbearance,
    cumulative_default_upb / orig_upb_observable                                            as cumulative_default_rate_by_balance,
    cumulative_prepayments / loans_observable                                               as cumulative_prepayment_rate
from loan_months
inner join cohorts using (vintage_year, credit_score_band)
group by loan_months.vintage_year, loan_months.credit_score_band, loan_months.months_on_book

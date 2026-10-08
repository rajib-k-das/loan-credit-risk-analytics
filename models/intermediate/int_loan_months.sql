-- One row per loan per month, with two state columns (decision 003):
--
--   delinquency_bucket  what was reported that month. Not absorbing: a loan can go 90 -> 60 -> Current.
--                       Used for roll-rate matrices.
--   credit_state        the same, except that once a loan meets the default definition it stays 'Defaulted'
--                       (absorbing). Used for default rates, vintage curves and the Markov forecast.
--
-- Default definition (decision 002): the first month a loan is 90+ days delinquent
-- (var default_delinquency_months, 3 missed payments), or exits through a loss-type zero balance code.
-- A second version excludes forbearance (decision 004): delinquency while in forbearance does not count.

{% set dq_months = var('default_delinquency_months') %}

with performance as (

    select * from {{ ref('stg_freddie__performance') }}

),

originations as (

    select loan_id, first_payment_month from {{ ref('stg_freddie__originations') }}

),

classified as (

    select
        performance.*,
        originations.first_payment_month,
        date_diff('month', originations.first_payment_month, performance.reporting_month) + 1
                                                                        as months_on_book,

        -- Loss-type exits: third-party sale (02), short sale or charge-off (03), REO disposition (09),
        -- or the REO-acquisition status 'RA'.
        coalesce(zero_balance_code in ('02', '03', '09'), false) or is_reo_acquisition
                                                                        as is_loss_exit,

        -- COVID-era and disaster forbearance (decision 004).
        coalesce(borrower_assistance_status = 'F', false) or coalesce(is_disaster_delinquency, false)
                                                                        as is_in_forbearance,

        case
            when zero_balance_code = '01'                               then 'Prepaid'
            when zero_balance_code in ('02', '03', '09')
                 or is_reo_acquisition                                  then 'Defaulted'
            -- Repurchases, whole-loan sales, reperforming securitizations and any other exit:
            -- the loan leaves the sample without a credit outcome, so it is censored, not defaulted.
            when zero_balance_code is not null                          then 'Removed'
            when months_delinquent = 0                                  then 'Current'
            when months_delinquent = 1                                  then '30'
            when months_delinquent = 2                                  then '60'
            when months_delinquent = 3                                  then '90'
            when months_delinquent >= 4                                 then '120+'
            else 'Unknown'
        end                                                             as delinquency_bucket

    from performance
    left join originations using (loan_id)

),

with_default_tests as (

    select
        *,
        is_loss_exit or coalesce(months_delinquent >= {{ dq_months }}, false)
                                                                        as meets_default_definition,
        is_loss_exit or coalesce(months_delinquent >= {{ dq_months }} and not is_in_forbearance, false)
                                                                        as meets_default_definition_excl_forbearance
    from classified

),

first_default as (

    select
        loan_id,
        min(reporting_month) filter (where meets_default_definition)                  as default_month,
        min(reporting_month) filter (where meets_default_definition_excl_forbearance) as default_month_excl_forbearance
    from with_default_tests
    group by loan_id

)

select
    with_default_tests.loan_id,
    with_default_tests.vintage_year,
    with_default_tests.reporting_month,
    with_default_tests.first_payment_month,
    with_default_tests.months_on_book,
    with_default_tests.loan_age,
    with_default_tests.current_upb,
    with_default_tests.current_interest_rate,
    with_default_tests.delinquency_status_code,
    with_default_tests.months_delinquent,
    with_default_tests.delinquency_bucket,

    case when with_default_tests.reporting_month >= first_default.default_month
         then 'Defaulted' else with_default_tests.delinquency_bucket end         as credit_state,
    case when with_default_tests.reporting_month >= first_default.default_month_excl_forbearance
         then 'Defaulted' else with_default_tests.delinquency_bucket end         as credit_state_excl_forbearance,

    coalesce(with_default_tests.reporting_month = first_default.default_month, false)
                                                                                 as is_default_event,
    coalesce(with_default_tests.reporting_month = first_default.default_month_excl_forbearance, false)
                                                                                 as is_default_event_excl_forbearance,
    first_default.default_month,
    first_default.default_month_excl_forbearance,

    with_default_tests.is_loss_exit,
    with_default_tests.is_in_forbearance,
    with_default_tests.borrower_assistance_status,
    with_default_tests.has_payment_deferral,
    with_default_tests.is_modified,
    with_default_tests.zero_balance_code,
    with_default_tests.zero_balance_month,
    with_default_tests.actual_loss

from with_default_tests
left join first_default using (loan_id)

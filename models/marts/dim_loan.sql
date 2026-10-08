-- One row per loan: origination attributes, risk bands, and how the loan has performed so far.

with originations as (

    select * from {{ ref('stg_freddie__originations') }}

),

loan_history as (

    select
        loan_id,
        min(reporting_month)                                            as first_reported_month,
        max(reporting_month)                                            as last_reported_month,
        count(*)                                                        as months_reported,
        any_value(default_month)                                        as default_month,
        any_value(default_month_excl_forbearance)                       as default_month_excl_forbearance,
        max(zero_balance_code)                                          as zero_balance_code,
        max(reporting_month) filter (where zero_balance_code is not null) as exit_month,
        max(months_delinquent)                                          as max_months_delinquent,
        bool_or(is_in_forbearance)                                      as ever_in_forbearance,
        bool_or(is_reo_acquisition)                                     as ever_reo,
        bool_or(is_modified)                                            as ever_modified,
        sum(actual_loss) filter (where zero_balance_code is not null)   as actual_loss,
        bool_or(is_default_before_first_payment)                        as is_default_before_first_payment
    from {{ ref('int_loan_months') }}
    group by loan_id

)

select
    originations.loan_id,
    originations.vintage_year,
    originations.first_payment_month,
    originations.orig_upb,
    originations.orig_interest_rate,
    originations.orig_loan_term,
    originations.credit_score,
    originations.orig_ltv,
    originations.orig_cltv,
    originations.orig_dti,
    originations.loan_purpose,
    originations.channel,
    originations.occupancy_status,
    originations.property_type,
    originations.property_state,
    originations.number_of_borrowers,
    originations.is_first_time_homebuyer,
    originations.seller_name,

    case
        when originations.credit_score is null then 'Unknown'
        when originations.credit_score < 620   then '<620'
        when originations.credit_score < 680   then '620-679'
        when originations.credit_score < 720   then '680-719'
        when originations.credit_score < 760   then '720-759'
        else '760+'
    end                                                                 as credit_score_band,
    case
        when originations.orig_ltv is null then 'Unknown'
        when originations.orig_ltv <= 60   then '<=60'
        when originations.orig_ltv <= 80   then '61-80'
        when originations.orig_ltv <= 90   then '81-90'
        else '>90'
    end                                                                 as ltv_band,
    case
        when originations.orig_dti is null then 'Unknown'
        when originations.orig_dti <= 36   then '<=36'
        when originations.orig_dti <= 43   then '37-43'
        else '>43'
    end                                                                 as dti_band,

    loan_history.first_reported_month,
    loan_history.last_reported_month,
    loan_history.months_reported,
    case
        when loan_history.zero_balance_code = '01'                      then 'Prepaid'
        when loan_history.zero_balance_code in ('02', '03', '09')       then 'Loss exit'
        when loan_history.zero_balance_code is not null                 then 'Removed'
        when loan_history.default_month is not null                     then 'Active, defaulted'
        else 'Active'
    end                                                                 as loan_status,
    loan_history.zero_balance_code,
    loan_history.exit_month,
    loan_history.default_month,
    loan_history.default_month_excl_forbearance,
    loan_history.default_month is not null                              as has_defaulted,
    loan_history.default_month_excl_forbearance is not null             as has_defaulted_excl_forbearance,
    date_diff('month', originations.first_payment_month, loan_history.default_month) + 1
                                                                        as months_to_default,
    loan_history.max_months_delinquent,
    loan_history.ever_in_forbearance,
    loan_history.ever_reo,
    loan_history.ever_modified,
    loan_history.actual_loss,
    coalesce(loan_history.is_default_before_first_payment, false)       as is_default_before_first_payment

from originations
left join loan_history using (loan_id)

-- One row per loan per month, typed.
-- Delinquency status is text in the source: '0', '1', '2', ... (months behind), 'RA' (REO acquisition)
-- or 'XX' (unknown). It is mapped explicitly rather than cast, so 'RA' and 'XX' can never become numbers.

with source as (

    select * from {{ source('freddie', 'loan_performance') }}

)

select
    trim(loan_id)                                                       as loan_id,
    vintage_year,
    {{ yyyymm_to_date('reporting_period') }}                            as reporting_month,
    try_cast(loan_age as integer)                                       as loan_age,
    try_cast(remaining_months_to_maturity as integer)                   as remaining_months_to_maturity,
    try_cast(current_upb as decimal(14, 2))                             as current_upb,
    try_cast(current_interest_rate as decimal(7, 3))                    as current_interest_rate,

    trim(delinquency_status)                                            as delinquency_status_code,
    case when regexp_full_match(trim(delinquency_status), '[0-9]{1,3}')
         then cast(trim(delinquency_status) as integer) end             as months_delinquent,
    trim(delinquency_status) = 'RA'                                     as is_reo_acquisition,

    nullif(trim(zero_balance_code), '')                                 as zero_balance_code,
    {{ yyyymm_to_date('zero_balance_date') }}                           as zero_balance_month,
    try_cast(zero_balance_removal_upb as decimal(14, 2))                as zero_balance_removal_upb,

    -- Hardship and forbearance indicators (decision 004)
    nullif(trim(borrower_assistance_status), '')                        as borrower_assistance_status,
    trim(delinquency_due_to_disaster) = 'Y'                             as is_disaster_delinquency,
    -- Payment deferral: 'C' = deferral granted this month, 'P' = a deferral in a prior month (decision 004).
    trim(payment_deferral_flag) = 'C'                                   as is_deferral_month,
    trim(payment_deferral_flag) in ('C', 'P')                           as has_payment_deferral,
    trim(modification_flag) in ('Y', 'P')                               as is_modified,

    -- Loss components, populated only for loans that ended in a loss
    try_cast(actual_loss as decimal(14, 2))                             as actual_loss,
    try_cast(net_sales_proceeds as decimal(14, 2))                      as net_sales_proceeds,
    try_cast(total_expenses as decimal(14, 2))                          as total_expenses,
    nullif(try_cast(estimated_ltv as integer), 999)                     as estimated_ltv,

    nullif(trim(servicer_name), '')                                     as servicer_name,
    source_file

from source

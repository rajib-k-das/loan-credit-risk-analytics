-- One row per loan, typed. Freddie Mac codes "not available" as 9, 99, 999 or 9999 depending on the field;
-- these become nulls so they can never leak into an average.

with source as (

    select * from {{ source('freddie', 'loan_origination') }}

)

select
    trim(loan_id)                                                       as loan_id,
    vintage_year,
    {{ yyyymm_to_date('first_payment_date') }}                          as first_payment_month,
    {{ yyyymm_to_date('maturity_date') }}                               as maturity_month,

    -- Borrower
    case when try_cast(credit_score as integer) between 300 and 850
         then try_cast(credit_score as integer) end                     as credit_score,
    case when try_cast(vantage_score as integer) between 300 and 850
         then try_cast(vantage_score as integer) end                    as vantage_score,
    nullif(try_cast(orig_dti as integer), 999)                          as orig_dti,
    nullif(try_cast(number_of_borrowers as integer), 99)                as number_of_borrowers,
    case trim(first_time_homebuyer_flag) when 'Y' then true when 'N' then false end
                                                                        as is_first_time_homebuyer,

    -- Loan
    try_cast(orig_upb as decimal(14, 2))                                as orig_upb,
    try_cast(orig_interest_rate as decimal(7, 3))                       as orig_interest_rate,
    try_cast(orig_loan_term as integer)                                 as orig_loan_term,
    nullif(try_cast(orig_ltv as integer), 999)                          as orig_ltv,
    nullif(try_cast(orig_cltv as integer), 999)                         as orig_cltv,
    nullif(try_cast(mi_pct as integer), 999)                            as mi_pct,
    case trim(loan_purpose)
        when 'P' then 'Purchase'
        when 'C' then 'Cash-out refinance'
        when 'N' then 'No cash-out refinance'
        when 'R' then 'Refinance, not specified'
    end                                                                 as loan_purpose,
    case trim(channel)
        when 'R' then 'Retail'
        when 'B' then 'Broker'
        when 'C' then 'Correspondent'
        when 'T' then 'TPO, not specified'
    end                                                                 as channel,
    nullif(trim(amortization_type), '')                                 as amortization_type,
    trim(interest_only_flag) = 'Y'                                      as is_interest_only,
    trim(harp_indicator) = 'Y'                                          as is_harp,
    trim(super_conforming_flag) = 'Y'                                   as is_super_conforming,

    -- Property
    case trim(occupancy_status)
        when 'P' then 'Primary residence'
        when 'S' then 'Second home'
        when 'I' then 'Investment'
    end                                                                 as occupancy_status,
    nullif(nullif(trim(property_type), ''), '99')                       as property_type,
    nullif(try_cast(number_of_units as integer), 99)                    as number_of_units,
    nullif(trim(property_state), '')                                    as property_state,
    nullif(trim(msa), '')                                               as msa,
    nullif(trim(postal_code), '')                                       as postal_code_3,

    nullif(trim(seller_name), '')                                       as seller_name,
    source_file

from source

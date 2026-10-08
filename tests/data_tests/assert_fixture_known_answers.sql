-- Known answers for the four synthetic test loans in tests/fixtures (see make_fixtures.py).
-- Returns a row for every expectation that doesn't hold. Skipped when the fixture isn't loaded.

with expected (loan_id, reporting_month, delinquency_bucket, credit_state, credit_state_excl_forbearance,
               default_month, default_month_excl_forbearance) as (

    values
    -- Prepays: never defaults.
    ('FIXTURE00001', date '2019-06-01', 'Prepaid',   'Prepaid',   'Prepaid',   null::date,        null::date),
    -- Defaults at the first 90-day month (July 2019) and stays defaulted through 120 days, REO and the sale.
    ('FIXTURE00002', date '2019-06-01', '60',        '60',        '60',        date '2019-07-01', date '2019-07-01'),
    ('FIXTURE00002', date '2019-07-01', '90',        'Defaulted', 'Defaulted', date '2019-07-01', date '2019-07-01'),
    ('FIXTURE00002', date '2019-08-01', '120+',      'Defaulted', 'Defaulted', date '2019-07-01', date '2019-07-01'),
    ('FIXTURE00002', date '2019-09-01', 'REO',       'Defaulted', 'Defaulted', date '2019-07-01', date '2019-07-01'),
    ('FIXTURE00002', date '2019-10-01', 'Defaulted', 'Defaulted', 'Defaulted', date '2019-07-01', date '2019-07-01'),
    -- 90 days late in forbearance: a raw default, but not a default once forbearance is excluded.
    ('FIXTURE00003', date '2020-06-01', '90',        'Defaulted', '90',        date '2020-06-01', null::date),
    ('FIXTURE00003', date '2020-07-01', 'Current',   'Defaulted', 'Current',   date '2020-06-01', null::date),
    -- Unknown status stays unknown; a removal is censored, not a default.
    ('FIXTURE00004', date '2019-04-01', 'Unknown',   'Unknown',   'Unknown',   null::date,        null::date),
    ('FIXTURE00004', date '2019-07-01', 'Removed',   'Removed',   'Removed',   null::date,        null::date)

),

fixture_loaded as (

    select count(*) > 0 as is_loaded
    from {{ ref('int_loan_months') }}
    where loan_id like 'FIXTURE%'

)

select expected.*, actual.delinquency_bucket as actual_bucket, actual.credit_state as actual_state,
       actual.credit_state_excl_forbearance as actual_state_excl, actual.default_month as actual_default_month,
       actual.default_month_excl_forbearance as actual_default_month_excl
from expected
cross join fixture_loaded
left join {{ ref('int_loan_months') }} as actual
    on  actual.loan_id = expected.loan_id
    and actual.reporting_month = expected.reporting_month
where fixture_loaded.is_loaded
  and (   actual.loan_id is null
       or actual.delinquency_bucket is distinct from expected.delinquency_bucket
       or actual.credit_state is distinct from expected.credit_state
       or actual.credit_state_excl_forbearance is distinct from expected.credit_state_excl_forbearance
       or actual.default_month is distinct from expected.default_month
       or actual.default_month_excl_forbearance is distinct from expected.default_month_excl_forbearance)

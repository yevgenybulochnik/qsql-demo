-- Synthetic pharmacy/medical claims + eligibility for the kitchen-sink demo.
-- Entirely fake and deterministic (generate_series, no random()) — reseeding
-- produces identical data; nothing here is PHI. Every table and column carries
-- a COMMENT: the TUI catalog browser (S) surfaces them in the field-path
-- sheet's description column.
--
-- Runs automatically via /docker-entrypoint-initdb.d on first boot of the
-- kitchen-sink stack's empty volume (POSTGRES_DB=quicksql_claims). Also
-- reusable to seed the *root* compose stack's quicksql_claims database — the
-- one the postgres-marked tests introspect (idempotent: DROP SCHEMA ... CASCADE):
--
--   docker compose exec -T postgres psql -U quicksql -d quicksql_claims -q \
--     < demo/kitchen-sink/pg-init/10-claims-core.sql
--
-- Then: uv run quicksql tui demo/kitchen-sink/kitchen-sink.qsql

DROP SCHEMA IF EXISTS claims CASCADE;
CREATE SCHEMA claims;
COMMENT ON SCHEMA claims IS 'synthetic claims warehouse — fake members, fake claims, no PHI';

-- ---------- eligibility ----------

CREATE TABLE claims.eligibility (
  member_id     text NOT NULL,
  subscriber_id text NOT NULL,
  relationship  text NOT NULL,
  birth_date    date NOT NULL,
  gender        text NOT NULL,
  plan_code     text NOT NULL,
  group_id      text NOT NULL,
  eff_date      date NOT NULL,
  term_date     date,
  PRIMARY KEY (member_id, eff_date)
);
COMMENT ON TABLE  claims.eligibility               IS 'member eligibility spans (one row per member per effective date)';
COMMENT ON COLUMN claims.eligibility.member_id     IS 'synthetic member identifier (M#####)';
COMMENT ON COLUMN claims.eligibility.subscriber_id IS 'family subscriber the member rides on (S#####)';
COMMENT ON COLUMN claims.eligibility.relationship  IS 'relationship to subscriber: subscriber | spouse | dependent';
COMMENT ON COLUMN claims.eligibility.birth_date    IS 'synthetic date of birth';
COMMENT ON COLUMN claims.eligibility.gender        IS 'administrative gender code: M | F';
COMMENT ON COLUMN claims.eligibility.plan_code     IS 'benefit plan: PPO1 | HMO2 | HDHP';
COMMENT ON COLUMN claims.eligibility.group_id      IS 'employer group number (G###)';
COMMENT ON COLUMN claims.eligibility.eff_date      IS 'coverage effective date (span start)';
COMMENT ON COLUMN claims.eligibility.term_date     IS 'coverage termination date; NULL while active';

INSERT INTO claims.eligibility
SELECT format('M%s', lpad(g::text, 5, '0')),
       format('S%s', lpad((((g - 1) / 3) * 3 + 1)::text, 5, '0')),
       CASE g % 3 WHEN 1 THEN 'subscriber' WHEN 2 THEN 'spouse' ELSE 'dependent' END,
       CASE WHEN g % 3 = 0
            THEN DATE '2005-01-01' + ((g * 61) % 6000)   -- dependents skew young
            ELSE DATE '1955-01-01' + ((g * 89) % 14600)
       END,
       CASE g % 2 WHEN 0 THEN 'F' ELSE 'M' END,
       (ARRAY['PPO1', 'HMO2', 'HDHP'])[1 + g % 3],
       format('G%s', 100 + g % 7),
       DATE '2025-01-01',
       CASE WHEN g % 10 = 0 THEN DATE '2026-03-31' END    -- ~10% termed
FROM generate_series(1, 500) g;

-- ---------- medical claims ----------

CREATE TABLE claims.medical_claims (
  claim_id         text NOT NULL,
  claim_line       int  NOT NULL,
  member_id        text NOT NULL,
  provider_npi     text NOT NULL,
  place_of_service text NOT NULL,
  diagnosis_code   text NOT NULL,
  procedure_code   text NOT NULL,
  service_date     date NOT NULL,
  billed_amount    numeric(10,2) NOT NULL,
  allowed_amount   numeric(10,2) NOT NULL,
  paid_amount      numeric(10,2) NOT NULL,
  member_liability numeric(10,2) NOT NULL,
  claim_status     text NOT NULL,
  adjudicated_at   date,
  PRIMARY KEY (claim_id, claim_line)
);
COMMENT ON TABLE  claims.medical_claims                  IS 'professional/facility claim lines (synthetic)';
COMMENT ON COLUMN claims.medical_claims.claim_id         IS 'claim header identifier (MC######); lines share it';
COMMENT ON COLUMN claims.medical_claims.claim_line       IS 'line number within the claim (1..n)';
COMMENT ON COLUMN claims.medical_claims.member_id        IS 'member the service was rendered to -> claims.eligibility';
COMMENT ON COLUMN claims.medical_claims.provider_npi     IS 'rendering provider NPI (synthetic 10-digit)';
COMMENT ON COLUMN claims.medical_claims.place_of_service IS 'CMS place-of-service code: 11 office, 22 outpatient, 23 ER, 81 lab';
COMMENT ON COLUMN claims.medical_claims.diagnosis_code   IS 'primary ICD-10-CM diagnosis on the line';
COMMENT ON COLUMN claims.medical_claims.procedure_code   IS 'CPT/HCPCS procedure code';
COMMENT ON COLUMN claims.medical_claims.service_date     IS 'date of service';
COMMENT ON COLUMN claims.medical_claims.billed_amount    IS 'provider billed charges';
COMMENT ON COLUMN claims.medical_claims.allowed_amount   IS 'plan-allowed amount after pricing; 0 when denied';
COMMENT ON COLUMN claims.medical_claims.paid_amount      IS 'plan-paid amount; 0 when denied or reversed';
COMMENT ON COLUMN claims.medical_claims.member_liability IS 'member cost share (copay/coinsurance/deductible)';
COMMENT ON COLUMN claims.medical_claims.claim_status     IS 'adjudication outcome: paid | denied | reversed';
COMMENT ON COLUMN claims.medical_claims.adjudicated_at   IS 'adjudication date; NULL while in process';

INSERT INTO claims.medical_claims
SELECT format('MC%s', lpad(((t.g + 1) / 2)::text, 6, '0')),
       2 - t.g % 2,
       format('M%s', lpad((1 + (t.g * 17) % 500)::text, 5, '0')),
       format('1%s', lpad((234567 + (t.g % 40) * 101317)::text, 9, '0')),
       (ARRAY['11', '22', '23', '81'])[1 + t.g % 4],
       (ARRAY['E11.9', 'I10', 'J45.909', 'M54.50', 'Z00.00', 'F41.1', 'K21.9', 'N39.0'])[1 + (t.g * 3) % 8],
       (ARRAY['99213', '99214', '80053', '93000', '71046', '36415', '97110', '99285'])[1 + (t.g * 5) % 8],
       t.svc,
       t.billed,
       CASE WHEN t.status = 'denied' THEN 0 ELSE round(t.billed * 0.62, 2) END,
       CASE WHEN t.status = 'paid' THEN round(t.billed * 0.62 * 0.85, 2) ELSE 0 END,
       CASE WHEN t.status = 'paid' THEN round(t.billed * 0.62 * 0.15, 2) ELSE 0 END,
       t.status,
       CASE WHEN t.g % 37 = 0 THEN NULL ELSE t.svc + 14 END
FROM (
  SELECT g,
         DATE '2025-01-01' + ((g * 11) % 540) AS svc,
         round((80 + (g * 53) % 2200)::numeric, 2) AS billed,
         CASE WHEN g % 50 = 0 THEN 'reversed'
              WHEN g % 16 = 0 THEN 'denied'
              ELSE 'paid' END AS status
  FROM generate_series(1, 6000) g
) t;

-- ---------- pharmacy claims ----------

CREATE TABLE claims.pharmacy_claims (
  rx_claim_id     text NOT NULL PRIMARY KEY,
  member_id       text NOT NULL,
  fill_date       date NOT NULL,
  ndc             text NOT NULL,
  drug_name       text NOT NULL,
  brand_generic   text NOT NULL,
  days_supply     int  NOT NULL,
  quantity        numeric(10,2) NOT NULL,
  refill_number   int  NOT NULL,
  pharmacy_npi    text NOT NULL,
  prescriber_npi  text NOT NULL,
  ingredient_cost numeric(10,2) NOT NULL,
  dispensing_fee  numeric(10,2) NOT NULL,
  patient_pay     numeric(10,2) NOT NULL,
  plan_paid       numeric(10,2) NOT NULL,
  formulary       boolean NOT NULL,
  claim_status    text NOT NULL
);
COMMENT ON TABLE  claims.pharmacy_claims                 IS 'retail pharmacy fills (synthetic)';
COMMENT ON COLUMN claims.pharmacy_claims.rx_claim_id     IS 'pharmacy claim identifier (RX######)';
COMMENT ON COLUMN claims.pharmacy_claims.member_id       IS 'member the fill was dispensed to -> claims.eligibility';
COMMENT ON COLUMN claims.pharmacy_claims.fill_date       IS 'dispense date';
COMMENT ON COLUMN claims.pharmacy_claims.ndc             IS '11-digit National Drug Code (synthetic)';
COMMENT ON COLUMN claims.pharmacy_claims.drug_name       IS 'drug label name and strength';
COMMENT ON COLUMN claims.pharmacy_claims.brand_generic   IS 'B brand | G generic';
COMMENT ON COLUMN claims.pharmacy_claims.days_supply     IS 'days of therapy dispensed (30 or 90)';
COMMENT ON COLUMN claims.pharmacy_claims.quantity        IS 'metric quantity dispensed (tabs/caps/mL)';
COMMENT ON COLUMN claims.pharmacy_claims.refill_number   IS '0 for the original fill, 1..n for refills';
COMMENT ON COLUMN claims.pharmacy_claims.pharmacy_npi    IS 'dispensing pharmacy NPI (synthetic 10-digit)';
COMMENT ON COLUMN claims.pharmacy_claims.prescriber_npi  IS 'prescribing provider NPI (synthetic 10-digit)';
COMMENT ON COLUMN claims.pharmacy_claims.ingredient_cost IS 'drug ingredient cost';
COMMENT ON COLUMN claims.pharmacy_claims.dispensing_fee  IS 'pharmacy dispensing fee';
COMMENT ON COLUMN claims.pharmacy_claims.patient_pay     IS 'member out-of-pocket for the fill';
COMMENT ON COLUMN claims.pharmacy_claims.plan_paid       IS 'plan-paid amount (cost + fee - patient pay); 0 when reversed';
COMMENT ON COLUMN claims.pharmacy_claims.formulary       IS 'whether the product was on formulary at fill time';
COMMENT ON COLUMN claims.pharmacy_claims.claim_status    IS 'paid | reversed';

INSERT INTO claims.pharmacy_claims
SELECT format('RX%s', lpad(t.g::text, 6, '0')),
       format('M%s', lpad((1 + (t.g * 23) % 500)::text, 5, '0')),
       DATE '2025-01-01' + ((t.g * 7) % 540),
       (ARRAY['00093104801', '00071015523', '68180051303', '69097012415', '00378602001',
              '68180035106', '00173068224', '00088221905', '00527134301', '67877022310'])[t.drug],
       (ARRAY['METFORMIN HCL 500MG TAB', 'ATORVASTATIN 20MG TAB', 'LISINOPRIL 10MG TAB',
              'AMLODIPINE 5MG TAB', 'OMEPRAZOLE 20MG CAP', 'SERTRALINE 50MG TAB',
              'ALBUTEROL HFA 90MCG INH', 'INSULIN GLARGINE 100U/ML VIAL',
              'LEVOTHYROXINE 50MCG TAB', 'GABAPENTIN 300MG CAP'])[t.drug],
       CASE WHEN t.drug IN (7, 8) THEN 'B' ELSE 'G' END,
       t.days,
       t.days * (1 + t.g % 2),
       t.g % 6,
       format('1%s', lpad((345678 + (t.g % 25) * 202119)::text, 9, '0')),
       format('1%s', lpad((456789 + (t.g % 40) * 101317)::text, 9, '0')),
       t.cost,
       2.50,
       CASE WHEN t.status = 'reversed' THEN 0 ELSE least(10.00, round(t.cost * 0.2, 2)) END,
       CASE WHEN t.status = 'reversed' THEN 0
            ELSE t.cost + 2.50 - least(10.00, round(t.cost * 0.2, 2)) END,
       t.g % 12 <> 0,
       t.status
FROM (
  SELECT g,
         1 + g % 10 AS drug,
         CASE WHEN g % 4 = 0 THEN 90 ELSE 30 END AS days,
         round((4 + (g * 31) % 350)::numeric
               * CASE WHEN 1 + g % 10 IN (7, 8) THEN 8 ELSE 1 END, 2) AS cost,
         CASE WHEN g % 25 = 0 THEN 'reversed' ELSE 'paid' END AS status
  FROM generate_series(1, 5000) g
) t;

ANALYZE claims.eligibility, claims.medical_claims, claims.pharmacy_claims;

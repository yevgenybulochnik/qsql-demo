#!/usr/bin/env python3
"""Emit pg-init/20-claims-wide.sql: claims.claims_837_wide, a flattened
837-style medical claim extract that is deliberately ultra-wide (250 columns).

Deterministic on purpose — no randomness, no timestamps — so the committed
output never drifts:

    uv run python demo/kitchen-sink/tools/gen_wide_claims.py \
        > demo/kitchen-sink/pg-init/20-claims-wide.sql

Row values are modular-arithmetic expressions over the generate_series
variable ``g`` (same style as 10-claims-core.sql), so the INSERT stays one
compact statement instead of thousands of literal rows. member_id lines up
with claims.eligibility (M00001..M00500) so joins hit.
"""

TABLE = "claims.claims_837_wide"
ROWS = 2000
EXPECTED_COLUMNS = 250


def arr(vals: list[str], mult: int, off: int = 0) -> str:
    """A deterministic pick from a pool of text literals."""
    items = ", ".join(f"'{v}'" for v in vals)
    return f"(ARRAY[{items}])[1 + (g * {mult} + {off}) % {len(vals)}]"


def money(base_cents: int, mult: int, mod: int) -> str:
    """A dollars-and-cents amount in [base, base + mod) cents."""
    return f"round(({base_cents} + (g * {mult}) % {mod})::numeric / 100, 2)"


def npi(seed: int, mult: int, mod: int) -> str:
    """A synthetic 10-digit NPI (leading 1, like the core seed)."""
    return f"format('1%s', lpad(({seed} + (g % {mod}) * {mult})::text, 9, '0'))"


def yn(mod: int, off: int = 0) -> str:
    """An EDI-style Y/N flag, mostly N."""
    return f"CASE WHEN (g + {off}) % {mod} = 0 THEN 'Y' ELSE 'N' END"


LAST_NAMES = ["NGUYEN", "GARCIA", "SMITH", "JOHNSON", "KIM", "PATEL", "OKAFOR", "MULLER"]
FIRST_NAMES = ["ALEX", "SAM", "JORDAN", "TAYLOR", "CASEY", "ROBIN", "MORGAN", "JAMIE"]
CITIES = ["SPRINGFIELD", "RIVERSIDE", "FRANKLIN", "GREENVILLE", "CLINTON", "SALEM", "MADISON", "GEORGETOWN"]
STATES = ["OH", "TX", "CA", "NY", "IL", "GA", "WA", "PA"]
STREETS = ["100 MAIN ST", "42 OAK AVE", "7 ELM CT", "1600 BIRCH BLVD", "250 CEDAR LN", "9 WALNUT WAY", "310 MAPLE DR", "88 PINE RD"]
DIAGS = ["E11.9", "I10", "J45.909", "M54.50", "Z00.00", "F41.1", "K21.9", "N39.0", "E78.5", "J06.9", "R51.9", "M25.561"]
PROCS = ["99213", "99214", "80053", "93000", "71046", "36415", "97110", "99285", "82947", "85025"]
MODIFIERS = ["25", "59", "76", "LT", "RT", "GT"]
REVENUE_CODES = ["0450", "0300", "0250", "0636", "0730"]
TAXONOMIES = ["207Q00000X", "207R00000X", "208D00000X", "261QP2300X", "282N00000X", "291U00000X"]
SPECIALTIES = ["01", "08", "11", "20", "30", "69"]

STMT_FROM = "DATE '2025-01-01' + ((g * 11) % 540)"
BILLED = money(8000, 5300, 220000)
ALLOWED = f"round({BILLED} * 0.62, 2)"
STATUS = "CASE WHEN g % 50 = 0 THEN 'reversed' WHEN g % 16 = 0 THEN 'denied' ELSE 'paid' END"

Col = tuple[str, str, str, str]  # (name, sql_type, comment, value_expr)


def zip5(mult: int, off: int = 0) -> str:
    return f"lpad((10000 + (g * {mult} + {off}) % 89999)::text, 5, '0')"


def phone(mult: int) -> str:
    return f"format('555%s', lpad(((g * {mult}) % 10000000)::text, 7, '0'))"


def claim_header() -> list[Col]:
    return [
        ("claim_id", "text NOT NULL", "wide-extract claim identifier (WC#######)",
         "format('WC%s', lpad(g::text, 7, '0'))"),
        ("claim_type", "text NOT NULL", "professional (837P) or institutional (837I)",
         arr(["professional", "institutional"], 1)),
        ("claim_frequency_code", "text NOT NULL", "NUBC frequency: 1 original, 7 replacement, 8 void",
         "CASE WHEN g % 20 = 0 THEN '7' WHEN g % 41 = 0 THEN '8' ELSE '1' END"),
        ("patient_control_number", "text NOT NULL", "provider-assigned patient account number",
         "format('PCN%s', lpad(((g * 13) % 100000)::text, 6, '0'))"),
        ("statement_from_date", "date NOT NULL", "earliest service date on the claim", STMT_FROM),
        ("statement_to_date", "date NOT NULL", "latest service date on the claim", f"{STMT_FROM} + (g % 3)"),
        ("received_date", "date NOT NULL", "date the payer received the claim", f"{STMT_FROM} + 5"),
        ("adjudication_date", "date", "date the claim finalized; NULL while in process",
         f"CASE WHEN g % 37 = 0 THEN NULL ELSE {STMT_FROM} + 19 END"),
        ("claim_status", "text NOT NULL", "adjudication outcome: paid | denied | reversed", STATUS),
        ("total_claim_charge", "numeric(10,2) NOT NULL", "total billed charges across all lines", BILLED),
        ("place_of_service", "text NOT NULL", "CMS place-of-service code",
         arr(["11", "21", "22", "23", "81"], 7)),
        ("bill_type_code", "text", "NUBC bill type (institutional claims only)",
         f"CASE WHEN g % 2 = 0 THEN {arr(['111', '131', '137', '851'], 3)} END"),
    ]


def patient_subscriber() -> list[Col]:
    return [
        ("member_id", "text NOT NULL", "member the claim was rendered to -> claims.eligibility",
         "format('M%s', lpad((1 + (g * 29) % 500)::text, 5, '0'))"),
        ("patient_last_name", "text NOT NULL", "patient last name (synthetic)", arr(LAST_NAMES, 3)),
        ("patient_first_name", "text NOT NULL", "patient first name (synthetic)", arr(FIRST_NAMES, 5)),
        ("patient_middle_initial", "text", "patient middle initial; often absent",
         f"CASE WHEN g % 3 = 0 THEN {arr(['A', 'J', 'L', 'M', 'R'], 7)} END"),
        ("patient_dob", "date NOT NULL", "patient date of birth (synthetic)",
         "DATE '1955-01-01' + ((g * 89) % 21900)"),
        ("patient_gender", "text NOT NULL", "administrative gender code: M | F",
         "CASE g % 2 WHEN 0 THEN 'F' ELSE 'M' END"),
        ("patient_addr_line1", "text NOT NULL", "patient street address (synthetic)", arr(STREETS, 11)),
        ("patient_addr_line2", "text", "patient address line 2; usually NULL",
         f"CASE WHEN g % 7 = 0 THEN format('APT %s', 1 + g % 40) END"),
        ("patient_city", "text NOT NULL", "patient city (synthetic)", arr(CITIES, 13)),
        ("patient_state", "text NOT NULL", "patient state code", arr(STATES, 13)),
        ("patient_zip", "text NOT NULL", "patient ZIP code (synthetic)", zip5(37)),
        ("patient_county_fips", "text NOT NULL", "patient county FIPS code (synthetic)",
         "lpad((39001 + (g * 17) % 173 * 2)::text, 5, '0')"),
        ("patient_phone", "text NOT NULL", "patient phone (synthetic 555 number)", phone(31)),
        ("patient_relationship_code", "text NOT NULL", "patient relationship to subscriber: 18 self, 01 spouse, 19 child",
         arr(["18", "01", "19"], 1)),
        ("subscriber_id", "text NOT NULL", "subscriber certificate number (S#####)",
         "format('S%s', lpad((((1 + (g * 29) % 500 - 1) / 3) * 3 + 1)::text, 5, '0'))"),
        ("subscriber_last_name", "text NOT NULL", "subscriber last name (synthetic)", arr(LAST_NAMES, 3)),
        ("subscriber_first_name", "text NOT NULL", "subscriber first name (synthetic)", arr(FIRST_NAMES, 7, 2)),
        ("subscriber_dob", "date NOT NULL", "subscriber date of birth (synthetic)",
         "DATE '1955-01-01' + ((g * 83) % 14600)"),
        ("subscriber_gender", "text NOT NULL", "subscriber administrative gender code: M | F",
         "CASE g % 3 WHEN 0 THEN 'F' ELSE 'M' END"),
        ("subscriber_addr_line1", "text NOT NULL", "subscriber street address (synthetic)", arr(STREETS, 11)),
        ("subscriber_city", "text NOT NULL", "subscriber city (synthetic)", arr(CITIES, 13)),
        ("subscriber_state", "text NOT NULL", "subscriber state code", arr(STATES, 13)),
        ("subscriber_zip", "text NOT NULL", "subscriber ZIP code (synthetic)", zip5(37)),
        ("subscriber_phone", "text NOT NULL", "subscriber phone (synthetic 555 number)", phone(43)),
        ("group_id", "text NOT NULL", "employer group number (G###) -> claims.eligibility",
         "format('G%s', 100 + (1 + (g * 29) % 500) % 7)"),
        ("plan_code", "text NOT NULL", "benefit plan: PPO1 | HMO2 | HDHP -> claims.eligibility",
         "(ARRAY['PPO1', 'HMO2', 'HDHP'])[1 + (1 + (g * 29) % 500) % 3]"),
        ("coverage_level_code", "text NOT NULL", "coverage level: EMP | ESP | FAM",
         arr(["EMP", "ESP", "FAM"], 5)),
        ("benefit_plan_name", "text NOT NULL", "marketing name of the benefit plan",
         arr(["CHOICE PPO", "SELECT HMO", "SAVER HDHP"], 5, 1)),
        ("enrollment_eff_date", "date NOT NULL", "coverage effective date at time of service",
         "DATE '2025-01-01'"),
        ("enrollment_term_date", "date", "coverage termination date; NULL while active",
         "CASE WHEN (1 + (g * 29) % 500) % 10 = 0 THEN DATE '2026-03-31' END"),
    ]


def providers() -> list[Col]:
    return [
        # billing provider (9)
        ("billing_provider_npi", "text NOT NULL", "billing provider NPI (synthetic)", npi(234567, 101317, 40)),
        ("billing_provider_tax_id", "text NOT NULL", "billing provider EIN (synthetic)",
         "format('9%s', lpad((1000000 + (g % 40) * 20233)::text, 8, '0'))"),
        ("billing_provider_taxonomy", "text NOT NULL", "billing provider taxonomy code", arr(TAXONOMIES, 3)),
        ("billing_provider_org_name", "text NOT NULL", "billing provider organization name (synthetic)",
         arr(["LAKESIDE MEDICAL GROUP", "SUMMIT HEALTH PARTNERS", "RIVERBEND CLINIC", "NORTHSTAR PHYSICIANS"], 3)),
        ("billing_provider_addr_line1", "text NOT NULL", "billing provider street address", arr(STREETS, 17)),
        ("billing_provider_city", "text NOT NULL", "billing provider city", arr(CITIES, 19)),
        ("billing_provider_state", "text NOT NULL", "billing provider state", arr(STATES, 19)),
        ("billing_provider_zip", "text NOT NULL", "billing provider ZIP", zip5(41, 7)),
        ("billing_signature_on_file", "text NOT NULL", "provider signature on file: Y | N", yn(9)),
        # rendering provider (7)
        ("rendering_provider_npi", "text NOT NULL", "rendering provider NPI (synthetic)", npi(456789, 101317, 40)),
        ("rendering_provider_taxonomy", "text NOT NULL", "rendering provider taxonomy code", arr(TAXONOMIES, 5, 1)),
        ("rendering_provider_last_name", "text NOT NULL", "rendering provider last name (synthetic)", arr(LAST_NAMES, 7, 3)),
        ("rendering_provider_first_name", "text NOT NULL", "rendering provider first name (synthetic)", arr(FIRST_NAMES, 11, 1)),
        ("rendering_provider_credential", "text NOT NULL", "rendering provider credential",
         arr(["MD", "DO", "NP", "PA"], 3)),
        ("rendering_specialty_code", "text NOT NULL", "CMS specialty code of the rendering provider", arr(SPECIALTIES, 5)),
        ("rendering_network_flag", "text NOT NULL", "rendering provider in network: Y | N", yn(11, 3)),
        # referring + supervising (5)
        ("referring_provider_npi", "text", "referring provider NPI; NULL when self-referred",
         f"CASE WHEN g % 3 = 0 THEN {npi(567890, 90017, 30)} END"),
        ("referring_provider_last_name", "text", "referring provider last name",
         f"CASE WHEN g % 3 = 0 THEN {arr(LAST_NAMES, 5, 5)} END"),
        ("referring_provider_first_name", "text", "referring provider first name",
         f"CASE WHEN g % 3 = 0 THEN {arr(FIRST_NAMES, 3, 4)} END"),
        ("referring_provider_taxonomy", "text", "referring provider taxonomy code",
         f"CASE WHEN g % 3 = 0 THEN {arr(TAXONOMIES, 7, 2)} END"),
        ("supervising_provider_npi", "text", "supervising provider NPI; rarely present",
         f"CASE WHEN g % 13 = 0 THEN {npi(678901, 90017, 30)} END"),
        # service facility (8)
        ("facility_npi", "text NOT NULL", "service facility NPI (synthetic)", npi(789012, 70117, 25)),
        ("facility_name", "text NOT NULL", "service facility name (synthetic)",
         arr(["LAKESIDE HOSPITAL", "SUMMIT SURGERY CENTER", "RIVERBEND IMAGING", "NORTHSTAR LAB", "GATEWAY URGENT CARE"], 3)),
        ("facility_addr_line1", "text NOT NULL", "service facility street address", arr(STREETS, 23)),
        ("facility_city", "text NOT NULL", "service facility city", arr(CITIES, 29)),
        ("facility_state", "text NOT NULL", "service facility state", arr(STATES, 29)),
        ("facility_zip", "text NOT NULL", "service facility ZIP", zip5(43, 11)),
        ("facility_taxonomy", "text NOT NULL", "service facility taxonomy code", arr(TAXONOMIES, 11, 4)),
        ("facility_medicare_ccn", "text NOT NULL", "facility CMS certification number (synthetic)",
         "lpad((360001 + (g * 7) % 180)::text, 6, '0')"),
        # pay-to provider (6)
        ("pay_to_provider_npi", "text NOT NULL", "pay-to provider NPI (often = billing)", npi(234567, 101317, 40)),
        ("pay_to_name", "text NOT NULL", "pay-to organization name",
         arr(["LAKESIDE MEDICAL GROUP", "SUMMIT HEALTH PARTNERS", "RIVERBEND CLINIC", "NORTHSTAR PHYSICIANS"], 3)),
        ("pay_to_addr_line1", "text NOT NULL", "pay-to street address (lockbox)",
         "format('PO BOX %s', 1000 + (g * 3) % 9000)"),
        ("pay_to_city", "text NOT NULL", "pay-to city", arr(CITIES, 19)),
        ("pay_to_state", "text NOT NULL", "pay-to state", arr(STATES, 19)),
        ("pay_to_zip", "text NOT NULL", "pay-to ZIP", zip5(41, 7)),
    ]


def payer_cob() -> list[Col]:
    cob = "g % 5 = 0"  # ~20% of claims have other coverage
    return [
        ("payer_id", "text NOT NULL", "adjudicating payer identifier",
         arr(["PAY001", "PAY002", "PAY003"], 3)),
        ("payer_name", "text NOT NULL", "adjudicating payer name (synthetic)",
         arr(["ACME HEALTH PLAN", "BEACON MUTUAL", "CASCADE BENEFITS"], 3)),
        ("line_of_business", "text NOT NULL", "line of business: commercial | medicare_adv | medicaid_mco",
         arr(["commercial", "commercial", "medicare_adv", "medicaid_mco"], 7)),
        ("cob_indicator", "text NOT NULL", "other coverage exists: Y | N",
         f"CASE WHEN {cob} THEN 'Y' ELSE 'N' END"),
        ("primary_payer_id", "text", "primary payer when this claim is secondary",
         f"CASE WHEN {cob} THEN {arr(['OTH100', 'OTH200'], 3)} END"),
        ("primary_payer_paid", "numeric(10,2)", "amount the primary payer paid",
         f"CASE WHEN {cob} THEN round({ALLOWED} * 0.5, 2) END"),
        ("primary_payer_allowed", "numeric(10,2)", "primary payer allowed amount",
         f"CASE WHEN {cob} THEN {ALLOWED} END"),
        ("medicare_crossover_flag", "text NOT NULL", "claim arrived via Medicare crossover: Y | N", yn(25, 5)),
        ("medicaid_indicator", "text NOT NULL", "member has Medicaid coverage: Y | N", yn(20, 7)),
        ("other_insurance_flag", "text NOT NULL", "other insurance reported on the claim: Y | N",
         f"CASE WHEN {cob} THEN 'Y' ELSE 'N' END"),
        ("cob_savings_amount", "numeric(10,2) NOT NULL", "savings attributed to coordination of benefits",
         f"CASE WHEN {cob} THEN round({ALLOWED} * 0.5, 2) ELSE 0 END"),
        ("subrogation_flag", "text NOT NULL", "claim flagged for subrogation review: Y | N", yn(97)),
    ]


def diagnoses() -> list[Col]:
    cols: list[Col] = []
    for k in range(1, 26):
        nn = " NOT NULL" if k == 1 else ""
        if k == 1:
            expr = arr(DIAGS, 3)
        elif k <= 3:
            expr = f"CASE WHEN g % {k} = 0 THEN {arr(DIAGS, 5, k)} END"
        else:
            expr = f"CASE WHEN g % {k} = 0 THEN {arr(DIAGS, 7, k)} END"
        cols.append((
            f"diag_code_{k:02d}", f"text{nn}",
            f"ICD-10-CM diagnosis code, slot {k:02d} of 25; NULL when unused",
            expr,
        ))
    for k in range(1, 26):
        poa = arr(["Y", "N", "U", "W"], 3, k)
        if k == 1:
            expr, nn = poa, " NOT NULL"
        else:
            expr, nn = f"CASE WHEN g % {k} = 0 THEN {poa} END", ""
        cols.append((
            f"diag_poa_{k:02d}", f"text{nn}",
            f"present-on-admission indicator for diagnosis slot {k:02d}; NULL when the slot is unused",
            expr,
        ))
    return cols


def service_lines() -> list[Col]:
    cols: list[Col] = []
    for j in range(1, 7):
        def line(expr: str) -> str:
            # number of populated lines = 1 + g % 6, so line j exists when j <= 1 + g % 6
            return expr if j == 1 else f"CASE WHEN 1 + g % 6 >= {j} THEN {expr} END"

        nn = " NOT NULL" if j == 1 else ""
        charge = money(2500, 91 + j * 13, 90000)
        cols += [
            (f"line{j}_proc_code", f"text{nn}",
             f"CPT/HCPCS procedure code on service line {j}; NULL when the line is unused",
             line(arr(PROCS, 5, j))),
            (f"line{j}_modifier_1", "text",
             f"first procedure modifier on line {j}; usually NULL",
             line(f"CASE WHEN g % 4 = {j % 4} THEN {arr(MODIFIERS, 3, j)} END")),
            (f"line{j}_modifier_2", "text",
             f"second procedure modifier on line {j}; rarely present",
             line(f"CASE WHEN g % 11 = {j} THEN {arr(MODIFIERS, 5, j + 2)} END")),
            (f"line{j}_revenue_code", "text",
             f"NUBC revenue code on line {j} (institutional claims)",
             line(f"CASE WHEN g % 2 = 0 THEN {arr(REVENUE_CODES, 7, j)} END")),
            (f"line{j}_units", f"int{nn}",
             f"units of service on line {j}",
             line(f"1 + (g + {j}) % 4")),
            (f"line{j}_charge_amount", f"numeric(10,2){nn}",
             f"billed charge on line {j}",
             line(charge)),
            (f"line{j}_allowed_amount", f"numeric(10,2){nn}",
             f"allowed amount on line {j}; 0 when denied",
             line(f"CASE WHEN {STATUS} = 'denied' THEN 0 ELSE round({charge} * 0.62, 2) END")),
            (f"line{j}_paid_amount", f"numeric(10,2){nn}",
             f"plan-paid amount on line {j}; 0 unless the claim paid",
             line(f"CASE WHEN {STATUS} = 'paid' THEN round({charge} * 0.62 * 0.85, 2) ELSE 0 END")),
        ]
    return cols


def adjudication() -> list[Col]:
    paid = f"CASE WHEN {STATUS} = 'paid' THEN round({ALLOWED} * 0.85, 2) ELSE 0 END"
    cols: list[Col] = [
        ("total_billed_amount", "numeric(10,2) NOT NULL", "total billed charges (= total_claim_charge)", BILLED),
        ("total_allowed_amount", "numeric(10,2) NOT NULL", "total plan-allowed amount; 0 when denied",
         f"CASE WHEN {STATUS} = 'denied' THEN 0 ELSE {ALLOWED} END"),
        ("total_paid_amount", "numeric(10,2) NOT NULL", "total plan-paid amount", paid),
        ("total_member_liability", "numeric(10,2) NOT NULL", "total member cost share",
         f"CASE WHEN {STATUS} = 'paid' THEN round({ALLOWED} * 0.15, 2) ELSE 0 END"),
        ("total_deductible_amount", "numeric(10,2) NOT NULL", "member liability applied to deductible",
         f"CASE WHEN {STATUS} = 'paid' THEN round({ALLOWED} * 0.05, 2) ELSE 0 END"),
        ("total_coinsurance_amount", "numeric(10,2) NOT NULL", "member liability from coinsurance",
         f"CASE WHEN {STATUS} = 'paid' THEN round({ALLOWED} * 0.08, 2) ELSE 0 END"),
        ("total_copay_amount", "numeric(10,2) NOT NULL", "member liability from copays",
         f"CASE WHEN {STATUS} = 'paid' THEN round({ALLOWED} * 0.02, 2) ELSE 0 END"),
        ("total_cob_paid_amount", "numeric(10,2) NOT NULL", "amount paid by other coverage",
         f"CASE WHEN g % 5 = 0 THEN round({ALLOWED} * 0.5, 2) ELSE 0 END"),
        ("total_patient_paid_amount", "numeric(10,2) NOT NULL", "amount the patient paid at point of service",
         money(0, 7, 5000)),
        ("claim_discount_amount", "numeric(10,2) NOT NULL", "provider discount / repricing reduction",
         f"round({BILLED} * 0.38, 2)"),
    ]
    for i in range(1, 6):
        cond = f"g % {3 * i} = 0"
        cols += [
            (f"cas_group_code_{i}", "text",
             f"claim adjustment group code, occurrence {i}: CO | PR | OA; NULL when unused",
             f"CASE WHEN {cond} THEN {arr(['CO', 'PR', 'OA'], 3, i)} END"),
            (f"cas_reason_code_{i}", "text",
             f"CARC adjustment reason code, occurrence {i}; NULL when unused",
             f"CASE WHEN {cond} THEN {arr(['1', '2', '3', '45', '96', '97'], 5, i)} END"),
            (f"cas_amount_{i}", "numeric(10,2)",
             f"adjustment amount, occurrence {i}; NULL when unused",
             f"CASE WHEN {cond} THEN {money(100, 17 + i, 20000)} END"),
        ]
    cols += [
        ("drg_code", "text", "MS-DRG assigned (institutional claims only)",
         f"CASE WHEN g % 2 = 0 THEN lpad((190 + (g * 3) % 120)::text, 3, '0') END"),
        ("drg_weight", "numeric(6,4)", "relative weight of the assigned MS-DRG",
         "CASE WHEN g % 2 = 0 THEN round((0.5 + (g * 7) % 300 / 100.0)::numeric, 4) END"),
        ("pricing_method", "text NOT NULL", "pricing methodology: fee_schedule | drg | per_diem | percent_of_charge",
         arr(["fee_schedule", "fee_schedule", "drg", "per_diem", "percent_of_charge"], 7)),
        ("network_indicator", "text NOT NULL", "claim priced in network: I | O",
         "CASE WHEN g % 8 = 0 THEN 'O' ELSE 'I' END"),
        ("allowed_percent", "numeric(5,2) NOT NULL", "allowed as a percent of billed", "62.00"),
    ]
    return cols


def envelope() -> list[Col]:
    resub = "g % 20 = 0 OR g % 41 = 0"  # claims with frequency 7 or 8
    return [
        ("isa_interchange_control_number", "text NOT NULL", "ISA13 interchange control number",
         "lpad(((g * 7) % 1000000000)::text, 9, '0')"),
        ("gs_group_control_number", "text NOT NULL", "GS06 functional group control number",
         "((g * 11) % 900000 + 100000)::text"),
        ("st_transaction_control_number", "text NOT NULL", "ST02 transaction set control number",
         "lpad((g % 10000)::text, 4, '0')"),
        ("se_segment_count", "int NOT NULL", "SE01 segment count of the transaction set", "30 + g % 40"),
        ("submitter_id", "text NOT NULL", "1000A submitter identifier", arr(["SUB001", "SUB002", "SUB003"], 3)),
        ("submitter_name", "text NOT NULL", "1000A submitter name",
         arr(["APEX BILLING SVC", "BRIGHTPATH RCM", "CLEARWATER BILLING"], 3)),
        ("receiver_id", "text NOT NULL", "1000B receiver identifier", "'RCV001'"),
        ("receiver_name", "text NOT NULL", "1000B receiver name", "'ACME HEALTH PLAN'"),
        ("clearinghouse_id", "text NOT NULL", "clearinghouse identifier", arr(["CH01", "CH02"], 1)),
        ("clearinghouse_name", "text NOT NULL", "clearinghouse name",
         arr(["RELAYNET", "SWITCHPOINT"], 1)),
        ("clearinghouse_batch_id", "text NOT NULL", "clearinghouse batch the claim arrived in",
         "format('B%s', lpad(((g - 1) / 100)::text, 5, '0'))"),
        ("edi_version_code", "text NOT NULL", "X12 implementation version", "'005010X222A1'"),
        ("transaction_set_purpose", "text NOT NULL", "BHT02 transaction set purpose code", "'00'"),
        ("original_claim_id", "text", "payer claim number being replaced/voided (frequency 7/8 only)",
         f"CASE WHEN {resub} THEN format('WC%s', lpad((g - 1)::text, 7, '0')) END"),
        ("resubmission_condition_code", "text", "resubmission condition code (frequency 7/8 only)",
         f"CASE WHEN {resub} THEN {arr(['1', '2', '3'], 3)} END"),
        ("prior_auth_number", "text", "prior authorization number; NULL when not required",
         f"CASE WHEN g % 6 = 0 THEN format('PA%s', lpad(((g * 19) % 1000000)::text, 6, '0')) END"),
        ("referral_number", "text", "referral number; NULL when not required",
         f"CASE WHEN g % 9 = 0 THEN format('RF%s', lpad(((g * 23) % 1000000)::text, 6, '0')) END"),
        ("attachment_control_number", "text", "PWK attachment control number; rarely present",
         f"CASE WHEN g % 31 = 0 THEN format('ATT%s', lpad((g % 100000)::text, 5, '0')) END"),
        ("attachment_flag", "text NOT NULL", "claim has a paperwork attachment: Y | N", yn(31)),
        ("emergency_indicator", "text NOT NULL", "emergency service indicator: Y | N", yn(12, 4)),
        ("epsdt_flag", "text NOT NULL", "EPSDT (early periodic screening) indicator: Y | N", yn(50, 9)),
        ("family_planning_flag", "text NOT NULL", "family planning indicator: Y | N", yn(60, 11)),
        ("accident_related_flag", "text NOT NULL", "claim is accident-related: Y | N", yn(15, 2)),
        ("auto_accident_flag", "text NOT NULL", "auto accident involved: Y | N", yn(45, 2)),
        ("accident_state", "text", "state where the accident occurred",
         f"CASE WHEN (g + 2) % 15 = 0 THEN {arr(STATES, 7)} END"),
        ("accident_date", "date", "date of the accident",
         f"CASE WHEN (g + 2) % 15 = 0 THEN {STMT_FROM} - 3 END"),
        ("employment_related_flag", "text NOT NULL", "condition is employment-related: Y | N", yn(75, 8)),
        ("release_of_information_code", "text NOT NULL", "release of information code: Y | I",
         "CASE WHEN g % 30 = 0 THEN 'I' ELSE 'Y' END"),
        ("assignment_of_benefits_flag", "text NOT NULL", "benefits assigned to provider: Y | N", yn(14, 6)),
        ("provider_accept_assignment", "text NOT NULL", "provider accepts assignment: A | C",
         "CASE WHEN g % 22 = 0 THEN 'C' ELSE 'A' END"),
        ("patient_signature_source", "text NOT NULL", "patient signature source code: P | S",
         "CASE WHEN g % 4 = 0 THEN 'S' ELSE 'P' END"),
        ("delay_reason_code", "text", "delay reason code for late submission; usually NULL",
         f"CASE WHEN g % 27 = 0 THEN {arr(['1', '3', '7', '9'], 3)} END"),
        ("claim_note_text", "text", "free-text claim note (NTE segment); usually NULL",
         f"CASE WHEN g % 17 = 0 THEN {arr(['SEE ATTACHED RECORDS', 'CORRECTED MEMBER ID', 'TIMELY FILING APPEAL'], 3)} END"),
    ]


def build_columns() -> list[Col]:
    cols = (
        claim_header()
        + patient_subscriber()
        + providers()
        + payer_cob()
        + diagnoses()
        + service_lines()
        + adjudication()
        + envelope()
    )
    names = [c[0] for c in cols]
    assert len(set(names)) == len(names), "duplicate column name"
    assert len(cols) == EXPECTED_COLUMNS, f"expected {EXPECTED_COLUMNS} columns, got {len(cols)}"
    return cols


def emit() -> str:
    cols = build_columns()
    out: list[str] = []
    out.append("-- GENERATED by tools/gen_wide_claims.py — edit the generator, not this file.")
    out.append(f"-- {TABLE}: flattened 837-style claim extract, {len(cols)} columns x {ROWS} rows.")
    out.append("-- Deterministic (generate_series, no random()); nothing here is PHI.")
    out.append("")
    out.append(f"DROP TABLE IF EXISTS {TABLE};")
    out.append("")
    out.append(f"CREATE TABLE {TABLE} (")
    width = max(len(c[0]) for c in cols)
    for i, (name, sql_type, _, _) in enumerate(cols):
        comma = "," if i < len(cols) - 1 else ""
        out.append(f"  {name:<{width}} {sql_type}{comma}")
    out.append(");")
    out.append("")
    out.append(f"ALTER TABLE {TABLE} ADD PRIMARY KEY (claim_id);")
    out.append("")
    out.append(f"COMMENT ON TABLE {TABLE} IS 'flattened 837-style claim extract "
               f"({len(cols)} columns; synthetic, ultra-wide on purpose)';")
    for name, _, comment, _ in cols:
        out.append(f"COMMENT ON COLUMN {TABLE}.{name} IS '{comment}';")
    out.append("")
    out.append(f"INSERT INTO {TABLE}")
    out.append("SELECT")
    for i, (name, _, _, expr) in enumerate(cols):
        comma = "," if i < len(cols) - 1 else ""
        out.append(f"  {expr}{comma}  -- {name}")
    out.append(f"FROM generate_series(1, {ROWS}) g;")
    out.append("")
    out.append(f"ANALYZE {TABLE};")
    out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    print(emit(), end="")

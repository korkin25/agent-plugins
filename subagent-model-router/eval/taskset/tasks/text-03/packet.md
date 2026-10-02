TASK: Extract the key commercial terms of a signed maintenance agreement into a JSON file for the contract register. Record the terms as they stand in the signed agreement.
WORKDIR: {workdir}
READ: {workdir}/agreement.txt — the whole document, including the schedule.
EDIT: create {workdir}/terms.json; change nothing else.
CHECKS: none are provided; the file is compared field by field with the agreement.
OUTPUT: terms.json holds one JSON object with exactly these keys and no others:
- "client": string, the Client's company name as given in the list of parties;
- "provider": string, the Provider's company name as given in the list of parties (letter case of the names is not checked);
- "effective_date": string, the Effective Date as YYYY-MM-DD;
- "initial_term_months": integer, the length of the initial term in months;
- "auto_renewal": boolean, whether the agreement renews automatically after the initial term;
- "renewal_period_months": integer, the length of each renewal period in months, or null if it does not renew;
- "monthly_fee": number, the Monthly Fee in the agreement's currency, without VAT;
- "currency": string, the ISO 4217 code of the agreement's currency, in upper case;
- "payment_days": integer, the number of days the Client has to pay an undisputed invoice;
- "late_interest_percent_per_month": number, the late-payment interest rate in per cent per month (for example 2.25 for 2.25%);
- "liability_cap_per_contract_year": number, the limit on each party's total liability in a Contract Year, as an amount in the agreement's currency;
- "termination_notice_days": integer, the minimum written notice in days for ending the agreement at the end of the initial term or a renewal period;
- "critical_response_hours_business_day": integer, the response time in hours for a critical fault reported on a Business Day;
- "governing_law": string, the legal system whose law governs the agreement, named as in the agreement (for example "Northern Ireland").
All amounts are plain JSON numbers: no currency signs, no thousands separators, not strings. Key order and whitespace are up to you.

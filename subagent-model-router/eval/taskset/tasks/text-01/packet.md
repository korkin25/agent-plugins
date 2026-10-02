TASK: Extract the invoice details from a supplier's email into a JSON file for the accounts payable system.
WORKDIR: {workdir}
READ: {workdir}/email.txt
EDIT: create {workdir}/invoice.json; change nothing else.
CHECKS: none are provided; the file is compared field by field with the email.
OUTPUT: invoice.json holds one JSON object with exactly these keys and no others:
- "invoice_number": string, the invoice number exactly as written in the email;
- "po_number": string, the purchase order number exactly as written in the email;
- "supplier": string, the supplier's legal company name as written in the email signature;
- "issue_date": string, the date the invoice was issued, as YYYY-MM-DD;
- "due_date": string, the payment due date, as YYYY-MM-DD;
- "total_amount": number, the total amount due including tax, as a JSON number (no currency sign, no thousands separators, not a string);
- "tax_amount": number, the tax amount, in the same format;
- "currency": string, the ISO 4217 currency code in upper case, for example "EUR";
- "status": string, exactly one of "paid", "partially_paid", "unpaid", according to what the email says about payment.
Key order, indentation and a trailing newline are up to you.

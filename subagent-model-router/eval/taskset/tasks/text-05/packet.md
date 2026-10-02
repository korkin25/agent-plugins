TASK: Classify each line of a monthly expense report into one budget category, following the finance team's category rules below.
WORKDIR: {workdir}
READ: {workdir}/expenses.txt — 32 numbered expense lines.
EDIT: create {workdir}/labels.csv; change nothing else.
CHECKS: none are provided. The check requires every one of the 32 labels to be correct; there is no tolerance.
OUTPUT: labels.csv is a comma-separated file. Its first line is the header `id,label`; then one line per expense line: the line's number and its category, for example `7,office`. Every number from 1 to 32 appears exactly once; the line order is free. Use exactly these lower-case category names.

Categories:
- travel: transport (flights, trains, taxis, car rental, fuel) and accommodation;
- meals: food and drink;
- software: software licences, software and online-service subscriptions, cloud hosting, domain names;
- hardware: computing devices, their parts and their peripherals;
- training: courses, workshops, certification exams, conference tickets, books;
- office: stationery, furniture, cleaning, postage and courier services.

Precedence rules — where a rule below applies, it overrides the category list above:
- P1. Food and drink are always "meals", even when bought during a trip, on a flight, or charged on a hotel bill.
- P2. An online course or course library is "training", even when it is billed as a subscription.
- P3. A conference ticket is "training", even when the price includes food.
- P4. A delivery or shipping charge on an order for hardware is "hardware"; every other postage or courier charge is "office".

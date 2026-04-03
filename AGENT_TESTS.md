# Agent Test Scenarios

---

## Test 1 — Single Tool
*Only one tool should fire. Trace must show exactly 1 tool call.*

### Option A — Database
```
What is the cheapest product in the database?
```
- Tool: `database`
- Check: The cheapest product in the database is the Wool Beanie Hat, priced at $12.99.



### Option B — Calculator
```
What is 1,250 multiplied by 0.92?
```
- Tool: `calculator`
- Check: answer is 1,150

### Option C — Weather
```
What is the current temperature in Tokyo?
```
- Tool: `weather`
- Check: temperature and conditions in answer

---

## Test 2 — Independent Multi-Tool
*Two or more tools fire with no dependency on each other.*

### Option A — Weather + Database
```
What is the current weather in Berlin, and how many total orders are in the database?
```
- Tools: `weather`, `database`
- Check: trace shows both tools, answer mentions temperature and order count

### Option B — Calculator + Database
```
What is 25 multiplied by 4, and what is the most expensive product in the database?
```
- Tools: `calculator`, `database`
- Check: answer is 100 for the math, and a product name with price

### Option C — Weather + Calculator
```
What is the current temperature in Dubai and what is 37 multiplied by 24?
```
- Tools: `weather`, `calculator`
- Check: temperature in answer, math result is 888

---

## Test 3 — Dependent Multi-Tool
*Each tool call depends on the result of the previous one.*

### Option A — Web Search → Calculator *(easiest)*
```
Search for the current price of Bitcoin in USD, then calculate how much 3 Bitcoins would cost.
```
- Tools: `web_search` → `calculator`
- Order matters: search must happen before calculator
- Check: final answer is 3 × the searched price

### Option B — Database → Calculator
```
Find the most expensive product in the database, then calculate how much 5 units of it would cost.
```
- Tools: `database` → `calculator`
- Order matters: database price is needed before calculator can run
- Check: final price is 5 × the product price from the database

### Option C — Web Search → Calculator → Unit Converter
```
Search for the current price of gold per ounce, then calculate the cost of 10 ounces, then convert that amount to Euros 
```
- Tools: `web_search` → `calculator` → `unit_converter`
- Order matters: each step feeds into the next
- Check: EUR amount is less than the USD amount, trace shows 3 tools in order

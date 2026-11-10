# Gabby & Jorgie · Expenses

Private household expense dashboard, published with GitHub Pages.

- `index.html` – the dashboard. It asks for a password and decrypts the data in the browser.
- `data.enc.json` – the expenses and monthly analysis, encrypted (AES-256-GCM, key derived from the password with PBKDF2). Nothing readable is stored in this repo.
- `encrypt_data.py` – encrypts `expenses.json` + `analysis.json` + `savings.json` (+ optional `debts.json`; if omitted, the stored debts are kept) into `data.enc.json`.
- `build_report.py` – builds the monthly email reports.
- `debt_plan.py` – builds Jorgie's debt payoff plan (shown in his view of the dashboard and emailed to him when he writes "send plan" in his note).
- `d3.min.js` – charting library (d3 v7).

The data is updated automatically on the 1st of every month from Gabby's and Jorgie's iPhone notes.

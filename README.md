# Gabby & Jorgie · Expenses

Private household expense dashboard, published with GitHub Pages.

- `index.html` – the dashboard. It asks for a password and decrypts the data in the browser.
- `data.enc.json` – the expenses and monthly analysis, encrypted (AES-256-GCM, key derived from the password with PBKDF2). Nothing readable is stored in this repo.
- `encrypt_data.py` – encrypts `expenses.json` + `analysis.json` into `data.enc.json`.
- `build_report.py` – builds the monthly email reports.
- `d3.min.js` – charting library (d3 v7).

The data is updated automatically on the 1st of every month from Gabby's and Jorgie's iPhone notes.

# Fair Value Calculator

Two-stage DCF calculator with live data from Financial Modeling Prep.

## Setup & Run

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the server
python app.py

# 3. Open in browser
# http://localhost:5000
```

## What each input fetches

| Input            | FMP Endpoint             | Method                                              |
|------------------|--------------------------|-----------------------------------------------------|
| EPS (TTM)        | `/income-statement`      | Latest annual diluted EPS from SEC filings          |
| Growth rate      | `/analyst-estimates`     | Implied 5yr CAGR from Wall St consensus EPS forecasts |
| Terminal growth  | Macro assumption         | 2–3% by sector (GDP growth proxy)                   |
| WACC             | `/key-metrics`           | Derived from ROIC + risk premium; CAPM fallback     |
| Exit P/E         | `/ratios`                | 3–4 year average historical P/E                     |
| Current price    | `/quote`                 | Real-time market price                              |

## API Key
The key is embedded in `app.py`. To change it, update the `API_KEY` constant at the top of the file.

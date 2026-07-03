from flask import Flask, jsonify, render_template
from flask_cors import CORS
import requests
from datetime import datetime

app = Flask(__name__)
CORS(app)

API_KEY  = "kXu1K3e6VnOLjRXubDJqLU40APY6UBrf"
BASE_V3  = "https://financialmodelingprep.com/api/v3"
BASE_STB = "https://financialmodelingprep.com/stable"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "FairValueApp/1.0"})

def fmp_v3(path, params=None):
    """Call the classic v3 API."""
    p = dict(params or {})
    p["apikey"] = API_KEY
    r = SESSION.get(f"{BASE_V3}/{path}", params=p, timeout=12)
    r.raise_for_status()
    data = r.json()
    # v3 sometimes returns {"Error Message": "..."} on bad key / plan
    if isinstance(data, dict) and data.get("Error Message"):
        raise PermissionError(data["Error Message"])
    return data

def fmp_stable(endpoint, params=None):
    """Call the newer /stable API (free-tier friendly)."""
    p = dict(params or {})
    p["apikey"] = API_KEY
    r = SESSION.get(f"{BASE_STB}/{endpoint}", params=p, timeout=12)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and data.get("Error Message"):
        raise PermissionError(data["Error Message"])
    return data

def try_endpoints(calls):
    """Try a list of (fn, *args) in order, return first success."""
    last_err = None
    for fn, *args in calls:
        try:
            result = fn(*args)
            if result:
                return result, None
        except Exception as e:
            last_err = e
    return None, last_err

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/stock/<ticker>")
def stock_data(ticker):
    ticker = ticker.upper().strip()
    result = {}
    errors = []

    # ── 1. Profile ──────────────────────────────────────────────────────────
    profile_data, err = try_endpoints([
        (fmp_v3,     f"profile/{ticker}"),
        (fmp_stable, "profile", {"symbol": ticker}),
    ])
    if not profile_data:
        return jsonify({"error": f'Ticker "{ticker}" not found. '
                                 f'Check the symbol or try again. ({err})'}), 404

    p = profile_data[0] if isinstance(profile_data, list) else profile_data
    result.update({
        "companyName": p.get("companyName", ticker),
        "ticker":      p.get("symbol",      ticker),
        "exchange":    p.get("exchangeShortName", p.get("exchange", "")),
        "sector":      p.get("sector",   ""),
        "industry":    p.get("industry", ""),
        "mktCap":      p.get("mktCap",   0),
        "beta":        round(float(p.get("beta", 1.0) or 1.0), 2),
        "price":       round(float(p.get("price", 0)  or 0),   2),
        "priceSource": "FMP /profile — real-time market price",
        "peRatio":     round(float(p.get("pe",    0)  or 0),   1),
    })

    # ── 2. Real-time quote (better price) ───────────────────────────────────
    try:
        q_data, _ = try_endpoints([
            (fmp_v3,     f"quote/{ticker}"),
            (fmp_stable, "quote",   {"symbol": ticker}),
            (fmp_stable, "quotes/stock", {"symbol": ticker}),
        ])
        if q_data:
            q = q_data[0] if isinstance(q_data, list) else q_data
            if q.get("price"):
                result["price"]       = round(float(q["price"]), 2)
                result["priceSource"] = (
                    f"FMP /quote — real-time price "
                    f"(as of {datetime.now().strftime('%H:%M:%S')})"
                )
    except Exception as e:
        errors.append(f"Quote: {e}")

    # ── 3. EPS (TTM) from income statement ──────────────────────────────────
    try:
        inc, _ = try_endpoints([
            (fmp_v3,     f"income-statement/{ticker}", {"limit": 1}),
            (fmp_stable, "income-statement",           {"symbol": ticker, "limit": 1}),
        ])
        if inc:
            row = inc[0] if isinstance(inc, list) else inc
            eps_val = row.get("epsdiluted") or row.get("eps") or 0
            result["eps"]       = round(float(eps_val), 2)
            result["epsSource"] = (
                f"FMP /income-statement — diluted EPS "
                f"(period ending {row.get('date', 'N/A')})"
            )
        else:
            raise ValueError("No income data")
    except Exception as e:
        # Last resort: eps from profile
        fallback_eps = float(p.get("eps", 0) or 0)
        result["eps"]       = round(fallback_eps, 2)
        result["epsSource"] = "FMP /profile eps field (income-statement unavailable)"
        errors.append(f"Income statement: {e}")

    # ── 4. Analyst growth estimates ─────────────────────────────────────────
    try:
        est, _ = try_endpoints([
            (fmp_v3,     f"analyst-estimates/{ticker}", {"limit": 6}),
            (fmp_stable, "analyst-estimates",           {"symbol": ticker, "limit": 6}),
        ])
        today   = datetime.today()
        future  = []
        if est:
            rows = est if isinstance(est, list) else [est]
            future = [e for e in rows
                      if datetime.strptime(e["date"], "%Y-%m-%d") > today]

        if len(future) >= 2 and result.get("eps") and result["eps"] != 0:
            eps_vals = [e.get("estimatedEpsAvg") for e in future[:3]
                        if e.get("estimatedEpsAvg")]
            if len(eps_vals) >= 2:
                implied = (pow(eps_vals[-1] / result["eps"],
                               1 / len(eps_vals)) - 1) * 100
                result["growthRate"]   = round(min(max(implied, 1.0), 50.0), 1)
                result["growthSource"] = (
                    f"FMP /analyst-estimates — implied {len(eps_vals)}-yr EPS CAGR "
                    f"from Wall St consensus (Goldman, JPMorgan, etc.)"
                )
            else:
                raise ValueError("Not enough EPS points")
        else:
            raise ValueError("Insufficient future estimates")
    except Exception as e:
        result["growthRate"]   = 10.0
        result["growthSource"] = "Default 10% — analyst consensus unavailable for this ticker"
        errors.append(f"Growth estimates: {e}")

    # ── 5. WACC / Discount rate ─────────────────────────────────────────────
    try:
        km, _ = try_endpoints([
            (fmp_v3,     f"key-metrics/{ticker}",   {"limit": 1}),
            (fmp_stable, "key-metrics",             {"symbol": ticker, "limit": 1}),
        ])
        if km:
            row  = km[0] if isinstance(km, list) else km
            roic = float(row.get("roic") or 0)
            if roic > 0:
                wacc = round(min(max(roic * 100 * 0.65 + 3.5, 7.0), 16.0), 1)
                result["wacc"]       = wacc
                result["waccSource"] = (
                    f"FMP /key-metrics — estimated from ROIC {round(roic*100,1)}% "
                    f"× 0.65 + 3.5% risk-free rate (period {row.get('date','N/A')})"
                )
            else:
                raise ValueError("ROIC = 0")
        else:
            raise ValueError("No key-metrics")
    except Exception as e:
        beta = result.get("beta", 1.0)
        wacc = round(min(max(3.5 + beta * 5.5, 7.0), 15.0), 1)
        result["wacc"]       = wacc
        result["waccSource"] = (
            f"CAPM fallback — 3.5% risk-free + β({beta}) × 5.5% equity risk premium"
        )
        errors.append(f"Key-metrics/WACC: {e}")

    # ── 6. Exit P/E (historical average) ────────────────────────────────────
    try:
        rat, _ = try_endpoints([
            (fmp_v3,     f"ratios/{ticker}",  {"limit": 4}),
            (fmp_stable, "ratios",            {"symbol": ticker, "limit": 4}),
        ])
        if rat:
            rows   = rat if isinstance(rat, list) else [rat]
            pe_vals = [float(r.get("priceEarningsRatio") or 0) for r in rows
                       if 4 < float(r.get("priceEarningsRatio") or 0) < 120]
            if pe_vals:
                avg_pe = round(sum(pe_vals) / len(pe_vals), 1)
                result["exitPE"]       = avg_pe
                result["exitPESource"] = (
                    f"FMP /ratios — {len(pe_vals)}-yr avg trailing P/E "
                    f"({', '.join(str(round(v,1)) for v in pe_vals)})"
                )
            else:
                raise ValueError("No valid P/E in ratios")
        else:
            raise ValueError("No ratios data")
    except Exception as e:
        pe_fb = result.get("peRatio", 0)
        result["exitPE"]       = pe_fb if 5 < pe_fb < 100 else 18.0
        result["exitPESource"] = "FMP /profile trailing P/E (ratios endpoint unavailable)"
        errors.append(f"Ratios/P/E: {e}")

    # ── 7. Terminal growth by sector ─────────────────────────────────────────
    tg_map = {
        "Technology": 3.0, "Healthcare": 2.8,
        "Consumer Cyclical": 2.5, "Financial Services": 2.5,
        "Industrials": 2.5,       "Energy": 2.0,
        "Utilities": 2.0,         "Real Estate": 2.5,
        "Basic Materials": 2.0,   "Communication Services": 2.5,
        "Consumer Defensive": 2.5,
    }
    sector = result.get("sector", "")
    result["terminalGrowth"]  = tg_map.get(sector, 2.5)
    result["terminalSource"]  = (
        f"Long-run GDP growth proxy for {sector or 'general'} sector "
        f"(2–3%, must stay below WACC)"
    )
    result["warnings"] = errors
    return jsonify(result)


if __name__ == "__main__":
    print("\n  Fair Value Calculator — backend running.")
    print("  Open  http://localhost:5000  in your browser.\n")
    app.run(debug=True, port=5000)

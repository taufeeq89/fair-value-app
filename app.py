from flask import Flask, jsonify, render_template
from flask_cors import CORS
from datetime import datetime
import yfinance as yf

# Import modules from our segregated ecosystem files
from services import fmp_v3, fmp_stable, try_endpoints, fetch_yfinance_eps
from models import get_terminal_growth, run_dcf_engine

app = Flask(__name__)
CORS(app)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/stock/<ticker>")
def stock_data(ticker):
    ticker = ticker.upper().strip()
    result = {}
    errors = []

    # ── 1. PROFILE (Hardened FMP & yfinance Hybrid Sequence) ─────────────────
    profile_data, err = try_endpoints([
        (fmp_v3, f"profile/{ticker}"),
        (fmp_stable, f"profile/{ticker}"), # Fixed path structure
    ])
    
    if profile_data:
        p = profile_data[0] if isinstance(profile_data, list) else profile_data
        p_price = round(float(p.get("price", 0) or 0), 2)
        p_pe = round(float(p.get("pe", 0) or 0), 2)
        p_beta = round(float(p.get("beta", 1.0) or 1.0), 2)

        result.update({
            "companyName": p.get("companyName", ticker),
            "ticker": p.get("symbol", ticker),
            "exchange": p.get("exchangeShortName", p.get("exchange", "")),
            "sector": p.get("sector", "Healthcare"),
            "industry": p.get("industry", "Medical Devices"),
            "mktCap": p.get("mktCap", 0),
            "beta": p_beta,
            "price": p_price,
            "priceSource": "FMP /profile — primary core data",
            "peRatio": p_pe,
        })
    else:
        # ABSOLUTE RESCUE SEQUENCE: Fetch metadata profile using yfinance directly
        errors.append(f"FMP Profile blocked (403/Restricted Tier). Deploying yfinance recovery framework. Original error: {err}")
        try:
            yf_ticker = yf.Ticker(ticker)
            yf_info = yf_ticker.info
            
            p_price = round(float(yf_info.get("currentPrice") or yf_info.get("regularMarketPrice") or 0), 2)
            p_pe = round(float(yf_info.get("trailingPE") or yf_info.get("forwardPE") or 0), 2)
            p_beta = round(float(yf_info.get("beta" or 1.0)), 2)

            result.update({
                "companyName": yf_info.get("longName", ticker),
                "ticker": ticker,
                "exchange": yf_info.get("exchange", "NYSE"),
                "sector": yf_info.get("sector", "Healthcare"),
                "industry": yf_info.get("industry", "Medical Devices"),
                "mktCap": yf_info.get("marketCap", 0),
                "beta": p_beta if p_beta > 0 else 1.0,
                "price": p_price,
                "priceSource": "yfinance — profile scraping data engine backup",
                "peRatio": p_pe,
            })
        except Exception as yf_prof_err:
            return jsonify({"error": f"Profile execution completely locked. Failed FMP and yfinance options: {yf_prof_err}"}), 404

    # Cache profile readings to evaluate proxies later if endpoints fail
    p_price = result["price"]
    p_pe = result["peRatio"]

    # ── 2. REAL-TIME QUOTE OPTIMIZATION ─────────────────────────────────────
    try:
        q_data, _ = try_endpoints([
            (fmp_v3, f"quote/{ticker}"),
            (fmp_stable, f"quote/{ticker}"),
        ])
        if q_data:
            q = q_data[0] if isinstance(q_data, list) else q_data
            if q.get("price"):
                result["price"] = round(float(q["price"]), 2)
                result["priceSource"] = f"FMP /quote — live tracking (as of {datetime.now().strftime('%H:%M:%S')})"
    except Exception as e:
        errors.append(f"Quote module fallback skipped: {e}")

    # ── 3. DILUTED EPS HANDLING ─────────────────────────────────────────────
    try:
        inc, _ = try_endpoints([
            (fmp_v3, f"income-statement/{ticker}", {"limit": 1}),
            (fmp_stable, f"income-statement/{ticker}", {"limit": 1}),
        ])
        if inc:
            row = inc[0] if isinstance(inc, list) else inc
            eps_val = row.get("epsdiluted") or row.get("eps")
            if eps_val is None:
                raise ValueError("EPS elements missing from FMP statement data")
            result["eps"] = round(float(eps_val), 2)
            result["epsSource"] = f"FMP /income-statement — diluted EPS"
        else:
            raise ValueError("FMP tier restriction blocked statement")
    except Exception as e:
        errors.append(f"Income statement FMP failed: {e}")
        try:
            eps_val, source_label = fetch_yfinance_eps(ticker)
            result["eps"] = eps_val
            result["epsSource"] = source_label
        except Exception as yf_err:
            errors.append(f"yfinance Fallback failed: {yf_err}")
            if p_pe > 0 and p_price > 0:
                result["eps"] = round(p_price / p_pe, 2)
                result["epsSource"] = f"Calculated Profile Proxy (Price ${p_price} / P/E {p_pe})"
            else:
                result["eps"] = 0.0

    # ── 4. ANALYST GROWTH ESTIMATES ─────────────────────────────────────────
    try:
        est, _ = try_endpoints([
            (fmp_v3, f"analyst-estimates/{ticker}", {"limit": 6}),
            (fmp_stable, f"analyst-estimates/{ticker}", {"limit": 6}),
        ])
        current_eps = result.get("eps", 0)
        growth_calculated = False

        if est and current_eps > 0:
            rows = est if isinstance(est, list) else [est]
            today_str = datetime.today().strftime("%Y-%m-%d")
            future = [r for r in rows if r.get("date") and r["date"] > today_str]
            future.sort(key=lambda x: x["date"])
            
            if future:
                target_index = min(2, len(future) - 1)
                target_estimate = future[target_index].get("estimatedEpsAvg")
                if target_estimate and target_estimate > 0:
                    years_forward = target_index + 1
                    implied = (pow(target_estimate / current_eps, 1 / years_forward) - 1) * 100
                    result["growthRate"] = round(min(max(implied, 1.0), 50.0), 1)
                    result["growthSource"] = f"FMP /analyst-estimates — implied {years_forward}-yr EPS CAGR"
                    growth_calculated = True

        if not growth_calculated:
            raise ValueError("Insufficient coordinates")
    except Exception as e:
        errors.append(f"Growth estimates: {e}")
        sector_growth_defaults = {"Technology": 12.0, "Healthcare": 8.5, "Consumer Cyclical": 9.0, "Financial Services": 5.5}
        result["growthRate"] = sector_growth_defaults.get(result.get("sector"), 6.5)
        result["growthSource"] = f"Sector tracking proxy baseline default for {result.get('sector', 'General')}"

    # ── 5. WACC / DISCOUNT RATE ESTIMATION ─────────────────────────────────
    try:
        km, _ = try_endpoints([
            (fmp_v3, f"key-metrics/{ticker}", {"limit": 1}),
            (fmp_stable, f"key-metrics/{ticker}", {"limit": 1}),
        ])
        if km:
            row = km[0] if isinstance(km, list) else km
            roic = float(row.get("roic") or 0)
            if roic > 0:
                wacc = round(min(max(roic * 100 * 0.65 + 3.5, 7.0), 16.0), 1)
                result["wacc"] = wacc
                result["waccSource"] = f"FMP /key-metrics — inferred via ROIC {round(roic*100,1)}%"
            else:
                raise ValueError("ROIC calculation out of bounds")
        else:
            raise ValueError("Premium data restricted")
    except Exception as e:
        errors.append(f"Key-metrics/WACC fallback applied: {e}")
        wacc = round(min(max(3.5 + result["beta"] * 5.5, 7.0), 15.0), 1)
        result["wacc"] = wacc
        result["waccSource"] = f"CAPM Alternative: 3.5% Risk-Free Rate + β({result['beta']}) × 5.5% Equity Risk Premium"

    # ── 6. HISTORICAL EXIT P/E MULTIPLE GENERATOR ──────────────────────────
    try:
        rat, _ = try_endpoints([
            (fmp_v3, f"ratios/{ticker}", {"limit": 4}),
            (fmp_stable, f"ratios/{ticker}", {"limit": 4}),
        ])
        if rat:
            rows = rat if isinstance(rat, list) else [rat]
            pe_vals = [float(r.get("priceEarningsRatio") or 0) for r in rows if 4.0 < float(r.get("priceEarningsRatio") or 0) < 120.0]
            if pe_vals:
                result["exitPE"] = round(sum(pe_vals) / len(pe_vals), 1)
                result["exitPESource"] = f"FMP /ratios — {len(pe_vals)}-yr historical average trailing P/E"
            else:
                raise ValueError("Out of bounds lookups")
        else:
            raise ValueError("Premium tier locked")
    except Exception as e:
        errors.append(f"Ratios/PE Multiples fallback applied: {e}")
        if p_pe > 4.0:
            result["exitPE"] = p_pe
            result["exitPESource"] = "FMP / profile (or yfinance metadata proxy) current trailing P/E ratio"
        else:
            result["exitPE"] = 16.5
            result["exitPESource"] = "Market baseline valuation multi conservative choice"

    # ── 7. TERMINAL LONG-TERM GROWTH ───────────────────────────────────────
    sector = result.get("sector", "")
    result["terminalGrowth"] = get_terminal_growth(sector)
    result["terminalSource"] = f"Long-run macro economic GDP proxy expansion track for {sector or 'unclassified'} sector operations"

    # ── 8. INTRINSIC VALUE CALCULATION ENGINE ──────────────────────────────
    run_dcf_engine(result, errors)

    result["warnings"] = errors
    return jsonify(result)

if __name__ == "__main__":
    print("\n Modular Hybrid Backend Server Online — Listening on Port 5000")
    app.run(debug=True, port=5000)

import yfinance as yf
from config import API_KEY, BASE_V3, BASE_STB, SESSION

def fmp_v3(path, params=None):
    """Call the classic v3 API."""
    p = dict(params or {})
    p["apikey"] = API_KEY
    r = SESSION.get(f"{BASE_V3}/{path}", params=p, timeout=12)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and data.get("Error Message"):
        raise PermissionError(data["Error Message"])
    return data

def fmp_stable(path, params=None):
    """Call the newer /stable API using path-based variables to avoid 403 errors."""
    p = dict(params or {})
    p["apikey"] = API_KEY
    # FIXED: Appending the path directly to avoid bad query string parameters
    r = SESSION.get(f"{BASE_STB}/{path}", params=p, timeout=12)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and data.get("Error Message"):
        raise PermissionError(data["Error Message"])
    return data

def try_endpoints(calls):
    """Iterate through candidate endpoints using explicit tuple unpacking."""
    last_err = None
    for item in calls:
        try:
            fn = item
            path_or_endpoint = item
            params = item if len(item) > 2 else None
            
            result = fn(path_or_endpoint, params)
            if result and len(result) > 0:
                return result, None
        except Exception as e:
            last_err = e
    return None, last_err

def fetch_yfinance_eps(ticker):
    """Scrape rolling quarterly EPS metrics or static profiles directly from Yahoo."""
    yf_ticker = yf.Ticker(ticker)
    quarterly_income = yf_ticker.quarterly_income_stmt
    
    if "Diluted EPS" in quarterly_income.index:
        recent_quarters = quarterly_income.loc["Diluted EPS"].dropna().iloc[:4]
        if not recent_quarters.empty:
            return round(float(sum(recent_quarters)), 2), "yfinance — calculated 4-quarter rolling Diluted TTM EPS"
            
    yf_info = yf_ticker.info
    eps_val = yf_info.get("trailingEps") or yf_info.get("forwardEps")
    if eps_val:
        return round(float(eps_val), 2), "yfinance — .info static trailingEps metadata property"
        
    raise ValueError("No metrics discovered inside yfinance parameters")

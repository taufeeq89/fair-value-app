def get_terminal_growth(sector):
    """Retrieve long-run GDP expansion proxies by market macro sector."""
    tg_map = {
        "Technology": 3.0, "Healthcare": 2.8, "Consumer Cyclical": 2.5,
        "Financial Services": 2.5, "Industrials": 2.5, "Energy": 2.0,
        "Utilities": 2.0, "Real Estate": 2.5, "Basic Materials": 2.0,
        "Communication Services": 2.5, "Consumer Defensive": 2.5,
    }
    return tg_map.get(sector, 2.5)

def run_dcf_engine(result, errors):
    """Execute multi-stage EPS projection modeling with terminal multiples formatting."""
    try:
        eps = float(result.get("eps", 0))
        growth_rate = float(result.get("growthRate", 0)) / 100.0
        wacc_val = float(result.get("wacc", 10.0)) / 100.0
        exit_pe = float(result.get("exitPE", 15.0))
        current_price = float(result.get("price", 0))

        if eps <= 0:
            raise ValueError("Intrinsic calculations halted: Base structural EPS is 0 or negative.")

        # Compounding Growth Horizon
        projected_eps = []
        temp_eps = eps
        for year in range(1, 6):
            temp_eps *= (1 + growth_rate)
            projected_eps.append(temp_eps)

        # Cash Discounting Timeline
        pv_earnings = []
        for index, future_eps in enumerate(projected_eps):
            year = index + 1
            pv_earnings.append(future_eps / pow(1 + wacc_val, year))

        # Terminal Valuation Evaluation
        terminal_value_raw = projected_eps[-1] * exit_pe
        pv_terminal_value = terminal_value_raw / pow(1 + wacc_val, 5)

        intrinsic_value = round(sum(pv_earnings) + pv_terminal_value, 2)
        result["intrinsicValue"] = intrinsic_value

        # Margin of Safety Optimization
        if current_price > 0:
            margin = round(((intrinsic_value - current_price) / intrinsic_value) * 100, 1)
            result["marginOfSafety"] = margin
            result["valuationStatus"] = "Undervalued" if margin > 0 else "Overvalued"
        else:
            result["marginOfSafety"] = 0
            result["valuationStatus"] = "Unknown (Price 0)"

        result["valuationSource"] = "Multi-stage EPS Projection Model with terminal multiple execution"

    except Exception as e:
        errors.append(f"Valuation Engine: {e}")
        result["intrinsicValue"] = 0.0
        result["marginOfSafety"] = 0.0
        result["valuationStatus"] = "Calculation Error"
        result["valuationSource"] = "Calculation engine initialization failure"

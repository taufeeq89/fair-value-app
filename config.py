import requests

API_KEY = "kXu1K3e6VnOLjRXubDJqLU40APY6UBrf"
BASE_V3 = "https://financialmodelingprep.com"
BASE_STB = "https://financialmodelingprep.com"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "FairValueApp/1.0"})

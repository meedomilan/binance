import os
import time
from datetime import datetime, timezone, timedelta
import requests
import pandas as pd

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

TIMEFRAMES = {"1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w"}
SCAN_DELAY = 30
REQUEST_TIMEOUT = 20
KLINES_LIMIT = 250
BINANCE_BASE_URL = "https://fapi.binance.com"

last_alerted_candles = {}
session = requests.Session()
session.headers.update({"User-Agent": "Ahmed-Golden-Entry-AI/1.0", "Accept": "application/json"})

def get_ksa_time():
    return (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%d-%m-%Y %H:%M:%S")

def format_price(price):
    price = float(price)
    if price >= 1000: return f"{price:.2f}"
    if price >= 100: return f"{price:.3f}"
    if price >= 1: return f"{price:.4f}"
    if price >= 0.01: return f"{price:.6f}"
    return f"{price:.8f}"

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN is missing")
        return False
    if not TELEGRAM_CHAT_ID:
        print("ERROR: TELEGRAM_CHAT_ID is missing")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML",
               "disable_web_page_preview": True}
    for attempt in range(3):
        try:
            r = session.post(url, json=payload, timeout=REQUEST_TIMEOUT)
            if r.ok:
                print("Telegram alert sent")
                return True
            print("Telegram error:", r.status_code, r.text)
        except Exception as e:
            print("Telegram connection error:", e)
        time.sleep(2)
    return False

def get_binance_futures_symbols():
    url = f"{BINANCE_BASE_URL}/fapi/v1/exchangeInfo"
    for attempt in range(5):
        try:
            r = session.get(url, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            data = r.json()
            symbols = sorted({
                s["symbol"] for s in data.get("symbols", [])
                if s.get("contractType") == "PERPETUAL"
                and s.get("quoteAsset") == "USDT"
                and s.get("status") == "TRADING"
            })
            if symbols:
                print(f"Loaded {len(symbols)} Binance Futures symbols")
                return symbols
        except Exception as e:
            print(f"Binance symbols attempt {attempt+1}/5 failed:", e)
        time.sleep(3)
    return []

def fetch_klines(symbol, interval):
    url = f"{BINANCE_BASE_URL}/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "limit": KLINES_LIMIT}
    for _ in range(3):
        try:
            r = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, list) or not data:
                return None
            df = pd.DataFrame(data, columns=[
                "timestamp","open","high","low","close","volume","close_time",
                "quote_asset_volume","number_of_trades","taker_buy_base",
                "taker_buy_quote","ignore"
            ])
            for c in ["open","high","low","close","volume"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            return df.dropna(subset=["open","high","low","close","volume"])
        except Exception:
            time.sleep(1)
    return None

def calculate_golden_candle(df):
    if df is None or len(df) < 50:
        return None, 0.0, 0.0
    close, opn, high, low, volume = df["close"], df["open"], df["high"], df["low"], df["volume"]
    ma25 = close.ewm(span=25, adjust=False).mean()
    ma50 = close.ewm(span=50, adjust=False).mean()
    ma200 = close.ewm(span=200, adjust=False).mean()
    e12 = close.ewm(span=12, adjust=False).mean()
    e26 = close.ewm(span=26, adjust=False).mean()
    macd = e12 - e26
    sig = macd.ewm(span=9, adjust=False).mean()
    hist = macd - sig
    pos = ((close-low)/(high-low).clip(lower=1e-8)).clip(0,1)
    buy_pct = pos * 100
    sell_pct = (1-pos) * 100
    vr = volume / volume.rolling(20).mean().replace(0,1)

    bull = pd.Series(0.0, index=df.index)
    bull += (close > opn)*8 + (pos >= .75)*7 + ((pos >= .60)&(pos < .75))*4
    bull += (vr >= 2)*13 + ((vr >= 1.5)&(vr < 2))*10 + ((vr >= 1.2)&(vr < 1.5))*5
    bull += (macd > sig)*8 + (hist > 0)*7 + (hist > hist.shift(1))*5
    bull += (close > ma25)*5 + (close > ma50)*6 + (close > ma200)*7
    bull += (ma25 > ma50)*4 + (ma50 > ma200)*5
    bull += (buy_pct >= 70)*8 + ((buy_pct >= 60)&(buy_pct < 70))*5 + ((buy_pct >= 55)&(buy_pct < 60))*3

    bear = pd.Series(0.0, index=df.index)
    bear += (close < opn)*8 + (pos <= .25)*7 + ((pos > .25)&(pos <= .40))*4
    bear += (vr >= 2)*13 + ((vr >= 1.5)&(vr < 2))*10 + ((vr >= 1.2)&(vr < 1.5))*5
    bear += (macd < sig)*8 + (hist < 0)*7 + (hist < hist.shift(1))*5
    bear += (close < ma25)*5 + (close < ma50)*6 + (close < ma200)*7
    bear += (ma25 < ma50)*4 + (ma50 < ma200)*5
    bear += (sell_pct >= 70)*8 + ((sell_pct >= 60)&(sell_pct < 70))*5 + ((sell_pct >= 55)&(sell_pct < 60))*3

    b, s, price = min(float(bull.iloc[-1]),100), min(float(bear.iloc[-1]),100), float(close.iloc[-1])
    if b >= 78 and b > s: return "صاعدة 🟢", b, price
    if s >= 78 and s > b: return "هابطة 🔴", s, price
    return None, 0.0, price

def build_message(symbol, tf, price, direction, score, forming):
    symbol_p = f"{symbol}.P"
    tf_text = tf.upper()
    status = "قيد التكوين ⚠️" if forming else "مؤكدة بعد الإغلاق ✅"
    title = "🟡 GOLDEN CANDLE — LIVE" if forming else "✅ GOLDEN CANDLE — CONFIRMED"
    b = f"https://www.binance.com/en/futures/{symbol}"
    tv = f"https://www.tradingview.com/chart/?symbol=BINANCE%3A{symbol}.P"
    return f"""{title}

💰 العملة: <code>{symbol_p}</code>
⏰ الفريم: <b>{tf_text}</b>
💵 السعر: <code>{format_price(price)}</code>

✨ شمعة ذهبية: <b>{direction}</b>
🔥 قوة الإشارة: <b>{score:.1f}%</b>
⏳ حالة الشمعة: {status}

🕒 {get_ksa_time()} 🇸🇦

🔗 <a href="{b}">Binance Futures</a> | <a href="{tv}">TradingView</a>"""

def scan_market():
    print("Ahmed Golden Entry AI started | 1H 4H 1D 1W")
    while True:
        symbols = get_binance_futures_symbols()
        if not symbols:
            print("No symbols. Retry in 15 sec.")
            time.sleep(15)
            continue
        for symbol in symbols:
            for tf in TIMEFRAMES:
                try:
                    df = fetch_klines(symbol, TIMEFRAMES[tf])
                    if df is None or len(df) < 50:
                        continue
                    d, score, price = calculate_golden_candle(df)
                    ts = int(df["timestamp"].iloc[-1])
                    key = f"{symbol}_{tf}_{ts}_forming"
                    if d and key not in last_alerted_candles:
                        if send_telegram_message(build_message(symbol,tf,price,d,score,True)):
                            last_alerted_candles[key] = True
                    closed = df.iloc[:-1].copy()
                    d, score, price = calculate_golden_candle(closed)
                    ts = int(closed["timestamp"].iloc[-1])
                    key = f"{symbol}_{tf}_{ts}_closed"
                    if d and key not in last_alerted_candles:
                        if send_telegram_message(build_message(symbol,tf,price,d,score,False)):
                            last_alerted_candles[key] = True
                    time.sleep(.15)
                except Exception as e:
                    print("Scan error:", symbol, tf, e)
        if len(last_alerted_candles) > 10000:
            for k in list(last_alerted_candles)[:5000]:
                last_alerted_candles.pop(k, None)
        print("Full scan complete")
        time.sleep(SCAN_DELAY)

if __name__ == "__main__":
    scan_market()

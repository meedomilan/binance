import os
import time
from datetime import datetime, timezone, timedelta

import requests
import pandas as pd

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

TIMEFRAMES = {
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
    "1w": "1w",
}

SCAN_DELAY = 30
REQUEST_TIMEOUT = 20
KLINES_LIMIT = 250
BINANCE_BASE_URL = "https://fapi.binance.com"

last_alerted_candles = {}

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 Ahmed-Golden-Entry-AI/1.0",
    "Accept": "application/json",
})

def get_ksa_time():
    return (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%d-%m-%Y %H:%M:%S")

def format_timeframe(tf):
    return {"1h": "1H", "4h": "4H", "1d": "1D", "1w": "1W"}.get(tf, tf.upper())

def format_price(price):
    try:
        price = float(price)
        if price >= 1000:
            return f"{price:.2f}"
        if price >= 100:
            return f"{price:.3f}"
        if price >= 1:
            return f"{price:.4f}"
        if price >= 0.01:
            return f"{price:.6f}"
        return f"{price:.8f}"
    except Exception:
        return str(price)

def get_links(symbol):
    binance_url = f"https://www.binance.com/en/futures/{symbol}"
    tradingview_url = f"https://www.tradingview.com/chart/?symbol=BINANCE%3A{symbol}.P"
    return binance_url, tradingview_url

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN is missing")
        return False
    if not TELEGRAM_CHAT_ID:
        print("TELEGRAM_CHAT_ID is missing")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    for attempt in range(3):
        try:
            response = session.post(url, json=payload, timeout=REQUEST_TIMEOUT)
            if response.ok:
                print("Telegram alert sent")
                return True
            print(f"Telegram error {response.status_code}: {response.text}")
        except requests.exceptions.Timeout:
            print(f"Telegram timeout {attempt + 1}/3")
        except requests.exceptions.RequestException as e:
            print(f"Telegram connection error: {e}")
        except Exception as e:
            print(f"Telegram error: {e}")
        time.sleep(2)
    return False

def get_binance_futures_symbols():
    url = f"{BINANCE_BASE_URL}/fapi/v1/exchangeInfo"

    for attempt in range(5):
        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT)
            if response.status_code != 200:
                print(f"Binance HTTP {response.status_code}")
                time.sleep(3)
                continue
            if not response.text.strip():
                print("Binance returned an empty response")
                time.sleep(3)
                continue

            data = response.json()
            symbols = [
                item["symbol"]
                for item in data.get("symbols", [])
                if item.get("contractType") == "PERPETUAL"
                and item.get("quoteAsset") == "USDT"
                and item.get("status") == "TRADING"
            ]

            symbols = sorted(set(symbols))
            if symbols:
                print(f"Loaded {len(symbols)} Binance Futures symbols")
                return symbols
        except requests.exceptions.Timeout:
            print(f"Binance timeout {attempt + 1}/5")
        except ValueError:
            print("Binance response is not valid JSON")
        except requests.exceptions.RequestException as e:
            print(f"Binance connection error: {e}")
        except Exception as e:
            print(f"Binance error: {e}")
        time.sleep(3)

    print("Failed to load Binance symbols")
    return []

def fetch_klines(symbol, interval, limit=KLINES_LIMIT):
    url = f"{BINANCE_BASE_URL}/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}

    for _ in range(3):
        try:
            response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if response.status_code != 200 or not response.text.strip():
                time.sleep(1)
                continue

            data = response.json()
            if not isinstance(data, list) or not data:
                return None

            df = pd.DataFrame(data, columns=[
                "timestamp", "open", "high", "low", "close", "volume",
                "close_time", "quote_asset_volume", "number_of_trades",
                "taker_buy_base", "taker_buy_quote", "ignore",
            ])

            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")

            df.dropna(subset=["open", "high", "low", "close", "volume"], inplace=True)
            return df
        except Exception:
            time.sleep(1)

    return None

def calculate_golden_candle(df):
    if df is None or len(df) < 50:
        return None, 0, 0.0

    close = df["close"]
    open_p = df["open"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    ma25 = close.ewm(span=25, adjust=False).mean()
    ma50 = close.ewm(span=50, adjust=False).mean()
    ma200 = close.ewm(span=200, adjust=False).mean()

    exp1 = close.ewm(span=12, adjust=False).mean()
    exp2 = close.ewm(span=26, adjust=False).mean()
    macd_line = exp1 - exp2
    macd_sig = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - macd_sig

    candle_range = (high - low).clip(lower=1e-8)
    close_pos = ((close - low) / candle_range).clip(0.0, 1.0)

    est_buy_vol = volume * close_pos
    est_sell_vol = volume * (1.0 - close_pos)
    est_total_vol = (est_buy_vol + est_sell_vol).clip(lower=1.0)
    buy_pct_now = (est_buy_vol / est_total_vol) * 100.0
    sell_pct_now = (est_sell_vol / est_total_vol) * 100.0

    avg_vol = volume.rolling(window=20).mean().replace(0, 1.0)
    vol_ratio = volume / avg_vol

    bull_score = pd.Series(0.0, index=df.index)
    bull_score += (close > open_p) * 8.0
    bull_score += (close_pos >= 0.75) * 7.0
    bull_score += ((close_pos >= 0.60) & (close_pos < 0.75)) * 4.0
    bull_score += (vol_ratio >= 2.0) * 13.0
    bull_score += ((vol_ratio >= 1.5) & (vol_ratio < 2.0)) * 10.0
    bull_score += ((vol_ratio >= 1.2) & (vol_ratio < 1.5)) * 5.0
    bull_score += (macd_line > macd_sig) * 8.0
    bull_score += (macd_hist > 0) * 7.0
    bull_score += (macd_hist > macd_hist.shift(1)) * 5.0
    bull_score += (close > ma25) * 5.0
    bull_score += (close > ma50) * 6.0
    bull_score += (close > ma200) * 7.0
    bull_score += (ma25 > ma50) * 4.0
    bull_score += (ma50 > ma200) * 5.0
    bull_score += (buy_pct_now >= 70) * 8.0
    bull_score += ((buy_pct_now >= 60) & (buy_pct_now < 70)) * 5.0
    bull_score += ((buy_pct_now >= 55) & (buy_pct_now < 60)) * 3.0
    bull_score = bull_score.clip(upper=100.0)

    bear_score = pd.Series(0.0, index=df.index)
    bear_score += (close < open_p) * 8.0
    bear_score += (close_pos <= 0.25) * 7.0
    bear_score += ((close_pos > 0.25) & (close_pos <= 0.40)) * 4.0
    bear_score += (vol_ratio >= 2.0) * 13.0
    bear_score += ((vol_ratio >= 1.5) & (vol_ratio < 2.0)) * 10.0
    bear_score += ((vol_ratio >= 1.2) & (vol_ratio < 1.5)) * 5.0
    bear_score += (macd_line < macd_sig) * 8.0
    bear_score += (macd_hist < 0) * 7.0
    bear_score += (macd_hist < macd_hist.shift(1)) * 5.0
    bear_score += (close < ma25) * 5.0
    bear_score += (close < ma50) * 6.0
    bear_score += (close < ma200) * 7.0
    bear_score += (ma25 < ma50) * 4.0
    bear_score += (ma50 < ma200) * 5.0
    bear_score += (sell_pct_now >= 70) * 8.0
    bear_score += ((sell_pct_now >= 60) & (sell_pct_now < 70)) * 5.0
    bear_score += ((sell_pct_now >= 55) & (sell_pct_now < 60)) * 3.0
    bear_score = bear_score.clip(upper=100.0)

    b_score = float(bull_score.iloc[-1])
    r_score = float(bear_score.iloc[-1])
    price = float(close.iloc[-1])
    min_golden_score = 78.0

    if b_score >= min_golden_score and b_score > r_score:
        return "صاعدة 🟢", b_score, price
    if r_score >= min_golden_score and r_score > b_score:
        return "هابطة 🔴", r_score, price
    return None, 0, price

def get_strength_text(score):
    if score >= 90:
        return f"🔥 قوية جدًا ({score:.1f}%)"
    if score >= 80:
        return f"💪 قوية ({score:.1f}%)"
    if score >= 78:
        return f"⚡ جيدة ({score:.1f}%)"
    return f"متوسطة ({score:.1f}%)"

def build_message(symbol, timeframe, price, direction, score, candle_status):
    symbol_display = f"{symbol}.P"
    tf_display = format_timeframe(timeframe)
    strength = get_strength_text(score)
    ksa_time = get_ksa_time()
    price_text = format_price(price)
    binance_url, tradingview_url = get_links(symbol)

    if candle_status == "forming":
        status_text = "قيد التكوين ⚠️"
        title = "🟡 GOLDEN CANDLE — LIVE"
    else:
        status_text = "مؤكدة بعد الإغلاق ✅"
        title = "✅ GOLDEN CANDLE — CONFIRMED"

    return f"""{title}

💰 العملة: <code>{symbol_display}</code>
⏰ الفريم: <b>{tf_display}</b>
💵 السعر: <code>{price_text}</code>

✨ شمعة ذهبية: <b>{direction}</b>
🔥 قوة الإشارة: <b>{strength}</b>
⏳ حالة الشمعة: {status_text}

🕒 {ksa_time} 🇸🇦

🔗 <a href="{binance_url}">Binance Futures</a> | <a href="{tradingview_url}">TradingView</a>"""

def cleanup_alert_cache():
    if len(last_alerted_candles) > 10000:
        for key in list(last_alerted_candles.keys())[:5000]:
            last_alerted_candles.pop(key, None)

def scan_market():
    print("Ahmed Golden Entry AI started")

    while True:
        symbols = get_binance_futures_symbols()

        if not symbols:
            print("No symbols loaded. Retrying in 15 seconds...")
            time.sleep(15)
            continue

        print(f"Scanning {len(symbols)} symbols | 1H | 4H | 1D | 1W")

        for symbol in symbols:
            for tf_key, tf_val in TIMEFRAMES.items():
                try:
                    df = fetch_klines(symbol, tf_val)
                    if df is None or len(df) < 50:
                        continue

                    direction, score, price = calculate_golden_candle(df)
                    current_timestamp = int(df["timestamp"].iloc[-1])

                    if direction:
                        alert_key = f"{symbol}_{tf_key}_{current_timestamp}_forming_{direction}"
                        if alert_key not in last_alerted_candles:
                            msg = build_message(symbol, tf_key, price, direction, score, "forming")
                            if send_telegram_message(msg):
                                last_alerted_candles[alert_key] = True

                    closed_df = df.iloc[:-1].copy()
                    direction, score, price = calculate_golden_candle(closed_df)
                    closed_timestamp = int(closed_df["timestamp"].iloc[-1])

                    if direction:
                        alert_key = f"{symbol}_{tf_key}_{closed_timestamp}_closed_{direction}"
                        if alert_key not in last_alerted_candles:
                            msg = build_message(symbol, tf_key, price, direction, score, "closed")
                            if send_telegram_message(msg):
                                last_alerted_candles[alert_key] = True

                    time.sleep(0.15)

                except Exception as e:
                    print(f"Scan error {symbol} {tf_key}: {e}")

        cleanup_alert_cache()
        print(f"Scan completed. Waiting {SCAN_DELAY} seconds...")
        time.sleep(SCAN_DELAY)

if __name__ == "__main__":
    scan_market()

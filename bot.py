import time
from datetime import datetime, timezone, timedelta
import requests
import pandas as pd

# إعدادات بوت التليجرام
TELEGRAM_BOT_TOKEN = "7924553793:AAH_bk0YoW0EqTqQpjKS77n3WiWW0V9Yfag"
TELEGRAM_CHAT_ID = "-1003805942629"

# الفريمات المطلوبة للمتابعة
TIMEFRAMES = {
    '15m': '15m',
    '1h': '1h',
    '4h': '4h',
    '1d': 'd',
    '1w': 'W'
}

# تخزين حالة آخر شمعة تم تنبيهها لمنع التكرار
last_alerted_candles = {}

def get_ksa_time():
    """الحصول على التوقيت الحالي بتوقيت السعودية"""
    utc_now = datetime.now(timezone.utc)
    ksa_time = utc_now + timedelta(hours=3) # توقيت السعودية (UTC+3)
    return ksa_time.strftime('%Y-%m-%d %H:%M:%S')

def send_telegram_message(message):
    """إرسال الرسالة إلى بوت التليجرام"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if not response.ok:
            print(f"خطأ في إرسال التنبيه: {response.text}")
    except Exception as e:
        print(f"حدث استثناء أثناء الاتصال بالتليجرام: {e}")

def get_binance_futures_symbols():
    """جلب جميع أزواج العملات في العقود الآجلة لبانانس"""
    url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        symbols = [s['symbol'] for s in data['symbols'] if s['contractType'] == 'PERPETUAL' and s['quoteAsset'] == 'USDT']
        return symbols
    except Exception as e:
        print(f"خطأ في جلب العملات من بانانس: {e}")
        return []

def fetch_klines(symbol, interval, limit=120):
    """جلب بيانات الشموع التاريخية والجارية للعملة"""
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        if isinstance(data, list) and len(data) > 0:
            df = pd.DataFrame(data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'number_of_trades',
                'taker_buy_base', 'taker_buy_quote', 'ignore'
            ])
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)
            return df
    except Exception as e:
        pass
    return None

def calculate_golden_candle(df):
    """محاكاة معادلات مؤشر الشمعة الذهبية"""
    if df is None or len(df) < 50:
        return None, 0, 0.0

    close = df['close']
    open_p = df['open']
    high = df['high']
    low = df['low']
    volume = df['volume']

    ma25 = close.ewm(span=25, adjust=False).mean()
    ma50 = close.ewm(span=50, adjust=False).mean()
    ma200 = close.ewm(span=200, adjust=False).mean()

    exp1 = close.ewm(span=12, adjust=False).mean()
    exp2 = close.ewm(span=26, adjust=False).mean()
    macd_line = exp1 - exp2
    macd_sig = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - macd_sig

    candle_range = (high - low).apply(lambda x: max(x, 1e-8))
    close_pos = (close - low) / candle_range
    close_pos = close_pos.clip(0.0, 1.0)

    est_buy_vol = volume * close_pos
    est_sell_vol = volume * (1.0 - close_pos)
    est_total_vol = (est_buy_vol + est_sell_vol).apply(lambda x: max(x, 1.0))
    buy_pct_now = (est_buy_vol / est_total_vol) * 100.0
    sell_pct_now = (est_sell_vol / est_total_vol) * 100.0

    mom_avg_vol = volume.rolling(window=20).mean()
    vol_ratio = mom_avg_vol.apply(lambda x: 1.0 if x == 0 else max(x, 0))
    vol_ratio = volume / vol_ratio

    bull_score = 0.0
    bull_score += (close > open_p) * 8.0
    bull_score += (close_pos >= 0.75) * 7.0 + ((close_pos >= 0.60) & (close_pos < 0.75)) * 4.0
    bull_score += (vol_ratio >= 2.0) * 13.0 + ((vol_ratio >= 1.5) & (vol_ratio < 2.0)) * 10.0 + ((vol_ratio >= 1.2) & (vol_ratio < 1.5)) * 5.0
    bull_score += (macd_line > macd_sig) * 8.0
    bull_score += (macd_hist > 0) * 7.0
    bull_score += (macd_hist > macd_hist.shift(1)) * 5.0
    bull_score += (close > ma25) * 5.0
    bull_score += (close > ma50) * 6.0
    bull_score += (close > ma200) * 7.0
    bull_score += (ma25 > ma50) * 4.0
    bull_score += (ma50 > ma200) * 5.0
    bull_score += (buy_pct_now >= 70) * 8.0 + ((buy_pct_now >= 60) & (buy_pct_now < 70)) * 5.0 + ((buy_pct_now >= 55) & (buy_pct_now < 60)) * 3.0
    bull_score = bull_score.clip(upper=100.0)

    bear_score = 0.0
    bear_score += (close < open_p) * 8.0
    bear_score += (close_pos <= 0.25) * 7.0 + ((close_pos > 0.25) & (close_pos <= 0.40)) * 4.0
    bear_score += (vol_ratio >= 2.0) * 13.0 + ((vol_ratio >= 1.5) & (vol_ratio < 2.0)) * 10.0 + ((vol_ratio >= 1.2) & (vol_ratio < 1.5)) * 5.0
    bear_score += (macd_line < macd_sig) * 8.0
    bear_score += (macd_hist < 0) * 7.0
    bear_score += (macd_hist < macd_hist.shift(1)) * 5.0
    bear_score += (close < ma25) * 5.0
    bear_score += (close < ma50) * 6.0
    bear_score += (close < ma200) * 7.0
    bear_score += (ma25 < ma50) * 4.0
    bear_score += (ma50 < ma200) * 5.0
    bear_score += (sell_pct_now >= 70) * 8.0 + ((sell_pct_now >= 60) & (sell_pct_now < 70)) * 5.0 + ((sell_pct_now >= 55) & (sell_pct_now < 60)) * 3.0
    bear_score = bear_score.clip(upper=100.0)

    idx = -1
    b_score = bull_score.iloc[idx]
    r_score = bear_score.iloc[idx]
    min_golden_score = 78.0

    if b_score >= min_golden_score and b_score > r_score:
        return "صاعدة", b_score, close.iloc[idx]
    elif r_score >= min_golden_score and r_score > b_score:
        return "هابطة", r_score, close.iloc[idx]

    return None, 0, close.iloc[idx]

def get_strength_text(score):
    """تحديد قوة الإشارة والنسبة بدقة"""
    if 80 <= score <= 100:
        return f"قوية ({score:.1f}%)"
    elif 50 <= score <= 79:
        return f"متوسطة ({score:.1f}%)"
    else:
        return f"ضعيفة ({score:.1f}%)"

def scan_market():
    symbols = get_binance_futures_symbols()
    print(f"تم بدء فحص {len(symbols)} عملة عقود آجلة على بانانس...")

    while True:
        for symbol in symbols:
            for tf_key, tf_val in TIMEFRAMES.items():
                df = fetch_klines(symbol, tf_val, limit=120)
                if df is None or len(df) < 3:
                    continue

                # 1. فحص الشمعة الحالية (قيد التكوين)
                direction_forming, score_forming, price_forming = calculate_golden_candle(df)
                current_candle_timestamp = df['timestamp'].iloc[-1]
                
                if direction_forming:
                    alert_key_forming = f"{symbol}_{tf_key}_{current_candle_timestamp}_forming"
                    if alert_key_forming not in last_alerted_candles:
                        last_alerted_candles[alert_key_forming] = True
                        
                        strength_str = get_strength_text(score_forming)
                        ksa_time = get_ksa_time()
                        
                        msg = f"""💰 العملة: {symbol}
⏰ الفريم: {tf_key.upper()}
💲 السعر: {price_forming}

✅ ظهرت شمعة ذهبية {direction_forming}
⚡️ وقت الظهور: {ksa_time}
⏳ حالة الشمعة: قيد التكوين ⚠️
🔥 قوة الإشارة: {strength_str}

🔗 Binance Futures | TradingView"""
                        send_telegram_message(msg)

                # 2. فحص الشمعة المؤكدة (بعد إغلاقها تماماً)
                closed_df = df.iloc[:-1]
                direction_closed, score_closed, price_closed = calculate_golden_candle(closed_df)
                closed_candle_timestamp = closed_df['timestamp'].iloc[-1]

                if direction_closed:
                    alert_key_closed = f"{symbol}_{tf_key}_{closed_candle_timestamp}_closed"
                    if alert_key_closed not in last_alerted_candles:
                        last_alerted_candles[alert_key_closed] = True
                        
                        strength_str = get_strength_text(score_closed)
                        ksa_time = get_ksa_time()
                        
                        msg = f"""💰 العملة: {symbol}
⏰ الفريم: {tf_key.upper()}
💲 السعر: {price_closed}

✅ ظهرت شمعة ذهبية {direction_closed}
⚡️ وقت الظهور: {ksa_time}
⏳ حالة الشمعة: مؤكدة بعد الإغلاق ✅
🔥 قوة الإشارة: {strength_str}

🔗 Binance Futures | TradingView"""
                        send_telegram_message(msg)

                time.sleep(0.2)
        time.sleep(30)

if __name__ == "__main__":
    print("🚀 تم تشغيل نظام بوت التنبيهات بنجاح...")
    scan_market()

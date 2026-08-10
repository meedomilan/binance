import os
import time
from datetime import datetime, timezone, timedelta

import requests
import pandas as pd


# =========================================================
# إعدادات Telegram من Railway Variables
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv("7924553793:AAH_bk0YoW0EqTqQpjKS77n3WiWW0V9Yfag", "").strip()
TELEGRAM_CHAT_ID = os.getenv("1039965311", "").strip()


# =========================================================
# إعدادات الفريمات
# تم حذف 15M
# =========================================================

TIMEFRAMES = {
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
    "1w": "1w",
}


# =========================================================
# إعدادات عامة
# =========================================================

SCAN_DELAY = 30
REQUEST_TIMEOUT = 20
KLINES_LIMIT = 250

BINANCE_BASE_URL = "https://fapi.binance.com"


# =========================================================
# Session
# =========================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0 Ahmed-Golden-Entry-AI/1.0",
    "Accept": "application/json",
})


# =========================================================
# تخزين التنبيهات لمنع التكرار
# =========================================================

last_alerted_candles = {}


# =========================================================
# توقيت السعودية
# =========================================================

def get_ksa_time():
    utc_now = datetime.now(timezone.utc)
    ksa_time = utc_now + timedelta(hours=3)

    return ksa_time.strftime("%d-%m-%Y %H:%M:%S")


# =========================================================
# تحويل الفريم للشكل العربي/الواضح
# =========================================================

def format_timeframe(tf):
    names = {
        "1h": "1H",
        "4h": "4H",
        "1d": "1D",
        "1w": "1W",
    }

    return names.get(tf, tf.upper())


# =========================================================
# تنظيف السعر
# =========================================================

def format_price(price):
    try:
        price = float(price)

        if price >= 1000:
            return f"{price:.2f}"

        elif price >= 100:
            return f"{price:.3f}"

        elif price >= 1:
            return f"{price:.4f}"

        elif price >= 0.01:
            return f"{price:.6f}"

        else:
            return f"{price:.8f}"

    except Exception:
        return str(price)


# =========================================================
# روابط Binance و TradingView
# =========================================================

def get_links(symbol):

    # Binance يستخدم BTCUSDT
    binance_url = (
        f"https://www.binance.com/en/futures/{symbol}"
    )

    # TradingView يستخدم BTCUSDT.P
    tradingview_url = (
        f"https://www.tradingview.com/chart/"
        f"?symbol=BINANCE%3A{symbol}.P"
    )

    return binance_url, tradingview_url


# =========================================================
# إرسال Telegram
# =========================================================

def send_telegram_message(message):

    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN غير موجود")
        return False

    if not TELEGRAM_CHAT_ID:
        print("❌ TELEGRAM_CHAT_ID غير موجود")
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    for attempt in range(3):

        try:

            response = session.post(
                url,
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )

            if response.ok:
                print("✅ تم إرسال التنبيه")
                return True

            print(
                f"❌ خطأ Telegram "
                f"{response.status_code}: "
                f"{response.text}"
            )

        except requests.exceptions.Timeout:
            print(
                f"⚠️ Telegram Timeout "
                f"المحاولة {attempt + 1}/3"
            )

        except requests.exceptions.RequestException as e:
            print(
                f"⚠️ مشكلة اتصال Telegram: {e}"
            )

        except Exception as e:
            print(
                f"⚠️ خطأ Telegram غير متوقع: {e}"
            )

        time.sleep(2)

    return False


# =========================================================
# جلب عملات Binance Futures
# =========================================================

def get_binance_futures_symbols():

    url = (
        f"{BINANCE_BASE_URL}/"
        f"fapi/v1/exchangeInfo"
    )

    for attempt in range(5):

        try:

            response = session.get(
                url,
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code != 200:

                print(
                    f"⚠️ Binance HTTP "
                    f"{response.status_code}"
                )

                time.sleep(3)
                continue

            if not response.text.strip():

                print(
                    "⚠️ Binance أعاد استجابة فارغة"
                )

                time.sleep(3)
                continue

            data = response.json()

            if "symbols" not in data:

                print(
                    "⚠️ لم يتم العثور على symbols "
                    "في رد Binance"
                )

                time.sleep(3)
                continue

            symbols = []

            for item in data["symbols"]:

                if (
                    item.get("contractType") == "PERPETUAL"
                    and item.get("quoteAsset") == "USDT"
                    and item.get("status") == "TRADING"
                ):

                    symbols.append(
                        item["symbol"]
                    )

            symbols = sorted(
                list(set(symbols))
            )

            if symbols:

                print(
                    f"✅ تم جلب "
                    f"{len(symbols)} "
                    f"عملة Futures"
                )

                return symbols

        except requests.exceptions.Timeout:

            print(
                f"⚠️ Binance Timeout "
                f"{attempt + 1}/5"
            )

        except ValueError:

            print(
                "⚠️ رد Binance ليس JSON صالح"
            )

        except requests.exceptions.RequestException as e:

            print(
                f"⚠️ مشكلة اتصال Binance: {e}"
            )

        except Exception as e:

            print(
                f"⚠️ خطأ في جلب العملات: {e}"
            )

        time.sleep(3)

    print(
        "❌ فشل جلب العملات بعد عدة محاولات"
    )

    return []


# =========================================================
# جلب الشموع
# =========================================================

def fetch_klines(
    symbol,
    interval,
    limit=KLINES_LIMIT,
):

    url = (
        f"{BINANCE_BASE_URL}/"
        f"fapi/v1/klines"
    )

    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }

    for attempt in range(3):

        try:

            response = session.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code != 200:
                time.sleep(1)
                continue

            if not response.text.strip():
                time.sleep(1)
                continue

            data = response.json()

            if (
                not isinstance(data, list)
                or len(data) == 0
            ):
                return None

            df = pd.DataFrame(
                data,
                columns=[
                    "timestamp",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "close_time",
                    "quote_asset_volume",
                    "number_of_trades",
                    "taker_buy_base",
                    "taker_buy_quote",
                    "ignore",
                ],
            )

            numeric_columns = [
                "open",
                "high",
                "low",
                "close",
                "volume",
            ]

            for col in numeric_columns:

                df[col] = pd.to_numeric(
                    df[col],
                    errors="coerce",
                )

            df.dropna(
                subset=numeric_columns,
                inplace=True,
            )

            return df

        except Exception:
            time.sleep(1)

    return None


# =========================================================
# حساب الشمعة الذهبية
# =========================================================

def calculate_golden_candle(df):

    if df is None or len(df) < 50:
        return None, 0, 0.0

    close = df["close"]
    open_p = df["open"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]


    # =====================================================
    # المتوسطات
    # =====================================================

    ma25 = close.ewm(
        span=25,
        adjust=False,
    ).mean()

    ma50 = close.ewm(
        span=50,
        adjust=False,
    ).mean()

    ma200 = close.ewm(
        span=200,
        adjust=False,
    ).mean()


    # =====================================================
    # MACD
    # =====================================================

    exp1 = close.ewm(
        span=12,
        adjust=False,
    ).mean()

    exp2 = close.ewm(
        span=26,
        adjust=False,
    ).mean()

    macd_line = exp1 - exp2

    macd_sig = macd_line.ewm(
        span=9,
        adjust=False,
    ).mean()

    macd_hist = (
        macd_line - macd_sig
    )


    # =====================================================
    # مكان الإغلاق داخل الشمعة
    # =====================================================

    candle_range = (
        high - low
    ).clip(lower=1e-8)

    close_pos = (
        close - low
    ) / candle_range

    close_pos = close_pos.clip(
        0.0,
        1.0,
    )


    # =====================================================
    # تقدير حجم الشراء والبيع
    # =====================================================

    est_buy_vol = (
        volume * close_pos
    )

    est_sell_vol = (
        volume * (1.0 - close_pos)
    )

    est_total_vol = (
        est_buy_vol + est_sell_vol
    ).clip(lower=1.0)

    buy_pct_now = (
        est_buy_vol /
        est_total_vol
    ) * 100.0

    sell_pct_now = (
        est_sell_vol /
        est_total_vol
    ) * 100.0


    # =====================================================
    # Volume Ratio
    # =====================================================

    mom_avg_vol = (
        volume
        .rolling(window=20)
        .mean()
    )

    safe_avg_vol = (
        mom_avg_vol
        .replace(0, 1.0)
    )

    vol_ratio = (
        volume /
        safe_avg_vol
    )


    # =====================================================
    # Bull Score
    # =====================================================

    bull_score = pd.Series(
        0.0,
        index=df.index,
    )

    bull_score += (
        (close > open_p) * 8.0
    )

    bull_score += (
        (close_pos >= 0.75) * 7.0
    )

    bull_score += (
        (
            (close_pos >= 0.60)
            &
            (close_pos < 0.75)
        ) * 4.0
    )

    bull_score += (
        (vol_ratio >= 2.0) * 13.0
    )

    bull_score += (
        (
            (vol_ratio >= 1.5)
            &
            (vol_ratio < 2.0)
        ) * 10.0
    )

    bull_score += (
        (
            (vol_ratio >= 1.2)
            &
            (vol_ratio < 1.5)
        ) * 5.0
    )

    bull_score += (
        (macd_line > macd_sig) * 8.0
    )

    bull_score += (
        (macd_hist > 0) * 7.0
    )

    bull_score += (
        (
            macd_hist >
            macd_hist.shift(1)
        ) * 5.0
    )

    bull_score += (
        (close > ma25) * 5.0
    )

    bull_score += (
        (close > ma50) * 6.0
    )

    bull_score += (
        (close > ma200) * 7.0
    )

    bull_score += (
        (ma25 > ma50) * 4.0
    )

    bull_score += (
        (ma50 > ma200) * 5.0
    )

    bull_score += (
        (buy_pct_now >= 70) * 8.0
    )

    bull_score += (
        (
            (buy_pct_now >= 60)
            &
            (buy_pct_now < 70)
        ) * 5.0
    )

    bull_score += (
        (
            (buy_pct_now >= 55)
            &
            (buy_pct_now < 60)
        ) * 3.0
    )

    bull_score = bull_score.clip(
        upper=100.0
    )


    # =====================================================
    # Bear Score
    # =====================================================

    bear_score = pd.Series(
        0.0,
        index=df.index,
    )

    bear_score += (
        (close < open_p) * 8.0
    )

    bear_score += (
        (close_pos <= 0.25) * 7.0
    )

    bear_score += (
        (
            (close_pos > 0.25)
            &
            (close_pos <= 0.40)
        ) * 4.0
    )

    bear_score += (
        (vol_ratio >= 2.0) * 13.0
    )

    bear_score += (
        (
            (vol_ratio >= 1.5)
            &
            (vol_ratio < 2.0)
        ) * 10.0
    )

    bear_score += (
        (
            (vol_ratio >= 1.2)
            &
            (vol_ratio < 1.5)
        ) * 5.0
    )

    bear_score += (
        (macd_line < macd_sig) * 8.0
    )

    bear_score += (
        (macd_hist < 0) * 7.0
    )

    bear_score += (
        (
            macd_hist <
            macd_hist.shift(1)
        ) * 5.0
    )

    bear_score += (
        (close < ma25) * 5.0
    )

    bear_score += (
        (close < ma50) * 6.0
    )

    bear_score += (
        (close < ma200) * 7.0
    )

    bear_score += (
        (ma25 < ma50) * 4.0
    )

    bear_score += (
        (ma50 < ma200) * 5.0
    )

    bear_score += (
        (sell_pct_now >= 70) * 8.0
    )

    bear_score += (
        (
            (sell_pct_now >= 60)
            &
            (sell_pct_now < 70)
        ) * 5.0
    )

    bear_score += (
        (
            (sell_pct_now >= 55)
            &
            (sell_pct_now < 60)
        ) * 3.0
    )

    bear_score = bear_score.clip(
        upper=100.0
    )


    # =====================================================
    # آخر شمعة
    # =====================================================

    idx = -1

    b_score = float(
        bull_score.iloc[idx]
    )

    r_score = float(
        bear_score.iloc[idx]
    )

    price = float(
        close.iloc[idx]
    )


    # =====================================================
    # حد الشمعة الذهبية
    # =====================================================

    MIN_GOLDEN_SCORE = 78.0


    if (
        b_score >= MIN_GOLDEN_SCORE
        and b_score > r_score
    ):

        return (
            "صاعدة 🟢",
            b_score,
            price,
        )


    elif (
        r_score >= MIN_GOLDEN_SCORE
        and r_score > b_score
    ):

        return (
            "هابطة 🔴",
            r_score,
            price,
        )


    return (
        None,
        0,
        price,
    )


# =========================================================
# قوة الإشارة
# =========================================================

def get_strength_text(score):

    if score >= 90:

        return (
            f"🔥 قوية جدًا "
            f"({score:.1f}%)"
        )

    elif score >= 80:

        return (
            f"💪 قوية "
            f"({score:.1f}%)"
        )

    elif score >= 78:

        return (
            f"⚡ جيدة "
            f"({score:.1f}%)"
        )

    else:

        return (
            f"متوسطة "
            f"({score:.1f}%)"
        )


# =========================================================
# إنشاء رسالة Telegram
# =========================================================

def build_message(
    symbol,
    timeframe,
    price,
    direction,
    score,
    candle_status,
):

    symbol_display = (
        f"{symbol}.P"
    )

    tf_display = (
        format_timeframe(
            timeframe
        )
    )

    strength = (
        get_strength_text(
            score
        )
    )

    ksa_time = (
        get_ksa_time()
    )

    price_text = (
        format_price(
            price
        )
    )

    binance_url, tradingview_url = (
        get_links(symbol)
    )


    if candle_status == "forming":

        status_text = (
            "قيد التكوين ⚠️"
        )

        title = (
            "🟡 GOLDEN CANDLE — LIVE"
        )

    else:

        status_text = (
            "مؤكدة بعد الإغلاق ✅"
        )

        title = (
            "✅ GOLDEN CANDLE — CONFIRMED"
        )


    message = f"""
{title}

💰 العملة: <code>{symbol_display}</code>
⏰ الفريم: <b>{tf_display}</b>
💵 السعر: <code>{price_text}</code>

✨ شمعة ذهبية: <b>{direction}</b>
🔥 قوة الإشارة: <b>{strength}</b>
⏳ حالة الشمعة: {status_text}

🕒 {ksa_time} 🇸🇦

🔗 <a href="{binance_url}">Binance Futures</a> | <a href="{tradingview_url}">TradingView</a>
"""

    return message.strip()


# =========================================================
# تنظيف سجل التنبيهات القديم
# =========================================================

def cleanup_alert_cache():

    if len(last_alerted_candles) > 10000:

        keys = list(
            last_alerted_candles.keys()
        )

        for key in keys[:5000]:

            last_alerted_candles.pop(
                key,
                None,
            )


# =========================================================
# فحص السوق
# =========================================================

def scan_market():

    print(
        "🚀 تم تشغيل Ahmed Golden Entry AI"
    )

    while True:

        symbols = (
            get_binance_futures_symbols()
        )


        # =================================================
        # إذا Binance لم يعط العملات
        # لا يبدأ على 0 عملة
        # =================================================

        if not symbols:

            print(
                "⚠️ لم يتم جلب العملات."
            )

            print(
                "🔄 إعادة المحاولة بعد 15 ثانية..."
            )

            time.sleep(15)

            continue


        print(
            f"🔍 بدء فحص "
            f"{len(symbols)} "
            f"عملة"
        )

        print(
            "⏰ الفريمات: "
            "1H | 4H | 1D | 1W"
        )


        # =================================================
        # العملات
        # =================================================

        for symbol in symbols:


            # =============================================
            # الفريمات
            # =============================================

            for tf_key, tf_val in TIMEFRAMES.items():

                try:

                    df = fetch_klines(
                        symbol,
                        tf_val,
                        limit=KLINES_LIMIT,
                    )

                    if (
                        df is None
                        or len(df) < 50
                    ):

                        continue


                    # =====================================
                    # 1 - الشمعة الحالية
                    # =====================================

                    (
                        direction_forming,
                        score_forming,
                        price_forming,
                    ) = calculate_golden_candle(
                        df
                    )


                    current_candle_timestamp = int(
                        df["timestamp"].iloc[-1]
                    )


                    if direction_forming:

                        alert_key = (
                            f"{symbol}_"
                            f"{tf_key}_"
                            f"{current_candle_timestamp}_"
                            f"forming_"
                            f"{direction_forming}"
                        )


                        if (
                            alert_key
                            not in
                            last_alerted_candles
                        ):

                            msg = build_message(
                                symbol=symbol,
                                timeframe=tf_key,
                                price=price_forming,
                                direction=direction_forming,
                                score=score_forming,
                                candle_status="forming",
                            )


                            if send_telegram_message(
                                msg
                            ):

                                last_alerted_candles[
                                    alert_key
                                ] = True


                    # =====================================
                    # 2 - آخر شمعة مغلقة
                    # =====================================

                    closed_df = (
                        df.iloc[:-1].copy()
                    )


                    (
                        direction_closed,
                        score_closed,
                        price_closed,
                    ) = calculate_golden_candle(
                        closed_df
                    )


                    closed_candle_timestamp = int(
                        closed_df[
                            "timestamp"
                        ].iloc[-1]
                    )


                    if direction_closed:

                        alert_key = (
                            f"{symbol}_"
                            f"{tf_key}_"
                            f"{closed_candle_timestamp}_"
                            f"closed_"
                            f"{direction_closed}"
                        )


                        if (
                            alert_key
                            not in
                            last_alerted_candles
                        ):

                            msg = build_message(
                                symbol=symbol,
                                timeframe=tf_key,
                                price=price_closed,
                                direction=direction_closed,
                                score=score_closed,
                                candle_status="closed",
                            )


                            if send_telegram_message(
                                msg
                            ):

                                last_alerted_candles[
                                    alert_key
                                ] = True


                    time.sleep(0.15)


                except Exception as e:

                    print(
                        f"⚠️ خطأ "
                        f"{symbol} "
                        f"{tf_key}: "
                        f"{e}"
                    )


        cleanup_alert_cache()


        print(
            "✅ انتهى الفحص الكامل"
        )

        print(
            f"⏳ انتظار "
            f"{SCAN_DELAY} "
            f"ثانية..."
        )

        time.sleep(
            SCAN_DELAY
        )


# =========================================================
# تشغيل البرنامج
# =========================================================

if __name__ == "__main__":

    scan_market()

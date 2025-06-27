# V3 SIGNAL BOT 📱 - Render + UptimeRobot Edition
import pandas as pd, numpy as np, matplotlib.pyplot as plt, requests, datetime, pytz, hashlib, io
import telegram, threading, uvicorn
from fastapi import FastAPI
from apscheduler.schedulers.blocking import BlockingScheduler
from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator

# === CONFIG ===
API_KEY = "c78b6090d46845e0b311cc92ebb0b13d"
BOT_TOKEN = "7613620588:AAEui2boeLqJ7ukxmjiiUNF8njOgEUoWRM8"
CHAT_ID = "7765972595"
TIMEZONE = pytz.timezone("Asia/Kolkata")
SYMBOLS = ["BTC/USD", "XAU/USD", "EUR/USD", "USD/CAD", "GBP/USD", "USD/JPY", "AUD/USD", "NZD/USD"]
INTERVAL_MINUTES = 30
LAST_SIGNAL = {}

bot = telegram.Bot(token=BOT_TOKEN)
app = FastAPI()

@app.get("/")
@app.head("/")
def home():
    return {"status": "✅ V3 Signal Bot Online"}

def fetch(symbol):
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=30min&outputsize=100&apikey={API_KEY}"
    r = requests.get(url).json()
    if "values" not in r: return None
    df = pd.DataFrame(r["values"])[::-1]
    df["datetime"] = pd.to_datetime(df["datetime"])
    df.set_index("datetime", inplace=True)
    return df.astype(float)

def indicators(df):
    df["EMA20"] = EMAIndicator(df["close"], 20).ema_indicator()
    df["EMA50"] = EMAIndicator(df["close"], 50).ema_indicator()
    df["RSI"] = RSIIndicator(df["close"], 14).rsi()
    macd = MACD(df["close"])
    df["MACD"] = macd.macd()
    df["Signal"] = macd.macd_signal()
    return df

def candlestick_patterns(df):
    last, prev = df.iloc[-1], df.iloc[-2]
    body = abs(last["close"] - last["open"])
    range_ = last["high"] - last["low"]
    body_ratio = body / range_ if range_ else 0

    if last["open"] < last["close"] and prev["open"] > prev["close"] and last["open"] < prev["close"] and last["close"] > prev["open"]:
        return "Bullish Engulfing"
    if last["open"] > last["close"] and prev["open"] < prev["close"] and last["open"] > prev["close"] and last["close"] < prev["open"]:
        return "Bearish Engulfing"
    if body_ratio < 0.2: return "Doji"
    if last["close"] > last["open"] and last["open"] - last["low"] > 0.5 * range_: return "Hammer"
    if last["close"] < last["open"] and last["high"] - last["open"] > 0.5 * range_: return "Inverted Hammer"
    return "Neutral"

def chart_patterns(df):
    closes = df["close"].tail(20)
    highs, lows = closes.rolling(3).max(), closes.rolling(3).min()
    uptrend = all(x < y for x, y in zip(lows, lows[1:]))
    downtrend = all(x > y for x, y in zip(highs, highs[1:]))
    if uptrend: return "Rising Wedge"
    if downtrend: return "Falling Wedge"
    return "No Chart Pattern"

def signal(df):
    last, prev = df.iloc[-1], df.iloc[-2]
    buy = prev["EMA20"] < prev["EMA50"] and last["EMA20"] > last["EMA50"] and last["RSI"] > 50 and last["MACD"] > last["Signal"]
    sell = prev["EMA20"] > prev["EMA50"] and last["EMA20"] < last["EMA50"] and last["RSI"] < 50 and last["MACD"] < last["Signal"]
    return "BUY" if buy else "SELL" if sell else None

def calculate_tp_sl(df, direction):
    close = df["close"].iloc[-1]
    high, low = df["high"].iloc[-20:].max(), df["low"].iloc[-20:].min()
    range_ = high - low
    tp = close + range_ * 0.3 if direction == "BUY" else close - range_ * 0.3
    sl = close - range_ * 0.08 if direction == "BUY" else close + range_ * 0.08
    tp_pct = abs(tp - close) / close * 100
    sl_pct = abs(sl - close) / close * 100
    if tp_pct > 15 and sl_pct < 10 and round(tp, 2) != round(sl, 2): return sl, tp
    return None, None

def draw_chart(df, symbol, sig, pattern1, pattern2, sl, tp):
    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(7, 2.5))  # 📱 Horizontal layout only
    df["close"].tail(30).plot(ax=ax, color='cyan', label="Close")
    df["EMA20"].tail(30).plot(ax=ax, color='lime', label="EMA20", lw=0.8)
    df["EMA50"].tail(30).plot(ax=ax, color='red', label="EMA50", lw=0.8)
    ax.axhline(tp, color="green", linestyle="--", lw=0.6)
    ax.axhline(sl, color="orange", linestyle="--", lw=0.6)
    ax.set_title(f"{symbol} • {sig} • {pattern1} • {pattern2}", fontsize=9)
    ax.legend(fontsize=6, ncol=4, loc="upper left")
    plt.grid(alpha=0.2)
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=100)
    buf.seek(0)
    plt.close()
    return buf

def alert(sym, sig, sl, tp, pat1, pat2, img):
    now = datetime.datetime.now(TIMEZONE).strftime('%d %b %H:%M')
    msg = f"""📊 {sym}
🔁 Signal: {sig}
🧠 Candle: {pat1}
📐 Chart: {pat2}
📍 SL: {sl:.2f}
🎯 TP: {tp:.2f}
🕐 {now}
🧪 EMA + RSI + MACD Confirmed"""
    bot.send_photo(chat_id=CHAT_ID, photo=img, caption=msg)

def hash_signal(sym, sig, sl, tp):
    return hashlib.md5(f"{sym}_{sig}_{round(sl,2)}_{round(tp,2)}".encode()).hexdigest()

def is_market_open():
    now = datetime.datetime.now(TIMEZONE)
    return now.weekday() < 5 and 5 <= now.hour < 23  # Mon–Fri 5AM–11PM IST

def scan():
    print(f"\n⏰ Scan @ {datetime.datetime.now(TIMEZONE).strftime('%H:%M')}")
    for sym in SYMBOLS:
        if sym != "BTC/USD" and not is_market_open(): continue
        df = fetch(sym)
        if df is None: continue
        df = indicators(df)
        sig = signal(df)
        if not sig: continue
        sl, tp = calculate_tp_sl(df, sig)
        if not sl or not tp: continue
        sig_hash = hash_signal(sym, sig, sl, tp)
        if LAST_SIGNAL.get(sym) == sig_hash: continue
        LAST_SIGNAL[sym] = sig_hash
        pat1 = candlestick_patterns(df)
        pat2 = chart_patterns(df)
        chart = draw_chart(df, sym, sig, pat1, pat2, sl, tp)
        alert(sym, sig, sl, tp, pat1, pat2, chart)

# Run Render + UptimeRobot + 30-min scan
if __name__ == "__main__":
    scheduler = BlockingScheduler(timezone=TIMEZONE)
    scheduler.add_job(scan, "interval", minutes=INTERVAL_MINUTES)
    threading.Thread(target=lambda: uvicorn.run(app, host="0.0.0.0", port=10000)).start()
    scan()
    scheduler.start()

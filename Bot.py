# 📦 Dependencies (install in Colab or environment)
# !pip install pandas numpy matplotlib requests ta fastapi uvicorn python-telegram-bot apscheduler --quiet

import pandas as pd, numpy as np, matplotlib.pyplot as plt, requests, datetime, pytz, io, hashlib, threading
import telegram, uvicorn
from fastapi import FastAPI
from apscheduler.schedulers.blocking import BlockingScheduler
from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator

# === 🔧 CONFIG ===
API_KEY = "fdca7f8d553f469cbfb5050d59cbb331"
BOT_TOKEN = "7613620588:AAEui2boeLqJ7ukxmjiiUNF8njOgEUoWRM8"
CHAT_ID = "7765972595"
TIMEZONE = pytz.timezone("Asia/Kolkata")
INTERVAL_MINUTES = 30
SYMBOLS = ["BTC/USD", "XAU/USD", "EUR/USD", "USD/CAD", "GBP/USD", "USD/JPY", "AUD/USD", "NZD/USD"]
LAST_SIGNAL = {}

# === 📡 Setup ===
bot = telegram.Bot(token=BOT_TOKEN)
app = FastAPI()

@app.get("/")
def health():
    return {"status": "✅ V3 Bot Online"}

# === 📈 Fetch Data ===
def fetch(symbol):
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=30min&outputsize=100&apikey={API_KEY}"
    r = requests.get(url).json()
    if "values" not in r: return None
    df = pd.DataFrame(r["values"])[::-1]
    df["datetime"] = pd.to_datetime(df["datetime"])
    df.set_index("datetime", inplace=True)
    return df.astype(float)

# === 📊 Indicators ===
def add_indicators(df):
    df["EMA20"] = EMAIndicator(df["close"], 20).ema_indicator()
    df["EMA50"] = EMAIndicator(df["close"], 50).ema_indicator()
    df["RSI"] = RSIIndicator(df["close"], 14).rsi()
    macd = MACD(df["close"])
    df["MACD"] = macd.macd()
    df["MACD_Signal"] = macd.macd_signal()
    return df

# === 🕯️ Candlestick Patterns ===
def detect_candle(df):
    last, prev = df.iloc[-1], df.iloc[-2]
    body = abs(last["close"] - last["open"])
    range_ = last["high"] - last["low"]
    if body / range_ < 0.2: return "Doji"
    if last["close"] > last["open"] and prev["close"] < prev["open"]: return "Bullish Engulfing"
    if last["close"] < last["open"] and prev["close"] > prev["open"]: return "Bearish Engulfing"
    return "Neutral"

# === 🪜 Chart Patterns (simple wedge detector) ===
def detect_chart(df):
    close = df["close"].tail(20)
    highs = close.rolling(3).max()
    lows = close.rolling(3).min()
    up = all(x < y for x, y in zip(lows, lows[1:]))
    down = all(x > y for x, y in zip(highs, highs[1:]))
    if up: return "Rising Wedge"
    if down: return "Falling Wedge"
    return "Neutral"

# === 💡 Signal Logic ===
def generate_signal(df):
    last, prev = df.iloc[-1], df.iloc[-2]
    buy = (prev["EMA20"] < prev["EMA50"] and last["EMA20"] > last["EMA50"]
           and last["RSI"] > 50 and last["MACD"] > last["MACD_Signal"])
    sell = (prev["EMA20"] > prev["EMA50"] and last["EMA20"] < last["EMA50"]
            and last["RSI"] < 50 and last["MACD"] < last["MACD_Signal"])
    return "BUY" if buy else "SELL" if sell else None

# === 🎯 TP/SL Logic ===
def tp_sl(df, direction):
    close = df["close"].iloc[-1]
    high = df["high"].iloc[-20:].max()
    low = df["low"].iloc[-20:].min()
    rng = high - low
    tp = close + 0.3 * rng if direction == "BUY" else close - 0.3 * rng
    sl = close - 0.08 * rng if direction == "BUY" else close + 0.08 * rng
    tp_pct = abs(tp - close) / close * 100
    sl_pct = abs(sl - close) / close * 100
    if tp_pct > 15 and sl_pct < 10 and round(tp,2) != round(sl,2): return sl, tp
    return None, None

# === 📷 Chart Screenshot ===
def draw(df, sym, sig, candle, chart, sl, tp):
    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(6.5, 2.2))  # 📱 Horizontal layout
    df["close"].tail(30).plot(ax=ax, color="cyan", label="Close")
    df["EMA20"].tail(30).plot(ax=ax, color="lime", label="EMA20")
    df["EMA50"].tail(30).plot(ax=ax, color="red", label="EMA50")
    ax.axhline(tp, color="green", linestyle="--", linewidth=0.6)
    ax.axhline(sl, color="orange", linestyle="--", linewidth=0.6)
    ax.set_title(f"{sym} • {sig} • {candle} • {chart}", fontsize=9)
    ax.legend(fontsize=6, loc="upper left", ncol=4)
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=100)
    buf.seek(0)
    plt.close()
    return buf

# === 📤 Telegram Alert ===
def send_alert(sym, sig, sl, tp, candle, chart, img):
    now = datetime.datetime.now(TIMEZONE).strftime('%d %b %H:%M')
    msg = f"""📊 {sym}
🔁 Signal: {sig}
🧠 Candle: {candle}
📐 Chart: {chart}
📍 SL: {sl:.2f}
🎯 TP: {tp:.2f}
🧪 Confirmed with EMA+RSI+MACD
🕐 {now}"""
    bot.send_photo(chat_id=CHAT_ID, photo=img, caption=msg)

# === 🧠 Unique hash to avoid duplicate ===
def hash_it(sym, sig, sl, tp):
    return hashlib.md5(f"{sym}_{sig}_{round(sl,2)}_{round(tp,2)}".encode()).hexdigest()

# === 🕓 Market Hours Filter ===
def market_open():
    now = datetime.datetime.now(TIMEZONE)
    return now.weekday() < 5 and 5 <= now.hour < 23

# === 🔁 Main Scan ===
def scan():
    print(f"\n⏰ Scan @ {datetime.datetime.now(TIMEZONE).strftime('%H:%M')}")
    for sym in SYMBOLS:
        if sym != "BTC/USD" and not market_open(): continue
        df = fetch(sym)
        if df is None: continue
        df = add_indicators(df)
        sig = generate_signal(df)
        if not sig: continue
        sl, tp = tp_sl(df, sig)
        if not sl or not tp: continue
        sig_id = hash_it(sym, sig, sl, tp)
        if LAST_SIGNAL.get(sym) == sig_id: continue
        LAST_SIGNAL[sym] = sig_id
        candle = detect_candle(df)
        chart = detect_chart(df)
        img = draw(df, sym, sig, candle, chart, sl, tp)
        send_alert(sym, sig, sl, tp, candle, chart, img)

# === 🖥️ Run on Render (with port and scheduler)
if __name__ == "__main__":
    scheduler = BlockingScheduler(timezone=TIMEZONE)
    scheduler.add_job(scan, "interval", minutes=INTERVAL_MINUTES)
    threading.Thread(target=lambda: uvicorn.run(app, host="0.0.0.0", port=10001)).start()
    scan()
    scheduler.start()

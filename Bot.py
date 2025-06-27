# V3 Signal Bot 📱 – Render Ready (Mobile Horizontal View)
import pandas as pd, numpy as np, matplotlib.pyplot as plt, requests, datetime, pytz, hashlib, io, threading
import telegram, uvicorn
from fastapi import FastAPI
from apscheduler.schedulers.blocking import BlockingScheduler
from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator

# ========================== CONFIG ==========================
API_KEY = "c78b6090d46845e0b311cc92ebb0b13d"
BOT_TOKEN = "7613620588:AAEui2boeLqJ7ukxmjiiUNF8njOgEUoWRM8"
CHAT_ID = "7765972595"
TIMEZONE = pytz.timezone("Asia/Kolkata")
INTERVAL_MINUTES = 30
PORT = 10001
SYMBOLS = ["BTC/USD", "XAU/USD", "EUR/USD", "USD/CAD", "GBP/USD", "USD/JPY", "AUD/USD", "NZD/USD"]
LAST_SIGNAL = {}

# Telegram Bot
bot = telegram.Bot(token=BOT_TOKEN)

# Web server (health check for Render/UptimeRobot)
app = FastAPI()
@app.get("/")
def home(): return {"status": "✅ V3 Signal Bot Online"}

# ========================== HELPERS ==========================
def fetch(symbol):
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=30min&outputsize=100&apikey={API_KEY}"
    r = requests.get(url).json()
    if "values" not in r: return None
    df = pd.DataFrame(r["values"])[::-1]
    df["datetime"] = pd.to_datetime(df["datetime"])
    df.set_index("datetime", inplace=True)
    return df.astype(float)

def apply_indicators(df):
    df["EMA20"] = EMAIndicator(df["close"], 20).ema_indicator()
    df["EMA50"] = EMAIndicator(df["close"], 50).ema_indicator()
    df["RSI"] = RSIIndicator(df["close"], 14).rsi()
    macd = MACD(df["close"])
    df["MACD"] = macd.macd()
    df["Signal"] = macd.macd_signal()
    return df

def detect_candle_pattern(df):
    last, prev = df.iloc[-1], df.iloc[-2]
    if last["open"] < last["close"] and prev["open"] > prev["close"] and last["open"] < prev["close"]:
        return "Bullish Engulfing"
    if last["open"] > last["close"] and prev["open"] < prev["close"] and last["open"] > prev["close"]:
        return "Bearish Engulfing"
    if abs(last["close"] - last["open"]) / (last["high"] - last["low"]) < 0.2:
        return "Doji"
    return "Neutral"

def detect_chart_pattern(df):
    closes = df["close"].tail(20)
    highs = closes.rolling(3).max()
    lows = closes.rolling(3).min()
    if all(x < y for x, y in zip(lows, lows[1:])): return "Rising Wedge"
    if all(x > y for x, y in zip(highs, highs[1:])): return "Falling Wedge"
    return "No Chart Pattern"

def is_confirmed(df):
    last, prev = df.iloc[-1], df.iloc[-2]
    buy = prev["EMA20"] < prev["EMA50"] and last["EMA20"] > last["EMA50"] and last["RSI"] > 50 and last["MACD"] > last["Signal"]
    sell = prev["EMA20"] > prev["EMA50"] and last["EMA20"] < last["EMA50"] and last["RSI"] < 50 and last["MACD"] < last["Signal"]
    return "BUY" if buy else "SELL" if sell else None

def calculate_tp_sl(df, direction):
    close = df["close"].iloc[-1]
    high = df["high"].iloc[-20:].max()
    low = df["low"].iloc[-20:].min()
    range_ = high - low
    tp = close + range_ * 0.3 if direction == "BUY" else close - range_ * 0.3
    sl = close - range_ * 0.08 if direction == "BUY" else close + range_ * 0.08
    tp_pct = abs(tp - close) / close * 100
    sl_pct = abs(sl - close) / close * 100
    if tp_pct > 15 and sl_pct < 10 and round(tp, 2) != round(sl, 2): return sl, tp
    return None, None

def draw_chart(df, symbol, sig, candle, chart, sl, tp):
    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(7.2, 2.4))  # 📱 Horizontal layout
    df["close"].tail(30).plot(ax=ax, color='cyan', lw=1, label="Close")
    df["EMA20"].tail(30).plot(ax=ax, color='lime', lw=0.8, label="EMA20")
    df["EMA50"].tail(30).plot(ax=ax, color='red', lw=0.8, label="EMA50")
    ax.axhline(tp, color="green", linestyle="--", lw=0.6)
    ax.axhline(sl, color="orange", linestyle="--", lw=0.6)
    ax.set_title(f"{symbol} • {sig} • {candle} • {chart}", fontsize=9)
    ax.legend(fontsize=6, ncol=4, loc="upper left")
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=110)
    buf.seek(0)
    plt.close()
    return buf

def send_alert(symbol, sig, candle, chart, sl, tp, chart_img):
    now = datetime.datetime.now(TIMEZONE).strftime('%d %b %H:%M')
    text = f"""📊 {symbol}
🔁 Signal: {sig}
🧠 Candle: {candle}
📐 Chart: {chart}
📍 SL: {sl:.2f}
🎯 TP: {tp:.2f}
🕐 {now}
🧪 EMA + RSI + MACD Confirmed"""
    bot.send_photo(chat_id=CHAT_ID, photo=chart_img, caption=text)

def hash_signal(symbol, sig, sl, tp):
    return hashlib.md5(f"{symbol}_{sig}_{round(sl,2)}_{round(tp,2)}".encode()).hexdigest()

def market_open(symbol):
    now = datetime.datetime.now(TIMEZONE)
    return symbol == "BTC/USD" or (now.weekday() < 5 and 5 <= now.hour < 23)

# ========================== SCANNER ==========================
def scan():
    print(f"\n⏰ Scan @ {datetime.datetime.now(TIMEZONE).strftime('%H:%M')}")
    for symbol in SYMBOLS:
        if not market_open(symbol): continue
        df = fetch(symbol)
        if df is None: continue
        df = apply_indicators(df)
        sig = is_confirmed(df)
        if not sig: continue
        sl, tp = calculate_tp_sl(df, sig)
        if not sl or not tp: continue
        key = hash_signal(symbol, sig, sl, tp)
        if LAST_SIGNAL.get(symbol) == key: continue
        LAST_SIGNAL[symbol] = key
        candle = detect_candle_pattern(df)
        chart = detect_chart_pattern(df)
        img = draw_chart(df, symbol, sig, candle, chart, sl, tp)
        send_alert(symbol, sig, candle, chart, sl, tp, img)

# ========================== STARTUP ==========================
if __name__ == "__main__":
    scheduler = BlockingScheduler(timezone=TIMEZONE)
    scheduler.add_job(scan, "interval", minutes=INTERVAL_MINUTES)
    threading.Thread(target=lambda: uvicorn.run(app, host="0.0.0.0", port=PORT)).start()
    scan()
    scheduler.start()

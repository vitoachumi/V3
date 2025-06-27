# main.py

import requests, pandas as pd, numpy as np, matplotlib.pyplot as plt
import datetime, pytz, threading, uvicorn, os
from fastapi import FastAPI
from apscheduler.schedulers.background import BackgroundScheduler
import telegram

# === CONFIG ===
API_KEY = "d7aaa4b124994fee9cbc56bb956c3b98"
BOT_TOKEN = "7613620588:AAEui2boeLqJ7ukxmjiiUNF8njOgEUoWRM8"
CHAT_ID = "7765972595"
TIMEZONE = pytz.timezone("Asia/Kolkata")
INTERVAL = 30  # minutes

SYMBOLS = [
    "BTC/USD", "XAU/USD", "AUD/USD", "CAD/USD",
    "EUR/USD", "GBP/USD", "NZD/USD", "JPY/USD"
]

bot = telegram.Bot(token=BOT_TOKEN)
app = FastAPI()

@app.get("/")
def status():
    return {"status": "📡 Mr Bot V3 is running."}

def fetch(symbol):
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=30min&outputsize=100&apikey={API_KEY}"
    r = requests.get(url).json()
    if "values" not in r: return None
    df = pd.DataFrame(r['values'])[::-1]
    df['datetime'] = pd.to_datetime(df['datetime'])
    df.set_index('datetime', inplace=True)
    return df.astype(float)

def rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    gain = up.rolling(period).mean()
    loss = down.rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def apply_indicators(df):
    df["EMA20"] = df["close"].ewm(span=20).mean()
    df["EMA50"] = df["close"].ewm(span=50).mean()
    df["RSI"] = rsi(df["close"])
    df["MACD"] = df["close"].ewm(12).mean() - df["close"].ewm(26).mean()
    df["SIGNAL"] = df["MACD"].ewm(9).mean()
    return df

def confirm_price_action(df):
    candles = df.iloc[-3:]
    bullish = all(c["close"] > c["open"] for _, c in candles.iterrows())
    bearish = all(c["close"] < c["open"] for _, c in candles.iterrows())
    return "BUY" if bullish else "SELL" if bearish else None

def detect_signal(df):
    signal = confirm_price_action(df)
    if not signal: return None
    last = df.iloc[-1]
    ema = last["EMA20"] > last["EMA50"] if signal == "BUY" else last["EMA20"] < last["EMA50"]
    rsi = last["RSI"] > 50 if signal == "BUY" else last["RSI"] < 50
    macd = last["MACD"] > last["SIGNAL"] if signal == "BUY" else last["MACD"] < last["SIGNAL"]
    return signal if all([ema, rsi, macd]) else None

def calculate_tp_sl(df, signal):
    close = df["close"].iloc[-1]
    high = df["high"].iloc[-20:].max()
    low = df["low"].iloc[-20:].min()
    rng = high - low
    if rng == 0: return None, None

    if signal == "BUY":
        tp = close + rng * 0.25
        sl = close - rng * 0.08
    else:
        tp = close - rng * 0.25
        sl = close + rng * 0.08

    tp_pct = abs(tp - close) / rng * 100
    sl_pct = abs(sl - close) / rng * 100

    return (tp, sl) if tp_pct >= 20 and sl_pct <= 10 else (None, None)

def chart(df, symbol, sig):
    df[-30:]["close"].plot(figsize=(5,2.5), title=f"{symbol} • {sig}", color='blue')
    plt.tight_layout()
    path = f"/tmp/{symbol.replace('/', '')}.png"
    plt.savefig(path)
    plt.close()
    return path

def alert(symbol, signal, entry, tp, sl, img):
    now = datetime.datetime.now(TIMEZONE).strftime("%d %b • %I:%M%p")
    msg = (
        f"📡 {symbol} • *{signal}*\n"
        f"💰 Entry: `{entry:.2f}`\n"
        f"🎯 TP: `{tp:.2f}`\n"
        f"🛡️ SL: `{sl:.2f}`\n"
        f"⏱️ {now}\n"
        f"✅ Triple Indicator + Multi Candle Confirmed"
    )
    with open(img, 'rb') as photo:
        bot.send_photo(chat_id=CHAT_ID, photo=photo, caption=msg, parse_mode="Markdown")

def scan():
    print(f"\n📲 Scan started {datetime.datetime.now(TIMEZONE).strftime('%H:%M:%S')} IST")
    for sym in SYMBOLS:
        print(f"🔎 {sym}...", end=" ")
        df = fetch(sym)
        if df is None:
            print("❌ Data error.")
            continue
        df = apply_indicators(df)
        sig = detect_signal(df)
        if sig:
            entry = df["close"].iloc[-1]
            tp, sl = calculate_tp_sl(df, sig)
            if tp and sl:
                print(f"{sig} ✅")
                img = chart(df, sym, sig)
                alert(sym, sig, entry, tp, sl, img)
            else:
                print("❌ TP/SL rejected.")
        else:
            print("⏸️ No signal.")

# Scheduler + Web
if __name__ == "__main__":
    scheduler = BackgroundScheduler(timezone=TIMEZONE)
    scheduler.add_job(scan, 'interval', minutes=INTERVAL)
    threading.Thread(target=lambda: uvicorn.run(app, host="0.0.0.0", port=10000)).start()
    scan()
    scheduler.start()

import requests, pandas as pd, numpy as np, matplotlib.pyplot as plt
import datetime, pytz, threading, uvicorn, telegram, os, hashlib
from fastapi import FastAPI
from apscheduler.schedulers.background import BackgroundScheduler

# === CONFIG ===
API_KEY = "c78b6090d46845e0b311cc92ebb0b13d"
BOT_TOKEN = "7613620588:AAEui2boeLqJ7ukxmjiiUNF8njOgEUoWRM8"
CHAT_ID = "7765972595"
TIMEZONE = pytz.timezone("Asia/Kolkata")
INTERVAL = 30  # in minutes
MOBILE_FRAME_WIDTH = 400
SYMBOLS = ["BTC/USD", "XAU/USD", "USD/JPY", "USD/CAD", "AUD/USD", "NZD/USD", "GBP/USD", "EUR/USD"]
LAST_SENT = {}

bot = telegram.Bot(token=BOT_TOKEN)
app = FastAPI()

@app.get("/")  # For UptimeRobot ping
def root():
    return {"status": "✅ Mr Bot is alive"}

def fetch(symbol):
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=30min&outputsize=100&apikey={API_KEY}"
    r = requests.get(url).json()
    if "values" not in r:
        print(f"[{symbol}] ❌ API error: {r.get('message', '')}")
        return None
    df = pd.DataFrame(r["values"])[::-1]
    df["datetime"] = pd.to_datetime(df["datetime"])
    df.set_index("datetime", inplace=True)
    return df.astype(float)

def rsi(series, period=14):
    delta = series.diff()
    up, down = delta.clip(lower=0), -delta.clip(upper=0)
    gain = up.rolling(period).mean()
    loss = down.rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def supply_demand_zones(df):
    support = df['low'].rolling(window=3, center=True).min()
    resistance = df['high'].rolling(window=3, center=True).max()
    return support, resistance

def candlestick_pattern(df):
    last = df.iloc[-1]
    body = abs(last['close'] - last['open'])
    wick = last['high'] - last['low']
    if body < wick * 0.3:
        return "Doji"
    elif last['close'] > last['open']:
        return "Bullish"
    elif last['close'] < last['open']:
        return "Bearish"
    return None

def indicators(df):
    df['EMA20'] = df['close'].ewm(span=20).mean()
    df['EMA50'] = df['close'].ewm(span=50).mean()
    df['RSI'] = rsi(df['close'])
    df['MACD'] = df['close'].ewm(12).mean() - df['close'].ewm(26).mean()
    df['Signal'] = df['MACD'].ewm(9).mean()
    df['Pattern'] = candlestick_pattern(df)
    df['Support'], df['Resistance'] = supply_demand_zones(df)
    return df

def calculate_tp_sl(df, direction):
    close = df['close'].iloc[-1]
    high = df['high'].iloc[-20:].max()
    low = df['low'].iloc[-20:].min()
    range_ = high - low

    if direction == "BUY":
        tp = close + range_ * 0.3
        sl = close - range_ * 0.08
    else:
        tp = close - range_ * 0.3
        sl = close + range_ * 0.08

    tp_pct = abs(tp - close) / close * 100
    sl_pct = abs(sl - close) / close * 100
    if tp_pct > 15 and sl_pct < 10:
        return sl, tp
    return None, None

def signal(df):
    last, prev = df.iloc[-1], df.iloc[-2]
    buy = prev['EMA20'] < prev['EMA50'] and last['EMA20'] > last['EMA50'] and last['RSI'] > 50 and last['MACD'] > last['Signal']
    sell = prev['EMA20'] > prev['EMA50'] and last['EMA20'] < last['EMA50'] and last['RSI'] < 50 and last['MACD'] < last['Signal']
    return "BUY" if buy else "SELL" if sell else None

def hash_signal(symbol, sig, tp, sl):
    key = f"{symbol}_{sig}_{round(tp,2)}_{round(sl,2)}"
    return hashlib.md5(key.encode()).hexdigest()

def chart(df, sig, sym):
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(4, 3))
    df.tail(30)['close'].plot(ax=ax, label="Close", c='cyan')
    df.tail(30)['EMA20'].plot(ax=ax, label="EMA20", c='lime')
    df.tail(30)['EMA50'].plot(ax=ax, label="EMA50", c='red')
    ax.set_title(f"{sym} • {sig}", fontsize=10)
    ax.legend(loc='upper left', fontsize=6)
    path = f"/tmp/{sym.replace('/', '')}.png"
    plt.savefig(path, bbox_inches='tight')
    plt.close()
    return path

def alert(sym, sig, path, sl, tp, pattern):
    now = datetime.datetime.now(TIMEZONE).strftime('%d %b %H:%M')
    txt = f"""📊 *{sym}*
🔁 *Signal:* {sig}
🧠 *Pattern:* {pattern}
📍 *SL:* {sl:.2f}
🎯 *TP:* {tp:.2f}
🕐 {now}
📲 Confirmed by EMA+RSI+MACD"""
    with open(path, 'rb') as img:
        bot.send_photo(chat_id=CHAT_ID, photo=img, caption=txt, parse_mode='Markdown')

def is_market_open():
    now = datetime.datetime.now(TIMEZONE)
    return now.weekday() < 5 and 5 <= now.hour < 22  # Mon–Fri, 5AM to 10PM IST

def scan():
    now = datetime.datetime.now(TIMEZONE).strftime('%H:%M')
    print(f"\n⏰ {now} - Scanning...")
    for sym in SYMBOLS:
        if sym != "BTC/USD" and not is_market_open():
            print(f"⏳ {sym} skipped (market closed)")
            continue

        print(f"🔍 {sym}...", end=" ")
        df = fetch(sym)
        if df is None:
            continue

        df = indicators(df)
        sig = signal(df)
        if not sig:
            print("No signal.")
            continue

        sl, tp = calculate_tp_sl(df, sig)
        if not sl or not tp:
            print("❌ TP/SL rejected")
            continue

        sig_hash = hash_signal(sym, sig, tp, sl)
        if LAST_SENT.get(sym) == sig_hash:
            print("⛔ Duplicate")
            continue

        LAST_SENT[sym] = sig_hash
        path = chart(df, sig, sym)
        pattern = df['Pattern'].iloc[-1]
        alert(sym, sig, path, sl, tp, pattern)
        print(f"{sig} ✅")

# Start scheduler + FastAPI server
if __name__ == "__main__":
    scheduler = BackgroundScheduler(timezone=TIMEZONE)
    scheduler.add_job(scan, 'interval', minutes=INTERVAL)
    threading.Thread(target=lambda: uvicorn.run(app, host="0.0.0.0", port=10000)).start()
    scan()
    scheduler.start()

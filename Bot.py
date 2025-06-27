import requests, pandas as pd, numpy as np, matplotlib.pyplot as plt
import datetime, pytz, threading, uvicorn, telegram
from fastapi import FastAPI
from apscheduler.schedulers.blocking import BlockingScheduler

# === CONFIG ===
API_KEY = "c78b6090d46845e0b311cc92ebb0b13d"
BOT_TOKEN = "7613620588:AAEui2boeLqJ7ukxmjiiUNF8njOgEUoWRM8"
CHAT_ID = "7765972595"
TIMEZONE = pytz.timezone("Asia/Kolkata")
INTERVAL = 30  # minutes

SYMBOLS = ["BTC/USD", "XAU/USD", "USD/JPY", "USD/CAD",
           "AUD/USD", "NZD/USD", "GBP/USD", "EUR/USD"]

bot = telegram.Bot(token=BOT_TOKEN)
app = FastAPI()

@app.api_route("/", methods=["GET", "HEAD"])  # ✅ Fix for UptimeRobot
def root():
    return {"status": "✅ Mr Bot is online"}

def fetch(symbol):
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=30min&outputsize=100&apikey={API_KEY}"
    r = requests.get(url).json()
    if "values" not in r:
        print(f"[{symbol}] ❌ Fetch failed: {r.get('message', '')}")
        return None
    df = pd.DataFrame(r['values'])[::-1]
    df['datetime'] = pd.to_datetime(df['datetime'])
    df.set_index('datetime', inplace=True)
    return df.astype(float)

def rsi(series, period=14):
    delta = series.diff()
    up, down = delta.clip(lower=0), -delta.clip(upper=0)
    gain = up.rolling(period).mean()
    loss = down.rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def indicators(df):
    df['EMA20'] = df['close'].ewm(span=20).mean()
    df['EMA50'] = df['close'].ewm(span=50).mean()
    df['RSI'] = rsi(df['close'])
    df['MACD'] = df['close'].ewm(12).mean() - df['close'].ewm(26).mean()
    df['Signal'] = df['MACD'].ewm(9).mean()
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

    tp_dist = abs(tp - close)
    sl_dist = abs(sl - close)

    if tp_dist >= range_ * 0.2 and sl_dist <= range_ * 0.1:
        return sl, tp
    return None, None

def signal(df):
    last, prev = df.iloc[-1], df.iloc[-2]
    buy = prev['EMA20'] < prev['EMA50'] and last['EMA20'] > last['EMA50'] \
        and last['RSI'] > 50 and last['MACD'] > last['Signal']
    sell = prev['EMA20'] > prev['EMA50'] and last['EMA20'] < last['EMA50'] \
        and last['RSI'] < 50 and last['MACD'] < last['Signal']
    return "BUY" if buy else "SELL" if sell else None

def chart(df, sig, sym):
    plt.style.use('seaborn-dark')
    fig, ax = plt.subplots(figsize=(6, 3))
    df.tail(30)['close'].plot(ax=ax, label="Close", c='blue')
    df.tail(30)['EMA20'].plot(ax=ax, label="EMA20", c='green')
    df.tail(30)['EMA50'].plot(ax=ax, label="EMA50", c='red')
    ax.set_title(f"{sym} • {sig}")
    ax.legend()
    path = f"/tmp/{sym.replace('/', '')}.png"
    plt.savefig(path, bbox_inches='tight')
    plt.close()
    return path

def alert(sym, sig, path, sl, tp):
    now = datetime.datetime.now(TIMEZONE).strftime('%d %b %H:%M')
    txt = f"""📊 {sym}
🔁 Signal: {sig}
📍 SL: {sl:.2f}
🎯 TP: {tp:.2f}
🕐 {now}
🧠 Confirmed by EMA + RSI + MACD"""
    with open(path, 'rb') as img:
        bot.send_photo(chat_id=CHAT_ID, photo=img, caption=txt)

def scan():
    now = datetime.datetime.now(TIMEZONE).strftime('%H:%M')
    print(f"\n⏰ {now} - Scanning...")
    for s in SYMBOLS:
        print(f"🔍 {s}...", end=" ")
        df = fetch(s)
        if df is None:
            continue
        df = indicators(df)
        sig = signal(df)
        if sig:
            sl, tp = calculate_tp_sl(df, sig)
            if sl and tp:
                print(f"{sig} ✅")
                path = chart(df, sig, s)
                alert(s, sig, path, sl, tp)
            else:
                print("❌ TP/SL filter failed")
        else:
            print("No signal.")

# Run web + scanner
if __name__ == "__main__":
    scheduler = BlockingScheduler(timezone=TIMEZONE)
    scheduler.add_job(scan, 'interval', minutes=INTERVAL)
    threading.Thread(target=lambda: uvicorn.run(app, host="0.0.0.0", port=10000)).start()
    scan()
    scheduler.start()

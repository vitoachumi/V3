import requests, pandas as pd, numpy as np, matplotlib.pyplot as plt
import datetime, pytz, threading, uvicorn, telegram
from fastapi import FastAPI
from apscheduler.schedulers.blocking import BlockingScheduler

# === CONFIG ===
API_KEY = "fa799057279a4b3eb061e80b4b6504a6"
BOT_TOKEN = "7613620588:AAEui2boeLqJ7ukxmjiiUNF8njOgEUoWRM8"
CHAT_ID = "<7765972595>"  # <-- Replace with your Telegram user or channel ID
SYMBOLS = ["BTC/USD", "EUR/USD", "USD/JPY", "GBP/USD", "XAU/USD"]
TIMEZONE = pytz.timezone("Asia/Kolkata")
INTERVAL = 60  # Every 60 mins
bot = telegram.Bot(token=BOT_TOKEN)
app = FastAPI()

@app.get("/")
def root(): return {"status": "Mr Bot is alive"}

def fetch(symbol):
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=1h&apikey={API_KEY}&outputsize=100"
    r = requests.get(url).json()
    if "values" not in r: print(f"[{symbol}] ❌ Fetch failed."); return None
    df = pd.DataFrame(r['values'])[::-1]
    df['datetime'] = pd.to_datetime(df['datetime']); df.set_index('datetime', inplace=True)
    return df.astype(float)

def rsi(s, p=14):
    delta = s.diff(); up, dn = np.where(delta > 0, delta, 0), np.where(delta < 0, -delta, 0)
    gain, loss = pd.Series(up).rolling(p).mean(), pd.Series(dn).rolling(p).mean()
    rs = gain / loss; return 100 - (100 / (1 + rs))

def indicators(df):
    df['EMA20'] = df['close'].ewm(20).mean()
    df['EMA50'] = df['close'].ewm(50).mean()
    df['RSI'] = rsi(df['close'])
    df['MACD'] = df['close'].ewm(12).mean() - df['close'].ewm(26).mean()
    df['Signal'] = df['MACD'].ewm(9).mean()
    return df

def signal(df):
    last, prev = df.iloc[-1], df.iloc[-2]
    buy = prev['EMA20'] < prev['EMA50'] and last['EMA20'] > last['EMA50'] and last['RSI'] > 50 and last['MACD'] > last['Signal']
    sell = prev['EMA20'] > prev['EMA50'] and last['EMA20'] < last['EMA50'] and last['RSI'] < 50 and last['MACD'] < last['Signal']
    return "BUY" if buy else "SELL" if sell else None

def chart(df, sig, sym):
    plt.style.use('seaborn-dark'); fig, ax = plt.subplots(figsize=(6, 3))
    df.tail(30)['close'].plot(ax=ax, label="Close", c='blue')
    df.tail(30)['EMA20'].plot(ax=ax, label="EMA20", c='green')
    df.tail(30)['EMA50'].plot(ax=ax, label="EMA50", c='red')
    ax.set_title(f"{sym} • {sig}"); ax.legend()
    path = f"/tmp/{sym.replace('/', '')}.png"
    plt.savefig(path, bbox_inches='tight'); plt.close(); return path

def alert(sym, sig, path):
    now = datetime.datetime.now(TIMEZONE).strftime('%d %b %H:%M')
    txt = f"📊 {sym}\nSignal: {sig}\n🕐 {now}"
    with open(path, 'rb') as img: bot.send_photo(chat_id=CHAT_ID, photo=img, caption=txt)

def scan():
    now = datetime.datetime.now(TIMEZONE).strftime('%H:%M'); print(f"\n⏰ {now} - Scanning...")
    for s in SYMBOLS:
        print(f"🔍 {s}...", end=" ")
        df = fetch(s); 
        if df is None: continue
        df = indicators(df); sig = signal(df)
        if sig: print(f"{sig} ✅"); p = chart(df, sig, s); alert(s, sig, p)
        else: print("No signal.")

if __name__ == "__main__":
    scheduler = BlockingScheduler(timezone=TIMEZONE)
    scheduler.add_job(scan, 'interval', minutes=INTERVAL)
    threading.Thread(target=lambda: uvicorn.run(app, host="0.0.0.0", port=10000)).start()
    scan(); scheduler.start()

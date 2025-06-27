import requests
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os
import datetime
import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
import telegram

# === CONFIG ===
API_KEY = "fa799057279a4b3eb061e80b4b6504a6"
BOT_TOKEN = "7613620588:AAEui2boeLqJ7ukxmjiiUNF8njOgEUoWRM8"
CHAT_ID = "<YOUR_CHAT_ID>"  # Replace this
SYMBOLS = ["BTC/USD", "EUR/USD", "USD/JPY", "GBP/USD", "XAU/USD"]
TIMEFRAME = "1h"
INTERVAL = 60  # minutes
TIMEZONE = pytz.timezone("Asia/Kolkata")
bot = telegram.Bot(token=BOT_TOKEN)

# === Fetch Data ===
def fetch_data(symbol):
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={TIMEFRAME}&apikey={API_KEY}&outputsize=100"
    r = requests.get(url)
    data = r.json()
    if "values" not in data:
        print(f"[{symbol}] ❌ Data fetch failed.")
        return None
    df = pd.DataFrame(data['values'])
    df = df.iloc[::-1]
    df['datetime'] = pd.to_datetime(df['datetime'])
    df.set_index('datetime', inplace=True)
    df = df.astype(float)
    return df

# === Indicators ===
def add_indicators(df):
    df['EMA20'] = df['close'].ewm(span=20).mean()
    df['EMA50'] = df['close'].ewm(span=50).mean()
    df['RSI'] = compute_rsi(df['close'], 14)
    df['MACD'] = df['close'].ewm(12).mean() - df['close'].ewm(26).mean()
    df['Signal'] = df['MACD'].ewm(9).mean()
    return df

def compute_rsi(series, period=14):
    delta = series.diff()
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = pd.Series(gain).rolling(window=period).mean()
    avg_loss = pd.Series(loss).rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return pd.Series(rsi, index=series.index)

# === Signal Strategy ===
def detect_signal(df):
    last = df.iloc[-1]
    prev = df.iloc[-2]
    buy = (
        prev['EMA20'] < prev['EMA50'] and last['EMA20'] > last['EMA50'] and
        last['RSI'] > 50 and
        last['MACD'] > last['Signal']
    )
    sell = (
        prev['EMA20'] > prev['EMA50'] and last['EMA20'] < last['EMA50'] and
        last['RSI'] < 50 and
        last['MACD'] < last['Signal']
    )
    if buy:
        return "BUY"
    elif sell:
        return "SELL"
    return None

# === Plot Chart ===
def plot_chart(df, signal, symbol):
    plt.style.use('seaborn-dark')
    fig, ax = plt.subplots(figsize=(8, 4))
    df.tail(30)['close'].plot(ax=ax, label="Close", color='blue')
    df.tail(30)['EMA20'].plot(ax=ax, label="EMA20", color='green')
    df.tail(30)['EMA50'].plot(ax=ax, label="EMA50", color='red')
    ax.set_title(f"{symbol} - Signal: {signal}")
    ax.legend()
    chart_path = f"/tmp/{symbol.replace('/', '')}_chart.png"
    plt.savefig(chart_path, bbox_inches='tight')
    plt.close()
    return chart_path

# === Send Alert ===
def send_telegram_alert(symbol, signal, chart_path):
    msg = f"📊 {symbol}\nSignal: {signal}\nTime: {datetime.datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M')}"
    with open(chart_path, 'rb') as img:
        bot.send_photo(chat_id=CHAT_ID, photo=img, caption=msg)

# === Main Scan ===
def scan_all():
    now = datetime.datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M')
    print(f"\n=== 🔁 Scanning @ {now} ===")
    for symbol in SYMBOLS:
        print(f"📥 {symbol}...", end=" ")
        df = fetch_data(symbol)
        if df is None: continue
        df = add_indicators(df)
        signal = detect_signal(df)
        if signal:
            print(f"✅ {signal}")
            chart = plot_chart(df, signal, symbol)
            send_telegram_alert(symbol, signal, chart)
        else:
            print("No clear signal.")

# === Schedule Job ===
if __name__ == "__main__":
    scheduler = BlockingScheduler(timezone=TIMEZONE)
    scheduler.add_job(scan_all, 'interval', minutes=INTERVAL)
    print("🚀 Bot running every 15 minutes...\n")
    scan_all()  # Run once at start
    scheduler.start()

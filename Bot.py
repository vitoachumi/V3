import pandas as pd
import numpy as np
import requests
import datetime as dt
import pytz
import asyncio
import matplotlib.pyplot as plt
import mplfinance as mpf
from ta import trend, momentum
from telegram import Bot
from apscheduler.schedulers.blocking import BlockingScheduler

# Credentials
TELEGRAM_BOT_TOKEN = "7613620588:AAEui2boeLqJ7ukxmjiiUNF8njOgEUoWRM8"
TELEGRAM_CHAT_ID = "7765972595"
TWELVE_DATA_API_KEY = "d84bb3f43e4740e89e1368a29861d31d"

symbols = ["BTC/USD", "XAU/USD", "AUD/USD", "CAD/USD", "EUR/USD", "GBP/USD", "NZD/USD", "JPY/USD"]

def fetch_data(symbol):
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=30min&outputsize=100&apikey={TWELVE_DATA_API_KEY}"
    r = requests.get(url).json()
    if "values" not in r:
        raise Exception(f"{symbol} fetch failed: {r.get('message')}")
    df = pd.DataFrame(r["values"]).rename(columns={"datetime": "time"}).sort_values("time")
    df["time"] = pd.to_datetime(df["time"])
    df.set_index("time", inplace=True)
    df = df.astype(float)
    return df

def apply_indicators(df):
    df["EMA20"] = trend.ema_indicator(df["close"], window=20)
    df["EMA50"] = trend.ema_indicator(df["close"], window=50)
    df["RSI"] = momentum.rsi(df["close"], window=14)
    df["MACD_Hist"] = trend.macd_diff(df["close"])
    return df

def detect_zones(df):
    return df["high"].rolling(20).max().iloc[-1], df["low"].rolling(20).min().iloc[-1]

def confirm_price_action(df):
    last3 = df.iloc[-3:]
    bullish = all(row["close"] > row["open"] for _, row in last3.iterrows())
    bearish = all(row["close"] < row["open"] for _, row in last3.iterrows())
    return "BUY" if bullish else "SELL" if bearish else None

def detect_signal(df):
    last = df.iloc[-1]
    signal = confirm_price_action(df)
    if not signal:
        return None, 0
    ema = last["EMA20"] > last["EMA50"] if signal == "BUY" else last["EMA20"] < last["EMA50"]
    rsi = last["RSI"] > 50 if signal == "BUY" else last["RSI"] < 50
    macd = last["MACD_Hist"] > 0 if signal == "BUY" else last["MACD_Hist"] < 0
    demand, supply = detect_zones(df)
    breakout = last["close"] > supply * 1.001 if signal == "BUY" else last["close"] < demand * 0.999
    score = sum([ema, rsi, macd, breakout])
    return (signal, score) if score == 4 else (None, 0)

def calculate_tp_sl(df, signal):
    close = df["close"].iloc[-1]
    high = df["high"].iloc[-20:].max()
    low = df["low"].iloc[-20:].min()
    rng = high - low
    if signal == "BUY":
        tp, sl = close + rng * 0.25, close - rng * 0.08
    elif signal == "SELL":
        tp, sl = close - rng * 0.25, close + rng * 0.08
    else:
        return None, None
    tp_dist = abs(tp - close)
    sl_dist = abs(sl - close)
    return (sl, tp) if tp_dist >= rng * 0.2 and sl_dist <= rng * 0.1 else (None, None)

def plot_chart(df, symbol, signal, entry, sl, tp):
    dfp = df[-50:]
    apds = [
        mpf.make_addplot(dfp["EMA20"], color='blue'),
        mpf.make_addplot(dfp["EMA50"], color='red'),
        mpf.make_addplot(dfp["RSI"], panel=1, color='purple'),
        mpf.make_addplot(dfp["MACD_Hist"], panel=2, type='bar', color='green')
    ]
    fig, _ = mpf.plot(
        dfp, type='candle', volume=False, addplot=apds,
        hlines=dict(hlines=[entry, sl, tp], colors=['blue', 'red', 'green'], linestyle='--'),
        style='yahoo', title=f"{symbol} - {signal}", returnfig=True, figsize=(8,6))
    filename = f"{symbol.replace('/', '')}_{signal}.png"
    fig.savefig(filename)
    plt.close(fig)
    return filename

async def send_alert(symbol, signal, entry, sl, tp, file):
    msg = f"""📡 {symbol} — {signal}
💰 Entry: {entry:.2f}
🎯 TP: {tp:.2f}
🛡️ SL: {sl:.2f}

✅ Triple Indicator + Price Action"""
    bot = Bot(TELEGRAM_BOT_TOKEN)
    with open(file, 'rb') as img:
        await bot.send_photo(chat_id=TELEGRAM_CHAT_ID, photo=img, caption=msg)

def send_alert_sync(*args):
    loop = asyncio.get_event_loop()
    if loop.is_running():
        loop.create_task(send_alert(*args))
    else:
        loop.run_until_complete(send_alert(*args))

last_signal = {}

def scan_symbol(symbol):
    try:
        df = fetch_data(symbol)
        df = apply_indicators(df)
        signal, score = detect_signal(df)
        if signal and last_signal.get(symbol) != signal:
            entry = df["close"].iloc[-1]
            sl, tp = calculate_tp_sl(df, signal)
            if sl and tp:
                chart = plot_chart(df, symbol, signal, entry, sl, tp)
                send_alert_sync(symbol, signal, entry, sl, tp, chart)
                last_signal[symbol] = signal
                print(f"✅ {symbol} {signal} sent")
            else:
                print(f"🚫 {symbol}: TP/SL invalid")
        else:
            print(f"⏸️ {symbol}: No signal")
    except Exception as e:
        print(f"❌ {symbol} error: {e}")

def scan_all():
    now = dt.datetime.now(pytz.timezone("Asia/Kolkata"))
    print(f"
🔁 Scan: {now.strftime('%Y-%m-%d %H:%M:%S')} IST")
    for sym in symbols:
        scan_symbol(sym)

scheduler = BlockingScheduler(timezone="Asia/Kolkata")
scheduler.add_job(scan_all, "interval", minutes=30)

if __name__ == "__main__":
    print("🚀 EA V3 Bot Running on Render")
    scan_all()
    scheduler.start()

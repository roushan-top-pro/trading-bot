import os
import time
import requests
import pandas as pd
import yfinance as yf

# ================= Configuration =================
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"  # Apna bot token yahan dalein
TELEGRAM_CHAT_ID = "YOUR_TELEGRAM_CHAT_ID"      # Apna chat ID yahan dalein

# Assets to Monitor
SYMBOLS = {
    "NIFTY 50": "^NSEI",
    "SENSEX": "^BSESN",
    "GOLD (MCX/Global)": "GC=F",
    "SILVER (MCX/Global)": "SI=F"
}

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error sending alert: {e}")

def calculate_levels(df):
    high = df['High'].iloc[-1]
    low = df['Low'].iloc[-1]
    close = df['Close'].iloc[-1]
    pivot = (high + low + close) / 3
    r1 = (2 * pivot) - low
    s1 = (2 * pivot) - high
    return pivot, r1, s1

def scan_market():
    for name, ticker in SYMBOLS.items():
        try:
            data = yf.download(ticker, period="5d", interval="15m", progress=False)
            if data.empty or len(data) < 20:
                continue

            close = float(data['Close'].iloc[-1])
            prev_close = float(data['Close'].iloc[-2])
            pivot, r1, s1 = calculate_levels(data)

            # Signal Logic
            signal = None
            if close > r1 and prev_close <= r1:
                signal = "BUY / CALL"
                sl = s1
                target = close + (2 * (close - sl))
            elif close < s1 and prev_close >= s1:
                signal = "SELL / PUT"
                sl = r1
                target = close - (2 * (sl - close))

            if signal:
                msg = (
                    f"🚨 <b>MARKET ALERT / बाज़ार अलर्ट</b> 🚨\n\n"
                    f"📊 <b>Asset:</b> {name}\n"
                    f"🎯 <b>Signal / संकेत:</b> {signal}\n"
                    f"💵 <b>Price / मूल्य:</b> {close:.2f}\n"
                    f"🛡️ <b>SL:</b> {sl:.2f}\n"
                    f"🎯 <b>Target (1:2 R:R):</b> {target:.2f}\n\n"
                    f"<i>Dual-Language Automated Market Scanner</i>"
                )
                send_telegram_alert(msg)
                print(f"Alert sent for {name}")

        except Exception as err:
            print(f"Error scanning {name}: {err}")

# Start Notification
send_telegram_alert("🚀 <b>Trading Bot Live on Cloud!</b>\n24/7 Scanner shuru ho chuka hai.")

# Continuous Loop (Every 5 minutes)
while True:
    print("Scanning markets...")
    scan_market()
    time.sleep(300)

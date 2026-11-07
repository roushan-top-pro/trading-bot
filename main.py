import os
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import yfinance as yf
import requests

# ================= Configuration =================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "9219234073:AAGAnfOwkw0p-KzIDl8kdzgs-s6BkGWgkJQ")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "6861153040")

USD_INR = 91.50

assets_config = {
    "^NSEI": {"name": "Nifty 50", "step": 50, "unit": "₹", "mult": 1.0},
    "^BSESN": {"name": "Sensex", "step": 100, "unit": "₹", "mult": 1.0},
    "GC=F": {"name": "MCX Gold (10g)", "step": 100, "unit": "₹", "mult": (USD_INR / 31.1035) * 10},
    "SI=F": {"name": "MCX Silver (1kg)", "step": 500, "unit": "₹", "mult": (USD_INR / 31.1035) * 1000},
    "CL=F": {"name": "MCX Crude Oil", "step": 50, "unit": "₹", "mult": USD_INR},
    "NG=F": {"name": "MCX Natural Gas", "step": 5, "unit": "₹", "mult": USD_INR}
}

sent_alerts = {}

POS_WORDS = ["surge", "gain", "rally", "rise", "soar", "high", "growth", "jump", "record", "profit"]
NEG_WORDS = ["fall", "drop", "slump", "loss", "crash", "down", "low", "fear", "plunge", "decline"]

def send_alert(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=10)
    except:
        pass

def check_rbi_repo_news():
    try:
        t = yf.Ticker("^NSEI")
        for item in t.news[:6]:
            txt = (item.get("title", "") + " " + item.get("content", {}).get("title", "")).lower()
            if "repo rate" in txt or "rbi policy" in txt or "interest rate" in txt or "rbi" in txt:
                if any(w in txt for w in ["cut", "slashes", "reduced", "lower", "eas"]):
                    return "🟢 BULLISH / तेजी (रेपो रेट घटा/कटौती, बाज़ार में तेजी आ सकती है)"
                elif any(w in txt for w in ["hike", "raised", "increase", "higher", "tighten"]):
                    return "🔴 BEARISH / मंदी (रेपो रेट बढ़ा, बाज़ार पर दबाव आ सकता है)"
                elif any(w in txt for w in ["pause", "unchanged", "status quo", "holds"]):
                    return "🟡 NEUTRAL / स्थिर (रेपो रेट स्थिर, बाज़ार में बड़ा बदलाव नहीं)"
    except:
        pass
    return "⚪ STABLE (RBI नीति सामान्य / कोई नया बदलाव नहीं)"

def get_asset_news(sym):
    try:
        ticker = yf.Ticker(sym)
        news_list = ticker.news
        if news_list and len(news_list) > 0:
            latest = news_list[0]
            title = latest.get("title", "")
            if not title and "content" in latest:
                title = latest["content"].get("title", "")
            title_lower = title.lower()
            pos_score = sum(1 for w in POS_WORDS if w in title_lower)
            neg_score = sum(1 for w in NEG_WORDS if w in title_lower)
            if pos_score > neg_score:
                sentiment = "🟢 POSITIVE (सकारात्मक / Bullish)"
            elif neg_score > pos_score:
                sentiment = "🔴 NEGATIVE (नकारात्मक / Bearish)"
            else:
                sentiment = "🟡 NEUTRAL (सामान्य / Flat)"
            clean_title = (title[:55] + "...") if len(title) > 55 else title
            return clean_title, sentiment
    except:
        pass
    return "No major headline / कोई बड़ी खबर नहीं", "⚪ NEUTRAL"

def get_vix_status():
    try:
        vix = yf.Ticker("^INDIAVIX").history(period="2d", interval="1d")
        if len(vix) >= 2:
            prev_vix = vix["Close"].iloc[-2]
            curr_vix = vix["Close"].iloc[-1]
            change = curr_vix - prev_vix
            pct = (change / prev_vix) * 100
            sentiment = "🔴 RISING (बाज़ार में डर / Volatility)" if change > 0 else "🟢 COOLING (स्थिर बाज़ार)"
            return curr_vix, pct, sentiment
    except:
        pass
    return None, None, "VIX N/A"

def get_nifty_pcr():
    try:
        t = yf.Ticker("^NSEI")
        exp = t.options
        if exp:
            chain = t.option_chain(exp[0])
            c_oi = chain.calls['openInterest'].sum()
            p_oi = chain.puts['openInterest'].sum()
            pcr = p_oi / c_oi if c_oi > 0 else 1.0
            bias = "🟢 BULLISH OI (तेजी / मजबूत सपोर्ट)" if pcr > 1.10 else ("🔴 BEARISH OI (मंदी / भारी रेजिस्टेंस)" if pcr < 0.90 else "🟡 NEUTRAL OI")
            return pcr, bias
    except:
        pass
    return None, "N/A"

def analyze_candles(df, mult):
    df.columns = [c.lower() for c in df.columns]
    close = df['close'] * mult
    high = df['high'] * mult
    low = df['low'] * mult

    ema9 = close.ewm(span=9, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()

    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    rsi = 100 - (100 / (1 + rs))

    res = high.rolling(20).max().shift(1)
    sup = low.rolling(20).min().shift(1)
    tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()

    curr_p = float(close.iloc[-1])
    e9_v = float(ema9.iloc[-1])
    e21_v = float(ema21.iloc[-1])
    e50_v = float(ema50.iloc[-1])
    rsi_v = float(rsi.iloc[-1])
    res_v = float(res.iloc[-1])
    sup_v = float(sup.iloc[-1])
    atr_v = float(atr.iloc[-1]) if not np.isnan(atr.iloc[-1]) else 10.0

    bull = (curr_p > e9_v > e21_v) + (curr_p > e50_v) + (rsi_v >= 53)
    bear = (curr_p < e9_v < e21_v) + (curr_p < e50_v) + (rsi_v <= 47)

    if bull >= 2 and (curr_p >= res_v or abs(curr_p - sup_v) <= atr_v * 0.85):
        bias = "BULL"
    elif bear >= 2 and (curr_p <= sup_v or abs(curr_p - res_v) <= atr_v * 0.85):
        bias = "BEAR"
    else:
        bias = "SIDEWAYS"

    return {
        "price": curr_p, "bias": bias, "rsi": rsi_v, "atr": atr_v,
        "res": res_v, "sup": sup_v, "low_prev": float(low.iloc[-2]), "high_prev": float(high.iloc[-2])
    }

def run_mtf_scanner():
    now_time = datetime.now()
    entry_str = now_time.strftime("%I:%M:%S %p")
    exit_window_str = (now_time + timedelta(minutes=75)).strftime("%I:%M %p")

    rbi_status = check_rbi_repo_news()
    curr_vix, vix_pct, vix_bias = get_vix_status()
    pcr, pcr_bias = get_nifty_pcr()

    try:
        tickers = list(assets_config.keys())
        data = yf.download(tickers=tickers, period="2d", interval="5m", group_by='ticker', progress=False)
    except:
        return

    for sym, cfg in assets_config.items():
        name, step, unit, mult = cfg['name'], cfg['step'], cfg['unit'], cfg['mult']
        try:
            df = data[sym].copy().dropna() if isinstance(data.columns, pd.MultiIndex) else data.copy().dropna()
            if len(df) < 25:
                continue

            df.columns = [c.lower() for c in df.columns]
            if not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index)

            news_head, news_sent = get_asset_news(sym)

            df_1h = df.resample('60min').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()
            df_15m = df.resample('15min').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()
            df_5m = df

            if len(df_1h) < 10 or len(df_15m) < 15 or len(df_5m) < 15:
                continue

            res_1h = analyze_candles(df_1h, mult)
            res_15m = analyze_candles(df_15m, mult)
            res_5m = analyze_candles(df_5m, mult)

            p_now = res_5m['price']
            atm_strike = int(round(p_now / step) * step)

            is_confirmed_bull = (res_5m['bias'] == "BULL") and (res_15m['bias'] == "BULL") and (res_1h['bias'] != "BEAR")
            is_confirmed_bear = (res_5m['bias'] == "BEAR") and (res_15m['bias'] == "BEAR") and (res_1h['bias'] != "BULL")

            signal_key = f"{sym}_MTF"

            if is_confirmed_bull:
                itm = atm_strike - step
                sl = min(res_5m['low_prev'], p_now - max(res_5m['atr'] * 0.85, step * 0.5))
                risk = p_now - sl
                target = p_now + (risk * 2.0)

                if sent_alerts.get(signal_key) != "BULL":
                    msg = (
                        f"-----------------------------------------\n"
                        f"🐂 🐂 <b>BULL RUN</b> 🐂 🐂\n"
                        f"(तेजी का संकेत / High Conviction Trade)\n"
                        f"=========================================\n"
                        f"🟢 <b>SIGNAL :</b> CALL (CE) BUY | कॉल खरीदें\n"
                        f"📌 <b>ASSET :</b> {name} (15M & 5M Synced)\n"
                        f"-----------------------------------------\n"
                        f"⏰ <b>ENTRY TIME :</b> {entry_str}\n"
                        f"   (प्रवेश समय : केवल केंडल क्लोज़ होने पर)\n"
                        f"⌛ <b>EXIT TIME :</b> Target/SL or max {exit_window_str}\n"
                        f"   (निकास समय : लक्ष्य/स्टॉपलॉस पर या अधिकतम {exit_window_str} तक)\n"
                        f"-----------------------------------------\n"
                        f"⚡ <b>Spot Price :</b> {p_now:.2f} {unit} (वर्तमान भाव)\n"
                        f"🎯 <b>ATM Strike :</b> {atm_strike} CE\n"
                        f"🛡️ <b>Safe ITM :</b> {itm} CE\n"
                        f"🔴 <b>Stop Loss :</b> {sl:.2f} (Risk / जोखिम: {risk:.2f} pts)\n"
                        f"🎯 <b>Target 1:2 :</b> {target:.2f} (Reward / मुनाफा: {risk*2:.2f} pts)\n"
                        f"-----------------------------------------\n"
                        f"🏛️ <b>RBI Impact :</b> {rbi_status}\n"
                        f"⏱️ <b>MTF Status :</b> 1H-({res_1h['bias']}) | 15M-({res_15m['bias']}) | 5M-({res_5m['bias']})\n"
                        f"📰 <b>News Alert :</b> {news_sent}\n"
                        f"ℹ️ <b>Headline :</b> {news_head}\n"
                        f"📊 <b>Indicators :</b> VIX: {curr_vix:.2f if curr_vix else 'N/A'} | PCR: {pcr:.2f if pcr else 'N/A'}\n"
                        f"-----------------------------------------"
                    )
                    send_alert(msg)
                    sent_alerts[signal_key] = "BULL"

            elif is_confirmed_bear:
                itm = atm_strike + step
                sl = max(res_5m['high_prev'], p_now + max(res_5m['atr'] * 0.85, step * 0.5))
                risk = sl - p_now
                target = p_now - (risk * 2.0)

                if sent_alerts.get(signal_key) != "BEAR":
                    msg = (
                        f"-----------------------------------------\n"
                        f"🐻 🐻 <b>BEAR FALL</b> 🐻 🐻\n"
                        f"(मंदी का संकेत / High Conviction Trade)\n"
                        f"=========================================\n"
                        f"🔴 <b>SIGNAL :</b> PUT (PE) BUY | पुट खरीदें\n"
                        f"📌 <b>ASSET :</b> {name} (15M & 5M Synced)\n"
                        f"-----------------------------------------\n"
                        f"⏰ <b>ENTRY TIME :</b> {entry_str}\n"
                        f"   (प्रवेश समय : केवल केंडल क्लोज़ होने पर)\n"
                        f"⌛ <b>EXIT TIME :</b> Target/SL or max {exit_window_str}\n"
                        f"   (निकास समय : लक्ष्य/स्टॉपलॉस पर या अधिकतम {exit_window_str} तक)\n"
                        f"-----------------------------------------\n"
                        f"⚡ <b>Spot Price :</b> {p_now:.2f} {unit} (वर्तमान भाव)\n"
                        f"🎯 <b>ATM Strike :</b> {atm_strike} PE\n"
                        f"🛡️ <b>Safe ITM :</b> {itm} PE\n"
                        f"🔴 <b>Stop Loss :</b> {sl:.2f} (Risk / जोखिम: {risk:.2f} pts)\n"
                        f"🎯 <b>Target 1:2 :</b> {target:.2f} (Reward / मुनाफा: {risk*2:.2f} pts)\n"
                        f"-----------------------------------------\n"
                        f"🏛️ <b>RBI Impact :</b> {rbi_status}\n"
                        f"⏱️ <b>MTF Status :</b> 1H-({res_1h['bias']}) | 15M-({res_15m['bias']}) | 5M-({res_5m['bias']})\n"
                        f"📰 <b>News Alert :</b> {news_sent}\n"
                        f"ℹ️ <b>Headline :</b> {news_head}\n"
                        f"📊 <b>Indicators :</b> VIX: {curr_vix:.2f if curr_vix else 'N/A'} | PCR: {pcr:.2f if pcr else 'N/A'}\n"
                        f"-----------------------------------------"
                    )
                    send_alert(msg)
                    sent_alerts[signal_key] = "BEAR"

        except Exception as e:
            continue

# Render Web Service Binding
class DummyServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ROUSHAN TOP PRO Scanner is Active 24/7!")

def run_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), DummyServer)
    server.serve_forever()

def loop_scanner():
    send_alert("=========================================\n🚀 <b>ROUSHAN TOP PRO LIVE</b> 🚀\n=========================================\nRBI Repo Rate + Hindi/English MTF Alerts Ready!\nआरबीआई रेपो रेट और द्विभाषी अलर्ट चालू हैं।")
    while True:
        try:
            run_mtf_scanner()
        except:
            pass
        time.sleep(60)

if __name__ == "__main__":
    t = threading.Thread(target=loop_scanner, daemon=True)
    t.start()
    run_server()

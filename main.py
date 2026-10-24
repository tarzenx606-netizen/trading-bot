from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.clock import Clock
from threading import Thread
import requests, time

FAST, SLOW, RP = 9, 21, 14
OB, OS = 70, 30
SCAN = 300

TF_MAP = {
 "Binance": {"1m":"1m","5m":"5m","15m":"15m","1h":"1h","4h":"4h","1d":"1d"},
 "Bybit":   {"1m":"1","5m":"5","15m":"15","1h":"60","4h":"240","1d":"D"},
 "OKX":     {"1m":"1m","5m":"5m","15m":"15m","1h":"1H","4h":"4H","1d":"1D"},
 "KuCoin":  {"1m":"1min","5m":"5min","15m":"15min","1h":"1hour","4h":"4hour","1d":"1day"},
 "Kraken":  {"1m":"1","5m":"5","15m":"15","1h":"60","4h":"240","1d":"1440"},
}

def sym_for(ex, sym):
    b, q = sym.split("/")
    if ex == "Kraken" and b == "BTC":
        b = "XBT"
    if ex in ("Binance", "Bybit"):
        return b + q
    return b + "-" + q

def fetch(ex, sym, tf, n=300):
    s = sym_for(ex, sym)
    if ex == "Binance":
        for u in ["https://api.binance.com/api/v3/klines", "https://data-api.binance.vision/api/v3/klines"]:
            try:
                r = requests.get(u, params={"symbol": s, "interval": tf, "limit": n}, timeout=15)
                if r.status_code == 200:
                    return [[float(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in r.json()]
            except Exception:
                pass
        raise Exception("Binance not reachable")
    if ex == "Bybit":
        r = requests.get("https://api.bybit.com/v5/market/kline", params={"category":"spot","symbol":s,"interval":tf,"limit":n}, timeout=15)
        d = r.json().get("result", {}).get("list", [])
        return [[float(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in d[::-1]]
    if ex == "OKX":
        r = requests.get("https://www.okx.com/api/v5/market/candles", params={"instId":s,"bar":tf,"limit":n}, timeout=15)
        d = r.json().get("data", [])
        return [[float(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in d[::-1]]
    if ex == "KuCoin":
        r = requests.get("https://api.kucoin.com/api/v1/market/candles", params={"type":tf,"symbol":s}, timeout=15)
        d = r.json().get("data", [])
        return [[float(k[0]), float(k[1]), float(k[3]), float(k[4]), float(k[2]), float(k[5])] for k in d[::-1]]
    if ex == "Kraken":
        r = requests.get("https://api.kraken.com/0/public/OHLC", params={"pair":s,"interval":tf}, timeout=15)
        res = r.json().get("result", {})
        d = list(res.values())[0] if res else []
        return [[float(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[6])] for k in d]
    raise Exception("Unknown exchange")

def ema_series(vals, p):
    k = 2.0/(p+1)
    out, e = [], vals[0]
    for v in vals:
        e = v*k + e*(1-k)
        out.append(e)
    return out

def rsi_series(closes, p=14):
    out = [50.0]*len(closes)
    ag = al = 0.0
    for i in range(1, len(closes)):
        d = closes[i]-closes[i-1]
        g = d if d > 0 else 0.0
        l = -d if d < 0 else 0.0
        if i <= p:
            ag += g/p
            al += l/p
        else:
            ag = (ag*(p-1)+g)/p
            al = (al*(p-1)+l)/p
        if i >= p:
            out[i] = 100.0 if al == 0 else 100 - 100/(1+ag/al)
    return out

def analyze(rows):
    closes = [r[4] for r in rows]
    ef = ema_series(closes, FAST)
    es = ema_series(closes, SLOW)
    rsi = rsi_series(closes, RP)
    pv = vv = 0.0
    vwap = []
    for r in rows:
        tp = (r[2]+r[3]+r[4])/3
        pv += tp*r[5]
        vv += r[5]
        vwap.append(pv/vv if vv else tp)
    n = len(rows)
    a, b = n-1, n-2
    atr = sum(rows[i][2]-rows[i][3] for i in range(max(0, n-14), n))/14.0
    trend = "UP" if ef[a] > es[a] else "DOWN"
    long = ef[a] > es[a] and rsi[a] < OB and closes[a] > vwap[a] and (ef[b] <= es[b] or closes[a] > ef[a])
    short = ef[a] < es[a] and rsi[a] > OS and closes[a] < vwap[a] and (ef[b] >= es[b] or closes[a] < ef[a])
    g = None
    if long or short:
        side = "LONG" if long else "SHORT"
        c = closes[a]
        sl = c - 1.5*atr if long else c + 1.5*atr
        tp2 = c + 2*atr if long else c - 2*atr
        g = dict(side=side, price=round(c, 2), sl=round(sl, 2), tp=round(tp2, 2),
                 rsi=round(rsi[a], 1), time=str(rows[a][0]))
    return dict(price=round(closes[a], 2), rsi=round(rsi[a], 1), trend=trend, sig=g)

class BotApp(App):
    def build(self):
        self.running = False
        root = BoxLayout(orientation="vertical", padding=10, spacing=6)
        root.add_widget(Label(text="TRADING SIGNAL BOT", font_size="24sp", size_hint_y=None, height=50))
        row1 = BoxLayout(size_hint_y=None, height=44)
        row1.add_widget(Label(text="Exchange:", size_hint_x=0.3))
        self.ex = Spinner(text="Binance", values=list(TF_MAP.keys()), size_hint_x=0.7)
        row1.add_widget(self.ex)
        root.add_widget(row1)
        row2 = BoxLayout(size_hint_y=None, height=44)
        row2.add_widget(Label(text="Timeframe:", size_hint_x=0.3))
        self.tf = Spinner(text="1h", values=["1m","5m","15m","1h","4h","1d"], size_hint_x=0.7)
        row2.add_widget(self.tf)
        root.add_widget(row2)
        row3 = BoxLayout(size_hint_y=None, height=44)
        row3.add_widget(Label(text="Coins:", size_hint_x=0.3))
        self.coins = TextInput(text="BTC/USDT, ETH/USDT", multiline=False, size_hint_x=0.7)
        row3.add_widget(self.coins)
        root.add_widget(row3)
        row4 = BoxLayout(size_hint_y=None, height=54)
        self.bstart = Button(text="START", background_color=(0,0.7,0,1))
        self.bstart.bind(on_press=self.start)
        self.bstop = Button(text="STOP", background_color=(0.8,0,0,1))
        self.bstop.bind(on_press=self.stop)
        row4.add_widget(self.bstart)
        row4.add_widget(self.bstop)
        root.add_widget(row4)
        self.status = Label(text="START dabayein", size_hint_y=None, height=34)
        root.add_widget(self.status)
        self.log = Label(text="Bot tayyar hai.\n", size_hint_y=None, valign="top")
        self.log.bind(texture_size=self.log.setter("size"))
        sv = ScrollView()
        sv.add_widget(self.log)
        root.add_widget(sv)
        Clock.schedule_interval(self.poll, 0.5)
        return root

    def add_log(self, line):
        self.log.text = time.strftime("%H:%M:%S") + "  " + line + "\n" + self.log.text

    def poll(self, dt):
        while not self.q.empty():
            line = self.q.get()
            self.add_log(line)
            if line.startswith("SIGNAL"):
                self.status.text = "SIGNAL AAYA!"
                self.status.color = (0,1,0,1)

    q = None
    def start(self, inst):
        if self.running:
            return
        import queue as qmod
        self.q = qmod.Queue()
        self.running = True
        ex = self.ex.text
        tf = TF_MAP[ex][self.tf.text]
        syms = [x.strip() for x in self.coins.text.split(",") if x.strip()]
        self.status.text = "Bot chal raha hai..."
        self.status.color = (0,0,1,1)
        Thread(target=self.loop, args=(ex, syms, tf), daemon=True).start()

    def stop(self, inst):
        self.running = False
        self.status.text = "Bot ruk gaya. START dabayein."
        self.status.color = (1,0,0,1)

    def loop(self, ex, syms, tf):
        sent = set()
        self.q.put("Bot shuru: " + ex + " | " + tf)
        while self.running:
            for s in syms:
                try:
                    a = analyze(fetch(ex, s, tf))
                    self.q.put(s + " | Price: " + str(a["price"]) + " | RSI: " + str(a["rsi"]) + " | Trend: " + a["trend"])
                    g = a["sig"]
                    if g and (s, g["time"]) not in sent:
                        sent.add((s, g["time"]))
                        self.q.put("SIGNAL: " + g["side"] + " " + s + " | Entry: " + str(g["price"]) + " | SL: " + str(g["sl"]) + " | TP: " + str(g["tp"]))
                except Exception as e:
                    self.q.put("Error " + s + ": " + str(e))
            for _ in range(SCAN):
                if not self.running:
                    break
                time.sleep(1)
        self.q.put("Bot band ho gaya.")

BotApp().run()

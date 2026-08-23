# Whisplay Bitcoin Market Dashboard

A real-time cryptocurrency market dashboard for the **Raspberry Pi Zero 2 W + Whisplay HAT**,
driven entirely by the HAT's **single physical button**. No touchscreen, no keyboard, no SSH.

It runs as a Whisplay **daemon app**: the `whisplay-daemon` service owns the LCD, backlight,
RGB LED and button, and this app draws into the shared framebuffer it hands out.

```
        BOOT                    1 CLICK                HOLD
          |                        |                     |
          v                        v                     v
   +-------------+          next chart timeframe   next dashboard
   |  BTC/USD    |          1H > 4H > 1D > 1W > 1Y page in the ring
   |             |
   | $112,540.32 |          3 CLICKS              4 CLICKS
   |  +2.41%     |             |                     |
   |    /\/\     |             v                     v
   |  1H 4H 1D   |       force refresh         leave the app
   +-------------+       (2 clicks = HOME)
```

---

## 1. Hardware

| Item | Notes |
|---|---|
| Raspberry Pi Zero 2 W | Target platform; also runs on any 40-pin Pi |
| Whisplay HAT | 240x280 LCD, one push button, RGB LED |
| Wi-Fi | Required for market data (works offline from cache) |
| PiSugar battery | Optional |

The display is **240 x 280 px, RGB565**, exactly 134,400 bytes per frame.

### Pin usage (for reference)

The app never touches GPIO directly — the daemon owns the hardware. These are the HAT's
pins, taken from `Whisplay/runtime/whisplay.py`:

| Function | BOARD pin | BCM GPIO |
|---|---|---|
| LCD DC | 13 | GPIO27 |
| LCD RST | 7 | GPIO4 |
| Backlight | 15 | GPIO22 |
| **Button** | **11** | **GPIO17** |
| LED red | 22 | GPIO25 |
| LED green | 18 | GPIO24 |
| LED blue | 16 | GPIO23 |
| SPI MOSI / MISO / SCLK / CE0 | 19 / 21 / 23 / 24 | GPIO10 / 9 / 11 / 8 |

Buses used: **SPI** (LCD), **I2C + I2S** (audio, unused here).

> **Radxa Cubie A7Z warning** (from the Whisplay docs): the physical button is *not safe to
> press* on that board. This project is for the Raspberry Pi.

---

## 2. Install

Install the Whisplay daemon first, if it is not already running:

```bash
cd ~/Whisplay
./install_driver.sh                              # one time, reboot after
./daemon/install_whisplay_daemon_service.sh
```

Then install the dashboard:

```bash
cd ~/whisplay-crypto-dashboard
./install.sh                 # register as a daemon app
./install.sh --autostart     # ...and start automatically at boot
```

`install.sh` prefers **apt** packages for Pillow/numpy/requests — building those from source
with pip on a Pi Zero 2 W can take close to an hour.

No API key is required. The defaults use free, key-less endpoints.

Run it directly:

```bash
./run.sh
```

Or launch from the Whisplay desktop: single-click to select **BTC Dashboard**, then long press.
(Those are the *desktop's* gestures, set by the daemon. Once the app is running it uses its own
mapping — see Controls below.)

---

## 3. Controls

| Gesture | Action |
|---|---|
| **1 click** | Next chart timeframe (1H > 4H > 1D > 1W > 1Y) |
| **hold** | Next page (Bitcoin > Market > Top > Statistics > System > Bitcoin) |
| **2 clicks** | Return **HOME**, from any page |
| **3 clicks** | Force an immediate refresh of every data source |
| **4 clicks** | Leave the app, back to the Whisplay desktop |

### Why the app owns every gesture

The app registers with `exit_gesture: "none"`, so the daemon reserves nothing and all five
gestures above are handled in-app.

This is required, not a preference. The daemon's own quad-click exit uses a **3-second**
window, and stepping through `1H > 4H > 1D > 1W > 1Y` is exactly **four single clicks** — a
user cycling briskly would be thrown out of the app mid-cycle. Handling exit in-app instead
uses the much tighter `click_window_ms` (400 ms default), which draws a clean line:

- clicks spaced **wider** than 400 ms are independent timeframe changes
- clicks landing **inside** 400 ms of each other accumulate toward the exit gesture

So: click at a normal pace to browse timeframes; click four times rapidly to leave.

The daemon's `app_exit_requested` is still honoured, so setting `exit_gesture` back to
`"quad_click"` or `"long_press"` in `packaging/whisplay-crypto-dashboard.json` still works if
you prefer a daemon-level exit. An external keyboard's `Esc` also still returns to the desktop.

Gesture timing is configurable in `config.yaml`:

```yaml
button:
  debounce_ms: 75        # contact bounce filter
  click_window_ms: 400   # window to collect further clicks
  long_press_ms: 700     # at/over this, the press is not counted as a click
```

Four clicks fire **immediately** on the fourth release rather than waiting out the click
window, so leaving the app feels instant. Debounce is applied to the press edge only — gating
the release edge as well would swallow genuine short clicks, which are often only 30–60 ms long.

Raise `click_window_ms` if you find yourself exiting by accident while cycling timeframes;
lower it if single clicks feel sluggish (each one waits out the window before acting).

**Tuning it from real data.** Every gesture is logged with the measured gap between clicks:

```
gesture: quad   (gaps 37360/215/189/158 ms, window 700 ms)
gesture: single (gaps 1214 ms, window 700 ms)
```

Measured on the HAT's button, two clearly separated clusters emerged:

| Intent | Measured inter-click gap |
|---|---|
| Deliberate multi-click (double / quad) | **158–522 ms** |
| Ordinary browsing clicks | **≥ 1214 ms** |

`click_window_ms: 700` sits in the empty band between them, which is why it is the default.
The original 400 ms was below the top of the deliberate cluster, so four intentional clicks
kept registering as four separate timeframe changes. If multi-click gestures are not forming
for you, read your own gaps out of the log and set the window between your two clusters.

---

## 4. The five pages

**1. Bitcoin (HOME)** — price, 24h change, 24h high/low, auto-scaling chart, window change,
volume, timeframe selector, last-update time.

**2. Market Overview** — total market cap and its 24h change, total volume, BTC and ETH
dominance, stablecoin cap, Fear & Greed index with meter, BTC/ETH quotes.

**3. Top Cryptocurrencies** — top 5 by market cap: rank, symbol, market cap, price, 24h change.

**4. Bitcoin Statistics** — market cap, volume, 24h high/low, circulating and max supply,
all-time high, distance from ATH, 7d and 30d change, market-cap rank.

**5. System Status** — Wi-Fi / Internet / API checks, CPU, RAM, temperature, uptime, app
memory, last update, and the last error message.

Any metric a provider does not return is **omitted entirely**. Nothing is faked or zero-filled.

---

## 5. Data providers

```
MarketDataProvider  (app/market/provider.py)
        |
        +-- BinanceProvider        price + candles, no key, fast
        +-- CoinGeckoProvider      market cap, supply, dominance, top coins
        +-- AlternativeMeProvider  Fear & Greed index
```

Each capability has its own ordered fallback list in `config.yaml`:

```yaml
providers:
  price: [binance, coingecko]     # first success wins
  chart: [binance, coingecko]
  market: [coingecko]
```

Binance is the default for price and charts (sub-second data, generous limits); CoinGecko
supplies everything an exchange ticker cannot know, such as market cap and supply.

**Adding a provider:** subclass `MarketDataProvider`, implement only the calls you can serve,
decorate with `@register_provider`, import it in `app/market/registry.py`, and add its name to
the relevant list in `config.yaml`. No UI code changes.

API keys are read from `.env` only, are never written to logs, and `.env` is git-ignored.

---

## 6. Offline behaviour

The last successful data is cached to `~/.whisplay-crypto/cache.json` and restored at boot, so
a Pi that starts without Internet still shows its last known market state.

Stale data is **never presented as live**:

| Indicator | Meaning |
|---|---|
| `● LIVE` (filled dot) | Data is current |
| `○ OFFLINE` (hollow ring) | The API is unreachable; the age of the data is shown |

Retries follow an exponential ladder — **5s, 10s, 30s, 60s, 120s** — per data lane, so a
rate-limited market call never slows the price tape. Any lane that fails keeps its previous
value rather than blanking the screen.

---

## 7. Configuration

Everything lives in `config.yaml`; no code changes needed. See the file for the full set.

```yaml
bitcoin:
  default_timeframe: 1D     # remembered across restarts

refresh:
  price_seconds: 10
  market_seconds: 60
  chart_seconds: 60

display:
  brightness: 80
  fps: 20                   # ceiling, not a target
  led_enabled: true         # LED shows market direction
```

The selected timeframe persists in `~/.whisplay-crypto/state.json`.

The RGB LED reports state at a glance: **green** up, **red** down, **amber** offline,
**blue** refreshing.

---

## 8. Architecture

```
whisplay-crypto-dashboard/
├── app/
│   ├── main.py              state machine, render loop, gesture routing
│   ├── board.py             daemon/direct/headless hardware acquisition
│   ├── ui/
│   │   ├── display.py       PIL canvas -> RGB565 framebuffer
│   │   ├── theme.py         palette, fonts, text fitting
│   │   ├── widgets.py       header, arrows, meters, toasts
│   │   └── *_screen.py      the five pages
│   ├── input/button.py      single/double/triple/quad gesture detection
│   ├── market/
│   │   ├── provider.py      interface + data models
│   │   ├── binance.py  coingecko.py  alternative_me.py
│   │   ├── registry.py      provider registration
│   │   ├── service.py       scheduling, fallback, connection state
│   │   └── cache.py         persistent cache + app state
│   ├── chart/renderer.py    hand-rolled chart
│   ├── config/settings.py   defaults < config.yaml < environment
│   └── utils/               logger, format, network, system
├── tests/                   77 tests
├── tools/preview.py         render screens to PNG without hardware
└── packaging/               systemd unit + daemon app manifest
```

**Three threads, one job each:**

| Thread | Responsibility |
|---|---|
| `main` | Renders only. Never touches the network. |
| `market-service` | All HTTP. Publishes immutable snapshots. |
| `gesture-detector` | Button timing. |
| `foreground-retry` | Only when another app holds the screen; exits once granted. |

The render loop is **event-driven**: it sleeps on a condition variable until data changes, a
button is pressed, or the status tick expires. It redraws only when:

- new market data arrives
- the user changes page or timeframe
- the connection state changes
- the status tick fires (clock / data age)

Measured idle rate: **~9 redraws per minute**, not 20 per second.

---

## 9. Performance on a Pi Zero 2 W

Measured over 90 s of steady state with live data (x86 dev host; expect a few percent CPU on
Pi Zero silicon):

| Metric | Result | Target |
|---|---|---|
| CPU (idle) | 0.18% of one core | low |
| RSS memory | 52.6 MB | < 100 MB |
| Redraws | 8.7 / min | only on change |
| Threads | 4 | — |
| Frame size | 134,400 B | exact |

Recommendations:

- **Install `python3-numpy`** — RGB565 conversion is roughly 10x faster. The app works without
  it but burns noticeably more CPU per frame.
- **Use apt, not pip**, for Pillow and numpy.
- Keep `fps` at 20 or below; it matches the daemon's own refresh and is a ceiling, not a target.
- Do not lower `price_seconds` below ~5 s. It adds load and risks provider rate limits.
- Leave `cache_enabled: true`. Cache writes are throttled (30 s minimum) and atomic to limit
  SD-card wear.
- Logging is rotated at 512 KB x 3. Display redraws are deliberately never logged.
- The systemd unit sets `MemoryMax=180M` and `Nice=5`.
- Avoid running Chromium, Electron, X, or any browser-based dashboard alongside this.

---

## 10. Autostart

`./install.sh --autostart` installs `whisplay-crypto.service`:

```ini
After=network-online.target whisplay-daemon.service
BindsTo=whisplay-daemon.service
Restart=on-failure
RestartSec=5
StartLimitIntervalSec=0
```

**Why `on-failure` and not `always`:** the app exits cleanly when you click four times to
return to the Whisplay desktop. With `Restart=always`, systemd would relaunch it five seconds
later and take the screen back, making the exit gesture useless on a Pi that also runs other
Whisplay apps. `on-failure` still restarts after a crash, which is the actual requirement. If
your Pi is a dedicated single-purpose BTC display, change it to `always`.

**Starting while another app owns the screen:** if the dashboard starts while the Wi-Fi app (or
any other app) is in the foreground, the daemon refuses to hand over the framebuffer. The app
does not go blind — it reports mode `waiting`, keeps its data fresh, draws nothing, and retries
every 5 seconds. The moment the other app exits, the dashboard appears by itself.

`run.sh` waits up to 30 s for `/tmp/whisplay-daemon.sock` before starting, so boot does not
race the daemon. If the daemon never appears, the app falls back to direct hardware access.

```bash
sudo systemctl status  whisplay-crypto
sudo systemctl restart whisplay-crypto
journalctl -u whisplay-crypto -f
```

Boot sequence: `Pi > Wi-Fi > whisplay-daemon > run.sh waits for socket > dashboard (HOME)`.

---

## 11. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Blank screen, app appears to run | Check the mode on the System page. `WAITING` means another app owns the foreground — exit that app and this one appears within 5s. `HEADLESS` means the Whisplay runtime was not found — set `WHISPLAY_RUNTIME=/path/to/Whisplay/runtime`. |
| Log says `foreground unavailable ... retrying` | Expected. Another Whisplay app holds the screen; the dashboard takes over when that app exits. |
| Four clicks exit, then the app comes straight back | The unit is set to `Restart=always`. Change it to `Restart=on-failure` (the shipped default). |
| `whisplay runtime is unusable: No module named 'spidev'` | Whisplay drivers not installed. Run `Whisplay/install_driver.sh` and reboot. |
| App not on the Whisplay desktop | `ls ~/.whisplay-daemon/app/` should list `whisplay-crypto-dashboard.json`. Re-run `./install.sh`, then restart the daemon. |
| App exits while cycling timeframes | Four clicks inside the click window is the exit gesture. Click at a slower pace, or raise `click_window_ms` in `config.yaml`. |
| Holding the button exits instead of changing page | `exit_gesture` is not `none`. Confirm it in `~/.whisplay-daemon/app/whisplay-crypto-dashboard.json`, re-run `./install.sh`, and restart the daemon. |
| Clicks register as the wrong count | Tune `click_window_ms` (raise to 500 for slower clicking) and `debounce_ms` in `config.yaml`. |
| `OFFLINE` but the Pi has Internet | Check the System page's last error. A CoinGecko `429` is rate limiting — it backs off automatically; increase `market_seconds`/`top_seconds` if persistent. |
| Chart shows `CHART UNAVAILABLE` | Candles have not loaded yet, or Binance is unreachable in your region. Set `BINANCE_API_BASE` in `.env`, or put `coingecko` first in `providers.chart`. |
| Prices update, market cap does not | CoinGecko lane is failing while Binance succeeds. Expected degradation — the missing fields hide rather than showing stale numbers. |
| Nothing in `/var/log/whisplay-crypto/` | Directory not writable; logging fell back to `~/.whisplay-crypto/app.log`. |
| Service restarts repeatedly | `journalctl -u whisplay-crypto -n 50`. If the daemon is down, `BindsTo` stops this unit too. |
| Screen never updates | By design it only redraws on change. Press the button — if it responds, it is working. |

Useful checks:

```bash
tail -f /var/log/whisplay-crypto/app.log
tail -f ~/.whisplay-daemon/daemon-app.log
python3 -c "import socket,json;s=socket.socket(socket.AF_UNIX);s.connect('/tmp/whisplay-daemon.sock');s.sendall(b'{\"version\":1,\"cmd\":\"health.ping\",\"payload\":{}}\n');print(s.recv(4096))"
```

---

## 12. Development

```bash
python3 -m pytest tests/ -q          # 77 tests, no hardware needed
python3 tools/preview.py --mock      # render all five screens to PNG
python3 tools/preview.py             # ...with live market data
```

`tools/preview.py` writes each screen plus a contact sheet to `/tmp/whisplay-preview`, which
makes layout work possible without deploying to the Pi.

---

## 13. Extending

The architecture is ready for:

- **More coins** — `CoinSummary` and the provider interface are already symbol-agnostic;
  `bitcoin.symbol` in `config.yaml` drives the whole app.
- **New pages** — subclass `Screen`, add it to `self.screens` in `main.py`. It joins the ring.
- **New providers** — see section 5.
- **Currency switching** — `bitcoin.currency` is threaded through formatting and both providers.

Deliberately out of scope for v1: portfolio tracking, price alerts, funding rates, ETF flows,
Telegram notifications, web configuration.

---

## 14. Security

- API keys live only in `.env`, which is `chmod 600` and git-ignored.
- Keys are attached as request headers and never logged; log lines carry provider names only.
- No inbound network listeners. All traffic is outbound HTTPS.
- The app talks to the daemon over a local Unix socket.

## License

Follows the license of the parent Whisplay project.

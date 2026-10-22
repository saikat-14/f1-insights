"""F1 Insights UI: design system (CSS), brand, championship cards, podium, countdown and the 2D circuit map."""
import base64
import html
import json
import math
from functools import lru_cache
from pathlib import Path

from teams import team_style

ASSETS = Path(__file__).resolve().parents[1] / "app" / "assets"
FONT = "@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');"
FONT_STACK = "'Inter',system-ui,-apple-system,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif"


@lru_cache(maxsize=None)
def asset_uri(name: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode((ASSETS / name).read_bytes()).decode()


# ============================================================================ GLOBAL CSS
GLOBAL_CSS = "<style>" + FONT + """
:root{--bg:#0A0B0F;--s1:#12141A;--s2:#171A22;--line:#262A35;--line2:#323746;--tx:#ECEEF3;--mut:#8D93A5;--red:#E10600;--red2:#FF3B30;--ok:#2FD07A;--bad:#FF5C5C}
html,body,.stApp,button,input,textarea,select{font-family:%FS%!important}
.stApp{background:radial-gradient(900px 440px at 90% -12%,rgba(225,6,0,.15),transparent 62%),var(--bg);color:var(--tx);font-feature-settings:"tnum" 1,"cv11" 1}
[data-testid="stHeader"]{background:rgba(10,11,15,.86);backdrop-filter:blur(12px);border-bottom:1px solid var(--line)}
.block-container{padding:1.6rem 2rem 4rem;max-width:1240px}
h1,h2,h3,h4{font-family:%FS%!important;font-weight:700!important;letter-spacing:-.02em;text-transform:none;color:#fff}
h1{font-size:clamp(1.7rem,4.2vw,2.5rem)!important;line-height:1.1!important;margin:.15rem 0 .35rem!important}
h2{font-size:1.5rem!important}h3{font-size:1.2rem!important;margin-top:1.4rem!important}h4{font-size:1rem!important;color:#DDE0E8}
p,li,label,.stMarkdown{color:var(--tx)}
[data-testid="stCaptionContainer"]{color:var(--mut)}
[data-testid="stMetric"]{background:linear-gradient(180deg,var(--s2),var(--s1));border:1px solid var(--line);border-radius:12px;padding:14px 16px}
[data-testid="stMetricLabel"] p{color:var(--mut);font-size:.74rem;text-transform:uppercase;letter-spacing:.08em;font-weight:600}
[data-testid="stMetricValue"]{font-weight:700;letter-spacing:-.02em}
.stButton>button,.stDownloadButton>button{background:var(--red);color:#fff;border:0;border-radius:9px;font-weight:600;letter-spacing:.01em;padding:.5rem 1rem;transition:background .15s,transform .15s,box-shadow .15s}
.stButton>button:hover{background:var(--red2);color:#fff;transform:translateY(-1px);box-shadow:0 8px 22px rgba(225,6,0,.28)}
.stTabs [data-baseweb="tab-list"]{gap:6px;border-bottom:1px solid var(--line)}
.stTabs [data-baseweb="tab"]{font-weight:600;font-size:.95rem;padding:.55rem .9rem}
.stTabs [aria-selected="true"]{color:#fff!important}
.stTabs [data-baseweb="tab-highlight"]{background:var(--red)!important;height:3px}
[data-testid="stDataFrame"]{border:1px solid var(--line);border-radius:12px;overflow:hidden}
[data-testid="stExpander"]{border:1px solid var(--line)!important;border-radius:12px!important;background:var(--s1)}
/* ---- brand ---- */
.fi-brand{display:flex;align-items:center;gap:12px;margin:0 0 .9rem}
.fi-brand img{width:42px;height:42px;display:block;flex:none}
.fi-brand-name{font-weight:800;font-size:1.15rem;letter-spacing:.14em;color:#fff;line-height:1}
.fi-brand-name b{color:var(--red2);font-weight:800}
.fi-brand-tag{display:block;font-size:.68rem;letter-spacing:.18em;color:var(--mut);text-transform:uppercase;margin-top:4px;font-weight:600}
.fi-banner{display:flex;align-items:center;gap:20px;padding:22px 26px;border:1px solid var(--line);border-radius:16px;margin-bottom:1.2rem;
 background:linear-gradient(110deg,rgba(225,6,0,.16),rgba(18,20,26,.4) 46%),var(--s1);position:relative;overflow:hidden}
.fi-banner:after{content:"";position:absolute;right:-40px;top:-30px;width:220px;height:200px;background:var(--red);opacity:.07;transform:skewX(-24deg)}
.fi-banner img{width:76px;height:76px;flex:none}
.fi-banner .n{font-weight:800;font-size:clamp(1.7rem,4.4vw,2.6rem);letter-spacing:.1em;line-height:1;color:#fff}.fi-banner .n b{color:var(--red2)}
.fi-banner .t{color:#B7BBC9;font-size:clamp(.8rem,1.9vw,1rem);margin-top:8px;max-width:640px}
.fi-sub{color:var(--mut);font-size:1rem;margin-bottom:1rem;max-width:760px}
/* ---- cards ---- */
.fi-card{background:linear-gradient(180deg,var(--s2),var(--s1));border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin:8px 0}
.fi-eyebrow{font-size:.7rem;letter-spacing:.14em;text-transform:uppercase;color:var(--mut);font-weight:700}
.fi-card .v{font-weight:700;font-size:1.5rem;letter-spacing:-.02em;margin-top:4px}
.fi-grid{display:grid;gap:12px}.fi-g4{grid-template-columns:repeat(4,1fr)}.fi-g3{grid-template-columns:repeat(3,1fr)}
.fi-tile{background:var(--s1);border:1px solid var(--line);border-radius:12px;padding:12px 14px}.fi-tile .v{font-size:1.35rem;font-weight:700;margin-top:3px;letter-spacing:-.02em}
.fi-sess{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:10px}
.fi-s{background:var(--s1);border:1px solid var(--line);border-left:3px solid var(--line2);border-radius:10px;padding:10px 12px}
.fi-s.next{border-left-color:var(--red);background:rgba(225,6,0,.08)}.fi-s.done{opacity:.5}
.fi-s .a{font-weight:700;font-size:.92rem}.fi-s .b{color:var(--mut);font-size:.84rem;margin-top:2px}
.fi-hero{padding:22px 24px;border:1px solid var(--line);border-radius:16px;background:linear-gradient(120deg,rgba(225,6,0,.12),transparent 55%),var(--s1)}
.fi-hero .ev{font-weight:800;font-size:clamp(1.7rem,5vw,3rem);letter-spacing:-.03em;line-height:1.05;margin:6px 0 4px;color:#fff}
.fi-hero .ct{color:#B7BBC9;font-size:.95rem}
.fi-pill{display:inline-block;background:var(--red);color:#fff;font-size:.7rem;font-weight:700;letter-spacing:.12em;padding:4px 10px;border-radius:999px;text-transform:uppercase}
.fi-meter{margin:10px 0}.fi-meter .lb{display:flex;justify-content:space-between;font-weight:600;font-size:.92rem;margin-bottom:5px}
.fi-meter .tr{height:8px;background:#21242E;border-radius:99px;overflow:hidden}.fi-meter .fl{height:100%;background:linear-gradient(90deg,#9B0500,var(--red2));border-radius:99px}
.fi-note{color:var(--mut);font-size:.8rem;margin-top:3px}
.fi-status{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;color:var(--mut);font-size:.84rem;margin:2px 0 14px}
.fi-dot{width:8px;height:8px;border-radius:50%;background:var(--ok);display:inline-block;margin-right:6px}.fi-dot.warn{background:#F5B301}.fi-dot.bad{background:var(--bad)}
/* ---- leader ---- */
.fi-leader{display:grid;grid-template-columns:auto 1fr auto;gap:26px;align-items:center;padding:24px 26px;border-radius:18px;border:1px solid var(--line);position:relative;overflow:hidden;
 background:linear-gradient(115deg,color-mix(in srgb,var(--tc) 22%,transparent),transparent 58%),var(--s1)}
.fi-leader:before{content:"";position:absolute;left:0;top:0;bottom:0;width:5px;background:var(--tc)}
.fi-ava{width:118px;height:118px;border-radius:50%;position:relative;flex:none;border:3px solid var(--tc);background:linear-gradient(160deg,#242836,#14161D);display:flex;align-items:center;justify-content:center;
 font-weight:800;font-size:2rem;color:#fff;box-shadow:0 0 0 6px rgba(255,255,255,.04)}
.fi-ava img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:50% 18%;border-radius:50%}
.fi-ava.sm{width:52px;height:52px;font-size:1rem;border-width:2px;box-shadow:none}
.fi-crown{position:absolute;right:-6px;bottom:-2px;z-index:2;background:var(--red);color:#fff;border-radius:99px;font-size:.68rem;font-weight:800;letter-spacing:.08em;padding:4px 8px;border:2px solid var(--s1)}
.fi-leader .nm{font-weight:800;font-size:clamp(1.6rem,4vw,2.6rem);letter-spacing:-.03em;line-height:1.05;color:#fff}
.fi-leader .tm{display:flex;align-items:center;gap:8px;color:#C4C8D4;font-weight:500;margin-top:6px}
.fi-sw{width:10px;height:10px;border-radius:3px;background:var(--tc);display:inline-block}
.fi-stats{display:flex;flex-wrap:wrap;gap:10px 28px;margin-top:16px}.fi-stats div b{display:block;font-size:1.5rem;font-weight:700;letter-spacing:-.02em;color:#fff}
.fi-stats div span{font-size:.68rem;letter-spacing:.12em;text-transform:uppercase;color:var(--mut);font-weight:600}
.fi-bigp{text-align:right}.fi-bigp b{display:block;font-size:clamp(2.2rem,5vw,3.4rem);font-weight:800;letter-spacing:-.04em;line-height:1;color:#fff}
.fi-bigp span{font-size:.68rem;letter-spacing:.12em;text-transform:uppercase;color:var(--mut);font-weight:600}
/* ---- contenders ---- */
.fi-cg{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:14px;margin-top:10px}
.fi-c{background:linear-gradient(180deg,var(--s2),var(--s1));border:1px solid var(--line);border-top:3px solid var(--tc);border-radius:14px;padding:16px}
.fi-c.lead{border-color:var(--red);box-shadow:0 0 0 1px rgba(225,6,0,.35)}
.fi-ch{display:flex;gap:12px;align-items:center}.fi-ch .who{flex:1;min-width:0}.fi-ch .who b{display:block;font-size:1.02rem;font-weight:700;line-height:1.2;overflow-wrap:break-word}
.fi-ch .who span{font-size:.8rem;color:var(--mut)}
.fi-pr{text-align:right}.fi-pr b{display:block;font-size:1.7rem;font-weight:800;letter-spacing:-.03em;line-height:1}
.fi-tr{font-size:.74rem;font-weight:700;margin-top:4px;display:inline-block}.fi-tr.up{color:var(--ok)}.fi-tr.down{color:var(--bad)}.fi-tr.flat{color:var(--mut)}
.fi-bar{margin-top:12px}.fi-bar .l{display:flex;justify-content:space-between;font-size:.74rem;color:var(--mut);margin-bottom:5px}
.fi-bar .t{height:9px;background:#20232D;border-radius:99px;overflow:hidden}.fi-bar .f{height:100%;border-radius:99px;background:var(--tc)}
.fi-bar .f.red{background:linear-gradient(90deg,#9B0500,var(--red2))}
.fi-meta{display:flex;justify-content:space-between;align-items:center;margin-top:14px;gap:8px;flex-wrap:wrap}
.fi-form{display:flex;gap:4px}.fi-fp{min-width:30px;text-align:center;font-size:.7rem;font-weight:700;padding:3px 0;border-radius:6px;background:#242834;color:#C4C8D4}
.fi-fp.w{background:var(--red);color:#fff}.fi-fp.p{background:rgba(225,6,0,.22);color:#FFB3AE}.fi-fp.x{background:transparent;border:1px dashed #4a4f5f;color:#8D93A5}
.fi-spark{display:flex;align-items:flex-end;gap:3px;height:26px}.fi-spark i{width:7px;border-radius:2px 2px 0 0;background:#3a4052;min-height:2px}.fi-spark i:last-child{background:var(--red2)}
.fi-mini{display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--line)}.fi-mini:last-child{border:0}
.fi-mini .who{flex:1;min-width:0;font-weight:600;font-size:.92rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fi-mini .bar{flex:1.2;height:8px;background:#20232D;border-radius:99px;overflow:hidden}.fi-mini .bar i{display:block;height:100%;background:var(--tc);border-radius:99px}
.fi-mini .p{width:54px;text-align:right;font-weight:700}
.fi-wx{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px}
/* ---- responsive ---- */
@media(max-width:900px){.fi-g4{grid-template-columns:repeat(2,1fr)}.fi-g3{grid-template-columns:1fr 1fr}.fi-leader{grid-template-columns:auto 1fr}.fi-bigp{grid-column:1/-1;text-align:left;display:flex;align-items:baseline;gap:10px}}
@media(max-width:640px){.block-container{padding:1rem .9rem 3rem}.fi-banner{padding:16px;gap:14px}.fi-banner img{width:54px;height:54px}.fi-leader{grid-template-columns:1fr;padding:18px;gap:16px}
 .fi-ava{width:92px;height:92px}.fi-g3,.fi-g4{grid-template-columns:1fr 1fr}.fi-cg{grid-template-columns:1fr}.fi-hero{padding:16px}}
</style>""".replace("%FS%", FONT_STACK)


# ============================================================================ brand + small blocks
def brand(page_title: str, sub: str = "") -> str:
    mark = asset_uri("logo_mark.svg")
    return (f'<div class="fi-brand"><img src="{mark}" alt="F1 Insights logo"><div><div class="fi-brand-name">F1 <b>INSIGHTS</b></div>'
            f'<span class="fi-brand-tag">Formula 1 analytics platform</span></div></div>'
            f'<h1>{html.escape(page_title)}</h1>' + (f'<div class="fi-sub">{sub}</div>' if sub else ""))


def brand_banner() -> str:
    mark = asset_uri("logo_mark.svg")
    return (f'<div class="fi-banner"><img src="{mark}" alt="F1 Insights logo"><div><div class="n">F1 <b>INSIGHTS</b></div>'
            f'<div class="t">Race data, championship standings, circuit maps and driver performance insight, in one place. All times in IST.</div></div></div>')


def meter(label: str, pct: float, note: str = "") -> str:
    pct = max(0, min(100, pct))
    return (f'<div class="fi-meter"><div class="lb"><span>{html.escape(label)}</span><span>{pct:.0f}%</span></div>'
            f'<div class="tr"><div class="fl" style="width:{pct}%"></div></div>' + (f'<div class="fi-note">{note}</div>' if note else "") + "</div>")


def stat_card(k: str, v: str) -> str:
    return f'<div class="fi-card"><div class="fi-eyebrow">{html.escape(k)}</div><div class="v">{v}</div></div>'


def tiles(items, cls="fi-g4") -> str:
    return f'<div class="fi-grid {cls}">' + "".join(
        f'<div class="fi-tile"><div class="fi-eyebrow">{html.escape(k)}</div><div class="v">{v}</div></div>' for k, v in items) + "</div>"


def weather_cards(w) -> str:
    if not w:
        return '<div class="fi-note">Race-day forecast becomes available within about 16 days of the race.</div>'
    items = []
    for key, label, fmt in (("temp_c", "Air", "{:.0f}°C"), ("track_c", "Track", "{:.0f}°C"), ("rain_prob", "Rain chance", "{:.0f}%"),
                            ("humidity", "Humidity", "{:.0f}%"), ("wind_kph", "Wind", "{:.0f} km/h"), ("cloud", "Cloud", "{:.0f}%")):
        if w.get(key) is not None:
            items.append((label, fmt.format(w[key])))
    if w.get("rain_prob") is None and w.get("wet") is not None:
        items.append(("Race", "Wet" if w["wet"] else "Dry"))
    return '<div class="fi-wx">' + "".join(f'<div class="fi-tile"><div class="fi-eyebrow">{k}</div><div class="v">{v}</div></div>' for k, v in items) + \
           f'</div><div class="fi-note">Source: {html.escape(str(w.get("source", "")))}</div>'


def hero_card(info: dict) -> str:
    sess = "".join(f'<div class="fi-s {s["state"]}"><div class="a">{html.escape(s["name"])}</div><div class="b">{s["day"]} · {s["time"]}</div></div>'
                   for s in info["sessions"])
    return (f'<div class="fi-hero"><span class="fi-pill">Next Grand Prix · Round {info["round"]}</span><div class="ev">{html.escape(info["event"])}</div>'
            f'<div class="ct">{html.escape(str(info["country"]))} · weekend schedule in IST (UTC+5:30)</div><div class="fi-sess">{sess}</div></div>')


_COUNTDOWN = """<!doctype html><html><head><meta charset="utf-8"><style>%FONT%
*{box-sizing:border-box}body{margin:0;background:transparent;font-family:%FS%;color:#fff}
.l{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:#8D93A5;font-weight:700;margin:12px 2px 8px}
.r{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;max-width:520px}
.u{background:#12141A;border:1px solid #262A35;border-bottom:3px solid #E10600;border-radius:12px;padding:10px 6px;text-align:center}
.u b{display:block;font-size:clamp(26px,7vw,40px);font-weight:800;letter-spacing:-.03em;line-height:1;font-variant-numeric:tabular-nums}
.u span{font-size:10px;letter-spacing:.14em;color:#8D93A5;text-transform:uppercase;font-weight:600}
</style></head><body><div class="l">%LABEL%</div><div class="r"><div class="u"><b id="d">--</b><span>days</span></div><div class="u"><b id="h">--</b><span>hours</span></div>
<div class="u"><b id="m">--</b><span>min</span></div><div class="u"><b id="s">--</b><span>sec</span></div></div>
<script>const T=new Date("%ISO%").getTime();const p=n=>String(n).padStart(2,"0");
function tick(){let l=Math.max(0,T-Date.now())/1000;const d=Math.floor(l/86400);l-=d*86400;const h=Math.floor(l/3600);l-=h*3600;const m=Math.floor(l/60);l-=m*60;
document.getElementById("d").textContent=d;document.getElementById("h").textContent=p(h);document.getElementById("m").textContent=p(m);document.getElementById("s").textContent=p(Math.floor(l))}
tick();setInterval(tick,1000)</script></body></html>"""


def countdown_html(target_iso: str, label: str) -> str:
    return (_COUNTDOWN.replace("%FONT%", FONT).replace("%FS%", FONT_STACK).replace("%LABEL%", html.escape(label)).replace("%ISO%", target_iso))


# ============================================================================ championship
def fmt_prob(p: float, clinched=False) -> str:
    if clinched and p >= 0.999:
        return "Champion"
    if p >= 0.995:
        return ">99%"
    if p < 0.001:
        return "<0.1%"
    return f"{p * 100:.1f}%" if p < 0.01 else f"{p * 100:.0f}%"


def _pts(v: float) -> str:
    return f"{v:.0f}" if abs(v - round(v)) < 1e-9 else f"{v:.1f}"


def _initials(name: str) -> str:
    parts = [x for x in str(name).split() if x]
    return (parts[0][0] + parts[-1][0]).upper() if len(parts) > 1 else str(name)[:3].upper()


def avatar(row: dict, small=False) -> str:
    img = f'<img src="{html.escape(row["image"])}" alt="" loading="lazy" referrerpolicy="no-referrer">' if row.get("image") else ""
    cls = "fi-ava sm" if small else "fi-ava"
    return f'<div class="{cls}">{html.escape(_initials(row["name"]))}{img}</div>'


def trend_badge(row: dict) -> str:
    ch = row.get("prob_change")
    if row.get("eliminated"):
        return '<span class="fi-tr flat">Mathematically out</span>'
    if ch is None:
        return '<span class="fi-tr flat">First estimate</span>'
    pp = ch * 100
    if row["trend"] == "up":
        return f'<span class="fi-tr up">▲ +{pp:.1f} pp since last race</span>'
    if row["trend"] == "down":
        return f'<span class="fi-tr down">▼ −{abs(pp):.1f} pp since last race</span>'
    return '<span class="fi-tr flat">● Steady since last race</span>'


def leader_card(p: dict) -> str:
    rows = p["standings"]
    L = rows[0]
    second = rows[1] if len(rows) > 1 else None
    tc = team_style(L["team"])["ui"]
    gap = (L["points"] - second["points"]) if second else 0
    gap_txt = f"+{_pts(gap)}" if second else "–"
    head = "Drivers' Champion" if p.get("clinched") else "Drivers' Championship leader"
    chance = fmt_prob(L["prob"], p.get("clinched"))
    ahead = f'{html.escape(second["name"])} is second' if second else ""
    return (f'<div class="fi-leader" style="--tc:{tc}">{_crowned(L)}'
            f'<div><div class="fi-eyebrow">{head} · after round {p["as_of_round"]} of {p["total_rounds"]}</div>'
            f'<div class="nm">{html.escape(L["name"])}</div><div class="tm"><span class="fi-sw"></span>{html.escape(L["team"])}</div>'
            f'<div class="fi-stats"><div><b>{_pts(L["points"])}</b><span>Points</span></div><div><b>{gap_txt}</b><span>Gap to P2</span></div>'
            f'<div><b>{L["wins"]}</b><span>Wins</span></div><div><b>{L["podiums"]}</b><span>Podiums</span></div></div>'
            f'<div class="fi-note" style="margin-top:12px">{ahead}</div></div>'
            f'<div class="fi-bigp"><b>{chance}</b><span>Estimated title chance</span></div></div>')


def _crowned(row: dict) -> str:
    img = f'<img src="{html.escape(row["image"])}" alt="" loading="lazy" referrerpolicy="no-referrer">' if row.get("image") else ""
    return (f'<div class="fi-ava">{html.escape(_initials(row["name"]))}{img}<span class="fi-crown">P1</span></div>')


def _form_pills(form) -> str:
    out = []
    for f in form:
        if f["dnf"] or not f["pos"]:
            out.append('<span class="fi-fp x">DNF</span>')
        else:
            c = "w" if f["pos"] == 1 else ("p" if f["pos"] <= 3 else "")
            out.append(f'<span class="fi-fp {c}">P{f["pos"]}</span>')
    return "".join(out) or '<span class="fi-note">No results yet</span>'


def _spark(history, code, n=8) -> str:
    vals = [h["probs"].get(code, 0.0) for h in history][-n:]
    m = max(max(vals), 0.01) if vals else 0.01
    return '<div class="fi-spark" title="Title chance, last races">' + "".join(f'<i style="height:{max(2, v / m * 26):.0f}px"></i>' for v in vals) + "</div>"


def contender_cards(p: dict, rows: list) -> str:
    leader_pts = p["standings"][0]["points"]
    cards = []
    for r in rows:
        tc = team_style(r["team"])["ui"]
        pts_pct = 100 * r["points"] / leader_pts if leader_pts else 0
        gap = "Leader" if r["pos"] == 1 else f"−{_pts(r['gap_leader'])} pts"
        cards.append(
            f'<div class="fi-c {"lead" if r["pos"] == 1 else ""}" style="--tc:{tc}"><div class="fi-ch">{avatar(r, True)}'
            f'<div class="who"><b>{html.escape(r["name"])}</b><span>P{r["pos"]} · {html.escape(r["team"])}</span></div>'
            f'<div class="fi-pr"><b>{fmt_prob(r["prob"], p.get("clinched") and r["pos"] == 1)}</b></div></div>'
            f'<div style="margin-top:8px">{trend_badge(r)}</div>'
            f'<div class="fi-bar"><div class="l"><span>Title chance (est.)</span><span>{fmt_prob(r["prob"])}</span></div>'
            f'<div class="t"><div class="f red" style="width:{max(1.5, r["prob"] * 100):.1f}%"></div></div></div>'
            f'<div class="fi-bar"><div class="l"><span>{_pts(r["points"])} pts</span><span>{gap}</span></div>'
            f'<div class="t"><div class="f" style="width:{pts_pct:.1f}%"></div></div></div>'
            f'<div class="fi-meta"><div class="fi-form">{_form_pills(r["form"])}</div>{_spark(p["history"], r["code"])}</div>'
            f'<div class="fi-meta"><span class="fi-note">Last 3 rounds: <b style="color:#fff">+{_pts(r["points_last3"])} pts</b></span>'
            f'<span class="fi-note">Max possible: {_pts(r["max_possible"])}</span></div></div>')
    return f'<div class="fi-cg">{"".join(cards)}</div>'


def mini_contenders(rows: list) -> str:
    out = []
    for r in rows:
        tc = team_style(r["team"])["ui"]
        out.append(f'<div class="fi-mini" style="--tc:{tc}"><div class="who">{r["pos"]}. {html.escape(r["name"])}</div>'
                   f'<div class="bar"><i style="width:{max(1.5, r["prob"] * 100):.1f}%"></i></div><div class="p">{fmt_prob(r["prob"])}</div></div>')
    return '<div class="fi-card">' + "".join(out) + "</div>"


# ============================================================================ podium (race predictor)
_PODIUM_CSS = FONT + """
*{box-sizing:border-box}body{margin:0;background:transparent;color:#ECEEF3;font-family:%FS%}
.top{display:flex;justify-content:center;align-items:flex-end;gap:14px;padding:6px 6px 0;height:400px}
.col{flex:0 1 240px;min-width:0;display:flex;flex-direction:column;justify-content:flex-end}
.stat{text-align:center;margin-bottom:6px}.win{font-weight:800;font-size:34px;letter-spacing:-.03em;line-height:1}
.lbl{font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:#8D93A5;font-weight:600;margin-top:3px}
.drv{font-weight:800;font-size:36px;letter-spacing:-.03em;text-align:center;line-height:1.05;margin-top:6px}
.tm{font-size:12px;color:#B7BBC9;text-align:center;margin:2px 0 8px}
.bar{height:0;border-radius:12px 12px 0 0;position:relative;overflow:hidden;background:var(--c);animation:grow 1s cubic-bezier(.2,.8,.2,1) forwards}
.bar:before{content:"";position:absolute;inset:0;background:linear-gradient(180deg,rgba(255,255,255,.16),rgba(0,0,0,.55))}
.bar b{position:absolute;left:0;right:0;bottom:4px;text-align:center;font-weight:800;font-size:84px;color:rgba(0,0,0,.4);z-index:1;line-height:1;letter-spacing:-.04em}
.chipline{display:flex;justify-content:center;flex-wrap:wrap;gap:4px 12px;font-size:12px;color:#B7BBC9;margin-top:8px}.chipline b{color:#fff}
@keyframes grow{to{height:var(--h)}}
.hd{margin:18px 4px 8px;font-weight:700;font-size:18px;letter-spacing:-.01em;display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:4px}
.hd small{font-weight:500;font-size:12px;color:#8D93A5}
.row{display:grid;grid-template-columns:30px 6px 52px minmax(80px,150px) 1fr 50px 160px;align-items:center;gap:10px;padding:8px 10px;border-bottom:1px solid #20232D;transition:background .2s}
.row:hover{background:#14171E}
.pos{font-weight:700;font-size:15px;color:#B7BBC9;text-align:right}.chip{width:5px;height:24px;background:var(--c);border-radius:3px}
.dn{font-weight:700;font-size:16px}.tn{font-size:12px;color:#8D93A5;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.track{height:9px;background:#1E212A;border-radius:99px;overflow:hidden}.fill{height:100%;width:0;background:var(--c);border-radius:99px;transition:width 1.1s cubic-bezier(.2,.8,.2,1)}
.val{font-weight:700;font-size:15px;text-align:right}.meta{font-size:11px;color:#8D93A5;text-align:right}
@media(max-width:640px){.row{grid-template-columns:24px 5px 46px 1fr 44px}.row .tn,.row .meta{display:none}.col{flex-basis:100px}.drv{font-size:24px}.win{font-size:24px}.bar b{font-size:56px}.top{gap:8px}}
""".replace("%FS%", FONT_STACK)


def podium_html(df, actual=False, caption="", show_rest=True) -> str:
    d = df.sort_values("exp_pos").reset_index(drop=True)
    heights = {0: 270, 1: 210, 2: 165}
    cols = []
    for i in (1, 0, 2):  # P2 | P1 | P3
        if i >= len(d):
            continue
        r = d.iloc[i]
        c = team_style(r["team"])["ui"]
        act = f'<span>Actual <b>P{int(r["finish_pos"])}</b></span>' if actual and "finish_pos" in d else ""
        cols.append(f'<div class="col" style="--c:{c};--h:{heights[i]}px"><div class="stat"><div class="win">{r["win_prob"] * 100:.0f}%</div>'
                    f'<div class="lbl">win chance</div></div><div class="drv">{html.escape(str(r["driver"]))}</div><div class="tm">{html.escape(str(r["team"]))}</div>'
                    f'<div class="bar"><b>{i + 1}</b></div><div class="chipline"><span>Podium <b>{r["podium_prob"] * 100:.0f}%</b></span>'
                    f'<span>Grid <b>P{int(r["grid"])}</b></span>{act}</div></div>')
    rows = []
    if show_rest:
        for i in range(3, len(d)):
            r = d.iloc[i]
            c = team_style(r["team"])["ui"]
            act = f" · Actual P{int(r['finish_pos'])}" if actual and "finish_pos" in d else ""
            rows.append(f'<div class="row" style="--c:{c}"><div class="pos">{i + 1}</div><div class="chip"></div><div class="dn">{html.escape(str(r["driver"]))}</div>'
                        f'<div class="tn">{html.escape(str(r["team"]))}</div><div class="track"><div class="fill" data-w="{r["top10_prob"] * 100:.0f}"></div></div>'
                        f'<div class="val">{r["top10_prob"] * 100:.0f}%</div><div class="meta">xP {r["exp_pos"]:.1f} · DNF {r["pred_dnf"] * 100:.0f}% · Grid {int(r["grid"])}{act}</div></div>')
    rest = ('<div class="hd"><span>Rest of the field</span><small>bar = chance of a points finish (top 10)</small></div>' + "".join(rows)) if rows else ""
    cap = f'<div class="hd"><span>{html.escape(caption)}</span><small>Monte Carlo · 5,000 simulated races</small></div>' if caption else ""
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>{_PODIUM_CSS}</style></head><body>{cap}<div class="top">{"".join(cols)}</div>{rest}'
            '<script>setTimeout(()=>document.querySelectorAll(".fill").forEach(e=>e.style.width=e.dataset.w+"%"),150)</script></body></html>')


def podium_height(n_drivers: int, show_rest=True, caption=True) -> int:
    return 440 + (30 if caption else 0) + (60 + 43 * max(0, n_drivers - 3) if show_rest else 0)


# ============================================================================ 2D circuit map
SECTOR_COLORS = ("#E10600", "#F5B301", "#2D9CFF")


def _bez(pts, i):
    n = len(pts)
    p0, p1, p2, p3 = pts[(i - 1) % n], pts[i % n], pts[(i + 1) % n], pts[(i + 2) % n]
    c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
    c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
    return f"C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}"


def _path(pts, a, b):
    """Smooth path from point a to point b (indices, b may be n for 'back to the start')."""
    return f"M{pts[a % len(pts)][0]:.1f},{pts[a % len(pts)][1]:.1f}" + "".join(_bez(pts, i) for i in range(a, b))


_TRACK2D = """<!doctype html><html><head><meta charset="utf-8"><style>%FONT%
*{box-sizing:border-box}html,body{margin:0;height:100%;background:transparent;font-family:%FS%;color:#ECEEF3}
.wrap{height:100%;display:flex;flex-direction:column;background:linear-gradient(180deg,#14161D,#0F1117);border:1px solid #262A35;border-radius:16px;overflow:hidden}
.top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;padding:16px 18px 6px;flex-wrap:wrap}
.t{font-weight:800;font-size:clamp(18px,3.4vw,26px);letter-spacing:-.02em;line-height:1.1}.s{color:#8D93A5;font-size:13px;margin-top:4px}
.seg{display:flex;background:#0B0C10;border:1px solid #262A35;border-radius:10px;padding:3px;gap:2px}
.seg button{background:transparent;color:#B7BBC9;border:0;border-radius:8px;padding:7px 12px;font:600 12px %FS%;cursor:pointer}
.seg button.on{background:#E10600;color:#fff}
.map{flex:1;min-height:0;padding:4px 10px 0}svg{width:100%;height:100%;display:block}
.casing{fill:none;stroke:#2A2E3B;stroke-width:17px;stroke-linecap:round;stroke-linejoin:round;vector-effect:non-scaling-stroke}
.body{fill:none;stroke:#EEF0F5;stroke-width:7px;stroke-linecap:round;stroke-linejoin:round;vector-effect:non-scaling-stroke}
.sec{stroke-width:7px}.spd{stroke-width:7px;stroke-linecap:butt}
@media(max-width:560px){.casing{stroke-width:12px}.body,.sec,.spd{stroke-width:5px}.sf-label{display:none}}
.lg{display:flex;flex-wrap:wrap;gap:6px 16px;padding:8px 18px 14px;font-size:12px;color:#8D93A5;align-items:center}
.lg i{display:inline-block;width:18px;height:6px;border-radius:3px;margin-right:6px;vertical-align:middle}
.grad{width:140px;height:6px;border-radius:3px;background:linear-gradient(90deg,hsl(238,90%,50%),hsl(160,90%,50%),hsl(80,90%,50%),hsl(0,90%,50%))}
</style></head><body><div class="wrap">
<div class="top"><div><div class="t">%TITLE%</div><div class="s">%SUB%</div></div><div class="seg" id="seg">%BTNS%</div></div>
<div class="map"><svg id="map" viewBox="0 0 %W% %H%" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Circuit map">
<g id="g-base"><path class="casing" d="%FULL%"/><path class="body" d="%FULL%"/></g>
<g id="g-sec" style="display:none"><path class="casing" d="%FULL%"/>%SECPATHS%</g>
<g id="g-spd" style="display:none"><path class="casing" d="%FULL%"/>%SPDPATHS%</g>
%MARKERS%
</svg></div><div class="lg" id="lg"></div></div>
<script>
(function(){
const svg=document.getElementById('map'),W0=%W%,H0=%H%,PAD=%PAD%,BW=W0-2*PAD,BH=H0-2*PAD;
function fit(){const cw=svg.clientWidth||600,ch=svg.clientHeight||400,m=cw>560?Math.min(112,cw*0.16):Math.min(68,cw*0.13);
 const k=Math.max(0.0001,Math.min((cw-2*m)/BW,(ch-2*m)/BH)),vw=cw/k,vh=ch/k;
 svg.setAttribute('viewBox',(PAD+BW/2-vw/2)+' '+(PAD+BH/2-vh/2)+' '+vw+' '+vh);
 document.querySelectorAll('.mk').forEach(g=>{g.setAttribute('transform','translate('+g.dataset.x+' '+g.dataset.y+') rotate('+(g.dataset.r||0)+') scale('+(1/k)+')');});}
const L={base:'<span><i style="background:#EEF0F5"></i>Racing surface</span><span>Numbered markers = turns</span><span>Chequered line = start / finish</span>',
 sectors:'<span><i style="background:%C1%"></i>Sector 1</span><span><i style="background:%C2%"></i>Sector 2</span><span><i style="background:%C3%"></i>Sector 3</span><span>Chequered line = start / finish</span>',
 speed:'<span>Slow</span><span class="grad"></span><span>Fast</span><span>Colour = speed on the fastest qualifying lap</span>'};
function mode(m){['base','sec','spd'].forEach(x=>{const g=document.getElementById('g-'+x);if(g)g.style.display=(x===(m==='sectors'?'sec':m==='speed'?'spd':'base'))?'':'none';});
 document.querySelectorAll('.seg button').forEach(b=>b.classList.toggle('on',b.dataset.m===m));
 document.querySelectorAll('.mk-sec').forEach(g=>g.style.display=(m==='sectors')?'':'none');
 document.getElementById('lg').innerHTML=L[m];}
document.querySelectorAll('.seg button').forEach(b=>b.addEventListener('click',()=>mode(b.dataset.m)));
mode('base');fit();addEventListener('resize',fit);
})();
</script></body></html>"""


def track2d_html(track: dict, title: str, subtitle: str = "") -> str:
    """Top-down 2D circuit map: smooth outline, turn numbers, start/finish line, sectors (when known), speed view."""
    xs, ys = track["x"], [-v for v in track["y"]]
    n = len(xs)
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    span = max(maxx - minx, maxy - miny) or 1.0
    S, pad = 880 / span, 90
    pts = [((x - minx) * S + pad, (y - miny) * S + pad) for x, y in zip(xs, ys)]
    W, H = (maxx - minx) * S + 2 * pad, (maxy - miny) * S + 2 * pad
    cx, cy = sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n

    def tangent(i):
        a, b = pts[(i - 1) % n], pts[(i + 1) % n]
        d = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
        return (b[0] - a[0]) / d, (b[1] - a[1]) / d

    def outward(i):
        tx, ty = tangent(i)
        nx, ny = -ty, tx
        return (nx, ny) if (nx * (pts[i][0] - cx) + ny * (pts[i][1] - cy)) >= 0 else (-nx, -ny)

    full = _path(pts, 0, n) + "Z"
    sectors = track.get("sectors")
    sec_paths, markers = "", []
    if sectors and 0 < sectors[0] < sectors[1] < n:
        b = [0, sectors[0], sectors[1], n]
        sec_paths = "".join(f'<path class="body sec" style="stroke:{SECTOR_COLORS[k]}" d="{_path(pts, b[k], b[k + 1])}"/>' for k in range(3))
        for k, idx in enumerate(sectors, start=2):
            ox, oy = (-v for v in outward(idx))  # inside the loop, so labels never collide with the outward turn numbers
            col = SECTOR_COLORS[k - 1]
            markers.append(f'<g class="mk mk-sec" data-x="{pts[idx][0]:.1f}" data-y="{pts[idx][1]:.1f}" data-r="0" style="display:none">'
                           f'<line x1="0" y1="0" x2="{ox * 22:.1f}" y2="{oy * 22:.1f}" stroke="{col}" stroke-width="2"/>'
                           f'<rect x="{ox * 36 - 15:.1f}" y="{oy * 36 - 9:.1f}" width="30" height="18" rx="5" fill="{col}"/>'
                           f'<text x="{ox * 36:.1f}" y="{oy * 36 + 4.5:.1f}" text-anchor="middle" font-size="11" font-weight="800" fill="#fff" font-family="Inter,Arial">S{k}</text></g>')
    spd = track.get("speed")
    spd_paths = ""
    if spd and len(spd) == n:
        lo, hi = min(spd), max(spd)
        spd_paths = "".join(f'<path class="body spd" style="stroke:hsl({238 * (1 - (spd[i] - lo) / max(1, hi - lo)):.0f},90%,52%)" d="M{pts[i][0]:.1f},{pts[i][1]:.1f}{_bez(pts, i)}"/>'
                            for i in range(n))

    for c in track.get("corners", []):  # turn numbers, offset away from the track
        cxm, cym = (c["x"] - minx) * S + pad, (-c["y"] - miny) * S + pad
        i = min(range(n), key=lambda j: (pts[j][0] - cxm) ** 2 + (pts[j][1] - cym) ** 2)
        ox, oy = outward(i)
        markers.append(f'<g class="mk" data-x="{pts[i][0]:.1f}" data-y="{pts[i][1]:.1f}"><line x1="0" y1="0" x2="{ox * 17:.1f}" y2="{oy * 17:.1f}" stroke="#6B7185" stroke-width="1"/>'
                       f'<circle cx="{ox * 26:.1f}" cy="{oy * 26:.1f}" r="11" fill="#0B0C10" stroke="#E10600" stroke-width="1.8"/>'
                       f'<text x="{ox * 26:.1f}" y="{oy * 26 + 4:.1f}" text-anchor="middle" font-size="11" font-weight="700" fill="#fff" font-family="Inter,Arial">{c["n"]}</text></g>')

    tx, ty = tangent(0)
    ox, oy = outward(0)
    ang = math.degrees(math.atan2(ty, tx))
    markers.append(f'<g class="mk" data-x="{pts[0][0]:.1f}" data-y="{pts[0][1]:.1f}" data-r="{ang:.1f}">'
                   f'<line x1="0" y1="-17" x2="0" y2="17" stroke="#fff" stroke-width="7"/><line x1="0" y1="-17" x2="0" y2="17" stroke="#0B0C10" stroke-width="7" stroke-dasharray="3.5 3.5"/>'
                   f'<path d="M14,-6 L26,0 L14,6 Z" fill="#E10600"/></g>')
    lab_x, lab_y = pts[0][0], pts[0][1]
    markers.append(f'<g class="mk sf-label" data-x="{lab_x:.1f}" data-y="{lab_y:.1f}"><rect x="{ox * 65 - 42:.1f}" y="{oy * 65 - 10:.1f}" width="84" height="20" rx="6" fill="#E10600"/>'
                   f'<text x="{ox * 65:.1f}" y="{oy * 65 + 3.5:.1f}" text-anchor="middle" font-size="9.5" font-weight="800" fill="#fff" font-family="Inter,Arial" letter-spacing=".3">START/FINISH</text></g>')

    btns = '<button data-m="base">Circuit</button>' + ('<button data-m="sectors">Sectors</button>' if sec_paths else "") + \
           ('<button data-m="speed">Speed</button>' if spd_paths else "")
    out = (_TRACK2D.replace("%FONT%", FONT).replace("%FS%", FONT_STACK).replace("%TITLE%", html.escape(title)).replace("%SUB%", html.escape(subtitle))
           .replace("%W%", f"{W:.0f}").replace("%H%", f"{H:.0f}").replace("%PAD%", str(pad)).replace("%FULL%", full).replace("%SECPATHS%", sec_paths)
           .replace("%SPDPATHS%", spd_paths).replace("%MARKERS%", "".join(markers)).replace("%BTNS%", btns)
           .replace("%C1%", SECTOR_COLORS[0]).replace("%C2%", SECTOR_COLORS[1]).replace("%C3%", SECTOR_COLORS[2]))
    return out

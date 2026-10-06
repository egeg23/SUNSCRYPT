"""Render brand/brandbook.html (the page the owner approves) from the generated assets."""
import base64
import os

HERE = os.path.dirname(os.path.abspath(__file__))
A = os.path.join(HERE, "assets")


def svg(name: str) -> str:
    s = open(os.path.join(A, name)).read()
    return s.split("?>")[-1]


def png64(name: str) -> str:
    return "data:image/png;base64," + base64.b64encode(open(os.path.join(A, name), "rb").read()).decode()


def sized(name: str, h: int) -> str:
    s = svg(name)
    s = s.replace('height="64"', f'height="{h}"', 1).replace('width="64"', f'width="{h}"', 1)
    return s


PALETTE = [
    ("Ночь", "--ink", "#0D1320", "Фон тёмной темы, текст на светлом", "#FFF3DE"),
    ("Солнце", "--solar", "#FFB21A", "Верх знака, акцент в тёмной теме", "#0D1320"),
    ("Вспышка", "--flare", "#FF5A36", "Низ знака, градиент", "#0D1320"),
    ("Рассвет", "--dawn", "#FFF3DE", "Текст на тёмном, тёплый фон", "#0D1320"),
    ("Сланец", "--slate", "#7D879A", "Вторичный текст, оси графиков", "#0D1320"),
    ("Рост", "--up", "#1F9D6B", "Прибыль, лонг (только данные)", "#FFFFFF"),
    ("Падение", "--down", "#D93F45", "Убыток, шорт (только данные)", "#FFFFFF"),
]

swatches = "".join(
    f'<div class="sw"><div class="chip" style="background:{hx};color:{tc}"><span>{name}</span></div>'
    f'<div class="meta"><code>{hx}</code><code class="tok">{tok}</code><p>{role}</p></div></div>'
    for name, tok, hx, role, tc in PALETTE
)

sizes = "".join(f'<figure>{sized("icon.svg", h)}<figcaption>{h} px</figcaption></figure>' for h in (16, 32, 64, 128))

html = f"""<title>SUNSCRYPT Brand</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Golos+Text:wght@400;500;600&family=JetBrains+Mono:wght@400;500&family=Unbounded:wght@500;700&display=swap" rel="stylesheet">
<style>
/* Layout: brand-book sheet, one column of plates; each plate shows an asset on the ground it is meant for. */
:root {{
  --ink:#0D1320; --solar:#FFB21A; --flare:#FF5A36; --dawn:#FFF3DE; --slate:#7D879A;
  --bg:#FBF8F2; --surface:#FFFFFF; --fg:#0D1320; --muted:#5B6475; --line:#E8E2D6;
  --display:"Unbounded", "Arial Black", system-ui, sans-serif;
  --body:"Golos Text", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono:"JetBrains Mono", ui-monospace, monospace;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg:#0B101B; --surface:#121A2A; --fg:#F3EDE2; --muted:#9AA3B4; --line:#222C3F; color-scheme:dark; }} }}
:root[data-theme="dark"] {{ --bg:#0B101B; --surface:#121A2A; --fg:#F3EDE2; --muted:#9AA3B4; --line:#222C3F; color-scheme:dark; }}
* {{ box-sizing:border-box; }}
body {{ background:var(--bg); color:var(--fg); font:16px/1.55 var(--body); margin:0; padding-inline:16px; padding-block:40px 72px; }}
main {{ max-width:1000px; margin:0 auto; display:grid; gap:56px; }}
h1,h2 {{ font-family:var(--display); margin:0; line-height:1.15; text-wrap:balance; }}
h1 {{ font-size:clamp(28px,4.5vw,44px); }}
h2 {{ font-size:22px; }}
section {{ display:grid; gap:18px; min-width:0; }}
.lede {{ color:var(--muted); max-width:62ch; margin:0; }}
.eyebrow {{ font:500 12px/1 var(--mono); letter-spacing:.1em; text-transform:uppercase; color:var(--muted); }}
.plates {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:16px; }}
.plate {{ border-radius:10px; padding:36px 28px; display:grid; place-items:center; min-height:180px; border:1px solid var(--line); }}
.plate.light {{ background:#FFF3DE; }} .plate.dark {{ background:#0D1320; border-color:#0D1320; }}
.plate svg {{ max-width:100%; height:auto; }}
.cap {{ font-size:13px; color:var(--muted); margin:6px 2px 0; }}
.sizes {{ display:flex; flex-wrap:wrap; align-items:flex-end; gap:28px; padding:24px; background:var(--surface); border:1px solid var(--line); border-radius:10px; }}
.sizes figure {{ margin:0; display:grid; gap:8px; justify-items:center; }}
.sizes figcaption {{ font:12px var(--mono); color:var(--muted); }}
.swatches {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:14px; }}
.sw {{ background:var(--surface); border:1px solid var(--line); border-radius:10px; overflow:hidden; }}
.chip {{ box-shadow:inset 0 0 0 1px var(--line); height:92px; display:flex; align-items:flex-end; padding:12px 14px; font:600 15px var(--body); }}
.meta {{ padding:12px 14px; display:grid; gap:2px; }}
.meta code {{ font:13px var(--mono); }} .meta .tok {{ color:var(--muted); }}
.meta p {{ margin:4px 0 0; font-size:13px; color:var(--muted); }}
.type {{ display:grid; gap:14px; }}
.spec {{ background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:20px 22px; display:grid; gap:6px; min-width:0; }}
.spec .name {{ font:500 12px var(--mono); color:var(--muted); letter-spacing:.06em; text-transform:uppercase; }}
.spec .d {{ font-family:var(--display); font-weight:700; font-size:clamp(24px,4vw,36px); line-height:1.15; }}
.spec .b {{ font-family:var(--body); font-size:17px; max-width:62ch; }}
.spec .m {{ font-family:var(--mono); font-size:15px; font-variant-numeric:tabular-nums; overflow-x:auto; }}
.tg {{ display:grid; grid-template-columns:minmax(0,260px) minmax(0,1fr); gap:20px; align-items:start; }}
@media (max-width:640px) {{ .tg {{ grid-template-columns:1fr; }} }}
.profile {{ background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:22px; display:grid; gap:10px; justify-items:center; text-align:center; }}
.profile img {{ width:120px; height:120px; border-radius:50%; }}
.profile b {{ font-family:var(--display); font-size:17px; }}
.profile span {{ font:13px var(--mono); color:var(--muted); }}
.profile p {{ margin:0; font-size:13px; color:var(--muted); }}
.chat {{ background:#17212B; border-radius:10px; padding:18px; display:grid; gap:10px; min-width:0; }}
.msg {{ background:#182533; color:#E9EEF3; border-radius:12px 12px 12px 4px; padding:10px 13px; font:14px/1.45 var(--body); max-width:440px; }}
.msg .t {{ display:block; text-align:right; font-size:11px; color:#7F91A4; margin-top:4px; }}
.msg .n {{ font-family:var(--mono); font-variant-numeric:tabular-nums; }}
ul.rules {{ margin:0; padding-left:1.2em; display:grid; gap:6px; max-width:70ch; }}
.ok {{ color:#1F9D6B; }} .no {{ color:#D93F45; }}
</style>
<main>
  <header style="display:grid;gap:14px">
    <span class="eyebrow">Бренд · версия 1 · на согласование</span>
    <h1>SUNSCRYPT</h1>
    <p class="lede">Знак — солнце над горизонтом, нижняя часть которого разрезана на полосы, как уровни цены на графике.
    Тёплое солнце на ночном небе: рынок, который открывается каждый день. Надпись набрана шрифтом Unbounded и переведена в кривые,
    поэтому логотип выглядит одинаково без установленных шрифтов.</p>
  </header>

  <section>
    <h2>Логотип</h2>
    <div class="plates">
      <div><div class="plate light">{svg("logo-light.svg")}</div><p class="cap">На светлом фоне · logo-light.svg</p></div>
      <div><div class="plate dark">{svg("logo-dark.svg")}</div><p class="cap">На тёмном фоне · logo-dark.svg</p></div>
    </div>
  </section>

  <section>
    <h2>Знак и иконка приложения</h2>
    <div class="sizes">{sizes}</div>
    <p class="cap">favicon 16 и 32 px, иконка приложения 180 и 512 px. Полосы остаются различимыми от 16 px.</p>
  </section>

  <section>
    <h2>Палитра</h2>
    <div class="swatches">{swatches}</div>
    <p class="cap">Зелёный и красный — только для данных: прибыль и убыток, лонг и шорт. В элементах интерфейса их не используем.</p>
  </section>

  <section class="type">
    <h2>Шрифты</h2>
    <div class="spec"><span class="name">Заголовки · Unbounded Bold</span><span class="d">Рост баланса за 30 дней</span></div>
    <div class="spec"><span class="name">Текст · Golos Text</span><span class="b">Подключите кабинет Bybit по API-ключу без права вывода. Начните на демо-счёте и смотрите каждую сделку в реальном времени.</span></div>
    <div class="spec"><span class="name">Цифры · JetBrains Mono</span><span class="m">BTCUSDT · 61 240.5 · +18.40 USDT · 56.3 %</span></div>
    <p class="cap">Все три шрифта поддерживают кириллицу и распространяются по лицензии OFL. На сайте они раздаются с нашего домена, без запросов к Google.</p>
  </section>

  <section>
    <h2>Telegram-бот</h2>
    <div class="tg">
      <div class="profile">
        <img src="{png64("telegram-avatar-640.png")}" alt="Аватар бота SUNSCRYPT">
        <b>SUNSCRYPT</b><span>@sunscrypt_bot</span>
        <p>Уведомления о сделках робота SUNSCRYPT на Bybit: сделки, дневной отчёт, тревоги и аварийная остановка.</p>
      </div>
      <div class="chat" aria-label="Пример сообщений бота">
        <div class="msg">Готово, бот привязан к кабинету. Режим: <b>ДЕМО</b>. Пришлю каждую сделку и вечерний отчёт в 21:00 по Москве. Остановить торговлю: /stop<span class="t">12:00</span></div>
        <div class="msg">🟢 ЛОНГ BTCUSDT · <span class="n">0.012</span> по <span class="n">61 240.5</span> · демо<span class="t">16:00</span></div>
        <div class="msg">⚪ Закрыто BTCUSDT · <span class="n">+18.40 USDT (+0.61%)</span><span class="t">23:58</span></div>
        <div class="msg">Отчёт за 07.10 · баланс <span class="n">10 184.20 USDT (+1.84%)</span> · сделок 9, успешных 56% · просадка <span class="n">−2.1%</span><span class="t">21:00</span></div>
      </div>
    </div>
    <p class="cap">Пример данных для показа вида сообщений. Тексты, команды и адреса — в brand/telegram.md.</p>
  </section>

  <section>
    <h2>Правила использования</h2>
    <ul class="rules">
      <li><span class="ok">Можно:</span> знак отдельно от надписи (иконки, аватар, favicon).</li>
      <li><span class="ok">Можно:</span> поле вокруг логотипа не меньше половины высоты знака.</li>
      <li><span class="no">Нельзя:</span> менять цвета градиента, поворачивать знак, растягивать надпись.</li>
      <li><span class="no">Нельзя:</span> ставить светлую версию на светлый фон и тёмную на тёмный.</li>
      <li>Минимальный размер: знак 16 px, логотип с надписью 24 px по высоте.</li>
    </ul>
  </section>
</main>
"""

with open(os.path.join(HERE, "brandbook.html"), "w") as f:
    f.write(html)
print("brand/brandbook.html written")

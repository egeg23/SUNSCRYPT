import type { Metadata } from "next";
import { Footer } from "@/components/Footer";
import { Header } from "@/components/Header";
import { bot, limits } from "@/brand/telegram";
import { fonts, palette } from "@/brand/tokens";
import s from "./brand.module.css";

export const metadata: Metadata = { title: "Бренд" };

/* eslint-disable @next/next/no-img-element -- SVG-логотипы показываем как есть */

function Counted({ label, text, max }: { label: string; text: string; max?: number }) {
  return (
    <div className={s.field}>
      <div className={s.label}>
        <span>{label}</span>
        {max ? (
          <span className="mono">
            {text.length} / {max}
          </span>
        ) : null}
      </div>
      <div className={s.text}>{text}</div>
    </div>
  );
}

export default function BrandPage() {
  return (
    <main className="wrap">
      <Header />
      <h1>Бренд SUNSCRYPT</h1>
      <p className="muted" style={{ maxWidth: 720 }}>
        Знак — солнце над горизонтом, лучи — биржевые свечи: зелёные (рост) и красные (падение). Тёплый янтарный акцент на
        глубоком ночном фоне: спокойно, без «казино». Ниже — логотип, цвета, шрифты, значки
        и всё для Telegram-бота. Все файлы можно скачать.
      </p>

      <section>
        <h2>Логотип</h2>
        <div className={s.logos}>
          <div className={`${s.plate} ${s.onDark}`}>
            <img src="/brand/logo-dark.svg" alt="SUNSCRYPT — на тёмном фоне" width={350} height={64} />
            <div className={s.links}>
              <a href="/brand/logo-dark.svg" download>logo-dark.svg</a>
              <a href="/brand/mark-dark.svg" download>mark-dark.svg</a>
              <a href="/brand/wordmark-dark.svg" download>wordmark-dark.svg</a>
            </div>
          </div>
          <div className={`${s.plate} ${s.onLight}`}>
            <img src="/brand/logo-light.svg" alt="SUNSCRYPT — на светлом фоне" width={350} height={64} />
            <div className={s.links}>
              <a href="/brand/logo-light.svg" download>logo-light.svg</a>
              <a href="/brand/mark-light.svg" download>mark-light.svg</a>
              <a href="/brand/wordmark-light.svg" download>wordmark-light.svg</a>
            </div>
          </div>
          <div className={`${s.plate} ${s.onDark}`} style={{ alignItems: "center" }}>
            <img src="/brand/mark-dark.svg" alt="Знак SUNSCRYPT" width={128} height={128} />
            <span style={{ fontSize: 13, opacity: 0.7 }}>
              Знак отдельно — для мелких мест и аватаров
            </span>
          </div>
        </div>
        <p className="muted" style={{ fontSize: 14, marginTop: 12 }}>
          Надпись — шрифт Unbounded SemiBold, переведена в кривые: выглядит одинаково везде.
          Поле вокруг логотипа — не меньше высоты знака на четверть.
        </p>
      </section>

      <section>
        <h2>Палитра</h2>
        {palette.map((g) => (
          <div key={g.group}>
            <h3>{g.group}</h3>
            <div className={s.swatches}>
              {g.swatches.map((c) => (
                <div className={s.swatch} key={c.name}>
                  <div
                    className={s.chip}
                    style={{ background: c.hex, color: c.dark ? "#fff" : "#14171c" }}
                  >
                    {c.hex}
                  </div>
                  <div className={s.swatchBody}>
                    <b>{c.name}</b>
                    <div className="muted">{c.role}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
        <p className="muted" style={{ fontSize: 14 }}>
          Рост и убыток — не единственный признак: рядом всегда знак «+/−» и число, чтобы
          цифры читались и без различения цветов.
        </p>
      </section>

      <section>
        <h2>Шрифты</h2>
        <p className="muted" style={{ fontSize: 14 }}>
          Все три — с кириллицей, открытая лицензия (SIL OFL), лежат на нашем сервере, без
          внешних сервисов.
        </p>
        {fonts.map((f) => (
          <div className={s.fontRow} key={f.name}>
            <div className={s.label}>
              <span>
                {f.name} — {f.role}
              </span>
            </div>
            <div className={s.fontSample} style={{ fontFamily: f.family, fontWeight: f.weight }}>
              {f.sample}
            </div>
            <div className="muted" style={{ fontFamily: f.family, fontSize: 14 }}>
              АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ abcdefghijklmnopqrstuvwxyz 0123456789 ₽ $ % +−
            </div>
          </div>
        ))}
      </section>

      <section>
        <h2>Значки</h2>
        <div className={s.icons}>
          <figure>
            <img src="/icon.svg" alt="" width={16} height={16} />
            <figcaption>16 px</figcaption>
          </figure>
          <figure>
            <img src="/icon.svg" alt="" width={32} height={32} />
            <figcaption>32 px</figcaption>
          </figure>
          <figure>
            <img src="/icon.svg" alt="" width={64} height={64} />
            <figcaption>favicon, SVG</figcaption>
          </figure>
          <figure>
            <img src="/apple-icon.png" alt="" width={90} height={90} style={{ borderRadius: 20 }} />
            <figcaption>iPhone, 180 px</figcaption>
          </figure>
        </div>
      </section>

      <section>
        <h2>Telegram-бот</h2>
        <p className="muted" style={{ fontSize: 14, maxWidth: 720 }}>
          Бот создан: @SUNSCRYPT_tradebot. В @BotFather: /setuserpic — аватар,
          /setabouttext и /setdescription — тексты ниже, /setcommands — список команд. Токен
          бота в чат не присылайте: заведите его секретом репозитория
          <code> SUNSCRYPT_TELEGRAM_TOKEN</code> (Settings → Secrets and variables → Actions).
        </p>
        <div className={`card ${s.tg}`}>
          <div>
            <img className={s.avatar} src="/brand/telegram-avatar-640.png" alt="Аватар бота" width={160} height={160} />
            <p style={{ marginTop: 10 }}>
              <a href="/brand/telegram-avatar-640.png" download>
                Аватар 640×640, PNG
              </a>
            </p>
          </div>
          <div>
            <Counted label="Имя" text={bot.name} max={limits.name} />
            <div className={s.field}>
              <div className={s.label}>
                <span>Адрес бота</span>
              </div>
              <div className={s.handles}>
                {bot.handles.map((h) => (
                  <span className="pill mono" key={h}>
                    {h}
                  </span>
                ))}
              </div>
            </div>
            <Counted label="About — короткое описание в профиле" text={bot.about} max={limits.about} />
            <Counted
              label="Description — текст в пустом чате до «Start»"
              text={bot.description}
              max={limits.description}
            />
            <Counted label="Приветствие на /start" text={bot.greeting} />
            <Counted
              label="Команды для /setcommands"
              text={bot.commands.map(([c, d]) => `${c} - ${d}`).join("\n")}
            />
          </div>
        </div>
      </section>

      <section>
        <h2>Как мы говорим</h2>
        <ul className={s.rules}>
          <li>Честно и цифрами: результат — после комиссий и фандинга, рядом — риск.</li>
          <li>Никаких обещаний прибыли и слов «гарантированно», «пассивный доход», «x10».</li>
          <li>Демо — по умолчанию; реальный счёт — только отдельным решением.</li>
          <li>Просто, по-русски, без жаргона там, где можно без него.</li>
        </ul>
      </section>

      <Footer />
    </main>
  );
}

// Палитра SUNSCRYPT. Те же значения — в globals.css (переменные --sun-*,
// --night-*, …); меняя цвет, менять в обоих местах.
export type Swatch = { name: string; hex: string; role: string; dark?: boolean };

export const palette: { group: string; swatches: Swatch[] }[] = [
  {
    group: "Солнце — акцент",
    swatches: [
      { name: "Sun 300", hex: "#FFC861", role: "подсветка, графики на тёмном" },
      { name: "Sun 500", hex: "#F5A524", role: "акцент и знак на тёмном фоне" },
      { name: "Sun 700", hex: "#D97A00", role: "акцент и знак на светлом фоне", dark: true },
    ],
  },
  {
    group: "Ночь — тёмная тема",
    swatches: [
      { name: "Night 950", hex: "#0B0D10", role: "фон", dark: true },
      { name: "Night 900", hex: "#12161C", role: "карточки", dark: true },
      { name: "Night 800", hex: "#1B2129", role: "вторичный фон", dark: true },
      { name: "Night 700", hex: "#2A323D", role: "линии и рамки", dark: true },
    ],
  },
  {
    group: "Бумага — светлая тема",
    swatches: [
      { name: "Paper 50", hex: "#FAF7F0", role: "фон" },
      { name: "Paper 100", hex: "#F1ECE1", role: "вторичный фон" },
      { name: "Paper 200", hex: "#E2DBCC", role: "линии и рамки" },
      { name: "Ink 900", hex: "#14171C", role: "текст", dark: true },
    ],
  },
  {
    group: "Смысловые",
    swatches: [
      { name: "Рост", hex: "#2BB673", role: "прибыльная сделка, рост", dark: true },
      { name: "Убыток", hex: "#E5484D", role: "убыток, тревога", dark: true },
      { name: "Инфо", hex: "#4C8DFF", role: "нейтральные события", dark: true },
    ],
  },
];

export const fonts = [
  {
    name: "Unbounded",
    role: "Заголовки и надпись логотипа",
    family: "var(--font-display)",
    sample: "Солнце встаёт над рынком",
    weight: 600,
  },
  {
    name: "Manrope",
    role: "Основной текст интерфейса",
    family: "var(--font-text)",
    sample:
      "Подключите кабинет Bybit по ключу без права вывода. Демо-счёт — по умолчанию; реальный включается только отдельно.",
    weight: 400,
  },
  {
    name: "JetBrains Mono",
    role: "Цифры: баланс, цены, проценты",
    family: "var(--font-mono)",
    sample: "Баланс 10 000,00 USDT · сделок 128 · успешных 51,6 % · комиссии −84,12",
    weight: 400,
  },
];

// Сквозной тест этапа 2 в настоящем браузере на поднятом стеке Compose.
// Доступ закрытый: владелец входит и включает 2FA → создаёт приглашение →
// приглашённый регистрируется по ссылке, включает 2FA, выходит и входит с
// кодом → владелец выдаёт ссылку сброса пароля → новый пароль работает.
//
//   node e2e/auth.mjs http://localhost:3471 <почта владельца> <пароль владельца>
import { createHmac } from "node:crypto";
import { chromium } from "playwright";

const [, , BASE, OWNER_EMAIL, OWNER_PASSWORD] = process.argv;
const email = `e2e-${Date.now()}@example.com`;
const password = "e2e long password 1";
const GOOD_KEY = "GOODe2eK3y987654";
const GOOD_SECRET = "e2eS3cr3tAbCdEf0123456";

// Ссылки сервис строит на свой публичный адрес — в тесте открываем их на BASE.
const local = (link) => BASE + new URL(link).pathname + new URL(link).search;

function totp(secret, at = Date.now()) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const c of secret.replace(/=+$/, "")) bits += alphabet.indexOf(c).toString(2).padStart(5, "0");
  const key = Buffer.from(bits.match(/.{8}/g).map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(at / 1000 / 30)));
  const h = createHmac("sha1", key).update(counter).digest();
  const o = h[h.length - 1] & 15;
  return String((h.readUInt32BE(o) & 0x7fffffff) % 1e6).padStart(6, "0");
}

const step = (s) => console.log(`▸ ${s}`);
const browser = await chromium.launch();
const ctx = await browser.newContext({ permissions: ["clipboard-read", "clipboard-write"] });
const page = await ctx.newPage();
page.setDefaultTimeout(15000);

async function login(who, pass) {
  await page.goto(`${BASE}/login`);
  await page.fill('input[name="email"]', who);
  await page.fill('input[name="password"]', pass);
  await page.click("button.btn >> text=Войти");
}

async function enable2fa() {
  await page.click("text=Включить 2FA");
  const secret = (await page.locator("code").first().textContent()).trim();
  await page.fill('input[name="code"]', await freshCode(secret));
  await page.click("text=Подтвердить и включить");
  await page.getByText("Включена.").waitFor();
  return secret;
}

// Сервер принимает код шага ±1 от текущего и каждый шаг — один раз.
const lastStep = new Map();
const nowStep = () => Math.floor(Date.now() / 30000);

async function freshCode(secret) {
  const step = Math.max(nowStep(), (lastStep.get(secret) ?? -1) + 1);
  while (nowStep() < step - 1) await page.waitForTimeout(1000);
  lastStep.set(secret, step);
  return totp(secret, step * 30000);
}

async function codeStep(secret) {
  await page.locator('input[name="code"]').waitFor();
  await page.fill('input[name="code"]', await freshCode(secret));
  await page.click("button.btn >> text=Подтвердить");
  await page.waitForURL(`${BASE}/account`);
}

async function logout() {
  await page.goto(`${BASE}/account`);
  await page.click("text=Выйти");
  await page.waitForURL(`${BASE}/login`);
}

try {
  step("владелец: вход и включение 2FA");
  await login(OWNER_EMAIL, OWNER_PASSWORD);
  await page.waitForURL(`${BASE}/account`);
  const ownerSecret = await enable2fa();

  step("владелец: приглашение");
  await page.goto(`${BASE}/admin`);
  await page.fill('input[name="note"]', "e2e");
  await page.click("text=Создать приглашение");
  const inviteLink = (await page.locator("code").first().textContent()).trim();
  await logout();

  step("без приглашения регистрации нет");
  await page.goto(`${BASE}/invite?token=nonexistent-token`);
  await page.fill('input[name="email"]', email);
  await page.fill('input[name="password"]', password);
  await page.check('input[type="checkbox"]');
  await page.click("text=Создать аккаунт");
  await page.getByText("Приглашение недействительно").waitFor();

  step("регистрация по приглашению");
  await page.goto(local(inviteLink));
  await page.fill('input[name="email"]', email);
  await page.fill('input[name="password"]', password);
  await page.check('input[type="checkbox"]');
  await page.click("text=Создать аккаунт");
  await page.waitForURL(`${BASE}/account`);

  step("включение 2FA, выход и вход с кодом");
  const secret = await enable2fa();
  await logout();
  await login(email, password);
  await codeStep(secret);
  await page.getByText("Код 2FA").first().waitFor();

  step("не владелец в раздел владельца не попадает");
  await page.goto(`${BASE}/admin`);
  await page.getByText("Только для владельца").waitFor();
  await logout();

  step("владелец выдаёт ссылку сброса пароля");
  await login(OWNER_EMAIL, OWNER_PASSWORD);
  await codeStep(ownerSecret);
  await page.goto(`${BASE}/admin`);
  await page.locator("tr", { hasText: email }).locator("text=Ссылка сброса пароля").click();
  const resetLink = (await page.locator("code").first().textContent()).trim();
  await logout();

  step("сброс пароля и вход с новым");
  await page.goto(local(resetLink));
  await page.fill('input[name="password"]', "new e2e password 2");
  await page.fill('input[name="password2"]', "new e2e password 2");
  await page.click("text=Сохранить");
  await page.getByText("Пароль изменён").waitFor();
  await login(email, "new e2e password 2");
  await codeStep(secret);

  step("кабинет Bybit: ключ с правом вывода отклоняется");
  await page.goto(`${BASE}/accounts`);
  await page.click("text=Добавить кабинет");
  await page.click("text=Демо-счёт · рекомендуем");
  await page.getByText("109.73.198.185").first().waitFor();
  await page.fill('input[name="api_key"]', "WITHDRAWk3y123456");
  await page.fill('input[name="api_secret"]', "s3cr3tWithdraw123456");
  await page.click("text=Проверить и подключить");
  await page.getByText("переводы и вывод").waitFor();

  step("кабинет Bybit: демо-ключ проходит, ключ не виден");
  await page.fill('input[name="api_key"]', GOOD_KEY);
  await page.fill('input[name="api_secret"]', GOOD_SECRET);
  await page.click("text=Проверить и подключить");
  await page.getByText("Ключ в порядке").waitFor();
  await page.getByText(`••••${GOOD_KEY.slice(-4)}`).waitFor();
  const html = await page.content();
  if (html.includes(GOOD_KEY) || html.includes(GOOD_SECRET)) throw new Error("ключ виден на странице");

  step("кабинет Bybit: остановка и удаление");
  await page.click("text=Аварийная остановка");
  await page.getByText("Остановлен вручную").waitFor();
  page.once("dialog", (d) => d.accept());
  await page.click("text=Удалить");
  await page.getByText("Кабинетов пока нет").waitFor();

  console.log("✓ e2e: закрытый доступ, 2FA, сброс пароля и кабинеты Bybit работают");
} catch (e) {
  await page.screenshot({ path: "e2e-failure.png", fullPage: true }).catch(() => {});
  console.error("✗ e2e:", e.message);
  process.exitCode = 1;
} finally {
  await browser.close();
}

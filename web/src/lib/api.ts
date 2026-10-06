// Запросы к API того же сайта. Cookie сессии — httpOnly, браузер шлёт её сам.
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    // Разбор ключа Bybit: что не так и о чём предупредить.
    public problems: string[] = [],
    public warnings: string[] = [],
  ) {
    super(message);
  }
}

function detail(body: unknown, status: number): string {
  const d = (body as { detail?: unknown } | null)?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    // Ошибки проверки полей от FastAPI.
    const f = d[0] as { loc?: string[]; type?: string } | undefined;
    const field = f?.loc?.at(-1);
    if (field === "password") return "Пароль — не короче 10 символов";
    if (field === "email") return "Проверьте адрес почты";
    if (field === "code") return "Код — 6 цифр";
    if (field === "api_key" || field === "api_secret")
      return "Ключ и секрет — только латинские буквы и цифры, без пробелов";
    return "Проверьте введённые данные";
  }
  if (status === 429) return "Слишком много попыток. Подождите и попробуйте снова.";
  return "Что-то пошло не так. Попробуйте ещё раз.";
}

export async function api<T = Record<string, unknown>>(
  path: string,
  body?: unknown,
): Promise<T> {
  const r = await fetch(`/api${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
    credentials: "same-origin",
  });
  const data = await r.json().catch(() => null);
  if (!r.ok) {
    const d = (data as { detail?: { problems?: string[]; warnings?: string[] } } | null)?.detail;
    if (d && typeof d === "object" && !Array.isArray(d) && d.problems) {
      throw new ApiError(r.status, d.problems[0] ?? "Ошибка", d.problems, d.warnings ?? []);
    }
    throw new ApiError(r.status, detail(data, r.status));
  }
  return data as T;
}

export type Me = {
  email: string;
  totp_enabled: boolean;
  mfa_passed: boolean;
  is_admin: boolean;
};

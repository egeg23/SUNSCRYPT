"use client";

import { useState } from "react";
import { ApiError } from "@/lib/api";

/** Состояние отправки формы: занято, ошибка. */
export function useSubmit() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Нет связи с сервером. Попробуйте ещё раз.");
    } finally {
      setBusy(false);
    }
  }
  return { busy, error, run, setError };
}

export function tokenFromUrl(): string {
  if (typeof window === "undefined") return "";
  return new URLSearchParams(window.location.search).get("token") ?? "";
}

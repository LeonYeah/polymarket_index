export type ApiResult<T> = {
  data: T | null;
  error: string | null;
};

const API_BASE_URL =
  process.env.API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export function apiUrl(path: string) {
  return `${API_BASE_URL}${path}`;
}

export async function getJson<T>(path: string): Promise<ApiResult<T>> {
  try {
    const response = await fetch(apiUrl(path), {
      cache: "no-store",
      headers: { accept: "application/json" },
    });
    if (!response.ok) {
      return { data: null, error: `${response.status} ${response.statusText}` };
    }
    return { data: (await response.json()) as T, error: null };
  } catch (error) {
    return { data: null, error: error instanceof Error ? error.message : "request failed" };
  }
}

export function money(value: unknown) {
  const number = Number(value ?? 0);
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 0,
    style: "currency",
    currency: "USD",
  }).format(number);
}

export function decimal(value: unknown, digits = 2) {
  const number = Number(value ?? 0);
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(number);
}

export function pct(value: unknown, digits = 1) {
  if (value === null || value === undefined || value === "") {
    return "n/a";
  }
  return `${decimal(Number(value) * 100, digits)}%`;
}

export function shortId(value: unknown, left = 6, right = 4) {
  const text = String(value ?? "");
  if (text.length <= left + right + 3) {
    return text;
  }
  return `${text.slice(0, left)}...${text.slice(-right)}`;
}

export function isoDate(value: unknown) {
  if (!value) {
    return "n/a";
  }
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toISOString().replace(".000Z", "Z");
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

export class ApiError extends Error {
  status: number;
  code: string | null;
  constructor(status: number, code: string | null, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

async function parseError(path: string, res: Response): Promise<ApiError> {
  let code: string | null = null;
  let message: string = res.statusText;
  try {
    const json = await res.json();
    if (json?.detail && typeof json.detail === "object") {
      code = json.detail.code ?? null;
      message = json.detail.message ?? message;
    } else if (typeof json?.detail === "string") {
      message = json.detail;
    }
  } catch {
    /* non-JSON body */
  }
  return new ApiError(res.status, code, `${path} → ${res.status}: ${message}`);
}

export async function apiPost<T>(
  path: string,
  body: object,
  token: string,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await parseError(path, res);
  return res.json() as T;
}

export async function apiFetch<T>(path: string, token: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw await parseError(path, res);
  return res.json() as T;
}

export async function apiPatch<T>(
  path: string,
  body: object,
  token: string,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await parseError(path, res);
  return res.json() as T;
}

export async function apiDelete(path: string, token: string): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw await parseError(path, res);
}

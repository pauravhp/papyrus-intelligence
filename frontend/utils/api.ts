const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const json = await res.json();
      detail = json.detail ?? detail;
    } catch {
      /* non-JSON body */
    }
    throw new Error(`${path} → ${res.status}: ${detail}`);
  }
  return res.json() as T;
}

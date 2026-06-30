import { createClient } from "@/lib/supabase/server";

const API = process.env.OBSERVER_API_URL ?? "http://localhost:8090";

export async function apiFetch<T>(path: string): Promise<T> {
  const supabase = await createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const res = await fetch(`${API}${path}`, {
    headers: session ? { Authorization: `Bearer ${session.access_token}` } : {},
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`observer-api ${path}: ${res.status}`);
  return res.json() as Promise<T>;
}

export function roleFromSession(accessToken: string): string {
  try {
    const payload = JSON.parse(Buffer.from(accessToken.split(".")[1], "base64url").toString());
    return typeof payload.user_role === "string" ? payload.user_role : "viewer";
  } catch {
    return "viewer";
  }
}

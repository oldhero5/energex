/**
 * Same-origin proxy to observer-api for client-side components.
 *
 * Design notes:
 * - Only proxies GET requests; only ever calls observer-api via `apiFetch` (never
 *   a caller-supplied host) — not an open proxy to arbitrary URLs.
 * - Requires an authenticated session: apiFetch resolves the Supabase bearer and
 *   throws on 401/403. A missing/invalid session returns 401 to the browser.
 * - Maps apiFetch error status codes back to the response (parses ": NNN" from the
 *   thrown message; defaults to 502 for unknown upstream errors).
 */

import type { NextRequest } from "next/server";
import { apiFetch } from "@/lib/api";

function parseStatus(msg: string): number {
  const m = msg.match(/:\s*([45]\d{2})/);
  if (m) return Number(m[1]);
  return 502;
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  const apiPath = "/" + path.join("/");

  // Forward the incoming query string to observer-api
  const qs = request.nextUrl.search; // e.g. "?as_of=2026-06-02T00:00:00Z" or ""
  const fullPath = `${apiPath}${qs}`;

  let data: unknown;
  try {
    data = await apiFetch<unknown>(fullPath);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    const status = parseStatus(msg);
    // Surface auth errors as 401 so the browser can redirect to /login
    return new Response(JSON.stringify({ error: msg }), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  }

  return Response.json(data);
}

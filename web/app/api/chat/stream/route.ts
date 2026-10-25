export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function POST(req: Request) {
  const base = process.env.PY_SERVER_URL || "http://127.0.0.1:8001";
  try {
    const body = await req.json();
    const upstream = await fetch(`${base}/api/v1/chat/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify(body),
      cache: "no-store",
      signal: req.signal,
    });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type":
          upstream.headers.get("Content-Type") || "application/json",
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
      },
    });
  } catch {
    return Response.json(
      {
        error: "Couldn’t reach the server. Check the connection and try again.",
      },
      { status: 502 },
    );
  }
}

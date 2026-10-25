export const runtime = "nodejs";
export const dynamic = "force-dynamic";
async function forward(
  req: Request,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const base = process.env.PY_SERVER_URL || "http://127.0.0.1:8001";
  const parts = (await params).path.map(encodeURIComponent).join("/");
  try {
    const response = await fetch(
      `${base}/api/v1/routing/${parts}${new URL(req.url).search}`,
      {
        method: req.method,
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        ...(req.method === "POST" ? { body: await req.text() } : {}),
      },
    );
    return new Response(await response.text(), {
      status: response.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    return Response.json(
      { error: "Backend unavailable. Start the Python server on port 8001." },
      { status: 502 },
    );
  }
}
export const GET = forward;
export const POST = forward;

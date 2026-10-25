import type { Activity, Trace } from "@/components/routing/types";

/** SSE frames can span any network chunk boundary, including a multibyte character. */
export async function readChatStream(
  response: Response,
  requestId: string,
  onActivity: (event: Activity) => void,
): Promise<Trace> {
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.error || error.detail || `Request failed (${response.status}).`,
    );
  }
  if (!response.body) throw new Error("The server returned an empty response.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: Trace | null = null;
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer = (buffer + decoder.decode(value, { stream: !done })).replace(
        /\r\n/g,
        "\n",
      );
      let boundary: number;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const kind = frame
          .split("\n")
          .find((line) => line.startsWith("event:"))
          ?.slice(6)
          .trim();
        const payload = frame
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trimStart())
          .join("\n");
        if (!payload) continue;
        const data = JSON.parse(payload);
        if (data.request_id !== requestId)
          throw new Error(
            "The response belonged to a different request. Reload this chat.",
          );
        if (kind === "activity") onActivity(data);
        if (kind === "error") throw new Error(data.message);
        if (kind === "result") result = data;
      }
      if (done) break;
    }
  } finally {
    reader.releaseLock();
  }
  if (!result)
    throw new Error(
      "The connection closed before the result arrived. Reload this chat to check its saved outcome.",
    );
  return result;
}

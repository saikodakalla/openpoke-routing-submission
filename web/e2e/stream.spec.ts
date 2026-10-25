import { test, expect } from "@playwright/test";
import { readChatStream } from "../lib/chat-stream";

test("SSE parsing tolerates fragmented UTF-8 and never mistakes an old request for completion", async () => {
  const id = "request-current";
  const event = {
    request_id: id,
    label: "Searching task memory…",
    kind: "vector",
    status: "started",
  };
  const trace = { request_id: id, response: "Finished" };
  const bytes = new TextEncoder().encode(
    `event: activity\ndata: ${JSON.stringify(event)}\n\nevent: result\ndata: ${JSON.stringify(trace)}\n\n`.replace(
      /\n/g,
      "\r\n",
    ),
  );
  const body = new ReadableStream({
    start(controller) {
      for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
      controller.close();
    },
  });
  const activity: unknown[] = [];
  expect(
    await readChatStream(new Response(body), id, (event) =>
      activity.push(event),
    ),
  ).toEqual(trace);
  expect(activity).toEqual([event]);
  await expect(
    readChatStream(
      new Response(`event: result\ndata: {"request_id":"older-request"}\n\n`),
      id,
      () => {},
    ),
  ).rejects.toThrow("different request");
});

test("an interrupted stream preserves an explicit error instead of claiming completion", async () => {
  await expect(
    readChatStream(
      new Response('event: ready\ndata: {"request_id":"request-test"}\n\n'),
      "request-test",
      () => {},
    ),
  ).rejects.toThrow("connection closed");
});

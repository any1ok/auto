import { describe, expect, it } from "vitest";
import { AgentApiClient } from "./apiClient";

describe("AgentApiClient", () => {
  it("normalizes trailing slashes when building requests", async () => {
    const originalFetch = globalThis.fetch;
    let requestedUrl = "";
    globalThis.fetch = (async (url: RequestInfo | URL) => {
      requestedUrl = String(url);
      return new Response(JSON.stringify({ device: { id: "1" } }), { status: 200 });
    }) as typeof fetch;

    await new AgentApiClient("http://localhost:3000/", "token").heartbeat();
    globalThis.fetch = originalFetch;

    expect(requestedUrl).toBe("http://localhost:3000/api/agent/heartbeat");
  });
});


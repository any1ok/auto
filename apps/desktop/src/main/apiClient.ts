import type { AgentDevice, AgentJob, ClaimJobResponse, PairResponse, SendResultPayload } from "@autosend/shared";

export class AgentApiClient {
  constructor(
    private readonly serverUrl: string,
    private readonly token?: string | null
  ) {}

  async pair(input: { pairingCode: string; name: string; platform: string }): Promise<PairResponse> {
    return this.request<PairResponse>("/api/agent/pair", {
      method: "POST",
      body: JSON.stringify(input)
    });
  }

  async heartbeat(): Promise<AgentDevice> {
    const payload = await this.request<{ device: AgentDevice }>("/api/agent/heartbeat", { method: "POST" });
    return payload.device;
  }

  async claimJob(): Promise<AgentJob | null> {
    const payload = await this.request<ClaimJobResponse>("/api/agent/jobs/claim", { method: "POST" });
    return payload.job;
  }

  async sendResult(payload: SendResultPayload): Promise<void> {
    await this.request("/api/agent/jobs/result", {
      method: "POST",
      body: JSON.stringify(payload)
    });
  }

  private async request<T>(path: string, init: RequestInit): Promise<T> {
    const url = `${this.serverUrl.replace(/\/$/, "")}${path}`;
    const headers = new Headers(init.headers);
    headers.set("content-type", "application/json");
    if (this.token) headers.set("authorization", `Bearer ${this.token}`);

    const response = await fetch(url, { ...init, headers });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(typeof body.error === "string" ? body.error : `요청 실패: ${response.status}`);
    }
    return body as T;
  }
}


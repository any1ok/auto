import type { AgentDevice, AgentJob, SendResultPayload } from "@autosend/shared";

export type { SendResultPayload } from "@autosend/shared";

export type StoredConfig = {
  serverUrl: string;
  token: string | null;
  device: AgentDevice | null;
};

export type PairInput = {
  serverUrl: string;
  pairingCode: string;
  name: string;
  platform: string;
};

export type AutomationInput = {
  job: AgentJob;
  dryRun: boolean;
};

export type AutomationResult = {
  ok: boolean;
  dryRun: boolean;
  sent: boolean;
  room: string;
  message?: string;
  error?: string;
  steps?: string[];
};

export type AutomationPermissionStatus = {
  ok: boolean;
  platform: string;
  accessibility: boolean;
  screenRecording: boolean | null;
  automation: boolean | null;
  required: string[];
  optional: string[];
  requested: string[];
  message: string;
};

export type AutosendApi = {
  getConfig: () => Promise<StoredConfig>;
  saveConfig: (config: Partial<StoredConfig>) => Promise<StoredConfig>;
  pair: (input: PairInput) => Promise<StoredConfig>;
  heartbeat: () => Promise<AgentDevice>;
  claimJob: () => Promise<AgentJob | null>;
  sendResult: (payload: SendResultPayload) => Promise<void>;
  checkPermissions: () => Promise<AutomationPermissionStatus>;
  requestPermissions: (includeScreenRecording?: boolean) => Promise<AutomationPermissionStatus>;
  openPermissionSettings: (kind: "accessibility" | "screenRecording" | "automation") => Promise<void>;
  runAutomation: (input: AutomationInput) => Promise<AutomationResult>;
};

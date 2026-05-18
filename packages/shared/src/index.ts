export const JOB_STATUSES = ["DRAFT", "QUEUED", "LOCKED", "SENT", "FAILED", "CANCELLED"] as const;
export const DEVICE_STATUSES = ["PAIRING", "ONLINE", "OFFLINE", "REVOKED"] as const;
export const SEND_LOG_STATUSES = ["SENT", "FAILED"] as const;

export type JobStatus = (typeof JOB_STATUSES)[number];
export type DeviceStatus = (typeof DEVICE_STATUSES)[number];
export type SendLogStatus = (typeof SEND_LOG_STATUSES)[number];

export const jobStatusLabels: Record<JobStatus, string> = {
  DRAFT: "임시",
  QUEUED: "대기",
  LOCKED: "처리 중",
  SENT: "발송 완료",
  FAILED: "실패",
  CANCELLED: "취소"
};

export const deviceStatusLabels: Record<DeviceStatus, string> = {
  PAIRING: "페어링 대기",
  ONLINE: "온라인",
  OFFLINE: "오프라인",
  REVOKED: "해제됨"
};

export type AgentDevice = {
  id: string;
  name: string;
  platform: string | null;
  status: DeviceStatus;
  lastSeenAt: string | null;
};

export type AgentJob = {
  id: string;
  recipientName: string;
  phone: string | null;
  kakaoRoomName: string;
  message: string;
  scheduledAt: string;
  attempts: number;
};

export type PairResponse = {
  token: string;
  device: AgentDevice;
};

export type ClaimJobResponse = {
  job: AgentJob | null;
};

export type SendResultPayload = {
  jobId: string;
  status: "SENT" | "FAILED";
  message?: string;
  screenshotPath?: string;
};


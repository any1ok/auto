import { contextBridge, ipcRenderer } from "electron";
import type { AutomationInput, PairInput, SendResultPayload, StoredConfig } from "../main/types";

contextBridge.exposeInMainWorld("autosend", {
  getConfig: () => ipcRenderer.invoke("config:get"),
  saveConfig: (config: Partial<StoredConfig>) => ipcRenderer.invoke("config:save", config),
  pair: (input: PairInput) => ipcRenderer.invoke("agent:pair", input),
  heartbeat: () => ipcRenderer.invoke("agent:heartbeat"),
  claimJob: () => ipcRenderer.invoke("agent:claim"),
  sendResult: (payload: SendResultPayload) => ipcRenderer.invoke("agent:result", payload),
  checkPermissions: () => ipcRenderer.invoke("permissions:check"),
  requestPermissions: (includeScreenRecording = false) => ipcRenderer.invoke("permissions:request", includeScreenRecording),
  openPermissionSettings: (kind: "accessibility" | "screenRecording" | "automation") =>
    ipcRenderer.invoke("permissions:open", kind),
  runAutomation: (input: AutomationInput) => ipcRenderer.invoke("automation:run", input)
});

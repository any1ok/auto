import { app, BrowserWindow, ipcMain, shell } from "electron";
import { join } from "node:path";
import { AgentApiClient } from "./apiClient";
import { checkAutomationPermissions, requestAutomationPermissions, runAutomation } from "./automation";
import { readConfig, writeConfig } from "./store";
import type { AutomationInput, PairInput, SendResultPayload, StoredConfig } from "./types";

function createWindow(): void {
  const mainWindow = new BrowserWindow({
    width: 1100,
    height: 760,
    minWidth: 920,
    minHeight: 640,
    title: "AutoSend",
    webPreferences: {
      preload: join(__dirname, "../preload/index.mjs"),
      sandbox: false,
      contextIsolation: true
    }
  });

  mainWindow.webContents.setWindowOpenHandler((details) => {
    void shell.openExternal(details.url);
    return { action: "deny" };
  });

  if (process.env.ELECTRON_RENDERER_URL) {
    void mainWindow.loadURL(process.env.ELECTRON_RENDERER_URL);
  } else {
    void mainWindow.loadFile(join(__dirname, "../renderer/index.html"));
  }
}

function clientFromConfig(): AgentApiClient {
  const config = readConfig();
  return new AgentApiClient(config.serverUrl, config.token);
}

app.whenReady().then(() => {
  ipcMain.handle("config:get", () => readConfig());
  ipcMain.handle("config:save", (_event, config: Partial<StoredConfig>) => writeConfig(config));
  ipcMain.handle("agent:pair", async (_event, input: PairInput) => {
    const client = new AgentApiClient(input.serverUrl);
    const paired = await client.pair({
      pairingCode: input.pairingCode,
      name: input.name,
      platform: input.platform
    });
    return writeConfig({
      serverUrl: input.serverUrl,
      token: paired.token,
      device: paired.device
    });
  });
  ipcMain.handle("agent:heartbeat", async () => {
    const device = await clientFromConfig().heartbeat();
    writeConfig({ device });
    return device;
  });
  ipcMain.handle("agent:claim", async () => clientFromConfig().claimJob());
  ipcMain.handle("agent:result", async (_event, payload: SendResultPayload) => {
    await clientFromConfig().sendResult(payload);
  });
  ipcMain.handle("permissions:check", async () => checkAutomationPermissions());
  ipcMain.handle("permissions:request", async (_event, includeScreenRecording: boolean) =>
    requestAutomationPermissions(includeScreenRecording)
  );
  ipcMain.handle("permissions:open", async (_event, kind: "accessibility" | "screenRecording" | "automation") => {
    const urls = {
      accessibility: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
      screenRecording: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
      automation: "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation"
    };
    if (process.platform === "darwin") {
      await shell.openExternal(urls[kind]);
    }
  });
  ipcMain.handle("automation:run", async (_event, input: AutomationInput) => runAutomation(input));

  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

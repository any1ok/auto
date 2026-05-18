import { app } from "electron";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import type { AutomationInput, AutomationPermissionStatus, AutomationResult } from "./types";

function automationExecutable(): { command: string; argsPrefix: string[] } {
  if (app.isPackaged) {
    const executable = process.platform === "win32" ? "autosend_automation.exe" : "autosend_automation";
    return {
      command: join(process.resourcesPath, "automation", executable),
      argsPrefix: []
    };
  }

  const script = join(process.cwd(), "../automation/autosend_automation.py");
  const venvPython =
    process.platform === "win32"
      ? join(process.cwd(), "../automation/.venv/Scripts/python.exe")
      : join(process.cwd(), "../automation/.venv/bin/python");
  const command = existsSync(venvPython) ? venvPython : process.platform === "win32" ? "python" : "python3";
  return { command, argsPrefix: [script] };
}

export async function runAutomation(input: AutomationInput): Promise<AutomationResult> {
  const { command, argsPrefix } = automationExecutable();
  if (app.isPackaged && !existsSync(command)) {
    return {
      ok: false,
      dryRun: input.dryRun,
      sent: false,
      room: input.job.kakaoRoomName,
      error: "자동화 실행 파일을 찾을 수 없습니다."
    };
  }

  const args = [
    ...argsPrefix,
    "--room",
    input.job.kakaoRoomName,
    "--message",
    input.job.message,
    ...(input.dryRun ? ["--dry-run"] : [])
  ];

  return new Promise((resolve) => {
    const child = spawn(command, args, { windowsHide: true });
    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("error", (error) => {
      resolve({
        ok: false,
        dryRun: input.dryRun,
        sent: false,
        room: input.job.kakaoRoomName,
        error: error.message
      });
    });
    child.on("close", (code) => {
      try {
        const parsed = JSON.parse(stdout.trim()) as AutomationResult;
        resolve(parsed);
      } catch {
        resolve({
          ok: code === 0,
          dryRun: input.dryRun,
          sent: false,
          room: input.job.kakaoRoomName,
          error: stderr.trim() || stdout.trim() || `자동화 프로세스 종료 코드: ${code}`
        });
      }
    });
  });
}

export async function checkAutomationPermissions(): Promise<AutomationPermissionStatus> {
  const { command, argsPrefix } = automationExecutable();
  const args = [...argsPrefix, "--check-permissions"];

  return runPermissionCommand(command, args);
}

export async function requestAutomationPermissions(includeScreenRecording: boolean): Promise<AutomationPermissionStatus> {
  const { command, argsPrefix } = automationExecutable();
  const args = [
    ...argsPrefix,
    "--request-permissions",
    ...(includeScreenRecording ? ["--request-screen-recording"] : [])
  ];

  return runPermissionCommand(command, args);
}

function runPermissionCommand(command: string, args: string[]): Promise<AutomationPermissionStatus> {
  return new Promise((resolve) => {
    const child = spawn(command, args, { windowsHide: true });
    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("error", (error) => {
      resolve({
        ok: false,
        platform: process.platform,
        accessibility: false,
        screenRecording: null,
        automation: null,
        required: ["손쉬운 사용"],
        optional: [],
        requested: [],
        message: error.message
      });
    });
    child.on("close", () => {
      try {
        resolve(JSON.parse(stdout.trim()) as AutomationPermissionStatus);
      } catch {
        resolve({
          ok: process.platform !== "darwin",
          platform: process.platform,
          accessibility: process.platform !== "darwin",
          screenRecording: null,
          automation: null,
          required: process.platform === "darwin" ? ["손쉬운 사용"] : [],
          optional: [],
          requested: [],
          message: stderr.trim() || stdout.trim() || "권한 상태를 확인할 수 없습니다."
        });
      }
    });
  });
}

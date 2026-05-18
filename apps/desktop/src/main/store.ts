import { app } from "electron";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import type { StoredConfig } from "./types";

const defaultConfig: StoredConfig = {
  serverUrl: "http://localhost:3000",
  token: null,
  device: null
};

function getConfigPath(): string {
  return join(app.getPath("userData"), "config.json");
}

export function readConfig(): StoredConfig {
  const path = getConfigPath();
  if (!existsSync(path)) return defaultConfig;

  try {
    return { ...defaultConfig, ...JSON.parse(readFileSync(path, "utf8")) };
  } catch {
    return defaultConfig;
  }
}

export function writeConfig(config: Partial<StoredConfig>): StoredConfig {
  const nextConfig = { ...readConfig(), ...config };
  const path = getConfigPath();
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify(nextConfig, null, 2), "utf8");
  return nextConfig;
}


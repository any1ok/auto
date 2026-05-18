import { existsSync, rmSync } from "node:fs";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

const root = process.cwd();
const automationDir = join(root, "apps", "automation");
const venvDir = join(automationDir, ".venv");
const venvPython =
  process.platform === "win32" ? join(venvDir, "Scripts", "python.exe") : join(venvDir, "bin", "python");

const pythonCandidates =
  process.platform === "win32"
    ? ["py -3", "python"]
    : [
        process.env.PYTHON,
        "/opt/homebrew/bin/python3",
        "/usr/local/bin/python3",
        "/usr/bin/python3",
        "python3"
      ].filter(Boolean);

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    stdio: "inherit",
    cwd: options.cwd ?? root,
    shell: options.shell ?? false
  });

  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

function runQuiet(command, args, options = {}) {
  return spawnSync(command, args, {
    cwd: options.cwd ?? root,
    encoding: "utf8",
    shell: options.shell ?? false
  });
}

function checkPython(command) {
  const shell = command.includes(" ");
  const result = runQuiet(command, ["-c", "import ssl, sys; print(sys.executable); print(ssl.OPENSSL_VERSION)"], { shell });
  return result.status === 0 ? result.stdout.trim().split("\n")[0] : null;
}

function selectPython() {
  for (const candidate of pythonCandidates) {
    const executable = checkPython(candidate);
    if (executable) {
      console.log(`Using Python for automation venv: ${executable}`);
      return { command: candidate, shell: candidate.includes(" ") };
    }
  }

  console.error("No Python with a working ssl module was found. Install Homebrew Python or fix your pyenv Python SSL support.");
  process.exit(1);
}

function venvHasWorkingSsl() {
  if (!existsSync(venvPython)) return false;
  return runQuiet(venvPython, ["-c", "import ssl"]).status === 0;
}

const selectedPython = selectPython();

if (!venvHasWorkingSsl()) {
  rmSync(venvDir, { recursive: true, force: true });
  run(selectedPython.command, ["-m", "venv", venvDir], { shell: selectedPython.shell });
}

run(venvPython, ["-m", "pip", "install", "--upgrade", "pip"]);
run(venvPython, ["-m", "pip", "install", "-r", join(automationDir, "requirements.txt")]);

console.log(`Automation Python is ready: ${venvPython}`);

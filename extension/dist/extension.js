"use strict";
var __create = Object.create;
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __getProtoOf = Object.getPrototypeOf;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toESM = (mod, isNodeMode, target) => (target = mod != null ? __create(__getProtoOf(mod)) : {}, __copyProps(
  // If the importer is in node compatibility mode or this is not an ESM
  // file that has been converted to a CommonJS file using a Babel-
  // compatible transform (i.e. "__esModule" has not been set), then set
  // "default" to the CommonJS "module.exports" for node compatibility.
  isNodeMode || !mod || !mod.__esModule ? __defProp(target, "default", { value: mod, enumerable: true }) : target,
  mod
));
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

// extension/src/extension.ts
var extension_exports = {};
__export(extension_exports, {
  activate: () => activate,
  deactivate: () => deactivate
});
module.exports = __toCommonJS(extension_exports);
var vscode6 = __toESM(require("vscode"));

// extension/src/secretManager.ts
var vscode = __toESM(require("vscode"));
var fs = __toESM(require("fs"));
var path = __toESM(require("path"));
var SECRET_KEY = "JARVIS_GROQ_KEY";
var SecretManager = class {
  constructor(context, coreDir) {
    this.context = context;
    this.coreDir = coreDir;
  }
  context;
  coreDir;
  /**
   * Retrieves the Groq API key from VS Code SecretStorage, falling back to core .env.
   */
  async getGroqKey() {
    const secret = await this.context.secrets.get(SECRET_KEY);
    if (secret && secret.trim().length > 5) {
      return secret.trim();
    }
    const envKey = this.readKeyFromEnv(path.join(this.coreDir, ".env"));
    if (envKey) {
      await this.context.secrets.store(SECRET_KEY, envKey);
      return envKey;
    }
    return "";
  }
  /**
   * Prompts the user for their Groq API Key and persists it.
   */
  async promptForGroqKey(forcePrompt = false) {
    const existing = await this.getGroqKey();
    if (existing && !forcePrompt) {
      return existing;
    }
    const input = await vscode.window.showInputBox({
      title: "Jarvis Autonomous Assistant - Groq API Setup",
      prompt: "Enter your Groq API Key to enable Groq Whisper Speech-to-Text and Llama Reasoning",
      password: true,
      ignoreFocusOut: true,
      placeHolder: "gsk_...",
      value: existing || "",
      validateInput: (text) => {
        if (!text || text.trim().length < 10) {
          return "Please enter a valid Groq API key (starts with gsk_...)";
        }
        return null;
      }
    });
    if (input && input.trim()) {
      const cleanKey = input.trim();
      await this.context.secrets.store(SECRET_KEY, cleanKey);
      this.syncKeyToEnvFiles(cleanKey);
      vscode.window.showInformationMessage(
        "Jarvis: Groq API Key successfully configured and synchronized!"
      );
      return cleanKey;
    }
    if (!existing) {
      const getFreeKey = "Get Free Groq Key";
      vscode.window.showWarningMessage(
        "Jarvis requires a Groq API Key for zero-latency speech recognition and reasoning.",
        getFreeKey
      ).then((choice) => {
        if (choice === getFreeKey) {
          vscode.env.openExternal(vscode.Uri.parse("https://console.groq.com/keys"));
        }
      });
    }
    return void 0;
  }
  /**
   * Synchronizes the key to core .env and any open workspace .env.
   */
  syncKeyToEnvFiles(key) {
    const coreEnv = path.join(this.coreDir, ".env");
    this.updateEnvFile(coreEnv, key);
    const wsFolders = vscode.workspace.workspaceFolders;
    if (wsFolders) {
      for (const folder of wsFolders) {
        const wsEnv = path.join(folder.uri.fsPath, ".env");
        if (fs.existsSync(wsEnv)) {
          this.updateEnvFile(wsEnv, key);
        }
      }
    }
  }
  readKeyFromEnv(filePath) {
    if (!fs.existsSync(filePath)) {
      return "";
    }
    try {
      const content = fs.readFileSync(filePath, "utf-8");
      for (const line of content.split(/\r?\n/)) {
        if (line.startsWith("GROQ_API_KEY=")) {
          const val = line.split("=", 2)[1].trim();
          if (val && !val.includes("your_groq_api_key_here")) {
            return val;
          }
        }
      }
    } catch {
    }
    return "";
  }
  updateEnvFile(filePath, key) {
    try {
      let content = "";
      if (fs.existsSync(filePath)) {
        content = fs.readFileSync(filePath, "utf-8");
      }
      if (content.includes("GROQ_API_KEY=")) {
        content = content.replace(/GROQ_API_KEY=.*(?:\r?\n|$)/, `GROQ_API_KEY=${key}
`);
      } else {
        content += `
GROQ_API_KEY=${key}
`;
      }
      fs.writeFileSync(filePath, content, "utf-8");
    } catch {
    }
  }
};

// extension/src/n8nService.ts
var vscode2 = __toESM(require("vscode"));
var http = __toESM(require("http"));
var path2 = __toESM(require("path"));
var cp = __toESM(require("child_process"));
var fs2 = __toESM(require("fs"));
var N8nService = class {
  constructor(coreDir, n8nUrl = "http://localhost:5678") {
    this.coreDir = coreDir;
    this.n8nUrl = n8nUrl;
  }
  coreDir;
  n8nUrl;
  isOnline = false;
  checkInterval = null;
  onStatusChangeEmitter = new vscode2.EventEmitter();
  onStatusChange = this.onStatusChangeEmitter.event;
  getStatus() {
    return this.isOnline;
  }
  getUrl() {
    return this.n8nUrl;
  }
  startPolling(intervalMs = 4e3) {
    this.checkHealth();
    this.checkInterval = setInterval(() => {
      this.checkHealth();
    }, intervalMs);
  }
  stopPolling() {
    if (this.checkInterval) {
      clearInterval(this.checkInterval);
      this.checkInterval = null;
    }
  }
  /**
   * Pings the n8n HTTP server endpoint.
   */
  async checkHealth() {
    return new Promise((resolve) => {
      try {
        const parsed = new URL(this.n8nUrl);
        const req = http.get(
          {
            hostname: parsed.hostname,
            port: parsed.port || 5678,
            path: "/",
            timeout: 1e3
          },
          (res) => {
            const online = res.statusCode !== void 0;
            this.updateStatus(online);
            resolve(online);
          }
        );
        req.on("error", () => {
          this.updateStatus(false);
          resolve(false);
        });
        req.on("timeout", () => {
          req.destroy();
          this.updateStatus(false);
          resolve(false);
        });
      } catch {
        this.updateStatus(false);
        resolve(false);
      }
    });
  }
  /**
   * Spins up the background n8n process if not already online.
   */
  async ensureRunning(silent = false) {
    const online = await this.checkHealth();
    if (online) {
      if (!silent) {
        vscode2.window.showInformationMessage(`Jarvis: n8n Workflow Server is ONLINE at ${this.n8nUrl}`);
      }
      return true;
    }
    if (!silent) {
      vscode2.window.showInformationMessage("Jarvis: Initializing background n8n workflow server...");
    }
    const batFile = path2.join(this.coreDir, "start_n8n.bat");
    if (!fs2.existsSync(batFile)) {
      cp.spawn("npx.cmd", ["-y", "n8n", "start"], {
        cwd: this.coreDir,
        detached: true,
        stdio: "ignore",
        windowsHide: true
      }).unref();
    } else {
      cp.spawn("cmd.exe", ["/c", batFile], {
        cwd: this.coreDir,
        detached: true,
        stdio: "ignore",
        windowsHide: true
      }).unref();
    }
    for (let i = 0; i < 8; i++) {
      await new Promise((r) => setTimeout(r, 1e3));
      const up = await this.checkHealth();
      if (up) {
        if (!silent) {
          vscode2.window.showInformationMessage(`Jarvis: n8n Automation Engine is now ONLINE (${this.n8nUrl})`);
        }
        return true;
      }
    }
    return this.isOnline;
  }
  updateStatus(newStatus) {
    if (this.isOnline !== newStatus) {
      this.isOnline = newStatus;
      this.onStatusChangeEmitter.fire(this.isOnline);
    }
  }
};

// extension/src/processManager.ts
var vscode3 = __toESM(require("vscode"));
var path3 = __toESM(require("path"));
var cp2 = __toESM(require("child_process"));
var fs3 = __toESM(require("fs"));
var ProcessManager = class {
  constructor(coreDir) {
    this.coreDir = coreDir;
  }
  coreDir;
  listenerTerminal = null;
  /**
   * Resolves the current active workspace directory.
   */
  getActiveWorkspace() {
    const wsFolders = vscode3.workspace.workspaceFolders;
    if (wsFolders && wsFolders.length > 0) {
      return wsFolders[0].uri.fsPath;
    }
    return this.coreDir;
  }
  /**
   * Dynamically resolves whether to use 'py', 'python', or a configured python path.
   */
  getPythonCmd() {
    const config = vscode3.workspace.getConfiguration("jarvis");
    const configured = config.get("pythonPath");
    if (configured && configured.trim().length > 0) {
      return configured.trim();
    }
    try {
      cp2.execSync("py --version", { stdio: "ignore" });
      return "py";
    } catch {
      return "python";
    }
  }
  /**
   * Launches the Voice Listener in an integrated terminal.
   */
  startVoiceListener(targetWorkspace) {
    const ws = targetWorkspace || this.getActiveWorkspace();
    let listenerScript = path3.join(this.coreDir, "jarvis_listener.py");
    if (fs3.existsSync(path3.join(ws, "jarvis_listener.py"))) {
      listenerScript = path3.join(ws, "jarvis_listener.py");
    }
    if (this.listenerTerminal) {
      this.listenerTerminal.dispose();
      this.listenerTerminal = null;
    }
    this.listenerTerminal = vscode3.window.createTerminal({
      name: "JARVIS LISTENER",
      cwd: ws,
      env: {
        TARGET_REPO_PATH: ws
      },
      iconPath: new vscode3.ThemeIcon("mic")
    });
    const pyCmd = this.getPythonCmd();
    this.listenerTerminal.show(false);
    this.listenerTerminal.sendText(`${pyCmd} "${listenerScript}" --project "${ws}"`);
    vscode3.window.showInformationMessage(
      `Jarvis Voice Assistant active for [${path3.basename(ws).toUpperCase()}]. Say 'Hey Jarvis'!`
    );
  }
  /**
   * Stops active speech playback and the voice listener.
   */
  stopVoiceListener() {
    const ws = this.getActiveWorkspace();
    const pyCmd = this.getPythonCmd();
    let speakScript = path3.join(this.coreDir, "speak.py");
    if (fs3.existsSync(path3.join(ws, "speak.py"))) {
      speakScript = path3.join(ws, "speak.py");
    }
    try {
      cp2.exec(`${pyCmd} "${speakScript}" --stop`, { cwd: ws });
    } catch {
    }
    try {
      fs3.writeFileSync(path3.join(this.coreDir, "jarvis_stop.flag"), String(Date.now()), "utf-8");
      fs3.writeFileSync(path3.join(this.coreDir, "last_status.txt"), "[STOPPED] Jarvis halted by user.", "utf-8");
      if (ws !== this.coreDir) {
        fs3.writeFileSync(path3.join(ws, "jarvis_stop.flag"), String(Date.now()), "utf-8");
      }
    } catch {
    }
    let hadTerminal = false;
    if (this.listenerTerminal) {
      this.listenerTerminal.dispose();
      this.listenerTerminal = null;
      hadTerminal = true;
    }
    vscode3.window.showInformationMessage(
      hadTerminal ? "Jarvis: Voice Listener terminated and speech halted." : "Jarvis: Speech halted and systems silenced."
    );
  }
  /**
   * Spawns the native PyQt6 Sci-Fi holographic HUD window independently.
   */
  launchDesktopHud(targetWorkspace) {
    const ws = targetWorkspace || this.getActiveWorkspace();
    let hudScript = path3.join(this.coreDir, "jarvis_hud.py");
    if (fs3.existsSync(path3.join(ws, "jarvis_hud.py"))) {
      hudScript = path3.join(ws, "jarvis_hud.py");
    }
    if (!fs3.existsSync(hudScript)) {
      vscode3.window.showErrorMessage(`Jarvis HUD script not found at ${hudScript}`);
      return;
    }
    const pyCmd = this.getPythonCmd();
    const executable = pyCmd === "py" ? "py.exe" : pyCmd.endsWith(".exe") ? pyCmd : "python.exe";
    try {
      cp2.spawn(executable, [hudScript, "--project", ws], {
        cwd: ws,
        detached: true,
        windowsHide: false,
        stdio: "ignore",
        env: {
          ...process.env,
          TARGET_REPO_PATH: ws
        }
      }).unref();
      vscode3.window.showInformationMessage(
        `Jarvis: Desktop Cyber HUD launched for [${path3.basename(ws).toUpperCase()}].`
      );
    } catch (err) {
      vscode3.window.showErrorMessage(`Failed to launch Desktop HUD: ${err.message || err}`);
    }
  }
  /**
   * Initializes Jarvis for the current open workspace folder.
   */
  async initWorkspace(targetWorkspace) {
    const ws = targetWorkspace || this.getActiveWorkspace();
    let cliScript = path3.join(this.coreDir, "jarvis_cli.py");
    if (fs3.existsSync(path3.join(ws, "jarvis_cli.py"))) {
      cliScript = path3.join(ws, "jarvis_cli.py");
    }
    const terminal = vscode3.window.createTerminal({
      name: "JARVIS INIT",
      cwd: ws,
      iconPath: new vscode3.ThemeIcon("rocket")
    });
    const pyCmd = this.getPythonCmd();
    terminal.show();
    terminal.sendText(`${pyCmd} "${cliScript}" init "${ws}"`);
  }
};

// extension/src/statusBar.ts
var vscode4 = __toESM(require("vscode"));
var path4 = __toESM(require("path"));
var StatusBarManager = class {
  constructor(context, n8nService2, processManager) {
    this.context = context;
    this.n8nService = n8nService2;
    this.processManager = processManager;
    this.statusBarItem = vscode4.window.createStatusBarItem(
      vscode4.StatusBarAlignment.Right,
      1e3
    );
    this.statusBarItem.command = "jarvis.quickMenu";
    this.context.subscriptions.push(this.statusBarItem);
    this.n8nService.onStatusChange(() => {
      this.updateDisplay();
    });
    this.updateDisplay();
    this.statusBarItem.show();
  }
  context;
  n8nService;
  processManager;
  statusBarItem;
  updateDisplay() {
    const ws = this.processManager.getActiveWorkspace();
    const projName = path4.basename(ws).toUpperCase();
    const n8nOnline = this.n8nService.getStatus();
    this.statusBarItem.text = `$(hubot) JARVIS [${projName}]`;
    this.statusBarItem.tooltip = new vscode4.MarkdownString(
      `### \u26A1 JARVIS AUTONOMOUS ASSISTANT

- **Active Project**: \`${projName}\`
- **n8n Automation**: ${n8nOnline ? "\u{1F7E2} `ONLINE (5678)`" : "\u{1F534} `OFFLINE`"}
- **Voice Listener**: Standing by for *'Hey Jarvis'*

*Click to open Command Center Quick Actions*`
    );
    this.statusBarItem.tooltip.isTrusted = true;
    this.statusBarItem.color = n8nOnline ? "#00ff88" : "#00e1ff";
  }
  /**
   * Displays interactive Cyber Menu on status bar click.
   */
  async showQuickMenu() {
    const n8nOnline = this.n8nService.getStatus();
    const items = [
      {
        label: "$(mic) Start Voice Listener",
        description: "Listen for 'Hey Jarvis' wake word in active workspace"
      },
      {
        label: "$(primitive-square) Stop Voice Listener",
        description: "Terminate background voice listener process"
      },
      {
        label: "$(dashboard) Focus Cyber HUD Sidebar",
        description: "Open the embedded holographic HUD in Antigravity IDE"
      },
      {
        label: "$(window) Launch Desktop HUD Window",
        description: "Open high-FPS PyQt6 desktop holographic dashboard"
      },
      {
        label: `$(server-process) ${n8nOnline ? "n8n Workflow Engine: ONLINE" : "Start n8n Workflow Server"}`,
        description: n8nOnline ? "http://localhost:5678" : "Initialize background server"
      },
      {
        label: "$(key) Configure Groq API Key",
        description: "Update Whisper STT & Llama credentials"
      },
      {
        label: "$(rocket) Initialize Current Workspace",
        description: "Scaffold .jarvis config, git repo, and project launchers"
      }
    ];
    const pick = await vscode4.window.showQuickPick(items, {
      title: "Jarvis Autonomous Systems - Command Center",
      placeHolder: "Select action to execute..."
    });
    if (!pick) {
      return;
    }
    if (pick.label.includes("Start Voice Listener")) {
      vscode4.commands.executeCommand("jarvis.start");
    } else if (pick.label.includes("Stop Voice Listener")) {
      vscode4.commands.executeCommand("jarvis.stop");
    } else if (pick.label.includes("Focus Cyber HUD Sidebar")) {
      vscode4.commands.executeCommand("jarvis.openSidebarHud");
    } else if (pick.label.includes("Launch Desktop HUD Window")) {
      vscode4.commands.executeCommand("jarvis.openDesktopHud");
    } else if (pick.label.includes("n8n")) {
      vscode4.commands.executeCommand("jarvis.startN8n");
    } else if (pick.label.includes("Configure Groq API Key")) {
      vscode4.commands.executeCommand("jarvis.setGroqKey");
    } else if (pick.label.includes("Initialize Current Workspace")) {
      vscode4.commands.executeCommand("jarvis.initProject");
    }
  }
};

// extension/src/hudViewProvider.ts
var vscode5 = __toESM(require("vscode"));
var fs4 = __toESM(require("fs"));
var path5 = __toESM(require("path"));
var cp3 = __toESM(require("child_process"));
var HudViewProvider = class {
  constructor(context, coreDir, n8nService2, processManager) {
    this.context = context;
    this.coreDir = coreDir;
    this.n8nService = n8nService2;
    this.processManager = processManager;
  }
  context;
  coreDir;
  n8nService;
  processManager;
  static viewType = "jarvis-hud-view";
  _view;
  resolveWebviewView(webviewView, _context, _token) {
    this._view = webviewView;
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this.context.extensionUri]
    };
    webviewView.webview.html = this.getHtmlForWebview(webviewView.webview);
    webviewView.webview.onDidReceiveMessage(async (message) => {
      switch (message.command) {
        case "startListener":
          vscode5.commands.executeCommand("jarvis.start");
          break;
        case "stopJarvis":
        case "stopListener":
          vscode5.commands.executeCommand("jarvis.stop");
          break;
        case "openDesktopHud":
          vscode5.commands.executeCommand("jarvis.openDesktopHud");
          break;
        case "restartN8n":
          vscode5.commands.executeCommand("jarvis.startN8n");
          break;
        case "setGroqKey":
          vscode5.commands.executeCommand("jarvis.setGroqKey");
          break;
        case "initProject":
          vscode5.commands.executeCommand("jarvis.initProject");
          break;
        case "requestDeleteBranch":
          await this.promptForBranchDeletion();
          break;
        case "revertCommit":
          await this.promptAndRevertCommit();
          break;
        case "confirmBranch":
          await this.handleBranchConfirmation(message.choice, message.branchName);
          break;
        case "refresh":
          this.sendTelemetryUpdate();
          break;
      }
    });
    this.n8nService.onStatusChange(() => {
      this.sendTelemetryUpdate();
    });
    const telemetryTimer = setInterval(() => {
      if (this._view?.visible) {
        this.sendTelemetryUpdate();
      }
    }, 1500);
    this.context.subscriptions.push({
      dispose: () => clearInterval(telemetryTimer)
    });
  }
  sendTelemetryUpdate() {
    if (!this._view) {
      return;
    }
    const ws = this.processManager.getActiveWorkspace();
    const projName = path5.basename(ws).toUpperCase();
    const n8nOnline = this.n8nService.getStatus();
    let lastTranscript = "Standing by for wake word 'Hey Jarvis'...";
    let lastStatus = "Systems normal. Ready for commands.";
    let pendingConfirmation = null;
    try {
      const transFiles = [
        path5.join(this.coreDir, "last_transcript.txt"),
        path5.join(ws, "last_transcript.txt")
      ];
      for (const tf of transFiles) {
        if (fs4.existsSync(tf)) {
          const text = fs4.readFileSync(tf, "utf-8").trim();
          if (text) {
            lastTranscript = text;
            break;
          }
        }
      }
      const statusFiles = [
        path5.join(this.coreDir, "last_status.txt"),
        path5.join(ws, "last_status.txt")
      ];
      for (const sf of statusFiles) {
        if (fs4.existsSync(sf)) {
          const sText = fs4.readFileSync(sf, "utf-8").trim();
          if (sText) {
            lastStatus = sText;
            break;
          }
        }
      }
      const confFiles = [
        path5.join(this.coreDir, "pending_confirmation.json"),
        path5.join(ws, "pending_confirmation.json")
      ];
      for (const cf of confFiles) {
        if (fs4.existsSync(cf)) {
          try {
            const cText = fs4.readFileSync(cf, "utf-8").trim();
            if (cText) {
              const cData = JSON.parse(cText);
              const nowSec = Date.now() / 1e3;
              const ts = cData.timestamp || nowSec;
              if (nowSec - ts < 180 && cData.action === "delete_branch" && cData.branch_name) {
                pendingConfirmation = {
                  action: cData.action,
                  branchName: cData.branch_name
                };
                break;
              }
            }
          } catch {
          }
        }
      }
      if (!pendingConfirmation) {
        const intentFiles = [
          path5.join(this.coreDir, "last_intent.json"),
          path5.join(ws, "last_intent.json")
        ];
        for (const ifile of intentFiles) {
          if (fs4.existsSync(ifile)) {
            try {
              const iData = JSON.parse(fs4.readFileSync(ifile, "utf-8"));
              if (iData && (iData.type === "confirm_action" || iData.requires_confirmation) && iData.branch_name) {
                pendingConfirmation = {
                  action: "delete_branch",
                  branchName: iData.branch_name
                };
                break;
              }
            } catch {
            }
          }
        }
      }
      if (!pendingConfirmation && lastStatus.includes("[CONFIRMATION REQUIRED]")) {
        const match = lastStatus.match(/branch\s+['"]([^'"]+)['"]/i);
        if (match && match[1]) {
          pendingConfirmation = {
            action: "delete_branch",
            branchName: match[1]
          };
        }
      }
    } catch {
    }
    this._view.webview.postMessage({
      type: "telemetry",
      project: projName,
      workspace: ws,
      n8nOnline,
      lastTranscript,
      lastStatus,
      pendingConfirmation
    });
  }
  async promptForBranchDeletion() {
    const ws = this.processManager.getActiveWorkspace();
    let branches = [];
    try {
      const out = cp3.execSync("git branch --list --no-color", { cwd: ws, encoding: "utf-8" });
      branches = out.split("\n").map((b) => b.replace("*", "").trim()).filter((b) => b.length > 0 && b !== "main" && b !== "master");
    } catch {
    }
    let selectedBranch;
    if (branches.length > 0) {
      selectedBranch = await vscode5.window.showQuickPick(branches, {
        placeHolder: "Select a git branch to remove (or ESC to type custom branch)"
      });
    }
    if (!selectedBranch) {
      selectedBranch = await vscode5.window.showInputBox({
        prompt: "Enter git branch name to remove",
        placeHolder: "e.g. test, feature-ui"
      });
    }
    if (!selectedBranch || !selectedBranch.trim()) {
      return;
    }
    selectedBranch = selectedBranch.trim();
    if (selectedBranch === "main" || selectedBranch === "master") {
      vscode5.window.showErrorMessage(`Cannot delete protected branch '${selectedBranch}'.`);
      return;
    }
    const confData = {
      action: "delete_branch",
      branch_name: selectedBranch,
      target_repo: ws,
      timestamp: Date.now() / 1e3,
      task_description: `Delete branch ${selectedBranch}`
    };
    try {
      fs4.writeFileSync(path5.join(this.coreDir, "pending_confirmation.json"), JSON.stringify(confData, null, 2), "utf-8");
      if (ws !== this.coreDir) {
        fs4.writeFileSync(path5.join(ws, "pending_confirmation.json"), JSON.stringify(confData, null, 2), "utf-8");
      }
      fs4.writeFileSync(
        path5.join(this.coreDir, "last_status.txt"),
        `[CONFIRMATION REQUIRED] Delete branch '${selectedBranch}'? Say YES to confirm or NO to cancel.`,
        "utf-8"
      );
    } catch {
    }
    this.sendTelemetryUpdate();
  }
  async promptAndRevertCommit() {
    const ws = this.processManager.getActiveWorkspace();
    const confirm = await vscode5.window.showWarningMessage(
      "Are you sure you want to revert the last committed changes?",
      { modal: true },
      "Yes, Revert",
      "Cancel"
    );
    if (confirm !== "Yes, Revert") {
      return;
    }
    const statusFiles = [
      path5.join(this.coreDir, "last_status.txt"),
      path5.join(ws, "last_status.txt")
    ];
    const transcriptFiles = [
      path5.join(this.coreDir, "last_transcript.txt"),
      path5.join(ws, "last_transcript.txt")
    ];
    const writeAll = (files, content) => {
      for (const f of files) {
        try {
          fs4.writeFileSync(f, content, "utf-8");
        } catch {
        }
      }
    };
    writeAll(transcriptFiles, "[SIDEBAR ACTION] User requested revert of last commit");
    writeAll(statusFiles, "[EXECUTING] Reverting last commit and syncing repository...");
    this.sendTelemetryUpdate();
    const pyCmd = this.processManager.getPythonCmd();
    let execScript = path5.join(this.coreDir, "execute_git.py");
    if (!fs4.existsSync(execScript) && fs4.existsSync(path5.join(ws, "execute_git.py"))) {
      execScript = path5.join(ws, "execute_git.py");
    }
    let speakScript = path5.join(this.coreDir, "speak.py");
    if (!fs4.existsSync(speakScript) && fs4.existsSync(path5.join(ws, "speak.py"))) {
      speakScript = path5.join(ws, "speak.py");
    }
    cp3.exec(
      `${pyCmd} "${execScript}" --revert-commit`,
      {
        cwd: ws,
        env: { ...process.env, TARGET_REPO_PATH: ws }
      },
      (err, stdout, stderr) => {
        if (err) {
          const rawErr = (stderr || stdout || err.message).replace(/\r?\n/g, " ");
          writeAll(statusFiles, `[GIT ERROR] Failed to revert commit: ${rawErr.slice(0, 110)}`);
          cp3.exec(`${pyCmd} "${speakScript}" "Failed to revert the last commit, sir."`, { cwd: ws });
          vscode5.window.showErrorMessage("Jarvis: Failed to revert commit.");
        } else {
          writeAll(statusFiles, "[GIT SUCCESS] Last committed changes reverted successfully.");
          cp3.exec(`${pyCmd} "${speakScript}" "The last committed changes have been reverted successfully, sir."`, {
            cwd: ws
          });
          vscode5.window.showInformationMessage("Jarvis: Last committed changes reverted successfully.");
        }
        this.sendTelemetryUpdate();
      }
    );
  }
  async handleBranchConfirmation(choice, branchOverride) {
    const ws = this.processManager.getActiveWorkspace();
    let branchName = branchOverride || "test";
    let targetRepo = ws;
    const confFiles = [
      path5.join(this.coreDir, "pending_confirmation.json"),
      path5.join(ws, "pending_confirmation.json")
    ];
    for (const confFile of confFiles) {
      if (fs4.existsSync(confFile)) {
        try {
          const data = JSON.parse(fs4.readFileSync(confFile, "utf-8"));
          if (data.branch_name) {
            branchName = data.branch_name;
          }
          if (data.target_repo && fs4.existsSync(data.target_repo)) {
            targetRepo = data.target_repo;
          }
        } catch {
        }
        try {
          fs4.unlinkSync(confFile);
        } catch {
        }
      }
    }
    if (!branchName || branchName === "test") {
      const statusFiles2 = [
        path5.join(this.coreDir, "last_status.txt"),
        path5.join(ws, "last_status.txt")
      ];
      for (const sf of statusFiles2) {
        if (fs4.existsSync(sf)) {
          const txt = fs4.readFileSync(sf, "utf-8");
          const m = txt.match(/branch\s+['"]([^'"]+)['"]/i) || txt.match(/'([^']+)'/);
          if (m && m[1]) {
            branchName = m[1];
            break;
          }
        }
      }
    }
    const intentFiles = [
      path5.join(this.coreDir, "last_intent.json"),
      path5.join(ws, "last_intent.json")
    ];
    for (const ifile of intentFiles) {
      if (fs4.existsSync(ifile)) {
        try {
          const iData = JSON.parse(fs4.readFileSync(ifile, "utf-8"));
          if (iData.type === "confirm_action") {
            fs4.unlinkSync(ifile);
          }
        } catch {
        }
      }
    }
    const pyCmd = this.processManager.getPythonCmd();
    let execScript = path5.join(this.coreDir, "execute_git.py");
    if (!fs4.existsSync(execScript) && fs4.existsSync(path5.join(ws, "execute_git.py"))) {
      execScript = path5.join(ws, "execute_git.py");
    }
    let speakScript = path5.join(this.coreDir, "speak.py");
    if (!fs4.existsSync(speakScript) && fs4.existsSync(path5.join(ws, "speak.py"))) {
      speakScript = path5.join(ws, "speak.py");
    }
    const statusFiles = [
      path5.join(this.coreDir, "last_status.txt"),
      path5.join(ws, "last_status.txt")
    ];
    const transcriptFiles = [
      path5.join(this.coreDir, "last_transcript.txt"),
      path5.join(ws, "last_transcript.txt")
    ];
    const writeAll = (files, content) => {
      for (const f of files) {
        try {
          fs4.writeFileSync(f, content, "utf-8");
        } catch {
        }
      }
    };
    if (choice === "yes") {
      writeAll(transcriptFiles, `[CONFIRMED] Delete branch '${branchName}'`);
      writeAll(statusFiles, `[EXECUTING] Deleting branch '${branchName}' locally and from GitHub...`);
      this.sendTelemetryUpdate();
      cp3.exec(
        `${pyCmd} "${execScript}" --delete-branch "${branchName}"`,
        {
          cwd: targetRepo,
          env: { ...process.env, TARGET_REPO_PATH: targetRepo }
        },
        (err, stdout, stderr) => {
          if (err) {
            const rawErr = (stderr || stdout || err.message).replace(/\r?\n/g, " ");
            writeAll(statusFiles, `[GIT ERROR] Failed to delete branch '${branchName}': ${rawErr.slice(0, 110)}`);
            cp3.exec(`${pyCmd} "${speakScript}" "Failed to delete branch ${branchName}, sir."`, { cwd: targetRepo });
            vscode5.window.showErrorMessage(`Jarvis: Failed to delete branch '${branchName}'`);
          } else {
            writeAll(statusFiles, `[GIT SUCCESS] Branch '${branchName}' deleted successfully.`);
            cp3.exec(`${pyCmd} "${speakScript}" "Branch ${branchName} has been deleted successfully, sir."`, {
              cwd: targetRepo
            });
            vscode5.window.showInformationMessage(`Jarvis: Branch '${branchName}' deleted successfully.`);
          }
          this.sendTelemetryUpdate();
        }
      );
    } else {
      writeAll(transcriptFiles, `[CANCELLED] Branch '${branchName}' deletion cancelled`);
      writeAll(statusFiles, `[CANCELLED] Deletion of branch '${branchName}' cancelled by user.`);
      cp3.exec(`${pyCmd} "${speakScript}" "Branch deletion cancelled, sir."`, { cwd: targetRepo });
      vscode5.window.showInformationMessage(`Jarvis: Branch '${branchName}' deletion cancelled.`);
      this.sendTelemetryUpdate();
    }
  }
  getHtmlForWebview(_webview) {
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Jarvis Cyber HUD</title>
  <style>
    :root {
      --cyan: #00e1ff;
      --cyan-dim: rgba(0, 225, 255, 0.2);
      --green: #00ff88;
      --amber: #ff9d00;
      --red: #ff4444;
      --bg: #0b0b1e;
      --panel-bg: rgba(14, 16, 40, 0.7);
    }
    body {
      background-color: var(--bg);
      color: #cad8e6;
      font-family: 'Consolas', 'Segoe UI', monospace;
      margin: 0;
      padding: 12px;
      user-select: none;
    }
    .hud-header {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-bottom: 12px;
    }
    .badge {
      font-size: 10px;
      font-weight: bold;
      padding: 3px 6px;
      border-radius: 2px;
      border: 1px solid currentColor;
      letter-spacing: 1px;
    }
    .badge-green { color: var(--green); background: rgba(0, 255, 136, 0.12); }
    .badge-cyan { color: var(--cyan); background: rgba(0, 225, 255, 0.12); }
    .badge-amber { color: var(--amber); background: rgba(255, 157, 0, 0.12); }
    .badge-red { color: var(--red); background: rgba(255, 68, 68, 0.12); }

    .reactor-container {
      display: flex;
      flex-direction: column;
      align-items: center;
      margin: 10px 0;
    }
    canvas {
      width: 140px;
      height: 140px;
    }

    .project-title {
      font-size: 13px;
      font-weight: bold;
      color: var(--cyan);
      letter-spacing: 1.5px;
      text-align: center;
      margin-top: 4px;
      border-bottom: 1px solid var(--cyan-dim);
      padding-bottom: 6px;
      width: 100%;
    }

    .panel {
      background: var(--panel-bg);
      border: 1px solid var(--cyan-dim);
      border-radius: 3px;
      padding: 8px 10px;
      margin-bottom: 10px;
      position: relative;
    }
    .panel-title {
      font-size: 9px;
      font-weight: bold;
      color: var(--cyan);
      letter-spacing: 1.5px;
      margin-bottom: 6px;
      text-transform: uppercase;
    }

    .transcript-box {
      font-size: 11px;
      color: #00ff88;
      min-height: 38px;
      word-break: break-word;
      line-height: 1.4;
    }
    .status-box {
      font-size: 11px;
      color: #cad8e6;
      min-height: 30px;
      word-break: break-word;
      line-height: 1.4;
    }

    .btn-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 6px;
      margin-top: 8px;
    }
    button {
      background: rgba(0, 225, 255, 0.08);
      border: 1px solid var(--cyan);
      color: var(--cyan);
      font-family: inherit;
      font-size: 10px;
      font-weight: bold;
      padding: 7px 4px;
      border-radius: 2px;
      cursor: pointer;
      transition: all 0.2s ease;
      text-transform: uppercase;
      letter-spacing: 1px;
    }
    button:hover {
      background: rgba(0, 225, 255, 0.25);
      box-shadow: 0 0 10px rgba(0, 225, 255, 0.5);
    }
    button.btn-primary {
      grid-column: span 2;
      background: rgba(0, 255, 136, 0.15);
      border-color: var(--green);
      color: var(--green);
    }
    button.btn-primary:hover {
      background: rgba(0, 255, 136, 0.3);
      box-shadow: 0 0 12px rgba(0, 255, 136, 0.6);
    }
    button.btn-danger {
      grid-column: span 2;
      background: rgba(255, 68, 68, 0.15);
      border-color: var(--red);
      color: var(--red);
    }
    button.btn-danger:hover {
      background: rgba(255, 68, 68, 0.35);
      box-shadow: 0 0 12px rgba(255, 68, 68, 0.7);
    }
    button.btn-warn {
      background: rgba(255, 157, 0, 0.15);
      border-color: var(--amber);
      color: var(--amber);
    }
    button.btn-warn:hover {
      background: rgba(255, 157, 0, 0.35);
      box-shadow: 0 0 12px rgba(255, 157, 0, 0.7);
    }
  </style>
</head>
<body>
  <div class="hud-header">
    <div class="badge badge-green">[ACTIVE]</div>
    <div class="badge badge-cyan">[SYS_OK]</div>
    <div id="badge-n8n" class="badge badge-green">[N8N: ONLINE]</div>
    <div class="badge badge-amber">[GROQ: OK]</div>
  </div>

  <div class="reactor-container">
    <canvas id="reactorCanvas" width="280" height="280"></canvas>
    <div id="projName" class="project-title">// JARVIS COMMAND CENTER //</div>
  </div>

  <div class="panel">
    <div class="panel-title">// 1. VOICE TRANSCRIPT //</div>
    <div id="transcriptBox" class="transcript-box">Standing by for wake word 'Hey Jarvis'...</div>
  </div>

  <div class="panel">
    <div class="panel-title">// 2. TELEMETRY & STATUS //</div>
    <div id="statusBox" class="status-box">Systems normal. Initialized for active workspace.</div>
  </div>

  <div class="btn-grid">
    <button class="btn-warn" onclick="sendMessage('requestDeleteBranch')">\u{1F5D1}\uFE0F REMOVE BRANCH</button>
    <button class="btn-warn" onclick="sendMessage('revertCommit')">\u21A9\uFE0F REVERT COMMIT</button>
    <button class="btn-primary" onclick="sendMessage('startListener')">\u{1F3A4} START VOICE LISTENER</button>
    <button class="btn-danger" onclick="sendMessage('stopJarvis')">\u{1F6D1} STOP / SILENCE JARVIS</button>
    <button onclick="sendMessage('openDesktopHud')">\u{1F5A5}\uFE0F DESKTOP HUD</button>
    <button onclick="sendMessage('restartN8n')">\u{1F504} RESTART N8N</button>
    <button onclick="sendMessage('setGroqKey')">\u{1F511} SET GROQ KEY</button>
    <button onclick="sendMessage('initProject')">\u{1F680} INIT WORKSPACE</button>
  </div>

  <script>
    const vscode = acquireVsCodeApi();

    function sendMessage(cmd) {
      vscode.postMessage({ command: cmd });
    }

    // Arc reactor canvas animation
    const canvas = document.getElementById('reactorCanvas');
    const ctx = canvas.getContext('2d');
    let angle = 0;
    let pulse = 0;

    function drawReactor() {
      const cx = canvas.width / 2;
      const cy = canvas.height / 2;
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      angle += 0.02;
      pulse = (Math.sin(angle * 3) + 1) / 2;

      // Outer dashed spinning ring
      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(angle);
      ctx.strokeStyle = '#00e1ff';
      ctx.lineWidth = 3;
      ctx.setLineDash([12, 8]);
      ctx.beginPath();
      ctx.arc(0, 0, 110, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();

      // Middle counter-rotating amber ring
      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(-angle * 1.5);
      ctx.strokeStyle = '#ff9d00';
      ctx.lineWidth = 2;
      ctx.setLineDash([8, 12]);
      ctx.beginPath();
      ctx.arc(0, 0, 75, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();

      // Inner glowing core
      ctx.save();
      ctx.translate(cx, cy);
      ctx.fillStyle = '#00ff88';
      ctx.shadowColor = '#00ff88';
      ctx.shadowBlur = 15 + pulse * 10;
      ctx.beginPath();
      ctx.arc(0, 0, 22 + pulse * 6, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();

      requestAnimationFrame(drawReactor);
    }
    drawReactor();

    // Handle messages from VS Code
    window.addEventListener('message', event => {
      const msg = event.data;
      if (msg.type === 'telemetry') {
        document.getElementById('projName').textContent = '// [' + msg.project + '] //';
        document.getElementById('transcriptBox').textContent = msg.lastTranscript;
        document.getElementById('statusBox').textContent = msg.lastStatus;

        const n8nBadge = document.getElementById('badge-n8n');
        if (msg.n8nOnline) {
          n8nBadge.className = 'badge badge-green';
          n8nBadge.textContent = '[N8N: ONLINE]';
        } else {
          n8nBadge.className = 'badge badge-red';
          n8nBadge.textContent = '[N8N: OFFLINE]';
        }
      }
    });
  </script>
</body>
</html>`;
  }
};

// extension/src/extension.ts
var path6 = __toESM(require("path"));
var fs5 = __toESM(require("fs"));
var cp4 = __toESM(require("child_process"));
var n8nService;
function checkPythonDependencies(coreDir, processManager) {
  const pyCmd = processManager.getPythonCmd();
  cp4.exec(`${pyCmd} -c "import PyQt6, openwakeword, edge_tts"`, (err) => {
    if (err) {
      vscode6.window.showWarningMessage(
        "Jarvis: Python dependencies are missing on this system. Would you like to install them now?",
        "Install Dependencies"
      ).then((choice) => {
        if (choice === "Install Dependencies") {
          vscode6.commands.executeCommand("jarvis.installDependencies");
        }
      });
    }
  });
}
async function activate(context) {
  console.log("[Jarvis Extension] Activating Autonomous Systems...");
  const config = vscode6.workspace.getConfiguration("jarvis");
  const configuredDir = config.get("coreDir");
  const bundledDir = path6.join(context.extensionPath, "python");
  const activeWs = vscode6.workspace.workspaceFolders?.[0]?.uri.fsPath;
  let coreDir = bundledDir;
  if (configuredDir && fs5.existsSync(configuredDir)) {
    coreDir = configuredDir;
  } else if (activeWs && (fs5.existsSync(path6.join(activeWs, "jarvis_listener.py")) || fs5.existsSync(path6.join(activeWs, "transcribe.py")))) {
    coreDir = activeWs;
  } else if (fs5.existsSync(bundledDir)) {
    coreDir = bundledDir;
  } else if (fs5.existsSync("C:\\Programming\\Jarvis\\Jarvis-Voice-Assistant")) {
    coreDir = "C:\\Programming\\Jarvis\\Jarvis-Voice-Assistant";
  }
  const autoStartN8n = config.get("autoStartN8n") ?? true;
  const n8nUrl = config.get("n8nUrl") || "http://localhost:5678";
  const secretManager = new SecretManager(context, coreDir);
  n8nService = new N8nService(coreDir, n8nUrl);
  const processManager = new ProcessManager(coreDir);
  const statusBar = new StatusBarManager(context, n8nService, processManager);
  const hudProvider = new HudViewProvider(context, coreDir, n8nService, processManager);
  context.subscriptions.push(
    vscode6.window.registerWebviewViewProvider(
      HudViewProvider.viewType,
      hudProvider,
      {
        webviewOptions: {
          retainContextWhenHidden: true
        }
      }
    )
  );
  context.subscriptions.push(
    vscode6.commands.registerCommand("jarvis.start", () => {
      processManager.startVoiceListener();
    }),
    vscode6.commands.registerCommand("jarvis.stop", () => {
      processManager.stopVoiceListener();
    }),
    vscode6.commands.registerCommand("jarvis.openDesktopHud", () => {
      processManager.launchDesktopHud();
    }),
    vscode6.commands.registerCommand("jarvis.openSidebarHud", () => {
      vscode6.commands.executeCommand("workbench.view.extension.jarvis-sidebar");
    }),
    vscode6.commands.registerCommand("jarvis.setGroqKey", async () => {
      await secretManager.promptForGroqKey(true);
    }),
    vscode6.commands.registerCommand("jarvis.startN8n", async () => {
      await n8nService?.ensureRunning(false);
    }),
    vscode6.commands.registerCommand("jarvis.initProject", async () => {
      await processManager.initWorkspace();
    }),
    vscode6.commands.registerCommand("jarvis.status", () => {
      const ws = processManager.getActiveWorkspace();
      const n8nUp = n8nService?.getStatus() ? "ONLINE (5678)" : "OFFLINE";
      vscode6.window.showInformationMessage(
        `Jarvis Status: Project [${path6.basename(ws).toUpperCase()}] | n8n: ${n8nUp} | Core: ${coreDir}`
      );
    }),
    vscode6.commands.registerCommand("jarvis.installDependencies", () => {
      const term = vscode6.window.createTerminal({
        name: "JARVIS SETUP",
        iconPath: new vscode6.ThemeIcon("tools")
      });
      term.show();
      const reqFile = path6.join(coreDir, "requirements.txt");
      const pyCmd = processManager.getPythonCmd();
      term.sendText(`${pyCmd} -m pip install -r "${reqFile}"`);
    }),
    vscode6.commands.registerCommand("jarvis.quickMenu", async () => {
      await statusBar.showQuickMenu();
    })
  );
  const groqKey = await secretManager.getGroqKey();
  if (!groqKey) {
    setTimeout(() => {
      secretManager.promptForGroqKey(false);
    }, 1200);
  }
  setTimeout(() => {
    checkPythonDependencies(coreDir, processManager);
  }, 2500);
  if (autoStartN8n) {
    n8nService.startPolling(5e3);
    setTimeout(() => {
      n8nService?.ensureRunning(true);
    }, 2e3);
  }
  console.log("[Jarvis Extension] Fully activated and operational.");
}
function deactivate() {
  if (n8nService) {
    n8nService.stopPolling();
  }
}
// Annotate the CommonJS export names for ESM import in node:
0 && (module.exports = {
  activate,
  deactivate
});

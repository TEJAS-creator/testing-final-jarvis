import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";
import * as cp from "child_process";
import { N8nService } from "./n8nService";
import { ProcessManager } from "./processManager";

export class HudViewProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = "jarvis-hud-view";
  private _view?: vscode.WebviewView;

  constructor(
    private readonly context: vscode.ExtensionContext,
    private readonly coreDir: string,
    private readonly n8nService: N8nService,
    private readonly processManager: ProcessManager
  ) {}

  public resolveWebviewView(
    webviewView: vscode.WebviewView,
    _context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken
  ): void {
    this._view = webviewView;

    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this.context.extensionUri],
    };

    webviewView.webview.html = this.getHtmlForWebview(webviewView.webview);

    // Handle messages sent from Webview UI
    webviewView.webview.onDidReceiveMessage(async (message) => {
      switch (message.command) {
        case "startListener":
          vscode.commands.executeCommand("jarvis.start");
          break;
        case "stopJarvis":
        case "stopListener":
          vscode.commands.executeCommand("jarvis.stop");
          break;
        case "openDesktopHud":
          vscode.commands.executeCommand("jarvis.openDesktopHud");
          break;
        case "restartN8n":
          vscode.commands.executeCommand("jarvis.startN8n");
          break;
        case "setGroqKey":
          vscode.commands.executeCommand("jarvis.setGroqKey");
          break;
        case "initProject":
          vscode.commands.executeCommand("jarvis.initProject");
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

    // Update on n8n status change
    this.n8nService.onStatusChange(() => {
      this.sendTelemetryUpdate();
    });

    // Stream telemetry every 1.5 seconds for instant UI response
    const telemetryTimer = setInterval(() => {
      if (this._view?.visible) {
        this.sendTelemetryUpdate();
      }
    }, 1500);

    this.context.subscriptions.push({
      dispose: () => clearInterval(telemetryTimer),
    });
  }

  public sendTelemetryUpdate(): void {
    if (!this._view) {
      return;
    }

    const ws = this.processManager.getActiveWorkspace();
    const projName = path.basename(ws).toUpperCase();
    const n8nOnline = this.n8nService.getStatus();

    let lastTranscript = "Standing by for wake word 'Hey Jarvis'...";
    let lastStatus = "Systems normal. Ready for commands.";
    let pendingConfirmation: { action: string; branchName: string } | null = null;

    try {
      // 1. Read transcript
      const transFiles = [
        path.join(this.coreDir, "last_transcript.txt"),
        path.join(ws, "last_transcript.txt"),
      ];
      for (const tf of transFiles) {
        if (fs.existsSync(tf)) {
          const text = fs.readFileSync(tf, "utf-8").trim();
          if (text) {
            lastTranscript = text;
            break;
          }
        }
      }

      // 2. Read status
      const statusFiles = [
        path.join(this.coreDir, "last_status.txt"),
        path.join(ws, "last_status.txt"),
      ];
      for (const sf of statusFiles) {
        if (fs.existsSync(sf)) {
          const sText = fs.readFileSync(sf, "utf-8").trim();
          if (sText) {
            lastStatus = sText;
            break;
          }
        }
      }

      // 3. Check pending confirmation file (TTL: 180 seconds)
      const confFiles = [
        path.join(this.coreDir, "pending_confirmation.json"),
        path.join(ws, "pending_confirmation.json"),
      ];
      for (const cf of confFiles) {
        if (fs.existsSync(cf)) {
          try {
            const cText = fs.readFileSync(cf, "utf-8").trim();
            if (cText) {
              const cData = JSON.parse(cText);
              const nowSec = Date.now() / 1000;
              const ts = cData.timestamp || nowSec;
              if (nowSec - ts < 180 && cData.action === "delete_branch" && cData.branch_name) {
                pendingConfirmation = {
                  action: cData.action,
                  branchName: cData.branch_name,
                };
                break;
              }
            }
          } catch {}
        }
      }

      // 4. Fallback check: last_intent.json
      if (!pendingConfirmation) {
        const intentFiles = [
          path.join(this.coreDir, "last_intent.json"),
          path.join(ws, "last_intent.json"),
        ];
        for (const ifile of intentFiles) {
          if (fs.existsSync(ifile)) {
            try {
              const iData = JSON.parse(fs.readFileSync(ifile, "utf-8"));
              if (iData && (iData.type === "confirm_action" || iData.requires_confirmation) && iData.branch_name) {
                pendingConfirmation = {
                  action: "delete_branch",
                  branchName: iData.branch_name,
                };
                break;
              }
            } catch {}
          }
        }
      }

      // 5. Fallback check: [CONFIRMATION REQUIRED] in lastStatus
      if (!pendingConfirmation && lastStatus.includes("[CONFIRMATION REQUIRED]")) {
        const match = lastStatus.match(/branch\s+['"]([^'"]+)['"]/i);
        if (match && match[1]) {
          pendingConfirmation = {
            action: "delete_branch",
            branchName: match[1],
          };
        }
      }
    } catch {
      // Ignore reading errors
    }

    this._view.webview.postMessage({
      type: "telemetry",
      project: projName,
      workspace: ws,
      n8nOnline: n8nOnline,
      lastTranscript: lastTranscript,
      lastStatus: lastStatus,
      pendingConfirmation: pendingConfirmation,
    });
  }

  private async promptForBranchDeletion(): Promise<void> {
    const ws = this.processManager.getActiveWorkspace();
    let branches: string[] = [];
    try {
      const out = cp.execSync("git branch --list --no-color", { cwd: ws, encoding: "utf-8" });
      branches = out
        .split("\n")
        .map((b) => b.replace("*", "").trim())
        .filter((b) => b.length > 0 && b !== "main" && b !== "master");
    } catch {}

    let selectedBranch: string | undefined;
    if (branches.length > 0) {
      selectedBranch = await vscode.window.showQuickPick(branches, {
        placeHolder: "Select a git branch to remove (or ESC to type custom branch)",
      });
    }

    if (!selectedBranch) {
      selectedBranch = await vscode.window.showInputBox({
        prompt: "Enter git branch name to remove",
        placeHolder: "e.g. test, feature-ui",
      });
    }

    if (!selectedBranch || !selectedBranch.trim()) {
      return;
    }

    selectedBranch = selectedBranch.trim();
    if (selectedBranch === "main" || selectedBranch === "master") {
      vscode.window.showErrorMessage(`Cannot delete protected branch '${selectedBranch}'.`);
      return;
    }

    const confData = {
      action: "delete_branch",
      branch_name: selectedBranch,
      target_repo: ws,
      timestamp: Date.now() / 1000,
      task_description: `Delete branch ${selectedBranch}`,
    };

    try {
      fs.writeFileSync(path.join(this.coreDir, "pending_confirmation.json"), JSON.stringify(confData, null, 2), "utf-8");
      if (ws !== this.coreDir) {
        fs.writeFileSync(path.join(ws, "pending_confirmation.json"), JSON.stringify(confData, null, 2), "utf-8");
      }
      fs.writeFileSync(
        path.join(this.coreDir, "last_status.txt"),
        `[CONFIRMATION REQUIRED] Delete branch '${selectedBranch}'? Say YES to confirm or NO to cancel.`,
        "utf-8"
      );
    } catch {}

    this.sendTelemetryUpdate();
  }

  private async promptAndRevertCommit(): Promise<void> {
    const ws = this.processManager.getActiveWorkspace();
    const confirm = await vscode.window.showWarningMessage(
      "Are you sure you want to revert the last committed changes?",
      { modal: true },
      "Yes, Revert",
      "Cancel"
    );

    if (confirm !== "Yes, Revert") {
      return;
    }

    const statusFiles = [
      path.join(this.coreDir, "last_status.txt"),
      path.join(ws, "last_status.txt"),
    ];
    const transcriptFiles = [
      path.join(this.coreDir, "last_transcript.txt"),
      path.join(ws, "last_transcript.txt"),
    ];

    const writeAll = (files: string[], content: string) => {
      for (const f of files) {
        try {
          fs.writeFileSync(f, content, "utf-8");
        } catch {}
      }
    };

    writeAll(transcriptFiles, "[SIDEBAR ACTION] User requested revert of last commit");
    writeAll(statusFiles, "[EXECUTING] Reverting last commit and syncing repository...");
    this.sendTelemetryUpdate();

    const pyCmd = this.processManager.getPythonCmd();
    let execScript = path.join(this.coreDir, "execute_git.py");
    if (!fs.existsSync(execScript) && fs.existsSync(path.join(ws, "execute_git.py"))) {
      execScript = path.join(ws, "execute_git.py");
    }
    let speakScript = path.join(this.coreDir, "speak.py");
    if (!fs.existsSync(speakScript) && fs.existsSync(path.join(ws, "speak.py"))) {
      speakScript = path.join(ws, "speak.py");
    }

    cp.exec(
      `${pyCmd} "${execScript}" --revert-commit`,
      {
        cwd: ws,
        env: { ...process.env, TARGET_REPO_PATH: ws },
      },
      (err, stdout, stderr) => {
        if (err) {
          const rawErr = (stderr || stdout || err.message).replace(/\r?\n/g, " ");
          writeAll(statusFiles, `[GIT ERROR] Failed to revert commit: ${rawErr.slice(0, 110)}`);
          cp.exec(`${pyCmd} "${speakScript}" "Failed to revert the last commit, sir."`, { cwd: ws });
          vscode.window.showErrorMessage("Jarvis: Failed to revert commit.");
        } else {
          writeAll(statusFiles, "[GIT SUCCESS] Last committed changes reverted successfully.");
          cp.exec(`${pyCmd} "${speakScript}" "The last committed changes have been reverted successfully, sir."`, {
            cwd: ws,
          });
          vscode.window.showInformationMessage("Jarvis: Last committed changes reverted successfully.");
        }
        this.sendTelemetryUpdate();
      }
    );
  }

  private async handleBranchConfirmation(choice: "yes" | "no", branchOverride?: string): Promise<void> {
    const ws = this.processManager.getActiveWorkspace();
    let branchName = branchOverride || "test";
    let targetRepo = ws;

    const confFiles = [
      path.join(this.coreDir, "pending_confirmation.json"),
      path.join(ws, "pending_confirmation.json"),
    ];

    for (const confFile of confFiles) {
      if (fs.existsSync(confFile)) {
        try {
          const data = JSON.parse(fs.readFileSync(confFile, "utf-8"));
          if (data.branch_name) {
            branchName = data.branch_name;
          }
          if (data.target_repo && fs.existsSync(data.target_repo)) {
            targetRepo = data.target_repo;
          }
        } catch {}
        try {
          fs.unlinkSync(confFile);
        } catch {}
      }
    }

    if (!branchName || branchName === "test") {
      const statusFiles = [
        path.join(this.coreDir, "last_status.txt"),
        path.join(ws, "last_status.txt"),
      ];
      for (const sf of statusFiles) {
        if (fs.existsSync(sf)) {
          const txt = fs.readFileSync(sf, "utf-8");
          const m = txt.match(/branch\s+['"]([^'"]+)['"]/i) || txt.match(/'([^']+)'/);
          if (m && m[1]) {
            branchName = m[1];
            break;
          }
        }
      }
    }

    // Clean up intent cache if it was confirm_action
    const intentFiles = [
      path.join(this.coreDir, "last_intent.json"),
      path.join(ws, "last_intent.json"),
    ];
    for (const ifile of intentFiles) {
      if (fs.existsSync(ifile)) {
        try {
          const iData = JSON.parse(fs.readFileSync(ifile, "utf-8"));
          if (iData.type === "confirm_action") {
            fs.unlinkSync(ifile);
          }
        } catch {}
      }
    }

    const pyCmd = this.processManager.getPythonCmd();
    let execScript = path.join(this.coreDir, "execute_git.py");
    if (!fs.existsSync(execScript) && fs.existsSync(path.join(ws, "execute_git.py"))) {
      execScript = path.join(ws, "execute_git.py");
    }
    let speakScript = path.join(this.coreDir, "speak.py");
    if (!fs.existsSync(speakScript) && fs.existsSync(path.join(ws, "speak.py"))) {
      speakScript = path.join(ws, "speak.py");
    }

    const statusFiles = [
      path.join(this.coreDir, "last_status.txt"),
      path.join(ws, "last_status.txt"),
    ];
    const transcriptFiles = [
      path.join(this.coreDir, "last_transcript.txt"),
      path.join(ws, "last_transcript.txt"),
    ];

    const writeAll = (files: string[], content: string) => {
      for (const f of files) {
        try {
          fs.writeFileSync(f, content, "utf-8");
        } catch {}
      }
    };

    if (choice === "yes") {
      writeAll(transcriptFiles, `[CONFIRMED] Delete branch '${branchName}'`);
      writeAll(statusFiles, `[EXECUTING] Deleting branch '${branchName}' locally and from GitHub...`);
      this.sendTelemetryUpdate();

      cp.exec(
        `${pyCmd} "${execScript}" --delete-branch "${branchName}"`,
        {
          cwd: targetRepo,
          env: { ...process.env, TARGET_REPO_PATH: targetRepo },
        },
        (err, stdout, stderr) => {
          if (err) {
            const rawErr = (stderr || stdout || err.message).replace(/\r?\n/g, " ");
            writeAll(statusFiles, `[GIT ERROR] Failed to delete branch '${branchName}': ${rawErr.slice(0, 110)}`);
            cp.exec(`${pyCmd} "${speakScript}" "Failed to delete branch ${branchName}, sir."`, { cwd: targetRepo });
            vscode.window.showErrorMessage(`Jarvis: Failed to delete branch '${branchName}'`);
          } else {
            writeAll(statusFiles, `[GIT SUCCESS] Branch '${branchName}' deleted successfully.`);
            cp.exec(`${pyCmd} "${speakScript}" "Branch ${branchName} has been deleted successfully, sir."`, {
              cwd: targetRepo,
            });
            vscode.window.showInformationMessage(`Jarvis: Branch '${branchName}' deleted successfully.`);
          }
          this.sendTelemetryUpdate();
        }
      );
    } else {
      writeAll(transcriptFiles, `[CANCELLED] Branch '${branchName}' deletion cancelled`);
      writeAll(statusFiles, `[CANCELLED] Deletion of branch '${branchName}' cancelled by user.`);
      cp.exec(`${pyCmd} "${speakScript}" "Branch deletion cancelled, sir."`, { cwd: targetRepo });
      vscode.window.showInformationMessage(`Jarvis: Branch '${branchName}' deletion cancelled.`);
      this.sendTelemetryUpdate();
    }
  }

  private getHtmlForWebview(_webview: vscode.Webview): string {
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
    <button class="btn-warn" onclick="sendMessage('requestDeleteBranch')">🗑️ REMOVE BRANCH</button>
    <button class="btn-warn" onclick="sendMessage('revertCommit')">↩️ REVERT COMMIT</button>
    <button class="btn-primary" onclick="sendMessage('startListener')">🎤 START VOICE LISTENER</button>
    <button class="btn-danger" onclick="sendMessage('stopJarvis')">🛑 STOP / SILENCE JARVIS</button>
    <button onclick="sendMessage('openDesktopHud')">🖥️ DESKTOP HUD</button>
    <button onclick="sendMessage('restartN8n')">🔄 RESTART N8N</button>
    <button onclick="sendMessage('setGroqKey')">🔑 SET GROQ KEY</button>
    <button onclick="sendMessage('initProject')">🚀 INIT WORKSPACE</button>
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
}

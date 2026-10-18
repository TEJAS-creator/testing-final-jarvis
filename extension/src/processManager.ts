import * as vscode from "vscode";
import * as path from "path";
import * as cp from "child_process";
import * as fs from "fs";

export class ProcessManager {
  private listenerTerminal: vscode.Terminal | null = null;

  constructor(private readonly coreDir: string) {}

  /**
   * Resolves the current active workspace directory.
   */
  public getActiveWorkspace(): string {
    const wsFolders = vscode.workspace.workspaceFolders;
    if (wsFolders && wsFolders.length > 0) {
      return wsFolders[0].uri.fsPath;
    }
    return this.coreDir;
  }

  /**
   * Dynamically resolves whether to use 'py', 'python', or a configured python path.
   */
  public getPythonCmd(): string {
    const config = vscode.workspace.getConfiguration("jarvis");
    const configured = config.get<string>("pythonPath");
    if (configured && configured.trim().length > 0) {
      return configured.trim();
    }
    try {
      cp.execSync("py --version", { stdio: "ignore" });
      return "py";
    } catch {
      return "python";
    }
  }

  /**
   * Launches the Voice Listener in an integrated terminal.
   */
  public startVoiceListener(targetWorkspace?: string): void {
    const ws = targetWorkspace || this.getActiveWorkspace();
    let listenerScript = path.join(this.coreDir, "jarvis_listener.py");
    if (fs.existsSync(path.join(ws, "jarvis_listener.py"))) {
      listenerScript = path.join(ws, "jarvis_listener.py");
    }

    // Close existing terminal if already open
    if (this.listenerTerminal) {
      this.listenerTerminal.dispose();
      this.listenerTerminal = null;
    }

    this.listenerTerminal = vscode.window.createTerminal({
      name: "JARVIS LISTENER",
      cwd: ws,
      env: {
        TARGET_REPO_PATH: ws,
      },
      iconPath: new vscode.ThemeIcon("mic"),
    });

    const pyCmd = this.getPythonCmd();
    this.listenerTerminal.show(false);
    this.listenerTerminal.sendText(`${pyCmd} "${listenerScript}" --project "${ws}"`);
    vscode.window.showInformationMessage(
      `Jarvis Voice Assistant active for [${path.basename(ws).toUpperCase()}]. Say 'Hey Jarvis'!`
    );
  }

  /**
   * Stops active speech playback and the voice listener.
   */
  public stopVoiceListener(): void {
    const ws = this.getActiveWorkspace();
    const pyCmd = this.getPythonCmd();
    let speakScript = path.join(this.coreDir, "speak.py");
    if (fs.existsSync(path.join(ws, "speak.py"))) {
      speakScript = path.join(ws, "speak.py");
    }

    // 1. Immediately kill speech via python speak.py --stop
    try {
      cp.exec(`${pyCmd} "${speakScript}" --stop`, { cwd: ws });
    } catch {
      // Ignore
    }

    // 2. Set emergency stop flag and update status
    try {
      fs.writeFileSync(path.join(this.coreDir, "jarvis_stop.flag"), String(Date.now()), "utf-8");
      fs.writeFileSync(path.join(this.coreDir, "last_status.txt"), "[STOPPED] Jarvis halted by user.", "utf-8");
      if (ws !== this.coreDir) {
        fs.writeFileSync(path.join(ws, "jarvis_stop.flag"), String(Date.now()), "utf-8");
      }
    } catch {
      // Ignore
    }

    // 3. Stop listener terminal if active
    let hadTerminal = false;
    if (this.listenerTerminal) {
      this.listenerTerminal.dispose();
      this.listenerTerminal = null;
      hadTerminal = true;
    }

    vscode.window.showInformationMessage(
      hadTerminal ? "Jarvis: Voice Listener terminated and speech halted." : "Jarvis: Speech halted and systems silenced."
    );
  }

  /**
   * Spawns the native PyQt6 Sci-Fi holographic HUD window independently.
   */
  public launchDesktopHud(targetWorkspace?: string): void {
    const ws = targetWorkspace || this.getActiveWorkspace();
    let hudScript = path.join(this.coreDir, "jarvis_hud.py");
    if (fs.existsSync(path.join(ws, "jarvis_hud.py"))) {
      hudScript = path.join(ws, "jarvis_hud.py");
    }

    if (!fs.existsSync(hudScript)) {
      vscode.window.showErrorMessage(`Jarvis HUD script not found at ${hudScript}`);
      return;
    }

    const pyCmd = this.getPythonCmd();
    const executable = pyCmd === "py" ? "py.exe" : (pyCmd.endsWith(".exe") ? pyCmd : "python.exe");

    try {
      cp.spawn(executable, [hudScript, "--project", ws], {
        cwd: ws,
        detached: true,
        windowsHide: false,
        stdio: "ignore",
        env: {
          ...process.env,
          TARGET_REPO_PATH: ws,
        },
      }).unref();

      vscode.window.showInformationMessage(
        `Jarvis: Desktop Cyber HUD launched for [${path.basename(ws).toUpperCase()}].`
      );
    } catch (err: any) {
      vscode.window.showErrorMessage(`Failed to launch Desktop HUD: ${err.message || err}`);
    }
  }

  /**
   * Initializes Jarvis for the current open workspace folder.
   */
  public async initWorkspace(targetWorkspace?: string): Promise<void> {
    const ws = targetWorkspace || this.getActiveWorkspace();
    let cliScript = path.join(this.coreDir, "jarvis_cli.py");
    if (fs.existsSync(path.join(ws, "jarvis_cli.py"))) {
      cliScript = path.join(ws, "jarvis_cli.py");
    }

    const terminal = vscode.window.createTerminal({
      name: "JARVIS INIT",
      cwd: ws,
      iconPath: new vscode.ThemeIcon("rocket"),
    });

    const pyCmd = this.getPythonCmd();
    terminal.show();
    terminal.sendText(`${pyCmd} "${cliScript}" init "${ws}"`);
  }
}

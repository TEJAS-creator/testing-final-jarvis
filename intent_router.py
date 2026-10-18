#!/usr/bin/env python3
"""
Jarvis Low-Latency Codebase & Conversational AI Router
Features:
- Fast cached repository file crawler: `get_project_context()` with 120s TTL cache.
- Concise architectural digest keeps Groq prompt under 800 tokens for sub-200ms responses.
- Tri-mode routing: `codebase_qa` | `git_action` | `general_qa`.
- Output Schema:
  {
    "type": "codebase_qa" | "git_action" | "general_qa",
    "command": "<cli_command_if_git>",
    "speaking_start": "<task_description_if_git>",
    "speaking_response": "<direct_concise_spoken_answer_for_qa_or_completion>"
  }
"""

import sys
import os
import json
import re
import time
import subprocess
import requests
from dotenv import load_dotenv

# Load configuration
load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")

from jarvis_config import (
    JARVIS_CORE_DIR,
    get_target_repo,
    get_project_name,
    get_current_git_branch,
    is_n8n_online,
)

PROJECT_ROOT = JARVIS_CORE_DIR
TRANSCRIPT_CACHE_FILE = os.path.join(JARVIS_CORE_DIR, "last_transcript.txt")
INTENT_CACHE_FILE = os.path.join(JARVIS_CORE_DIR, "last_intent.json")
STATUS_CACHE_FILE = os.path.join(JARVIS_CORE_DIR, "last_status.txt")
CODEBASE_CACHE_FILE = os.path.join(JARVIS_CORE_DIR, "codebase_cache.json")
ANTIGRAVITY_TASK_FILE = os.path.join(JARVIS_CORE_DIR, "antigravity_task.json")
ANTIGRAVITY_PROMPT_FILE = os.path.join(JARVIS_CORE_DIR, "antigravity_prompt.txt")
CONFIRMATION_CACHE_FILE = os.path.join(JARVIS_CORE_DIR, "pending_confirmation.json")

def get_project_context(force_refresh: bool = False) -> str:
    """Scans and caches key project source files to answer codebase questions with zero delay."""
    target_repo = get_target_repo()
    cache_file = os.path.join(target_repo, ".jarvis", "codebase_cache.json") if target_repo != JARVIS_CORE_DIR else CODEBASE_CACHE_FILE

    if not force_refresh and os.path.exists(cache_file):
        try:
            mtime = os.path.getmtime(cache_file)
            if time.time() - mtime < 120:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    cached_text = data.get("context", "")
                    if cached_text:
                        return cached_text
        except Exception:
            pass

    context_parts = []
    if target_repo != JARVIS_CORE_DIR:
        candidate_files = []
        for root, dirs, files in os.walk(target_repo):
            dirs[:] = [d for d in dirs if d not in [".git", "node_modules", "venv", ".venv", "__pycache__", ".jarvis"]]
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in [".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".json", ".md", ".txt", ".go", ".rs"]:
                    full_p = os.path.join(root, file)
                    rel_p = os.path.relpath(full_p, target_repo)
                    candidate_files.append((rel_p, full_p))
                    if len(candidate_files) >= 12:
                        break
            if len(candidate_files) >= 12:
                break

        for relpath, filepath in candidate_files:
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                snippet = "".join(lines[:25]).strip()
                context_parts.append(f"[{relpath}]\n{snippet}\n")
            except Exception:
                continue
    else:
        core_files = [
            "jarvis_listener.py",
            "speak.py",
            "transcribe.py",
            "intent_router.py",
            "execute_git.py",
            "workflows/jarvis_workflow.json",
            "README.md",
        ]
        for relpath in core_files:
            filepath = os.path.join(JARVIS_CORE_DIR, relpath)
            if os.path.exists(filepath):
                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                    snippet = "".join(lines[:25]).strip()
                    context_parts.append(f"[{relpath}]\n{snippet}\n")
                except Exception:
                    continue

    summary = "\n".join(context_parts)
    try:
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump({"context": summary, "timestamp": time.time()}, f)
    except Exception:
        pass

    return summary

ANTIGRAVITY_TRIGGER_KEYWORDS = [
    "debug", "debug it", "debug this", "debug the code", "debug issue", "debug error",
    "troubleshoot", "diagnose",
    "bug fix", "fix bug", "code changes", "create app", "modify hud", "theme", "antigravity",
    "solve", "bug", "fix", "error", "repair", "broken", "issue", "crash",
    "generate", "create script", "write script", "make script", "build script",
    "refactor", "patch", "modify code", "edit code", "new feature", "add feature", "implement",
    "ui change", "dark mode"
]

def sync_to_clipboard(text: str) -> bool:
    """Syncs formatted text to Windows clipboard using pyperclip and clip.exe."""
    try:
        from antigravity_bridge import sync_to_clipboard as bridge_sync
        return bridge_sync(text)
    except Exception:
        try:
            proc = subprocess.Popen(["clip"], stdin=subprocess.PIPE, shell=True)
            proc.communicate(input=text.encode("utf-8"))
            print("[intent_router.py] Formatted prompt synchronized to Windows clipboard.", file=sys.stderr)
            return True
        except Exception as e:
            print(f"[intent_router.py] Clipboard sync error: {e}", file=sys.stderr)
            return False

def is_antigravity_intent(transcript: str) -> bool:
    """Detects whether transcript requires Antigravity code generation, debugging, bug fixing, or HUD styling."""
    t = transcript.lower()
    # Explicit exclusions: Git queries, branch operations, commits, pushes, and reverts are NEVER Antigravity
    if is_git_query(transcript) or is_branch_creation(transcript) or is_branch_deletion(transcript) or is_revert_commit(transcript):
        return False
    if any(w in t for w in ["branch", "commit", "push", "git status", "git log", "git remote", "repo"]):
        if not any(k in t for k in ["antigravity", "debug", "troubleshoot", "fix"]):
            return False

    # Explicit regex patterns for critical trigger phrases
    patterns = [
        r'\bdebug(?:\s+it|\s+this|\s+the|\s+code|\s+issue|\s+error|\s+app)?\b',
        r'\bbug\s*fix\b',
        r'\bfix\s*bug\b',
        r'\bcode\s*changes?\b',
        r'\bcreate\s*app\b',
        r'\bmodify\s*hud\b',
        r'\btheme\b',
        r'\bantigravity\b',
        r'\btroubleshoot\b',
        r'\bdiagnose\b',
    ]
    for p in patterns:
        if re.search(p, t):
            return True
    return any(w in t for w in ANTIGRAVITY_TRIGGER_KEYWORDS)

def is_git_query(transcript: str) -> bool:
    """Detects informational git questions (NOT action commands).
    Examples: 'what branch am I on?', 'which branch am I in?', 'show me git status'
    """
    t = transcript.lower()
    # Question patterns about git state
    query_patterns = [
        r'\b(?:what|which|show|tell|current|check|display)\b.*\bbranch\b',
        r'\bbranch\b.*\b(?:am i|are we|currently|right now|on|in)\b',
        r'\b(?:what|which|show)\b.*\b(?:status|log|remote|diff|changes)\b',
        r'\b(?:am i on|are we on)\b.*\bbranch\b',
        r'\b(?:show|list|display)\b.*\b(?:branches|remotes|tags)\b',
    ]
    for p in query_patterns:
        if re.search(p, t):
            return True
    return False

def is_stop_intent(transcript: str) -> bool:
    """Detects commands to immediately stop speech, cancel, or hush Jarvis.
    Catches variations and phonetic Whisper transcriptions like 'der hvis stopt', 'jarvis stop', 'be quiet', etc.
    """
    if not transcript:
        return False
    t = transcript.lower().strip()
    t = re.sub(r'[^\w\s]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    stop_keywords = [
        "stop", "stopt", "stopped", "stopping",
        "quiet", "silence", "hush", "shut up",
        "cancel", "abort", "halt", "pause speech",
        "stop talking", "stop speaking"
    ]
    words = t.split()
    if any(k in words for k in ["stop", "stopt", "stopped", "halt", "quiet", "silence", "cancel", "abort"]):
        return True
    return any(phrase in t for phrase in stop_keywords)

def check_pending_confirmation(transcript: str) -> dict | None:
    """Checks if there is an active pending branch confirmation and matches user affirmation or cancellation."""
    if not os.path.exists(CONFIRMATION_CACHE_FILE):
        return None
    try:
        if time.time() - os.path.getmtime(CONFIRMATION_CACHE_FILE) > 120:
            os.remove(CONFIRMATION_CACHE_FILE)
            return None
        with open(CONFIRMATION_CACHE_FILE, "r", encoding="utf-8") as f:
            cdata = json.load(f)
    except Exception:
        return None

    bname = cdata.get("branch_name", "").strip()
    target_repo = cdata.get("target_repo", get_target_repo())
    cd_prefix = f'cd "{target_repo}"'

    clean_t = transcript.lower().strip()
    clean_norm = re.sub(r"[^\w\s']", " ", clean_t)
    words = set(re.findall(r"\b[\w']+\b", clean_norm))

    # --- 1. NEGATION & CANCELLATION (Strict Priority) ---
    # Phrases like "don't remove the branch", "do not delete", "no", "cancel", "stop", "abort", "keep it"
    no_words = {"no", "nope", "nah", "negative", "cancel", "cancelled", "cancelling", "stop", "abort", "halt", "nevermind", "never", "dont", "don't"}
    has_no_word = any(w in words for w in no_words)

    no_patterns = [
        r"\bdon'?t\b",
        r"\bdo\s+not\b",
        r"\bnever\b",
        r"\bno\b",
        r"\bnope\b",
        r"\bnah\b",
        r"\bcancel\b",
        r"\babort\b",
        r"\bstop\b",
        r"\bkeep\b",
        r"\bleave\b",
        r"\bnot\s+(?:now|yet|today|ready)\b",
        r"\b(?:don'?t|do\s+not|never|not)\s+(?:remove|delete|drop|destroy|touch)\b",
        r"\b(?:keep|leave)\s+(?:it|the\s+branch|this\s+branch|branch)\b",
    ]
    is_no = has_no_word or any(bool(re.search(p, clean_t)) for p in no_patterns)

    # --- 2. AFFIRMATION / CONFIRMATION ---
    # Can ONLY be true if NO negation was detected
    is_yes = False
    if not is_no:
        yes_words = {"yes", "yeah", "yep", "yup", "sure", "proceed", "confirm", "confirmed", "affirmative", "correct"}
        has_yes_word = any(w in words for w in yes_words)

        yes_patterns = [
            r"\bgo\s+ahead\b",
            r"\bdo\s+it\b",
            r"\byes\s+please\b",
            r"\byes\s+(?:delete|remove)\b",
            r"\bconfirm\s+(?:delete|removal|deletion)\b",
            r"\bplease\s+(?:delete|remove)\b",
            r"\b(?:delete|remove)\s+(?:it|the\s+branch|this\s+branch)\b",
            r"^(?:ok|okay|k|sure|fine|delete|remove)$",
        ]
        has_yes_pattern = any(bool(re.search(p, clean_t)) for p in yes_patterns)
        is_yes = has_yes_word or has_yes_pattern

    if is_no:
        try:
            if os.path.exists(CONFIRMATION_CACHE_FILE):
                os.remove(CONFIRMATION_CACHE_FILE)
        except Exception:
            pass
        try:
            with open(STATUS_CACHE_FILE, "w", encoding="utf-8") as sf:
                sf.write(f"[CANCELLED] Deletion of branch '{bname}' cancelled by user.")
        except Exception:
            pass
        return {
            "type": "general_qa",
            "action": "",
            "target_file": "",
            "task_description": "Branch deletion cancelled",
            "command": "",
            "speaking_start": "",
            "speaking_progress": "",
            "speaking_response": f"Understood, sir. Branch {bname} will not be deleted.",
        }
    elif is_yes:
        try:
            if os.path.exists(CONFIRMATION_CACHE_FILE):
                os.remove(CONFIRMATION_CACHE_FILE)
        except Exception:
            pass
        return {
            "type": "git_action",
            "action": "delete_branch",
            "target_file": "",
            "task_description": f"Delete branch {bname}",
            "command": f'{cd_prefix} && git branch -D {bname} && git push origin --delete {bname}',
            "speaking_start": f"Confirmation received. Deleting branch {bname} locally and from GitHub, sir.",
            "speaking_progress": "",
            "speaking_response": f"Branch {bname} has been deleted successfully, sir.",
        }

    return None

def is_branch_deletion(transcript: str) -> bool:
    """Detects git branch deletion requests."""
    t = transcript.lower()
    if is_git_query(transcript):
        return False
    # If the user explicitly negates the deletion (e.g. "don't delete", "do not remove", "never remove the branch")
    if re.search(r"\b(?:don'?t|do\s+not|never|not|shouldn'?t)\b.*?\b(?:delete|remove|drop|destroy)\b", t):
        return False
    if re.search(r"\b(?:delete|remove|drop|destroy)\b.*?\b(?:not|no|never)\b", t):
        return False
    patterns = [
        r'\b(?:delete|remove|drop|destroy)\s+(?:the\s+)?(?:a\s+)?branch\b',
        r'\bbranch\s+(?:delete|deletion|remove|removal)\b',
        r'\b(?:delete|remove|drop|destroy)\s+(?:the\s+)?(?:a\s+)?[a-zA-Z0-9_\-\.\/\"\']+\s+branch\b',
        r'\b(?:delete|remove|drop|destroy)\s+branch\s+[a-zA-Z0-9_\-\.\/\"\']+',
    ]
    return any(bool(re.search(p, t)) for p in patterns)

def is_revert_commit(transcript: str) -> bool:
    """Detects intent to revert or undo last committed changes."""
    t = transcript.lower().strip()
    if is_git_query(transcript):
        return False
    patterns = [
        r'\b(?:revert|undo|rollback|roll\s+back)\s+(?:the\s+)?(?:last\s+|latest\s+)?(?:committed\s+)?(?:changes?|commits?|code)\b',
        r'\b(?:revert|undo|rollback|roll\s+back)\s+(?:the\s+)?(?:last|latest)\s+(?:commit|change)\b',
        r'\b(?:revert|undo)\s+(?:my\s+)?(?:last\s+)?commit\b',
        r'\b(?:revert|undo)\s+committed\s+changes?\b',
        r'\b(?:revert|undo)\s+(?:the\s+)?changes?\b',
        r'\bundo\s+my\s+changes?\b',
        r'\bgit\s+revert\b',
        r'\brollback\s+commit\b',
    ]
    if any(bool(re.search(p, t)) for p in patterns):
        return True

    has_verb = any(w in t for w in ["revert", "undo", "rollback"])
    has_target = any(w in t for w in ["commit", "committed", "changes", "change"])
    return has_verb and has_target

def is_branch_creation(transcript: str) -> bool:
    """Detects git branch creation requests. Excludes query/question, deletion, and repo creation patterns."""
    t = transcript.lower()
    if is_git_query(transcript) or is_branch_deletion(transcript) or is_revert_commit(transcript):
        return False
    # If transcript is specifically repo creation and doesn't mention branch, it's not branch creation
    if any(k in t for k in ["repo", "repository"]) and not any(b in t for b in ["branch", "checkout -b"]):
        return False
    patterns = [
        r'\b(?:create|created|creates|creating|make|makes|making|checkout|switch\s+to|new)\s+(?:a\s+)?(?:new\s+)?branch\b',
        r'\bbranch\s+(?:called|named|as)\b',
        r'\b(?:create|created)\s+branch\b',
        r'\bnew\s+branch\b',
        r'\bcheckout\s+-b\b',
    ]
    return any(bool(re.search(p, t)) for p in patterns)

def extract_branch_name(transcript: str) -> str:
    """Extracts and sanitizes git branch name from user speech.
    e.g. 'created branch "rapport-extension"' -> 'rapport-extension'
         'create branch feature-login' -> 'feature-login'
         'create a branch called jarvis test' -> 'jarvis-test'
         'remove the test branch' -> 'test'
    """
    t = transcript.strip()
    raw = ""
    # Quoted string first
    m_q = re.search(r'["\']([^"\']+)["\']', t)
    if m_q and any(w in t.lower() for w in ["branch"]):
        raw = m_q.group(1).strip()

    if not raw:
        m_del = re.search(r'(?:delete|remove|drop|destroy)\s+(?:the\s+)?(?:a\s+)?branch\s+(?:called\s+|named\s+)?([a-zA-Z0-9_\-\.\/\s]+)', t, re.IGNORECASE)
        if m_del:
            raw = m_del.group(1).strip()
    if not raw:
        m_del_adj = re.search(r'(?:delete|remove|drop|destroy)\s+(?:the\s+)?(?:a\s+)?([a-zA-Z0-9_\-\.\/]+)\s+branch', t, re.IGNORECASE)
        if m_del_adj:
            raw = m_del_adj.group(1).strip()
    if not raw:
        m = re.search(r'branch\s+(?:called|named|as)\s+([a-zA-Z0-9_\-\.\/\s]+)', t, re.IGNORECASE)
        if m:
            raw = m.group(1).strip()
    if not raw:
        m2 = re.search(r'(?:create|created|make|checkout|switch to|new)\s+(?:a\s+)?(?:new\s+)?branch\s+([a-zA-Z0-9_\-\.\/\s]+)', t, re.IGNORECASE)
        if m2:
            raw = m2.group(1).strip()
    if not raw:
        m3 = re.search(r'(?:called|named)\s+([a-zA-Z0-9_\-\.\/\s]+)', t, re.IGNORECASE)
        if m3:
            raw = m3.group(1).strip()
    if not raw:
        raw = "feature-branch"

    raw = re.sub(r'\b(?:please|sir|in|and|push|to github|now|for me|from github)\b.*$', '', raw, flags=re.IGNORECASE).strip()
    raw = raw.rstrip('.!?,;: ')
    sanitized = re.sub(r'\s+', '-', raw)
    sanitized = re.sub(r'[^a-zA-Z0-9_\-\.\/]', '', sanitized).lower()
    sanitized = sanitized.strip('.-/')
    sanitized = re.sub(r'\.{2,}', '.', sanitized)
    sanitized = re.sub(r'/{2,}', '/', sanitized)
    return sanitized if sanitized else "feature-branch"

def check_python_syntax(filepath: str) -> tuple[bool, str, int | None, str]:
    """Runs actual `python -m py_compile <filepath>` to capture real compilation status."""
    if not filepath or not os.path.exists(filepath):
        return True, "File does not exist yet", None, ""

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "py_compile", filepath],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True
        )
        if proc.returncode == 0:
            return True, "Syntax check passed. No compilation errors found.", None, ""

        err_output = (proc.stderr or proc.stdout or "").strip()
        line_num = None
        m = re.search(r'line\s+(\d+)', err_output, re.IGNORECASE)
        if m:
            line_num = int(m.group(1))

        lines = [l.strip() for l in err_output.splitlines() if l.strip()]
        error_line = lines[-1] if lines else "SyntaxError: compilation failure"
        offending_code = ""
        for i, l in enumerate(lines):
            if "line " in l.lower() and i + 1 < len(lines):
                offending_code = lines[i + 1]
                break

        if offending_code:
            error_details = f"{error_line}: {offending_code}"
        else:
            error_details = error_line

        return False, err_output, line_num, error_details
    except Exception as e:
        return False, str(e), None, str(e)

def extract_target_file(transcript: str) -> str:
    """Extracts target python filename from transcript or matches known codebase files."""
    m = re.search(r'([a-zA-Z0-9_\-]+\.py)', transcript, re.IGNORECASE)
    if m:
        return m.group(1).lower()

    known_files = [
        "jarvis_listener", "speak", "transcribe", "intent_router",
        "jarvis_hud", "execute_git", "execute_agent", "start_hud", "start_jarvis"
    ]
    t = transcript.lower()
    for kf in known_files:
        if kf in t:
            return f"{kf}.py"

    if any(w in t for w in ["hud", "gui", "theme", "dashboard"]):
        return "jarvis_hud.py"

    if any(w in t for w in ["generate", "create script", "write script", "make script", "build script", "create app"]):
        return "custom_tool.py"

    # Check if last_status mentions a specific python file with an error
    try:
        if os.path.exists(STATUS_CACHE_FILE):
            with open(STATUS_CACHE_FILE, "r", encoding="utf-8") as sf:
                st = sf.read()
                mf = re.search(r'([a-zA-Z0-9_\-]+\.py)', st, re.IGNORECASE)
                if mf:
                    return mf.group(1).lower()
    except Exception:
        pass

    return ""

def build_system_prompt() -> str:
    target_repo = get_target_repo()
    codebase_context = get_project_context()
    proj_name = get_project_name(target_repo)
    return f"""You are Jarvis, a brilliant AI systems assistant and autonomous coding engineer.
You automate Git commands, dispatch code generation and bug fixes to Antigravity, and answer questions about this codebase or general topics.

=== CODEBASE DIGEST ({proj_name.upper()} @ {target_repo}) ===
{codebase_context}
========================================

Classify the user's input into one of five types:
1. "antigravity_task": Instruction to fix a bug, solve an error, write a new script, generate code, create an app, modify the HUD, change themes, or refactor code.
   - Any transcript mentioning "bug fix", "fix bug", "code changes", "create app", "modify HUD", "theme", or "antigravity" MUST be classified as "antigravity_task".
   - action: "bug_fix" | "code_generation" | "refactor"
   - target_file: specific file mentioned or implied (e.g. "speak.py", "jarvis_hud.py", "custom_tool.py")
   - task_description: detailed actionable instructions for the code fix or generation.
   - speaking_start: "Delegating task to Antigravity Agent, sir."
   - speaking_progress: "Antigravity is reading <filename> and applying code patches..."
   - speaking_response: "Task completed, sir. Antigravity has resolved the issue in <filename>."
2. "codebase_qa": Question about this project, its code, files, architecture, or behavior (no code change requested).
3. "git_query": An INFORMATIONAL QUESTION about git state — e.g. "what branch am I on?", "which branch am I in?", "show me git status", "what's the last commit?", "list all branches".
   - CRITICAL: If the user asks a QUESTION about git (what/which/show/tell/current branch, status, log, etc.), this is a git_query, NOT a git_action.
   - "What branch am I currently in?" is a git_query, NOT a branch creation.
   - command: the git CLI command to run (e.g. "git branch --show-current", "git status", "git log --oneline -5")
   - speaking_response: A direct spoken answer describing what was found.
4. "git_action": An INSTRUCTION to perform a Git/GitHub WRITE operation:
   a. "create_branch": User explicitly requests creating or checking out a branch (e.g. "create branch dev", "created branch feature-auth", "make a branch called test").
      - action: "create_branch"
      - command: cd "{target_repo}" && (git checkout -b <branch> 2>nul || git checkout <branch>) && git push -u origin <branch>
      - speaking_start: "Creating branch <branch>, sir."
      - speaking_response: "Branch <branch> has been created successfully, sir."
   b. "create_repo": User requests creating a new GitHub repository (e.g. "create repo my-app", "create a repo called rapport-extension", "create repository api", "create a rapport extension github").
      - action: "create_repo"
      - target_file: "<repo_name>"
      - command: cd "{target_repo}" && gh repo create <repo_name> --public
      - speaking_start: "Creating new GitHub repository <repo_name>, sir."
      - speaking_response: "Repository <repo_name> has been created on GitHub successfully, sir."
   c. "push_code": User requests pushing code to a repository or to GitHub (e.g. "push code to repo rapport-extension", "push code to my-app", "push code", "push all code to github").
      - action: "push_code"
      - target_file: "<repo_name_if_specified>"
      - command: cd "{target_repo}" && git add -A && (git commit -m "Automated update via Jarvis" || echo "No changes to commit") && git push
      - speaking_start: "Pushing code to repository <repo_name>, sir."
      - speaking_response: "Code has been pushed to repository <repo_name> successfully, sir."
   d. "delete_branch": User requests deleting a branch (e.g. "delete branch old-feature").
      - action: "delete_branch"
   e. "revert_commit": User requests reverting or undoing committed changes (e.g. "revert the committed changes", "revert the last commit", "undo last commit", "revert commit", "undo committed changes").
      - action: "revert_commit"
      - command: cd "{target_repo}" && git revert HEAD --no-edit
      - speaking_start: "Reverting the last committed changes, sir."
      - speaking_response: "The last committed changes have been reverted successfully, sir."
5. "general_qa": General knowledge question, reasoning, conversation, or math.

CRITICAL DISAMBIGUATION RULES:
- "What branch am I on?" / "Which branch am I currently in?" = git_query (NOT git_action, NOT branch creation)
- "Create branch <branch>" / "Created branch <branch>" = git_action (action: "create_branch", NEVER create_repo, NEVER push_code)
- "Create repo <repo>" / "Make a repo <repo>" / "Create <repo> github" = git_action (action: "create_repo", NEVER create_branch)
- "Push code to repo <repo>" / "Push code" / "Push all code" = git_action (action: "push_code", pushes code to specified repo or current repo)
- "Revert the committed changes" / "Undo last commit" / "Revert last commit" = git_action (action: "revert_commit", NEVER push_code)
- "Show me the git status" / "What are my uncommitted changes?" = git_query

You must respond with ONLY a valid, raw JSON object matching the exact schema below.
DO NOT include markdown code blocks (```json), explanations, or preamble.

Strict Output Schema:
{{
  "type": "antigravity_task" | "codebase_qa" | "git_query" | "git_action" | "general_qa",
  "action": "bug_fix" | "code_generation" | "refactor" | "create_branch" | "create_repo" | "push_code" | "delete_branch" | "revert_commit" | "",
  "target_file": "<filename_or_repo_name>",
  "task_description": "<detailed_prompt>",
  "command": "<cli_command>",
  "speaking_start": "<short_task_start_announcement>",
  "speaking_progress": "<spoken_progress_announcement_if_antigravity>",
  "speaking_response": "<direct_spoken_answer_2_to_3_sentences_max>"
}}

Rules:
- For "antigravity_task":
  - command: "cd \"{target_repo}\" && python execute_agent.py antigravity_task.json"
  - speaking_start: "Delegating task to Antigravity Agent, sir."
- For "codebase_qa":
  - Use the codebase digest above to give an accurate, crisp, 2-sentence conversational answer.
  - command: "", action: "", target_file: "", speaking_start: "", speaking_progress: ""
- For "git_query":
  - command: the exact git command to answer the question (e.g. "git branch --show-current", "git status --short", "git log --oneline -5")
  - speaking_start: ""
  - speaking_response: will be filled dynamically with the command output
- For "git_action":
  - For branch creation (e.g. "create branch feature" or "created branch dev"):
    command: cd "{target_repo}" && (git checkout -b <branch> 2>nul || git checkout <branch>) && git push -u origin <branch>
    action: "create_branch"
    speaking_start: "Creating branch <branch>, sir."
    speaking_response: "Branch <branch> has been created successfully, sir."
  - For repository creation (e.g. "create repo rapport-extension" or "create a repo called my-app"):
    command: cd "{target_repo}" && gh repo create <repo_name> --public
    action: "create_repo"
    target_file: "<repo_name>"
    speaking_start: "Creating new GitHub repository <repo_name>, sir."
    speaking_response: "Repository <repo_name> has been created on GitHub successfully, sir."
  - For push code (e.g. "push code to repo rapport-extension" or "push code"):
    command: cd "{target_repo}" && git add -A && (git commit -m "Automated update via Jarvis" || echo "No changes to commit") && git push
    action: "push_code"
    target_file: "<repo_name_if_specified>"
    speaking_start: "Pushing code to repository <repo_name>, sir."
    speaking_response: "Code has been pushed to repository <repo_name> successfully, sir."
- For "general_qa":
  - Provide a concise spoken answer (1-2 sentences maximum).
  - command: "", action: "", target_file: "", speaking_start: "", speaking_progress: ""

Examples:
1. "Jarvis, create branch feature" ->
{{
  "type": "git_action",
  "action": "create_branch",
  "target_file": "",
  "task_description": "Create branch feature",
  "command": "cd \\"{target_repo}\\" && (git checkout -b feature 2>nul || git checkout feature) && git push -u origin feature",
  "speaking_start": "Creating branch feature, sir.",
  "speaking_progress": "",
  "speaking_response": "Branch feature has been created successfully, sir."
}}

2. "Jarvis, create repo rapport-extension" ->
{{
  "type": "git_action",
  "action": "create_repo",
  "target_file": "rapport-extension",
  "task_description": "Create GitHub repository rapport-extension",
  "command": "cd \\"{target_repo}\\" && gh repo create rapport-extension --public",
  "speaking_start": "Creating new GitHub repository rapport-extension, sir.",
  "speaking_progress": "",
  "speaking_response": "Repository rapport-extension has been created on GitHub successfully, sir."
}}

3. "Jarvis, push code to repo rapport-extension" ->
{{
  "type": "git_action",
  "action": "push_code",
  "target_file": "rapport-extension",
  "task_description": "Push code to repo rapport-extension",
  "command": "cd \\"{target_repo}\\" && git add -A && (git commit -m \\"Automated update via Jarvis\\" || echo \\"No changes\\") && git push",
  "speaking_start": "Pushing code to repository rapport-extension, sir.",
  "speaking_progress": "",
  "speaking_response": "Code has been pushed to repository rapport-extension successfully, sir."
}}

4. "Jarvis, solve the bug in speak.py" ->
{{
  "type": "antigravity_task",
  "action": "bug_fix",
  "target_file": "speak.py",
  "task_description": "Diagnose and resolve audio playback and edge-tts synthesis locking bug in speak.py",
  "command": "cd \\"{target_repo}\\" && python execute_agent.py antigravity_task.json",
  "speaking_start": "Delegating task to Antigravity Agent, sir.",
  "speaking_progress": "Antigravity is reading speak.py and applying code patches...",
  "speaking_response": "Task completed, sir. Antigravity has resolved the issue in speak.py."
}}
"""

def resolve_git_query_command(transcript: str) -> str:
    """Maps informational git questions to the correct git CLI command."""
    t = transcript.lower()
    # Check current branch specific queries first
    if any(w in t for w in ["which branch am", "what branch am", "current branch", "am i on", "are we on", "which branch are"]):
        return "git branch --show-current"
    # General branch listing queries
    if any(w in t for w in ["all branch", "list branch", "show branch", "what branch", "branches in", "how many branch", "available branch", "the branch", "branches", "branch list"]):
        return "git branch -a"
    if any(w in t for w in ["status", "changes", "uncommitted", "modified"]):
        return "git status --short"
    if any(w in t for w in ["log", "commit history", "last commit", "recent commit"]):
        return "git log --oneline -5"
    if any(w in t for w in ["remote", "origin", "url"]):
        return "git remote -v"
    if any(w in t for w in ["diff", "difference"]):
        return "git diff --stat"
    if any(w in t for w in ["tag", "tags"]):
        return "git tag"
    return "git status"

def execute_git_query(git_cmd: str, transcript: str) -> str:
    """Executes a git query command and formats a concise spoken answer."""
    try:
        target_repo = get_target_repo()

        res = subprocess.run(git_cmd.split(), cwd=target_repo, capture_output=True, text=True)
        out = (res.stdout.strip() or res.stderr.strip() or "")

        if "show-current" in git_cmd:
            if not out:
                return "You are currently not on any branch, sir."
            return f"You are currently on the {out} branch, sir."
        elif "branch" in git_cmd:
            # 1. Prune deleted remote branches from origin
            subprocess.run(["git", "fetch", "--prune", "origin"], cwd=target_repo, capture_output=True)

            # 2. Automatically delete dead local branches whose upstream was deleted on GitHub (marked [gone])
            vv_proc = subprocess.run(["git", "branch", "-vv"], cwd=target_repo, capture_output=True, text=True)
            for vv_line in vv_proc.stdout.splitlines():
                if ": gone]" in vv_line:
                    gone_b = vv_line.strip().lstrip("*").split()[0]
                    if gone_b not in ["main", "master"]:
                        if vv_line.strip().startswith("*"):
                            subprocess.run(["git", "checkout", "main"], cwd=target_repo, capture_output=True)
                        subprocess.run(["git", "branch", "-D", gone_b], cwd=target_repo, capture_output=True)

            # 3. Query remote branches from origin (true repository branches on GitHub)
            r_proc = subprocess.run(["git", "branch", "-r"], cwd=target_repo, capture_output=True, text=True)
            branches = set()
            for line in r_proc.stdout.splitlines():
                clean = line.strip()
                if not clean or "->" in clean:
                    continue
                if clean.startswith("origin/"):
                    clean = clean.replace("origin/", "")
                branches.add(clean)

            # If no remote branches found (offline repo), fallback to local active branches
            if not branches:
                l_proc = subprocess.run(["git", "branch"], cwd=target_repo, capture_output=True, text=True)
                for line in l_proc.stdout.splitlines():
                    clean = line.strip().lstrip("*").strip()
                    if clean:
                        branches.add(clean)

            branch_list = sorted(branches)
            if not branch_list:
                return "No branches found in repository, sir."
            if len(branch_list) == 1:
                return f"There is 1 branch: {branch_list[0]}, sir."
            return f"The branches in your repository are: {', '.join(branch_list)}, sir."
        elif "status" in git_cmd:
            if not out:
                return "Your working tree is clean with no uncommitted changes, sir."
            return "Your working tree has uncommitted modifications, sir."
        elif "log" in git_cmd:
            if not out:
                return "No commit history found, sir."
            first_line = out.splitlines()[0] if out.splitlines() else out
            return f"The latest commit is: {first_line}, sir."
        elif "remote" in git_cmd:
            if not out:
                return "No remote repositories configured, sir."
            return f"Your repository remotes are configured, sir."
        else:
            return f"Git reports: {out[:80]}, sir."
    except Exception as e:
        return f"Unable to check git status: {e}"

def is_repo_creation(transcript: str) -> bool:
    """Detects intent to create a new GitHub repository."""
    t = transcript.lower()
    if is_git_query(transcript) or is_branch_deletion(transcript) or is_revert_commit(transcript):
        return False
    # If transcript is specifically branch creation and doesn't mention repo, exclude
    if any(k in t for k in ["branch", "checkout -b"]) and not any(r in t for r in ["repo", "repository"]):
        return False
    direct_keywords = [
        "create repo", "created repo", "create a repo", "created a repo",
        "make repo", "make a repo", "make a new repo", "new repo",
        "create repository", "created repository", "create a repository",
        "make repository", "make a repository", "new repository"
    ]
    if any(k in t for k in direct_keywords):
        return True
    patterns = [
        r'\b(?:create|created|creates|make|makes|new|init|initialize)\s+(?:a\s+)?(?:new\s+)?(?:github\s+)?(?:repo|repository)\b',
        r'\b(?:repo|repository)\s+(?:called|named|as)\b',
        r'\b(?:create|created|make)\s+(?:a\s+)?(?:new\s+)?([a-zA-Z0-9_\-\s]+?)\s+(?:github\s+)?(?:repo|repository)\b',
        r'\b(?:create|created|make)\s+(?:a\s+)?([a-zA-Z0-9_\-\s]+?)\s+github\b',
    ]
    return any(bool(re.search(p, t)) for p in patterns)

def is_push_code(transcript: str) -> bool:
    """Detects intent to push code to a repository or GitHub."""
    t = transcript.lower()
    if is_git_query(transcript) or is_branch_deletion(transcript) or is_revert_commit(transcript):
        return False
    patterns = [
        r'\bpush\s+(?:all\s+)?(?:the\s+)?(?:my\s+)?(?:code|changes|files|commits?)\b',
        r'\bpush\s+(?:code\s+)?to\s+(?:the\s+)?(?:repo|repository|github)\b',
        r'\bpush\s+to\s+(?:repo|repository)\b',
        r'\bpush\s+(?:code\s+)?to\s+([a-zA-Z0-9_\-\.]+)',
        r'\bcommit\s+and\s+push\b',
        r'\bpush\s+code\b',
        r'\bpush\s+changes\b',
        r'\bpush\s+to\s+github\b',
    ]
    return any(bool(re.search(p, t)) for p in patterns)

def extract_repo_name(t: str, default: str = "project-repo") -> str:
    """Extracts desired repository name from transcript or command string."""
    if not t:
        return default
    text = t.strip()

    # 1. Quoted string
    m_quoted = re.search(r'["\']([^"\']+)["\']', text)
    if m_quoted:
        cand = m_quoted.group(1).strip()
        clean = re.sub(r'[^a-zA-Z0-9_\-\.]', '-', cand).strip('-')
        clean = re.sub(r'-+', '-', clean)
        if clean and clean.lower() not in ['repo', 'repository', 'github', 'branch']:
            return clean

    # 2. 'named <name>', 'called <name>'
    m_named = re.search(r'(?:named|called|as)\s+([a-zA-Z0-9_\-\s]+?)(?:\s+(?:and|to|files?|on|in|please|sir)|\.|$)', text, re.IGNORECASE)
    if m_named:
        cand = m_named.group(1).strip()
        cand = re.sub(r'\s+(?:repo|repository|github|files?|and|please|sir)$', '', cand, flags=re.IGNORECASE).strip()
        clean = re.sub(r'[^a-zA-Z0-9_\-\.]', '-', cand).strip('-')
        clean = re.sub(r'-+', '-', clean)
        if clean and clean.lower() not in ['new', 'a', 'the', 'my', 'and', 'push', 'repo', 'repository']:
            return clean

    # 3. 'push code to (?:repo|repository)? <name>'
    m_push = re.search(r'push\s+(?:code|changes|files?)?\s*(?:to\s+)?(?:repo|repository)?\s+([a-zA-Z0-9_\-\s]+?)(?:\s+(?:on|in|please|sir)|\.|$)', text, re.IGNORECASE)
    if m_push:
        cand = m_push.group(1).strip()
        cand = re.sub(r'^(?:repo|repository|to)\s+', '', cand, flags=re.IGNORECASE).strip()
        cand = re.sub(r'\s+(?:repo|repository|github|files?|and|please|sir)$', '', cand, flags=re.IGNORECASE).strip()
        clean = re.sub(r'[^a-zA-Z0-9_\-\.]', '-', cand).strip('-')
        clean = re.sub(r'-+', '-', clean)
        if clean and clean.lower() not in ['new', 'a', 'the', 'my', 'and', 'push', 'repo', 'repository', 'github', 'origin']:
            return clean

    # 4. '(?:create|new|make)\s+(?:a\s+)?(?:new\s+)?(?:github\s+)?(?:repo|repository)\s+([a-zA-Z0-9_\-\s]+?)(?:\s+(?:and|files?|on|in|to|please|sir)|\.|$)'
    m_repo = re.search(r'(?:create|created|make|new|init)\s+(?:a\s+)?(?:new\s+)?(?:github\s+)?(?:repo|repository)\s+([a-zA-Z0-9_\-\s]+?)(?:\s+(?:and|files?|on|in|to|please|sir)|\.|$)', text, re.IGNORECASE)
    if m_repo:
        cand = m_repo.group(1).strip()
        cand = re.sub(r'\s+(?:repo|repository|github|files?|and|please|sir)$', '', cand, flags=re.IGNORECASE).strip()
        clean = re.sub(r'[^a-zA-Z0-9_\-\.]', '-', cand).strip('-')
        clean = re.sub(r'-+', '-', clean)
        if clean and clean.lower() not in ['new', 'a', 'the', 'my', 'and', 'push', 'repo', 'repository', 'github']:
            return clean

    # 5. '<name> (?:repo|repository|github)' e.g. 'Create a rapport extension GitHub.'
    m_trail = re.search(r'(?:create|created|make|new)\s+(?:a\s+)?([a-zA-Z0-9_\-\s]+?)\s+(?:github|repo|repository)(?:\s+(?:and|please|sir)|\.|$)', text, re.IGNORECASE)
    if m_trail:
        cand = m_trail.group(1).strip()
        clean = re.sub(r'[^a-zA-Z0-9_\-\.]', '-', cand).strip('-')
        clean = re.sub(r'-+', '-', clean)
        if clean and clean.lower() not in ['new', 'a', 'the', 'my', 'and', 'push', 'repo', 'repository', 'github']:
            return clean

    return default

def build_default_intent(transcript: str) -> dict:
    target_repo = get_target_repo()
    proj_name = get_project_name(target_repo)
    # 0. Emergency Stop Intent (Immediate Priority)
    if is_stop_intent(transcript):
        return {
            "type": "stop_action",
            "action": "stop",
            "target_file": "",
            "task_description": "Stop all speech and operations",
            "command": "python speak.py --stop",
            "speaking_start": "",
            "speaking_progress": "",
            "speaking_response": "",
        }

    # 0b. Active Pending Confirmation Check (Yes / No)
    pending_conf = check_pending_confirmation(transcript)
    if pending_conf:
        return pending_conf

    cd_prefix = f'cd "{target_repo}"'
    t = transcript.lower()

    # 1. Antigravity Coding, Bug Fixing, App Creation, HUD & Theme Intent (Immediate Priority)
    if is_antigravity_intent(transcript):
        target_file = extract_target_file(transcript)
        target_path = os.path.join(target_repo, target_file) if target_file else ""

        # Retrieve recent error context from status cache if available
        last_err_context = ""
        try:
            if os.path.exists(STATUS_CACHE_FILE):
                with open(STATUS_CACHE_FILE, "r", encoding="utf-8") as sf:
                    st_content = sf.read().strip()
                    if any(ew in st_content.lower() for ew in ["error", "fail", "defect", "exception"]):
                        last_err_context = st_content
        except Exception:
            pass

        if any(w in t for w in ["debug", "troubleshoot", "diagnose"]):
            action = "debug"
        elif "refactor" in t:
            action = "refactor"
        elif any(w in t for w in ["generate", "create", "write", "make", "build", "create app"]):
            action = "code_generation"
        else:
            action = "bug_fix"

        valid, full_tb, line_num, err_details = check_python_syntax(target_path) if target_path and os.path.exists(target_path) else (True, "", None, "")
        if not valid:
            action = "bug_fix"
            if line_num:
                speaking_response = f"Syntax error detected on line {line_num} in {target_file}. Dispatched fix prompt directly to Antigravity, sir."
                task_desc = f"@{target_file} Fix the compilation error on line {line_num}: {err_details}. Resolve this issue now."
            else:
                speaking_response = f"Syntax error detected in {target_file}. Dispatched fix prompt directly to Antigravity, sir."
                task_desc = f"@{target_file} Fix the compilation error: {err_details}. Resolve this issue now."
        else:
            if action == "debug":
                speaking_response = f"Dispatched debug directive to Antigravity Agent, sir. Investigating the issue now."
                task_desc = f"Debug and resolve the issue: {transcript}." + (f" Recent error context: {last_err_context}" if last_err_context else "")
            elif action == "code_generation":
                speaking_response = f"Delegating code generation for {target_file or 'tool'} to Antigravity Agent, sir."
                task_desc = transcript
            else:
                speaking_response = f"Delegating task to Antigravity Agent, sir. Inspecting {target_file or 'the workspace'}."
                task_desc = transcript

        return {
            "type": "antigravity_task",
            "action": action,
            "target_file": target_file,
            "task_description": task_desc,
            "command": f'{cd_prefix} && python execute_agent.py antigravity_task.json',
            "speaking_start": "Delegating task to Antigravity Agent, sir.",
            "speaking_progress": f"Antigravity is checking {target_file or 'the project'}...",
            "speaking_response": speaking_response,
        }

    # 2. Git QUERY Intent — informational questions about git state (MUST come before branch creation check)
    if is_git_query(transcript):
        git_cmd = resolve_git_query_command(transcript)
        speaking_resp = execute_git_query(git_cmd, transcript)
        return {
            "type": "git_query",
            "action": "",
            "target_file": "",
            "task_description": f"Answering git query: {transcript}",
            "command": git_cmd,
            "speaking_start": "",
            "speaking_progress": "",
            "speaking_response": speaking_resp,
        }

    # 3. Branch Deletion Intent (Requires Explicit User Confirmation)
    if is_branch_deletion(transcript):
        bname = extract_branch_name(transcript)
        if bname in ["main", "master"]:
            return {
                "type": "general_qa",
                "action": "",
                "target_file": "",
                "task_description": "Protected branch deletion rejected",
                "command": "",
                "speaking_start": "",
                "speaking_progress": "",
                "speaking_response": f"Cannot delete protected default branch {bname}, sir.",
            }

        # Store pending confirmation state
        try:
            with open(CONFIRMATION_CACHE_FILE, "w", encoding="utf-8") as cf:
                json.dump({
                    "action": "delete_branch",
                    "branch_name": bname,
                    "target_repo": target_repo,
                    "timestamp": time.time(),
                    "task_description": f"Delete branch {bname}"
                }, cf, indent=2)
            with open(STATUS_CACHE_FILE, "w", encoding="utf-8") as sf:
                sf.write(f"[CONFIRMATION REQUIRED] Delete branch '{bname}'? Say YES to confirm or NO to cancel.")
        except Exception as e:
            print(f"[intent_router.py] Confirmation cache notice: {e}", file=sys.stderr)

        return {
            "type": "confirm_action",
            "action": "delete_branch",
            "branch_name": bname,
            "target_file": "",
            "task_description": f"Confirm deletion of branch {bname}",
            "command": "",
            "speaking_start": "",
            "speaking_progress": "",
            "speaking_response": f"Are you sure you want to remove the {bname} branch, sir? Please say yes to confirm or no to cancel.",
            "requires_confirmation": True
        }

    # 3b. Revert Last Commit Intent (Undo Committed Changes)
    if is_revert_commit(transcript):
        return {
            "type": "git_action",
            "action": "revert_commit",
            "target_file": "",
            "task_description": "Revert last committed changes",
            "command": f'{cd_prefix} && python execute_git.py --revert-commit',
            "speaking_start": "Reverting the last committed changes, sir.",
            "speaking_progress": "Undoing the last commit and syncing repository...",
            "speaking_response": "The last committed changes have been reverted successfully, sir.",
        }

    # 4. Branch Creation Intent
    if is_branch_creation(transcript):
        bname = extract_branch_name(transcript)
        return {
            "type": "git_action",
            "action": "create_branch",
            "target_file": "",
            "task_description": f"Create branch {bname}",
            "command": (
                f'{cd_prefix} && (git checkout -b {bname} 2>nul || git checkout {bname}) && git push -u origin {bname}'
            ),
            "speaking_start": f"Creating branch {bname}, sir.",
            "speaking_progress": "",
            "speaking_response": f"Branch {bname} has been created successfully, sir.",
        }

    # 5. Repository Creation Intent (Dedicated Handler)
    if is_repo_creation(transcript):
        repo_name = extract_repo_name(transcript, default=proj_name)
        if any(w in t for w in ["and push", "push code", "push files"]):
            return {
                "type": "git_action",
                "action": "create_repo_and_push",
                "target_file": repo_name,
                "task_description": f"Create GitHub repository {repo_name} and push code",
                "command": f'{cd_prefix} && gh repo create {repo_name} --public --source=. --remote=origin --push',
                "speaking_start": f"Creating new GitHub repository {repo_name} and pushing workspace files, sir.",
                "speaking_progress": "",
                "speaking_response": f"Repository {repo_name} has been created on GitHub and files pushed successfully, sir.",
            }
        return {
            "type": "git_action",
            "action": "create_repo",
            "target_file": repo_name,
            "task_description": f"Create GitHub repository {repo_name}",
            "command": f'{cd_prefix} && gh repo create {repo_name} --public',
            "speaking_start": f"Creating new GitHub repository {repo_name}, sir.",
            "speaking_progress": "",
            "speaking_response": f"Repository {repo_name} has been created on GitHub successfully, sir.",
        }

    # 6. Push Code Intent (Dedicated Handler)
    if is_push_code(transcript):
        repo_name = extract_repo_name(transcript, default="")
        spk_start = f"Pushing code to repository {repo_name}, sir." if repo_name else "Pushing code to GitHub, sir."
        spk_resp = f"Code has been pushed to repository {repo_name} successfully, sir." if repo_name else "Code has been pushed to GitHub successfully, sir."
        return {
            "type": "git_action",
            "action": "push_code",
            "target_file": repo_name,
            "task_description": f"Push code to repo {repo_name}" if repo_name else "Push code to GitHub",
            "command": (
                f'{cd_prefix} && git add -A && '
                f'(git commit -m "Automated update via Jarvis" || echo "No changes to commit") && '
                f'git push'
            ),
            "speaking_start": spk_start,
            "speaking_progress": "",
            "speaking_response": spk_resp,
        }

    # 7. Standard Git Commit & Push Fallback
    if any(w in t for w in ["push", "commit"]):
        return {
            "type": "git_action",
            "action": "push_code",
            "target_file": "",
            "task_description": "Git commit and push",
            "command": (
                f'{cd_prefix} && git init && git add . && '
                f'(git commit -m "Automated update via Jarvis" || echo "No changes to commit") && '
                f'(git push || gh repo create "{proj_name}" --public --source=. --remote=origin --push)'
            ),
            "speaking_start": "Executing task: committing and pushing changes, sir.",
            "speaking_progress": "",
            "speaking_response": "Task completed successfully, sir.",
        }
    elif any(w in t for w in ["status", "changes"]):
        return {
            "type": "git_query",
            "action": "",
            "target_file": "",
            "task_description": "Git status check",
            "command": "git status --short",
            "speaking_start": "",
            "speaking_progress": "",
            "speaking_response": "",
        }
    else:
        return {
            "type": "general_qa",
            "action": "",
            "target_file": "",
            "task_description": "",
            "command": "",
            "speaking_start": "",
            "speaking_progress": "",
            "speaking_response": "I am standing by, sir. How may I assist you?",
        }

def clean_spoken_text(text: str) -> str:
    """Strips markdown asterisks, backticks, hashes, and formatting for clear TTS."""
    if not text:
        return ""
    # Strip markdown code blocks
    t = re.sub(r"```(?:[a-zA-Z0-9_\-]+)?\s*.*?\s*```", "", text, flags=re.DOTALL)
    # Strip inline code formatting `code`
    t = re.sub(r"`([^`]+)`", r"\1", t)
    # Strip markdown bold / italics
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)
    t = re.sub(r"\*([^*]+)\*", r"\1", t)
    t = re.sub(r"__([^_]+)__", r"\1", t)
    t = re.sub(r"_([^_]+)_", r"\1", t)
    # Strip markdown headers, blockquotes, bullets
    t = re.sub(r"^#+\s*", "", t, flags=re.MULTILINE)
    t = re.sub(r"^>\s*", "", t, flags=re.MULTILINE)
    t = re.sub(r"^[\*\-\+]\s+", "", t, flags=re.MULTILINE)
    # Strip markdown links [text](url) -> text
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    # Clean whitespace and newlines
    t = re.sub(r"[\r\n]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()

    # Limit to 2 concise sentences max for optimal voice delivery
    sentences = re.split(r'(?<=[.!?])\s+', t)
    if len(sentences) > 2:
        t = " ".join(sentences[:2]).strip()

    return t

def sanitize_json(raw_text: str, transcript: str) -> dict:
    clean = raw_text.strip()
    clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.MULTILINE)
    clean = re.sub(r"\s*```$", "", clean, flags=re.MULTILINE)
    clean = clean.replace("```json", "").replace("```", "").strip()

    start = clean.find("{")
    end = clean.rfind("}")
    if start != -1 and end != -1 and end > start:
        clean = clean[start : end + 1].strip()

    try:
        data = json.loads(clean)
    except Exception:
        return build_default_intent(transcript)

    req_type = str(data.get("type", "general_qa")).strip()
    cmd = str(data.get("command", "")).strip()

    # STRICT OVERRIDE: Emergency stop command
    if is_stop_intent(transcript):
        return build_default_intent(transcript)

    # STRICT OVERRIDE: Check active branch deletion confirmation first
    pending_conf = check_pending_confirmation(transcript)
    if pending_conf:
        return pending_conf

    # STRICT OVERRIDE: Branch deletion ALWAYS requires confirmation
    if is_branch_deletion(transcript):
        return build_default_intent(transcript)

    # STRICT OVERRIDE: Force git_query if the transcript is an informational git question
    if is_git_query(transcript):
        req_type = "git_query"
        cmd = resolve_git_query_command(transcript)
    cd_prefix = f'cd "{PROJECT_ROOT}"'

    # STRICT OVERRIDE: Force antigravity_task if any trigger keywords are in the transcript
    if is_antigravity_intent(transcript):
        req_type = "antigravity_task"

    # STRICT OVERRIDE: Force git_action if branch creation, repo creation, or push code
    if is_branch_creation(transcript) or is_repo_creation(transcript) or is_push_code(transcript):
        req_type = "git_action"

    target_file = str(data.get("target_file", "")).strip()
    if req_type == "antigravity_task" and not target_file:
        target_file = extract_target_file(transcript)

    raw_resp = str(data.get("speaking_response", ""))
    speaking_resp = clean_spoken_text(raw_resp)
    if not speaking_resp:
        if req_type == "codebase_qa":
            speaking_resp = "Codebase analysis complete, sir. Standing by for instructions."
        elif req_type == "git_action":
            speaking_resp = "Git task completed successfully, sir."
        elif req_type == "antigravity_task":
            speaking_resp = f"Task completed, sir. Antigravity has resolved the issue in {target_file}."
        else:
            speaking_resp = "I am standing by, sir. How may I assist you?"

    if req_type == "antigravity_task":
        action = str(data.get("action", "bug_fix")).strip() or "bug_fix"
        if any(w in transcript.lower() for w in ["debug", "troubleshoot", "diagnose"]):
            action = "debug"
        target_path = os.path.join(PROJECT_ROOT, target_file) if target_file else ""
        valid, full_tb, line_num, err_details = check_python_syntax(target_path) if target_path and os.path.exists(target_path) else (True, "", None, "")
        if not valid:
            action = "bug_fix"
            if line_num:
                speaking_resp = f"Syntax error detected on line {line_num} in {target_file}. Dispatched fix prompt directly to Antigravity, sir."
                task_desc = f"@{target_file} Fix the compilation error on line {line_num}: {err_details}. Resolve this issue now."
            else:
                speaking_resp = f"Syntax error detected in {target_file}. Dispatched fix prompt directly to Antigravity, sir."
                task_desc = f"@{target_file} Fix the compilation error: {err_details}. Resolve this issue now."
        elif action == "debug":
            speaking_resp = f"Dispatched debug directive to Antigravity Agent, sir. Investigating the issue now."
            task_desc = str(data.get("task_description", transcript)).strip()
        elif not speaking_resp or speaking_resp.startswith("Task completed"):
            speaking_resp = f"Delegating task to Antigravity Agent, sir. Inspecting {target_file or 'the workspace'}."
            task_desc = str(data.get("task_description", transcript)).strip()
        else:
            task_desc = str(data.get("task_description", transcript)).strip()

        start = "Delegating task to Antigravity Agent, sir."
        prog = clean_spoken_text(str(data.get("speaking_progress", f"Antigravity is checking {target_file}...")))
        if not cmd:
            cmd = f'{cd_prefix} && python execute_agent.py antigravity_task.json'
        elif not cmd.startswith("cd "):
            cmd = f'{cd_prefix} && {cmd}'

        return {
            "type": "antigravity_task",
            "action": action,
            "target_file": target_file,
            "task_description": task_desc,
            "command": cmd,
            "speaking_start": start,
            "speaking_progress": prog,
            "speaking_response": speaking_resp,
        }

    if req_type == "git_query":
        if not cmd:
            cmd = resolve_git_query_command(transcript)
        speaking_resp = execute_git_query(cmd, transcript)
        return {
            "type": "git_query",
            "action": "",
            "target_file": "",
            "task_description": f"Answering git query: {transcript}",
            "command": cmd,
            "speaking_start": "",
            "speaking_progress": "",
            "speaking_response": speaking_resp,
        }

    action_val = str(data.get("action", "")).strip()
    task_desc = str(data.get("task_description", "")).strip()
    start = clean_spoken_text(str(data.get("speaking_start", "")))
    prog = clean_spoken_text(str(data.get("speaking_progress", "")))

    if req_type == "git_action":
        if is_branch_deletion(transcript):
            action_val = "delete_branch"
            bname = extract_branch_name(transcript)
            cmd = f'{cd_prefix} && git branch -D {bname} && git push origin --delete {bname}'
            start = f"Deleting branch {bname} locally and from GitHub, sir."
            speaking_resp = f"Branch {bname} has been deleted successfully, sir."
            task_desc = f"Delete branch {bname}"
            target_file = ""
        elif is_branch_creation(transcript):
            action_val = "create_branch"
            bname = extract_branch_name(transcript)
            cmd = f'{cd_prefix} && (git checkout -b {bname} 2>nul || git checkout {bname}) && git push -u origin {bname}'
            start = f"Creating branch {bname}, sir."
            speaking_resp = f"Branch {bname} has been created successfully, sir."
            task_desc = f"Create branch {bname}"
            target_file = ""
        elif is_repo_creation(transcript):
            target_name = extract_repo_name(transcript, default=get_project_name(get_target_repo()))
            target_file = target_name
            if any(w in transcript.lower() for w in ["and push", "push code", "push files"]):
                action_val = "create_repo_and_push"
                cmd = f'{cd_prefix} && gh repo create {target_name} --public --source=. --remote=origin --push'
                start = f"Creating new GitHub repository {target_name} and pushing workspace files, sir."
                speaking_resp = f"Repository {target_name} has been created on GitHub and files pushed successfully, sir."
                task_desc = f"Create GitHub repository {target_name} and push code"
            else:
                action_val = "create_repo"
                cmd = f'{cd_prefix} && gh repo create {target_name} --public'
                start = f"Creating new GitHub repository {target_name}, sir."
                speaking_resp = f"Repository {target_name} has been created on GitHub, sir."
                task_desc = f"Create GitHub repository {target_name}"
        elif is_push_code(transcript):
            action_val = "push_code"
            target_name = extract_repo_name(transcript, default="")
            target_file = target_name
            cmd = f'{cd_prefix} && git add -A && (git commit -m "Automated update via Jarvis" || echo "No changes to commit") && git push'
            start = f"Pushing code to repository {target_name}, sir." if target_name else "Pushing code to GitHub, sir."
            speaking_resp = f"Code has been pushed to repository {target_name} successfully, sir." if target_name else "Code has been pushed to GitHub successfully, sir."
        elif is_revert_commit(transcript):
            action_val = "revert_commit"
            cmd = f'{cd_prefix} && python execute_git.py --revert-commit'
            start = "Reverting the last committed changes, sir."
            speaking_resp = "The last committed changes have been reverted successfully, sir."
            task_desc = "Revert last committed changes"
            target_file = ""
        else:
            if not cmd.startswith("cd "):
                cmd = f'{cd_prefix} && {cmd}' if cmd else f'{cd_prefix} && git status'
            if not start:
                start = "Executing Git task, sir."

    return {
        "type": req_type,
        "action": action_val,
        "target_file": target_file,
        "task_description": task_desc,
        "command": cmd,
        "speaking_start": start,
        "speaking_progress": prog,
        "speaking_response": speaking_resp,
    }

def call_groq(transcript: str) -> dict:
    if not GROQ_API_KEY or GROQ_API_KEY.startswith("your_"):
        raise ValueError("GROQ_API_KEY not configured.")

    models = [
        "qwen/qwen3.8-27b",
        "llama-3.3-70b-versatile",
        "qwen-2.5-32b",
        "openai/gpt-oss-120b",
    ]

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    system_prompt = build_system_prompt()
    last_err = None

    for m in models:
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json={
                    "model": m,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"User: {transcript}"},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 150,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                return sanitize_json(content, transcript)
            elif resp.status_code == 404:
                continue
            else:
                last_err = f"HTTP {resp.status_code}"
        except Exception as e:
            last_err = str(e)
            break

    raise RuntimeError(f"Groq API error: {last_err}")

def call_ollama(transcript: str) -> dict:
    system_prompt = build_system_prompt()
    resp = requests.post(
        f"{OLLAMA_HOST}/api/chat",
        json={
            "model": "qwen2.5-coder:7b",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"User: {transcript}"},
            ],
            "options": {"temperature": 0.2, "num_predict": 150},
            "stream": False,
        },
        timeout=25,
    )
    if resp.status_code == 200:
        content = resp.json().get("message", {}).get("content", "")
        return sanitize_json(content, transcript)
    raise RuntimeError(f"Ollama HTTP {resp.status_code}")

def route_intent(transcript: str) -> dict:
    cleaned = transcript.strip()
    if not cleaned or len(cleaned) < 2:
        return build_default_intent(cleaned)

    # 0a. IMMEDIATE ROUTING: Active pending confirmation check (Yes / No)
    pending_res = check_pending_confirmation(cleaned)
    if pending_res:
        return pending_res

    # 0. IMMEDIATE ROUTING: Emergency stop commands ('jarvis stop', 'stop', 'be quiet')
    if is_stop_intent(cleaned):
        return build_default_intent(cleaned)

    # 1. IMMEDIATE ROUTING: Git informational queries
    if is_git_query(cleaned):
        return build_default_intent(cleaned)

    # 2. IMMEDIATE ROUTING: Git branch deletion
    if is_branch_deletion(cleaned):
        return build_default_intent(cleaned)

    # 2b. IMMEDIATE ROUTING: Git revert last commit / undo committed changes
    if is_revert_commit(cleaned):
        return build_default_intent(cleaned)

    # 3. IMMEDIATE ROUTING: Git branch creation & remote push
    if is_branch_creation(cleaned):
        return build_default_intent(cleaned)

    # 4. IMMEDIATE ROUTING: Git repository creation & push
    if is_repo_creation(cleaned):
        return build_default_intent(cleaned)

    # 5. IMMEDIATE ROUTING: Antigravity task regex/classifier match
    if is_antigravity_intent(cleaned):
        return build_default_intent(cleaned)

    # 1. Primary: Groq Cloud API
    try:
        return call_groq(cleaned)
    except Exception as e:
        print(f"[intent_router.py] Groq fallback notice: {e}", file=sys.stderr)

    # 2. Offline Fallback: Local Ollama
    try:
        return call_ollama(cleaned)
    except Exception as e:
        print(f"[intent_router.py] Ollama fallback notice: {e}", file=sys.stderr)

    # 3. Deterministic Fallback
    return build_default_intent(cleaned)

def main():
    transcript = ""
    if len(sys.argv) > 1:
        transcript = " ".join(sys.argv[1:]).strip()

    if not transcript and os.path.exists(TRANSCRIPT_CACHE_FILE):
        try:
            with open(TRANSCRIPT_CACHE_FILE, "r", encoding="utf-8") as f:
                transcript = f.read().strip()
        except Exception:
            transcript = ""

    result = route_intent(transcript)

    # Save to status & intent cache
    try:
        with open(STATUS_CACHE_FILE, "w", encoding="utf-8") as f:
            if result.get("type") == "confirm_action":
                status_text = f"[CONFIRMATION REQUIRED] Delete branch '{result.get('branch_name')}'? Say YES to confirm or NO to cancel."
            elif "cancelled" in result.get("task_description", "").lower():
                status_text = f"[CANCELLED] {result.get('speaking_response')}"
            else:
                status_text = result.get("speaking_start") or f"Jarvis routing: {result.get('type')}"
            f.write(status_text)
    except Exception as e:
        print(f"[intent_router.py] Status caching notice: {e}", file=sys.stderr)

    # Save structured payload to antigravity_task.json and antigravity_prompt.txt
    if result.get("type") == "antigravity_task":
        action = result.get("action", "bug_fix")
        target_f = result.get("target_file", "")
        task_desc = result.get("task_description", transcript)
        target_path = os.path.join(PROJECT_ROOT, target_f) if target_f else ""

        valid, full_tb, line_num, err_details = check_python_syntax(target_path)
        if not valid:
            if line_num:
                formatted_prompt = f"@{target_f} Fix the compilation error on line {line_num}: {err_details}. Resolve this issue now."
                result["speaking_response"] = f"Syntax error detected on line {line_num} in {target_f}. Dispatched fix prompt directly to Antigravity, sir."
            else:
                formatted_prompt = f"@{target_f} Fix the compilation error: {err_details}. Resolve this issue now."
                result["speaking_response"] = f"Syntax error detected in {target_f}. Dispatched fix prompt directly to Antigravity, sir."
            hud_status = f"[SYNTAX ERROR] Line {line_num} in {target_f}: {err_details}"
        else:
            if str(task_desc).startswith("@"):
                formatted_prompt = task_desc
            else:
                formatted_prompt = f"""================================================================================
                    ANTIGRAVITY AUTONOMOUS TASK DISPATCH
================================================================================
ACTION      : {action.upper()}
TARGET FILE : {target_f or "Project Workspace"}
TIMESTAMP   : {time.strftime('%Y-%m-%d %H:%M:%S')}
WORKSPACE   : {PROJECT_ROOT}

TASK SPECIFICATION:
{task_desc}

DIRECTIVE:
1. Investigate the requested {action.replace('_', ' ')} in {target_f or "the workspace"}.
2. Check relevant files, error logs, and system behavior.
3. Formulate the resolution, apply code changes, and verify execution.
================================================================================
"""
            hud_status = f"[ANTIGRAVITY ACTIVE] {action.upper()}: {task_desc[:50]}"

        try:
            with open(ANTIGRAVITY_PROMPT_FILE, "w", encoding="utf-8") as f:
                f.write(formatted_prompt)
            print(f"[intent_router.py] Wrote formatted prompt to {ANTIGRAVITY_PROMPT_FILE}", file=sys.stderr)
        except Exception as e:
            print(f"[intent_router.py] Antigravity prompt caching notice: {e}", file=sys.stderr)

        # Automatically dispatch to Antigravity IDE agent (Ctrl+L -> Ctrl+V -> Enter)
        dispatched_ok = False
        try:
            from antigravity_bridge import dispatch_prompt_to_antigravity
            dispatched_ok = dispatch_prompt_to_antigravity(formatted_prompt)
        except Exception as e:
            print(f"[intent_router.py] Antigravity direct dispatch error: {e}", file=sys.stderr)
            sync_to_clipboard(formatted_prompt)

        # Stream update to last_status.txt for HUD Panel 3
        try:
            with open(STATUS_CACHE_FILE, "w", encoding="utf-8") as f:
                f.write(hud_status)
        except Exception:
            pass

        try:
            task_payload = {
                "type": "antigravity_task",
                "action": action,
                "target_file": target_f,
                "task_description": task_desc,
                "prompt": formatted_prompt,
                "speaking_start": result.get("speaking_start", ""),
                "speaking_progress": result.get("speaking_progress", ""),
                "speaking_response": result.get("speaking_response", ""),
                "status": "dispatched" if dispatched_ok else "pending",
                "dispatched": dispatched_ok,
                "created_at": time.time()
            }
            with open(ANTIGRAVITY_TASK_FILE, "w", encoding="utf-8") as f:
                json.dump(task_payload, f, indent=2)
            print(f"[intent_router.py] Wrote structured task to {ANTIGRAVITY_TASK_FILE}", file=sys.stderr)
        except Exception as e:
            print(f"[intent_router.py] Antigravity task caching notice: {e}", file=sys.stderr)

    try:
        with open(INTENT_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
    except Exception as e:
        print(f"[intent_router.py] Intent caching notice: {e}", file=sys.stderr)

    # Output strict JSON
    print(json.dumps(result, indent=2))
    sys.exit(0)

if __name__ == "__main__":
    main()

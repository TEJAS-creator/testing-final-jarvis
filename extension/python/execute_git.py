#!/usr/bin/env python3
"""
Jarvis Git Command Execution Module
Executes validated CLI actions inside the project root directory.
Guarantees execution in the project directory regardless of caller CWD,
auto-injects GitHub CLI path, and skips execution for general QA queries.
"""

import sys
import os
import json
import re
import subprocess
from dotenv import load_dotenv

load_dotenv()

from jarvis_config import JARVIS_CORE_DIR, get_target_repo, get_project_name

PROJECT_ROOT = JARVIS_CORE_DIR

# Ensure GitHub CLI and Git are in PATH
GH_PATH = r"C:\Program Files\GitHub CLI"
if os.path.exists(GH_PATH) and GH_PATH not in os.environ.get("PATH", ""):
    os.environ["PATH"] = GH_PATH + os.pathsep + os.environ.get("PATH", "")

def get_github_auth_token() -> str:
    """Retrieves GitHub token from environment or Git Credential Manager."""
    token = os.getenv("GITHUB_TOKEN", "").strip() or os.getenv("GH_TOKEN", "").strip()
    if token:
        return token

    try:
        proc = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n",
            capture_output=True,
            text=True,
            timeout=5
        )
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                if line.startswith("password="):
                    cand = line.split("=", 1)[1].strip()
                    if cand:
                        os.environ["GH_TOKEN"] = cand
                        os.environ["GITHUB_TOKEN"] = cand
                        return cand
    except Exception as e:
        print(f"[execute_git.py] Notice: Could not read git credential helper: {e}", file=sys.stderr)

    return ""

def get_github_username(token: str = "") -> str:
    """Dynamically resolves the active GitHub username."""
    gh_bin = r"C:\Program Files\GitHub CLI\gh.exe"
    gh_cmd = gh_bin if os.path.exists(gh_bin) else "gh"
    try:
        proc = subprocess.run([gh_cmd, "api", "user", "--jq", ".login"], capture_output=True, text=True, timeout=5)
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except Exception:
        pass

    if not token:
        token = get_github_auth_token()
    if token:
        try:
            import urllib.request
            req = urllib.request.Request(
                "https://api.github.com/user",
                headers={"Authorization": f"token {token}", "User-Agent": "Jarvis-Assistant"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                u_data = json.loads(resp.read().decode())
                if "login" in u_data and u_data["login"]:
                    return u_data["login"]
        except Exception:
            pass

    try:
        proc = subprocess.run(["git", "config", "user.name"], capture_output=True, text=True, timeout=3)
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except Exception:
        pass

    return "TEJAS-creator"

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

def handle_create_repo(target_repo: str, repo_name: str = None, is_private: bool = False) -> tuple[int, str]:
    """Creates a remote repository on GitHub and sets up local origin without pushing code."""
    if not repo_name or not repo_name.strip():
        repo_name = os.path.basename(target_repo.rstrip("\\/"))
    clean_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '-', repo_name.strip()).strip('-')
    clean_name = re.sub(r'-+', '-', clean_name)
    if not clean_name:
        clean_name = "project-repo"

    print(f"[execute_git.py] Creating GitHub repository '{clean_name}' for '{target_repo}'...")

    token = get_github_auth_token()
    username = get_github_username(token)

    repo_created = False
    repo_url = f"https://github.com/{username}/{clean_name}.git"

    # Try gh CLI first
    gh_bin = r"C:\Program Files\GitHub CLI\gh.exe"
    gh_cmd = gh_bin if os.path.exists(gh_bin) else "gh"
    gh_env = os.environ.copy()
    if token:
        gh_env["GH_TOKEN"] = token
    vis_flag = "--private" if is_private else "--public"

    try:
        print(f"[execute_git.py] Creating remote repo via gh CLI: {clean_name} ({vis_flag})...")
        gh_proc = subprocess.run(
            [gh_cmd, "repo", "create", clean_name, vis_flag],
            cwd=target_repo,
            env=gh_env,
            capture_output=True,
            text=True
        )
        if gh_proc.returncode == 0:
            repo_created = True
            print(f"[execute_git.py] Successfully created repository on GitHub: {clean_name}")
        else:
            out_err = gh_proc.stderr.strip() or gh_proc.stdout.strip()
            if "already exists" in out_err.lower():
                print(f"[execute_git.py] Repository '{clean_name}' already exists on GitHub under {username}.")
                repo_created = True
            else:
                print(f"[execute_git.py] gh CLI output: {out_err}")
    except Exception as e:
        print(f"[execute_git.py] gh CLI notice: {e}")

    # Fallback to GitHub REST API
    if not repo_created and token:
        try:
            import urllib.request
            create_payload = json.dumps({
                "name": clean_name,
                "private": is_private,
                "description": "Automated repository created via Jarvis Voice Assistant"
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.github.com/user/repos",
                data=create_payload,
                headers={
                    "Authorization": f"token {token}",
                    "User-Agent": "Jarvis-Assistant",
                    "Content-Type": "application/json"
                }
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp_data = json.loads(resp.read().decode())
                repo_url = resp_data.get("clone_url", repo_url)
                print(f"[execute_git.py] Successfully created GitHub repository via API: {repo_url}")
                repo_created = True
        except urllib.error.HTTPError as e:
            if e.code == 422:
                print(f"[execute_git.py] Repository '{clean_name}' already exists on GitHub under {username}.")
                repo_created = True
            else:
                err_body = e.read().decode("utf-8", errors="ignore")
                print(f"[execute_git.py] GitHub API creation returned HTTP {e.code}: {err_body}")
        except Exception as e:
            print(f"[execute_git.py] GitHub API request notice: {e}")

    # Configure local git repository and remote origin
    git_dir = os.path.join(target_repo, ".git")
    if not os.path.exists(git_dir):
        print(f"[execute_git.py] Initializing local git repository...")
        subprocess.run(["git", "init"], cwd=target_repo, capture_output=True)

    rem_check = subprocess.run(["git", "remote", "get-url", "origin"], cwd=target_repo, capture_output=True, text=True)
    if rem_check.returncode == 0:
        subprocess.run(["git", "remote", "set-url", "origin", repo_url], cwd=target_repo, capture_output=True)
    else:
        subprocess.run(["git", "remote", "add", "origin", repo_url], cwd=target_repo, capture_output=True)

    if repo_created:
        return 0, f"Repository '{clean_name}' created on GitHub successfully"
    return 0, f"Repository '{clean_name}' configured with remote {repo_url}"

def handle_push_code(target_repo: str, repo_name: str = None) -> tuple[int, str]:
    """Robustly stages, commits, and pushes code to the specified or current repository."""
    token = get_github_auth_token()
    username = get_github_username(token)

    # If a specific repository name is requested, configure remote origin to it
    if repo_name and repo_name.strip() and repo_name.lower() not in ["current-repo", "origin"]:
        clean_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '-', repo_name.strip()).strip('-')
        clean_name = re.sub(r'-+', '-', clean_name)
        if clean_name:
            repo_url = f"https://github.com/{username}/{clean_name}.git"
            git_dir = os.path.join(target_repo, ".git")
            if not os.path.exists(git_dir):
                subprocess.run(["git", "init"], cwd=target_repo, capture_output=True)

            rem_check = subprocess.run(["git", "remote", "get-url", "origin"], cwd=target_repo, capture_output=True, text=True)
            if rem_check.returncode == 0:
                subprocess.run(["git", "remote", "set-url", "origin", repo_url], cwd=target_repo, capture_output=True)
            else:
                subprocess.run(["git", "remote", "add", "origin", repo_url], cwd=target_repo, capture_output=True)

    return handle_commit_and_push(target_repo)

def handle_create_repo_and_push(target_repo: str, repo_name: str = None, is_private: bool = False) -> tuple[int, str]:
    """Creates a remote repository on GitHub and pushes all workspace files."""
    code, msg = handle_create_repo(target_repo, repo_name, is_private)
    if code != 0:
        return code, msg
    return handle_push_code(target_repo, repo_name)

def extract_branch_name(t: str) -> str:
    """Extracts and sanitizes git branch name from speech or task string."""
    text = t.strip()
    raw = ""
    m_q = re.search(r'["\']([^"\']+)["\']', text)
    if m_q and any(w in text.lower() for w in ["branch"]):
        raw = m_q.group(1).strip()

    if not raw:
        m_del = re.search(r'(?:delete|remove|drop|destroy)\s+(?:the\s+)?(?:a\s+)?branch\s+(?:called\s+|named\s+)?([a-zA-Z0-9_\-\.\/\s]+)', text, re.IGNORECASE)
        if m_del:
            raw = m_del.group(1).strip()
    if not raw:
        m_del_adj = re.search(r'(?:delete|remove|drop|destroy)\s+(?:the\s+)?(?:a\s+)?([a-zA-Z0-9_\-\.\/]+)\s+branch', text, re.IGNORECASE)
        if m_del_adj:
            raw = m_del_adj.group(1).strip()
    if not raw:
        m = re.search(r'branch\s+(?:called|named|as)\s+([a-zA-Z0-9_\-\.\/\s]+)', text, re.IGNORECASE)
        if m:
            raw = m.group(1).strip()
    if not raw:
        m2 = re.search(r'(?:create|created|make|checkout|switch to|new)\s+(?:a\s+)?(?:new\s+)?branch\s+([a-zA-Z0-9_\-\.\/\s]+)', text, re.IGNORECASE)
        if m2:
            raw = m2.group(1).strip()
    if not raw:
        m3 = re.search(r'(?:called|named)\s+([a-zA-Z0-9_\-\.\/\s]+)', text, re.IGNORECASE)
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

def handle_delete_branch(target_repo: str, branch_name: str) -> tuple[int, str]:
    """Deletes branch locally and on remote GitHub origin."""
    branch = branch_name.strip(".-/ \t\r\n")
    if not branch:
        return 1, "Branch name is empty"
    if branch in ["main", "master"]:
        return 1, f"Cannot delete protected default branch '{branch}'"

    # 1. If currently on the branch to be deleted, switch to default branch first
    curr_br = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=target_repo, capture_output=True, text=True).stdout.strip()
    if curr_br == branch:
        print(f"[execute_git.py] Currently on '{branch}'; switching to default branch first...")
        ck = subprocess.run(["git", "checkout", "main"], cwd=target_repo, capture_output=True)
        if ck.returncode != 0:
            subprocess.run(["git", "checkout", "master"], cwd=target_repo, capture_output=True)

    # 2. Delete local branch
    print(f"[execute_git.py] Deleting local branch '{branch}'...")
    del_local = subprocess.run(["git", "branch", "-D", branch], cwd=target_repo, capture_output=True, text=True)
    local_msg = del_local.stdout.strip() or del_local.stderr.strip()

    # 3. Delete remote branch on GitHub origin
    print(f"[execute_git.py] Deleting remote branch '{branch}' on origin...")
    del_remote = subprocess.run(["git", "push", "origin", "--delete", branch], cwd=target_repo, capture_output=True, text=True)
    remote_msg = del_remote.stdout.strip() or del_remote.stderr.strip()

    # 4. Prune remote tracking references
    subprocess.run(["git", "fetch", "--prune", "origin"], cwd=target_repo, capture_output=True)

    if del_local.returncode == 0 or del_remote.returncode == 0:
        return 0, f"Branch '{branch}' deleted successfully"
    return 1, f"Failed to delete branch '{branch}': {local_msg} {remote_msg}"

def handle_revert_commit(target_repo: str) -> tuple[int, str]:
    """Robustly reverts the last committed changes (HEAD), undoing them and syncing with remote origin."""
    chk = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=target_repo, capture_output=True, text=True)
    if chk.returncode != 0:
        return 1, f"Not a valid git repository: {target_repo}"

    head_chk = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=target_repo, capture_output=True, text=True)
    if head_chk.returncode != 0:
        return 1, "No commits found in repository to revert"

    commit_info = subprocess.run(
        ["git", "log", "-1", "--pretty=format:%h ('%s')"],
        cwd=target_repo,
        capture_output=True,
        text=True
    ).stdout.strip() or "HEAD"

    is_root = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD~1"],
        cwd=target_repo,
        capture_output=True,
        text=True
    ).returncode != 0

    print(f"[execute_git.py] Reverting last commit: {commit_info} in '{target_repo}'...")

    # Check for uncommitted working tree modifications
    status_out = subprocess.run(["git", "status", "--porcelain"], cwd=target_repo, capture_output=True, text=True).stdout.strip()
    did_stash = False
    if status_out:
        print("[execute_git.py] Stashing uncommitted local modifications prior to revert...")
        stash_res = subprocess.run(["git", "stash", "push", "-m", "jarvis_auto_stash_before_revert"], cwd=target_repo, capture_output=True, text=True)
        if stash_res.returncode == 0 and "No local changes to save" not in stash_res.stdout:
            did_stash = True

    # Execute git revert
    if is_root:
        print("[execute_git.py] Initial root commit detected; resetting HEAD reference...")
        rev_proc = subprocess.run(["git", "update-ref", "-d", "HEAD"], cwd=target_repo, capture_output=True, text=True)
        if rev_proc.returncode != 0:
            rev_proc = subprocess.run(["git", "rm", "-rf", "."], cwd=target_repo, capture_output=True, text=True)
    else:
        rev_proc = subprocess.run(["git", "revert", "HEAD", "--no-edit"], cwd=target_repo, capture_output=True, text=True)

    if rev_proc.returncode != 0:
        err = rev_proc.stderr.strip() or rev_proc.stdout.strip()
        print(f"[execute_git.py] Git revert failed: {err}", file=sys.stderr)
        subprocess.run(["git", "revert", "--abort"], cwd=target_repo, capture_output=True)
        if did_stash:
            subprocess.run(["git", "stash", "pop"], cwd=target_repo, capture_output=True)
        return 1, f"Failed to revert commit {commit_info}: {err}"

    # Sync revert with GitHub origin if remote branch exists
    curr_branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=target_repo, capture_output=True, text=True).stdout.strip()
    remotes = subprocess.run(["git", "remote"], cwd=target_repo, capture_output=True, text=True).stdout.strip().split()
    if "origin" in remotes and curr_branch and curr_branch != "HEAD":
        print(f"[execute_git.py] Syncing reverted changes to GitHub origin/{curr_branch}...")
        push_res = subprocess.run(["git", "push", "origin", curr_branch], cwd=target_repo, capture_output=True, text=True)
        if push_res.returncode != 0:
            print(f"[execute_git.py] Notice on push after revert: {push_res.stderr.strip() or push_res.stdout.strip()}")

    if did_stash:
        subprocess.run(["git", "stash", "pop"], cwd=target_repo, capture_output=True)

    return 0, f"Successfully reverted last committed changes: {commit_info}"

def handle_create_branch(target_repo: str, branch_name: str) -> tuple[int, str]:
    """Robustly checks out/creates a branch and pushes it to GitHub origin."""
    branch = branch_name.strip(".-/ \t\r\n")
    if not branch:
        return 1, "Branch name is empty"
    print(f"[execute_git.py] Creating/switching to branch '{branch}'...")
    res = subprocess.run(["git", "checkout", "-b", branch], cwd=target_repo, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[execute_git.py] Notice on checkout -b: {res.stderr.strip()}; trying git checkout {branch}...")
        res2 = subprocess.run(["git", "checkout", branch], cwd=target_repo, capture_output=True, text=True)
        if res2.returncode != 0:
            err = res2.stderr.strip() or res.stderr.strip()
            return res2.returncode, f"Failed to checkout branch: {err}"

    print(f"[execute_git.py] Pushing branch '{branch}' to origin...")
    push_res = subprocess.run(["git", "push", "-u", "origin", branch], cwd=target_repo, capture_output=True, text=True)
    if push_res.returncode != 0:
        err = push_res.stderr.strip() or push_res.stdout.strip()
        return push_res.returncode, f"Failed to push branch to GitHub: {err}"

    return 0, f"Successfully created and pushed branch '{branch}' to GitHub"

def handle_commit_and_push(target_repo: str) -> tuple[int, str]:
    """Robustly stages, commits, and pushes to GitHub with accurate branch detection and syncing."""
    # 1. Stage all changes
    print("[execute_git.py] Staging changes: git add -A")
    subprocess.run(["git", "add", "-A"], cwd=target_repo, capture_output=True)

    # 2. Check if changes exist to commit
    status_proc = subprocess.run(["git", "status", "--porcelain"], cwd=target_repo, capture_output=True, text=True)
    if status_proc.stdout.strip():
        print("[execute_git.py] Committing changes...")
        commit_proc = subprocess.run(
            ["git", "commit", "-m", "Automated update via Jarvis"],
            cwd=target_repo,
            capture_output=True,
            text=True
        )
        if commit_proc.returncode != 0:
            err = commit_proc.stderr.strip() or commit_proc.stdout.strip()
            print(f"[execute_git.py] Commit note: {err}")
    else:
        print("[execute_git.py] Working tree clean, nothing new to commit.")

    # 3. Detect current branch
    br_proc = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=target_repo, capture_output=True, text=True)
    curr_branch = br_proc.stdout.strip() or "main"
    print(f"[execute_git.py] Current active branch: {curr_branch}")

    # 4. Check if remote origin exists; if not, automatically create the GitHub repository and push
    rem_check = subprocess.run(["git", "remote", "get-url", "origin"], cwd=target_repo, capture_output=True, text=True)
    if rem_check.returncode != 0:
        print(f"[execute_git.py] Notice: No remote origin found for '{target_repo}'. Auto-creating GitHub repository...")
        return handle_create_repo_and_push(target_repo)

    # 5. Push current branch to origin
    print(f"[execute_git.py] Pushing to origin/{curr_branch}...")
    push_proc = subprocess.run(
        ["git", "push", "-u", "origin", curr_branch],
        cwd=target_repo,
        capture_output=True,
        text=True
    )
    if push_proc.returncode != 0:
        err = push_proc.stderr.strip() or push_proc.stdout.strip()
        return push_proc.returncode, f"Git push error: {err}"

    # 6. Synchronize both main and master so GitHub default branch is always updated
    if curr_branch == "main":
        print("[execute_git.py] Syncing main to master on origin...")
        subprocess.run(["git", "push", "origin", "main:master"], cwd=target_repo, capture_output=True)
    elif curr_branch == "master":
        print("[execute_git.py] Syncing master to main on origin...")
        subprocess.run(["git", "push", "origin", "master:main"], cwd=target_repo, capture_output=True)

    return 0, f"Successfully pushed to GitHub ({curr_branch})"

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--revert-commit":
        target_repo = get_target_repo()
        status_file = os.path.join(PROJECT_ROOT, "last_status.txt")
        print(f"[Jarvis Executing]: Direct Revert of Last Commit in '{target_repo}'")
        retcode, out_msg = handle_revert_commit(target_repo)
        if retcode != 0:
            with open(status_file, "w", encoding="utf-8") as f:
                f.write(f"[GIT ERROR] {out_msg}")
            sys.exit(retcode)
        else:
            with open(status_file, "w", encoding="utf-8") as f:
                f.write(f"[GIT SUCCESS] {out_msg}")
            sys.exit(0)

    if len(sys.argv) > 2 and sys.argv[1] == "--delete-branch":
        bname = sys.argv[2].strip()
        target_repo = get_target_repo()
        status_file = os.path.join(PROJECT_ROOT, "last_status.txt")
        print(f"[Jarvis Executing]: Direct Branch Deletion '{bname}' in '{target_repo}'")
        retcode, out_msg = handle_delete_branch(target_repo, bname)
        if retcode != 0:
            with open(status_file, "w", encoding="utf-8") as f:
                f.write(f"[GIT ERROR] {out_msg}")
            sys.exit(retcode)
        else:
            with open(status_file, "w", encoding="utf-8") as f:
                f.write(f"[GIT SUCCESS] Branch {bname} deleted successfully.")
            sys.exit(0)

    intent_file = sys.argv[1] if len(sys.argv) > 1 else os.path.join(PROJECT_ROOT, "last_intent.json")
    if not os.path.exists(intent_file):
        print(f"[execute_git.py] Error: {intent_file} does not exist.", file=sys.stderr)
        sys.exit(1)

    try:
        with open(intent_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[execute_git.py] Invalid intent JSON: {e}", file=sys.stderr)
        sys.exit(1)

    # Delegate to execute_agent if Antigravity task
    if data.get("type") == "antigravity_task":
        print("[execute_git.py] Antigravity task detected; delegating to execute_agent.py.")
        agent_script = os.path.join(PROJECT_ROOT, "execute_agent.py")
        proc = subprocess.run([sys.executable, agent_script], cwd=PROJECT_ROOT)
        sys.exit(proc.returncode)

    # Bypass if query is General QA, Codebase QA, or Git Query
    if data.get("type") in ["general_qa", "codebase_qa", "git_query"]:
        print("[execute_git.py] QA/Query detected; bypassing Git CLI write actions.")
        sys.exit(0)

    action = str(data.get("action", "")).lower()
    command = data.get("command", "git status").strip()
    task_desc = data.get("task_description", "").lower()
    target_repo = get_target_repo()
    status_file = os.path.join(PROJECT_ROOT, "last_status.txt")

    # 1. Dedicated Handler for Branch Deletion
    if action == "delete_branch" or "branch -d" in command.lower() or ("branch" in task_desc and ("delete" in task_desc or "remove" in task_desc)):
        m = re.search(r'branch\s+-[dD]\s+([^\s&|]+)', command)
        if m:
            bname = m.group(1).strip()
        else:
            m2 = re.search(r'branch\s+(?:called\s+|named\s+)?([a-zA-Z0-9_\-\.\/]+)', task_desc)
            bname = m2.group(1).strip() if m2 else "feature-branch"
        print(f"[Jarvis Executing]: Robust Branch Deletion '{bname}' in '{target_repo}'")
        retcode, out_msg = handle_delete_branch(target_repo, bname)
        print(f"[execute_git.py] {out_msg} (Exit code: {retcode})")
        if retcode != 0:
            with open(status_file, "w", encoding="utf-8") as f:
                f.write(f"[GIT ERROR] {out_msg}")
            sys.exit(retcode)
        else:
            with open(status_file, "w", encoding="utf-8") as f:
                f.write(f"[GIT SUCCESS] {data.get('speaking_response', f'Branch {bname} deleted.')}")
            sys.exit(0)

    # 2. Dedicated Handler for Branch Creation
    elif action == "create_branch" or "checkout -b" in command or ("branch" in task_desc and any(w in task_desc for w in ["create", "created", "make", "new"])):
        m = re.search(r'checkout\s+-b\s+([^\s&|]+)', command)
        if m:
            bname = m.group(1).strip()
        else:
            bname = extract_branch_name(task_desc or command)
        print(f"[Jarvis Executing]: Robust Branch Creation '{bname}' in '{target_repo}'")
        retcode, out_msg = handle_create_branch(target_repo, bname)
        print(f"[execute_git.py] {out_msg} (Exit code: {retcode})")
        if retcode != 0:
            with open(status_file, "w", encoding="utf-8") as f:
                f.write(f"[GIT ERROR] {out_msg}")
            sys.exit(retcode)
        else:
            with open(status_file, "w", encoding="utf-8") as f:
                f.write(f"[GIT SUCCESS] {data.get('speaking_response', f'Branch {bname} created.')}")
            sys.exit(0)

    # 3. Dedicated Handler for Repository Creation & Push (if user explicitly requested create AND push)
    elif action == "create_repo_and_push" or (action in ["create_repo", "new_repo"] and any(w in task_desc for w in ["and push", "push code", "push files"])):
        target_name = data.get("target_file") or extract_repo_name(task_desc or command, get_project_name(target_repo))
        print(f"[Jarvis Executing]: Robust GitHub Repository Creation & Push '{target_name}' for '{target_repo}'")
        retcode, out_msg = handle_create_repo_and_push(target_repo, target_name)
        print(f"[execute_git.py] {out_msg} (Exit code: {retcode})")
        if retcode != 0:
            with open(status_file, "w", encoding="utf-8") as f:
                f.write(f"[GIT ERROR] {out_msg}")
            sys.exit(retcode)
        else:
            with open(status_file, "w", encoding="utf-8") as f:
                f.write(f"[GIT SUCCESS] {data.get('speaking_response', f'Repository {target_name} created and files pushed.')}")
            sys.exit(0)

    # 4. Dedicated Handler for Repository Creation (without forcing code push)
    elif action in ["create_repo", "new_repo"] or "repo create" in command.lower() or ("repo" in task_desc and any(w in task_desc for w in ["create", "created", "new", "make"])):
        target_name = data.get("target_file") or extract_repo_name(task_desc or command, get_project_name(target_repo))
        print(f"[Jarvis Executing]: Robust GitHub Repository Creation '{target_name}' for '{target_repo}'")
        retcode, out_msg = handle_create_repo(target_repo, target_name)
        print(f"[execute_git.py] {out_msg} (Exit code: {retcode})")
        if retcode != 0:
            with open(status_file, "w", encoding="utf-8") as f:
                f.write(f"[GIT ERROR] {out_msg}")
            sys.exit(retcode)
        else:
            with open(status_file, "w", encoding="utf-8") as f:
                f.write(f"[GIT SUCCESS] {data.get('speaking_response', f'Repository {target_name} created on GitHub.')}")
            sys.exit(0)

    # 5. Dedicated Handler for Reverting Last Commit / Undoing Committed Changes
    elif (
        action == "revert_commit"
        or "git revert" in command.lower()
        or ("revert" in task_desc and any(w in task_desc for w in ["commit", "committed", "change", "changes", "last", "push"]))
        or ("undo" in task_desc and any(w in task_desc for w in ["commit", "committed", "change", "changes", "last"]))
        or ("rollback" in task_desc and any(w in task_desc for w in ["commit", "committed", "change", "changes"]))
    ):
        print(f"[Jarvis Executing]: Robust Revert of Last Commit in '{target_repo}'")
        retcode, out_msg = handle_revert_commit(target_repo)
        print(f"[execute_git.py] {out_msg} (Exit code: {retcode})")
        if retcode != 0:
            with open(status_file, "w", encoding="utf-8") as f:
                f.write(f"[GIT ERROR] {out_msg}")
            sys.exit(retcode)
        else:
            with open(status_file, "w", encoding="utf-8") as f:
                f.write(f"[GIT SUCCESS] {data.get('speaking_response', out_msg)}")
            sys.exit(0)

    # 6. Dedicated Handler for Push Code (push code to repo <name> or push code)
    elif action == "push_code" or "push" in command or "push" in task_desc or "commit" in task_desc:
        target_name = data.get("target_file") or extract_repo_name(task_desc or command, "")
        print(f"[Jarvis Executing]: Robust Push Code '{target_name or 'current'}' in '{target_repo}'")
        retcode, out_msg = handle_push_code(target_repo, target_name)
        print(f"[execute_git.py] {out_msg} (Exit code: {retcode})")
        if retcode != 0:
            with open(status_file, "w", encoding="utf-8") as f:
                f.write(f"[GIT ERROR] {out_msg}")
            sys.exit(retcode)
        else:
            with open(status_file, "w", encoding="utf-8") as f:
                f.write(f"[GIT SUCCESS] {data.get('speaking_response', 'Code pushed successfully.')}")
            sys.exit(0)

    print(f"[Jarvis Executing]: '{command}' in '{target_repo}'")

    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=target_repo,
            env=os.environ,
            capture_output=True,
            text=True
        )
        print(f"[execute_git.py] Process finished with exit code {proc.returncode}")
        if proc.stdout:
            print(f"[execute_git.py] Output:\n{proc.stdout.strip()}")
        if proc.stderr:
            print(f"[execute_git.py] Notice/Stderr:\n{proc.stderr.strip()}", file=sys.stderr)

        if proc.returncode != 0:
            err_details = proc.stderr.strip() or proc.stdout.strip() or f"Execution failed with code {proc.returncode}"
            print(f"[execute_git.py] Git execution FAILED: {err_details}", file=sys.stderr)
            try:
                with open(status_file, "w", encoding="utf-8") as f:
                    f.write(f"[GIT ERROR] {err_details}")
            except Exception:
                pass
            try:
                if os.path.exists(intent_file):
                    with open(intent_file, "r", encoding="utf-8") as inf:
                        idat = json.load(inf)
                    idat["speaking_error"] = f"Git operation failed, sir: {err_details[:80]}"
                    with open(intent_file, "w", encoding="utf-8") as inf:
                        json.dump(idat, inf, indent=2)
            except Exception:
                pass
            sys.exit(proc.returncode)

        # Execution succeeded
        try:
            with open(status_file, "w", encoding="utf-8") as f:
                f.write(f"[GIT SUCCESS] {data.get('speaking_response', 'Git action completed.')}")
        except Exception:
            pass
        sys.exit(0)
    except Exception as e:
        print(f"[execute_git.py] Execution error: {e}", file=sys.stderr)
        try:
            with open(status_file, "w", encoding="utf-8") as f:
                f.write(f"[GIT ERROR] {e}")
        except Exception:
            pass
        sys.exit(1)

if __name__ == "__main__":
    main()

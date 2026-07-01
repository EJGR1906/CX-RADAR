#!/usr/bin/env python3
import urllib.request
import json
import subprocess
import os
import sys
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent

def run_cmd(args: List[str], cwd: Path = REPO_ROOT) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, cwd=cwd, encoding='utf-8')
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as e:
        return -1, "", str(e)

def get_open_prs() -> List[Dict[str, Any]]:
    url = "https://api.github.com/repos/EJGR1906/CX-RADAR/pulls"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"Error fetching PRs: {e}")
        return []

def apply_pr_diff(pr_number: int) -> Tuple[bool, str]:
    url = f"https://github.com/EJGR1906/CX-RADAR/pull/{pr_number}.diff"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp:
            diff_content = resp.read()
        
        # Save diff locally
        diff_file = REPO_ROOT / f"pr_{pr_number}.diff"
        diff_file.write_bytes(diff_content)
        
        # Apply using git apply
        code, stdout, stderr = run_cmd(["git", "apply", str(diff_file)])
        
        # Remove diff file
        if diff_file.exists():
            diff_file.unlink()
            
        if code != 0:
            return False, f"Failed to apply git diff: {stderr or stdout}"
        return True, ""
    except Exception as e:
        return False, str(e)

def merge_pr_github(pr_number: int) -> Tuple[bool, str]:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return False, "GITHUB_TOKEN env variable not set. PR cannot be merged automatically on GitHub."
    
    url = f"https://api.github.com/repos/EJGR1906/CX-RADAR/pulls/{pr_number}/merge"
    try:
        req = urllib.request.Request(
            url,
            method="PUT",
            headers={
                "User-Agent": "Mozilla/5.0",
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json"
            }
        )
        with urllib.request.urlopen(req) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            if res.get("merged"):
                return True, "Merged successfully on GitHub."
            return False, f"GitHub merge response: {res.get('message', 'Unknown error')}"
    except Exception as e:
        return False, f"HTTP Error: {e}"

def main() -> None:
    print("=== AUTOMATIC PR REVIEWER & VERIFIER ===")
    prs = get_open_prs()
    if not prs:
        print("No open PRs found.")
        return
    
    print(f"Found {len(prs)} open PR(s). Starting validation loop...\n")
    
    # Save current branch
    _, current_branch, _ = run_cmd(["git", "branch", "--show-current"])
    current_branch = current_branch.strip() or "main"
    
    # Check if local changes exist before starting
    code_status, stdout_status, _ = run_cmd(["git", "status", "--porcelain"])
    stashed = False
    if stdout_status.strip():
        print("[INFO] Local workspace has uncommitted changes. Stashing them...")
        run_cmd(["git", "stash"])
        stashed = True
    
    try:
        for pr in prs:
            num = pr["number"]
            title = pr["title"]
            print(f"Reviewing PR #{num}: {title}...")
            
            # Create temp branch
            branch_name = f"review-pr-{num}"
            run_cmd(["git", "checkout", "-b", branch_name])
            
            success, err = apply_pr_diff(num)
            if not success:
                print(f"  [FAIL] Could not apply diff: {err}")
                run_cmd(["git", "checkout", current_branch])
                run_cmd(["git", "branch", "-D", branch_name])
                print()
                continue
                
            # Run validations
            print("  Running environment validation...")
            code_val, out_val, err_val = run_cmd([sys.executable, "scripts/validate_qoe_probe.py"])
            if code_val != 0:
                print("  [FAIL] Environment validation failed.")
                run_cmd(["git", "checkout", current_branch])
                run_cmd(["git", "branch", "-D", branch_name])
                print()
                continue
                
            print("  Running QA certification smoke and resilience suite...")
            code_cert, out_cert, err_cert = run_cmd([sys.executable, "scripts/run_qoe_certification.py", "--run-resilience-checks"])
            if code_cert != 0:
                print("  [FAIL] QA Certification suite failed.")
                run_cmd(["git", "checkout", current_branch])
                run_cmd(["git", "branch", "-D", branch_name])
                print()
                continue
                
            print("  [PASS] All validation and QA checks passed successfully!")
            
            # Attempt to merge on GitHub
            merged, merge_msg = merge_pr_github(num)
            if merged:
                print(f"  [SUCCESS] PR #{num} merged on GitHub: {merge_msg}")
            else:
                print(f"  [INFO] PR #{num} is ready for merge, but: {merge_msg}")
                
            # Go back to parent branch
            run_cmd(["git", "checkout", current_branch])
            run_cmd(["git", "branch", "-D", branch_name])
            print()
    finally:
        # Restore stash if needed
        if stashed:
            print("[INFO] Restoring stashed changes...")
            run_cmd(["git", "stash", "pop"])
            
    print("=== REVIEW PROCESS COMPLETED ===")

if __name__ == "__main__":
    main()

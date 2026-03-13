# Aitherhub Development Skill

> **This file is the canonical reference for the aitherhub skill.**
> The skill file at `/home/ubuntu/skills/aitherhub/SKILL.md` should mirror this content.

---

## Session Start (MANDATORY — do this before ANY work)

### Step 1: Clone & Rebase

```bash
gh repo clone LCJ-Group/aitherhub
cd /home/ubuntu/aitherhub
git pull --rebase origin master
```

### Step 2: Install Safety Hooks (Layer 3)

```bash
bash scripts/install-hooks.sh
```

### Step 3: Clear File Locks (Layer 2)

```bash
curl -sf -X POST -H "X-Admin-Key: aither:hub" -H "Content-Type: application/json" \
  "https://aitherhubapi-cpcjcnezbgf5f7e2.japaneast-01.azurewebsites.net/api/v1/admin/dev-safety/clear" \
  -d '{}'
```

### Step 4: Load AI-Context (Layer 1)

```bash
curl -sf -H "X-Admin-Key: aither:hub" \
  "https://aitherhubapi-cpcjcnezbgf5f7e2.japaneast-01.azurewebsites.net/api/v1/admin/ai-context?scope=aitherhub" \
  | python3 -m json.tool
```

Read the response carefully. It contains:
- `dangers` — things you MUST NOT do
- `checklist_by_file` — checks before modifying specific files
- `checklist_by_feature` — checks before modifying specific features
- `dependencies` — file dependency map
- `rules` — what "working correctly" means
- `feature_status` — current state of each feature
- `preferences` — user's priorities and policies
- `lessons` — past mistakes to avoid
- `open_bugs` — unresolved bugs (report to user before starting)
- `error_videos` / `stuck_videos` — problematic videos
- `action_required` — **warnings about missing lessons or urgent issues (address FIRST)**

---

## 4-Layer Defense System

### Layer 1: AI-Context Rules (Social Defense)
- Loaded at session start via `/api/v1/admin/ai-context`
- Contains dangers, checklists, lessons that guide behavior
- **No code changes needed** — already implemented

### Layer 2: File Lock API (Technical Defense)
- Endpoint: `POST /api/v1/admin/dev-safety/lock`
- Before editing a file, acquire a lock:
  ```bash
  curl -sf -X POST -H "X-Admin-Key: aither:hub" -H "Content-Type: application/json" \
    "https://aitherhubapi-cpcjcnezbgf5f7e2.japaneast-01.azurewebsites.net/api/v1/admin/dev-safety/lock" \
    -d '{"session_id":"manus-session-YYYYMMDD","files":["backend/app/api/v1/endpoints/admin.py"]}'
  ```
- If `denied` array is non-empty, **DO NOT edit those files**
- Locks auto-expire after 2 hours
- Clear all locks at session start (Step 3 above)

### Layer 3: Pre-push Git Hook
- Installed via `scripts/install-hooks.sh`
- Checks before every `git push`:
  1. **Rebase check**: Blocks push if remote has newer commits
  2. **Deletion check**: Warns if >50 lines net deleted in any file
- Overhead: < 0.5 seconds

### Layer 4: GitHub Actions (Post-Detection)
- Workflow: `.github/workflows/safety_check.yml`
- Runs automatically on every push to master
- Checks:
  1. Large deletion detection across all changed files
  2. Protected file monitoring (admin.py, video_sales.py, etc.)
  3. Critical function verification (endpoints, components)
- Results visible in GitHub Actions summary

---

## Before Changing Code

1. **Lock files** you plan to edit (Layer 2)
2. Check `checklist_by_file` for every file you plan to modify
3. Check `checklist_by_feature` for every feature you plan to touch
4. Check `dependencies` to understand impact on other files
5. Check `dangers` to ensure you don't repeat past mistakes

## After Changing Code

1. Verify existing features still work (check `rules` for expected behavior)
2. Test on production: https://www.aitherhub.com
3. **Unlock files** after push is complete

---

## Recording (MANDATORY — do this after EVERY change)

### Bug found → Record it
```bash
curl -sf -X POST -H "X-Admin-Key: aither:hub" -H "Content-Type: application/json" \
  "https://aitherhubapi-cpcjcnezbgf5f7e2.japaneast-01.azurewebsites.net/api/v1/admin/bug-reports" \
  -d '{"severity":"high","section_name":"<section>","title":"<title>","symptom":"<what happened>","cause":"<why>","resolution":"<how fixed>","affected_files":"<files>","status":"resolved","resolver":"manus-ai"}'
```

### Bug fixed → Create lesson (CRITICAL for knowledge retention)
```bash
curl -sf -X POST -H "X-Admin-Key: aither:hub" -H "Content-Type: application/json" \
  "https://aitherhubapi-cpcjcnezbgf5f7e2.japaneast-01.azurewebsites.net/api/v1/admin/lessons" \
  -d '{"category":"lesson","title":"<short rule>","content":"<details>","related_files":"<files>","related_feature":"aitherhub"}'
```

### New danger discovered → Record it
```bash
curl -sf -X POST -H "X-Admin-Key: aither:hub" -H "Content-Type: application/json" \
  "https://aitherhubapi-cpcjcnezbgf5f7e2.japaneast-01.azurewebsites.net/api/v1/admin/lessons" \
  -d '{"category":"danger","title":"<what NOT to do>","content":"<why>","related_files":"<files>","related_feature":"<feature>"}'
```

### New checklist item → Record it
```bash
curl -sf -X POST -H "X-Admin-Key: aither:hub" -H "Content-Type: application/json" \
  "https://aitherhubapi-cpcjcnezbgf5f7e2.japaneast-01.azurewebsites.net/api/v1/admin/lessons" \
  -d '{"category":"checklist","title":"<what to check>","content":"<details>","related_files":"<files>","related_feature":"<feature>"}'
```

### Work completed → Log it
```bash
curl -sf -X POST -H "X-Admin-Key: aither:hub" -H "Content-Type: application/json" \
  "https://aitherhubapi-cpcjcnezbgf5f7e2.japaneast-01.azurewebsites.net/api/v1/admin/work-logs" \
  -d '{"action":"<deploy|bugfix|feature|refactor>","summary":"<what was done>","details":"<details>","commit_hash":"<hash>","files_changed":"<files>","deploy_target":"aitherhubAPI, frontend","author":"manus-ai"}'
```

---

## Infrastructure

| Item | Value |
|------|-------|
| Repo | `LCJ-Group/aitherhub` |
| API | `https://aitherhubapi-cpcjcnezbgf5f7e2.japaneast-01.azurewebsites.net` |
| Auth header | `X-Admin-Key: aither:hub` |
| Frontend | `https://www.aitherhub.com` |
| Admin | `https://www.aitherhub.com/admin` (ID: `aither` / PW: `hub`) |
| Deploy | Push to `master` → GitHub Actions auto-deploy |
| Deploy note | `verify_deploy` step fails due to URL mismatch — if `build_and_deploy` succeeds, deploy is complete |

---

## Absolute Rules

- NEVER reset DONE/COMPLETED video status — all analysis data will be lost
- NEVER use "uploaded" as fallback — use STEP_0_EXTRACT_FRAMES
- NEVER edit files via GitHub Web UI — always deploy through git push
- NEVER make destructive changes without user confirmation
- Stability > New features — never break existing functionality
- Prefer root-cause fixes over temporary workarounds
- ALWAYS run `git pull --rebase origin master` before editing any file
- ALWAYS lock files before editing (Layer 2) and unlock after pushing

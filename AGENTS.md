# Project agent memory — Qwen-3.8-27B Strix Halo (gfx1151) fleet repo

Project-specific facts for serving + battery work on the Halo fleet. The
global `~/.pi/agent/AGENTS.md` applies everywhere and wins on overlap unless
this file is stricter. (Created 2026-08-26 under the operator's dream-apply
authorization — seeded from the nightly dream recommendations.)

## Serving topology

- `llama-router.service` (systemd USER unit, enabled) serves the
  `models/models.ini` recipes on `127.0.0.1:8080` — recipe set per the global
  Local-LLM fact (10 Qwen38-27B aliases + lazy-loaded `[Qwen38-flash]`
  try-out recipe). It `Requires/After=fleet-boot-gate.service`; a boot
  ordering cycle (fleet-boot-gate → default.target → llama-router) once left
  :8080 down after a driver-update reboot — fixed 2026-08-25 (commit
  `22564c0`, gate `After=basic.target`).
- The LAN rig `192.168.50.15:8080` runs the same router (pi provider `lan`).
- pi's `~/.pi/agent/models.json` / `settings.json enabledModels` can fall
  behind the alias set (⇒ `Warning: No models match pattern "lan/..."`) —
  re-sync against the served `/v1/models` list; done once 2026-08-25 (only
  2 of 10 aliases were registered).

## Fleet lanes + batteries

- Remote battery hosts: `admin@192.168.50.209` (`~/LLM/Tiel/` model
  downloads; liveness via `pgrep -f "wget.*Tiel"`) and
  `piero@192.168.50.15` (repo mirror, `git pull --ff-only` sync). Batteries
  write to local `results/` (`e1-battery.log`/`e1-cost.csv`, `e2c-`, `e4-`,
  `e7-` batteries, `hip-rocm715-256k-fill.csv`, `device lost` log greps).
- Fork re-pins land with a gate commit (pattern:
  `chore(fork): re-pin 9b9ac3e38 -> 0eb528051 (6 commits, gate PASS)`).
- Fleet lane defaults (night verdicts): Tiel-Coder = coding default; Ornith
  = traddy lane default. Unattended agent batches → `quality@128k`, agent
  context ceiling 100 k.

## GPU liveness

- `gpu_canary` (user timer, every 10 min; `scripts/gpu_canary.py` +
  `systemd-units/gpu-canary.{service,timer}`) closes the gap left by
  `amdgpu.lockup_timeout=-1` (no kernel ring watchdog): /health OK + a
  1-token completion dead ⇒ GPU ring wedged; 2 consecutive ⇒ journal + reboot.
  2026-08-26: model-load grace added so an in-flight LOAD is not misread as a
  wedge (reboot-loop incident, commit `84c5004`).

## Long-run monitoring discipline

- Battery/soak monitoring follows the global HARD WALL-TIME RULE
  (operator-enforced 2026-08-26): background the run (nohup/setsid + log),
  poll with ≤60 s commands or yield the turn — never foreground
  `sleep 300+` loops.

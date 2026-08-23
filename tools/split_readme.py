#!/usr/bin/env python3
"""Split README.md into front page + docs/ detail pages (one-shot tool).

Keeps in README: Why/TL;DR/headlines/quickstart/repo contents/recipes table
+ dial, Lessons, Thanks, License. Moves deep chapters to docs/ pages by
reader intent. Old external anchors preserved via stub headings in README.
Run from repo root:  uv run python3 tools/split_readme.py  (idempotent guard)
"""
import re
import os

SRC = "README.md"
text = open(SRC).read()

def find(pat):
    m = re.search(rf"^{re.escape(pat)}.*$", text, re.M)
    assert m, f"boundary not found: {pat[:60]}"
    return m.start(), m.end()

def span(a_text, b_text=None):
    """lines from start of a_text's heading up to (not incl.) b_text's heading"""
    a0, _ = find(a_text)
    b0 = find(b_text)[0] if b_text else len(text)
    return text[a0:b0].rstrip() + "\n"

# ---------------- original section spans ----------------
head_lines = [m.group(0) for m in re.finditer(r"^## .+$", text, re.M)]

why        = span("## Why this exists: cloud-free intelligence on a desk", "## Provenance note")
provenance = span("## Provenance note", "## TL;DR — reproduce on any gfx1151 (Strix Halo) box")
tldr       = span("## TL;DR — reproduce on any gfx1151 (Strix Halo) box", "## Headline findings")
headlines  = span("## Headline findings (the counterintuitive ones)", "## Quick start")
quickstart = span("## Quick start: run the prebuilt release (time-saving)", "## What’s in this repo" if False else "## What's in this repo")
repo       = span("## What's in this repo", "## Recommended configs (per goal)")
recipes_head = span("## Recommended configs (per goal)", "**Two measured realities temper the dial")
recipes_deep = text[find("**Two measured realities temper the dial")[0]: find("## Running it")[0]].rstrip() + "\n"
running    = span("## Running it", "## Sweep findings at a glance")
test_sec   = span("## Test — verify GPU, not silent CPU fallback", "## Sweep findings at a glance")
sweep      = span("## Sweep findings at a glance", "## Threads (`-t`), batch threads (`-tb`) and two concurrent clients — measured")
threads    = span("## Threads (`-t`), batch threads (`-tb`) and two concurrent clients — measured", "## The 1M-token context")
m1ctx      = span("## The 1M-token context: what works, what doesn't, and what it costs", "## Vulkan vs ROCm, which and why?")
vulkan     = span("## Vulkan vs ROCm, which and why?", "## Stability without the kernel GPU watchdog")
playbook   = span("## Stability without the kernel GPU watchdog (lockup_timeout=-1 playbook)", "## Reasoning levels")
reasoning  = span("## Reasoning levels: cost and quality — measured", "## Models — Unsloth Dynamic GGUFs")
models     = span("## Models — Unsloth Dynamic GGUFs, aligned with the repo tip", "## Environment")
env        = span("## Environment", "## Optional: HIP variant (ROCm build)")
# env block currently includes Dependencies/Build/Toolbox up to HIP; split later
hip        = span("## Optional: HIP variant (ROCm build)", "## Config research")
cfgres     = span("## Config research (`sweep_llama_configs.sh`)", "## Lessons learned")
lessons    = span("## Lessons learned", "## 🙏 Thanks")
thanks     = span("## 🙏 Thanks to the authors of this software stack", "## License")
license_s  = span("## License")

header  = text[:find("## Why this exists")[0]].rstrip() + "\n"

# ---------------- anchor -> owning page map ----------------
PAGES = {"RUNNING": "RUNNING.md", "DEEP": "DEEP-CONTEXT.md", "BACK": "BACKENDS.md",
         "REAS": "REASONING.md", "BENCH": "BENCHMARKS.md", "BUILD": "BUILDING.md"}
OWNER = {
    "#lessons-learned": "README",
    "#recommended-configs-per-goal": "README",
    "#sweep-findings-at-a-glance": "BENCH",
    "#threads--t--batch-threads--tb--and-two-concurrent-clients--measured": "BENCH",
    "#config-research-sweep_llama_configssh": "BENCH",
    "#vulkan-vs-rocm-which-and-why": "BACK",
    "#how-this-compares-with-halofpx-as-of-2026-08-22": "BACK",
    "#optional-hip-variant-rocm-build": "BACK",
    "#the-1m-token-context-what-works-what-doesnt-and-what-it-costs": "DEEP",
    "#deep-positions-the-amdgpu-watchdog-wall--and-how-to-remove-it": "DEEP",
    "#stability-without-the-kernel-gpu-watchdog-lockup_timeout-1-playbook": "DEEP",
    "#reasoning-levels-cost-and-quality--measured": "REAS",
    "#models--unsloth-dynamic-ggufs-aligned-with-the-repo-tip": "BUILD",
    "#ud-q4_k_xl-evaluated-and-dropped-2026-08-21--gguf-deleted-locally": "BUILD",
    "#running-it": "RUNNING",
    "#test--verify-gpu-not-silent-cpu-fallback": "RUNNING",
}

def fix_links(body, page_key):
    """page_key = owning page of body. Fix anchors + repo-relative paths."""
    def repl_anchor(m):
        anchor, label = m.group(2), m.group(1)
        owner = OWNER.get(anchor)
        if owner is None or owner == page_key:
            return m.group(0)
        if owner == "README":
            return f"[{label}](../README.md{anchor})"
        return f"[{label}]({PAGES[owner]}{anchor})"
    body = re.sub(r"\[([^\]]+)\]\((#[^)]+)\)",
                  lambda m: repl_anchor(m) if m.group(2) in OWNER else m.group(0),
                  body) if False else re.sub(r"\[([^\]]+)\]\((#[^)]+)\)", repl_anchor, body)
    # repo-root relative files -> ../
    sibling = "|".join(p.replace(".", r"\.") for p in PAGES.values())
    body = re.sub(r"\]\((?!https?://|/|#|\.\.|" + sibling + r")"
                  r"(results/|BUILD\.md|docs/|systemd-units/|"
                  r"[A-Za-z0-9_.-]+\.(?:sh|py|ini|jinja|service|timer|md|txt|log|csv))",
                  "](../\\1", body)
    return body

def page(title, purpose, page_key, *sections):
    body = "\n\n".join(sections)
    return (f"# {title}\n\n> From [Qwen3.8-27B on Strix Halo](../README.md) — "
            f"{purpose}\n\n{fix_links(body, page_key)}\n")

# ---------------- build pages ----------------
os.makedirs("docs", exist_ok=True)
open("docs/RUNNING.md", "w").write(page(
    "Running it — operations guide",
    "the router, recipes deep-dive, pairing with pi, the 24/7 margin rule, verification.",
    "RUNNING",
    "## Recipe deep-dive (continued from the front-page table)\n\n" + recipes_deep,
    running, test_sec))

open("docs/DEEP-CONTEXT.md", "w").write(page(
    "Deep context & unattended stability",
    "the 256k/1M window story, the amdgpu watchdog wall, and the lockup_timeout=-1 playbook.",
    "DEEP", m1ctx, playbook))

open("docs/BACKENDS.md", "w").write(page(
    "Backends — Vulkan vs ROCm (and halofpx)",
    "the measured A/B, speed and stability pictures, the halofpx comparison, the HIP build.",
    "BACK", vulkan, hip))

open("docs/REASONING.md", "w").write(page(
    "Reasoning levels — cost and quality, measured",
    "what low/medium/xhigh actually cost and buy on this model, and the budget guard.",
    "REAS", reasoning))

open("docs/BENCHMARKS.md", "w").write(page(
    "Benchmarks & config research",
    "sweep findings at a glance, threads-vs-concurrency, and the sweep harness.",
    "BENCH", sweep, threads, cfgres))

open("docs/BUILDING.md", "w").write(page(
    "Models, environment & builds",
    "which GGUFs and why, quant evaluations, dependencies, building the fork and toolbox.",
    "BUILD", models, env))

# ---------------- new README ----------------
stubs = """
## Running it

Operations — serving all recipes via the router, the movable `Qwen38-27B`
default alias, pairing with the [pi coding agent](docs/RUNNING.md#pair-it-with-pi-the-coding-agent),
the 24/7 agent margin rule, one operator's profile, and GPU verification:
**[docs/RUNNING.md](docs/RUNNING.md)** (the recipe deep-dive — fill-decay
table, when-to-pick notes, relative costs — lives there too).

## Test — verify GPU, not silent CPU fallback

[`llama-cli --list-devices` and the quiet-box reference bench](docs/RUNNING.md#test--verify-gpu-not-silent-cpu-fallback).

## Sweep findings at a glance

The full config-research table — KV types, n-max, batch sizes, host state,
n-gram replay findings: **[docs/BENCHMARKS.md](docs/BENCHMARKS.md#sweep-findings-at-a-glance)**.

## Threads (`-t`), batch threads (`-tb`) and two concurrent clients — measured

`-t 1 -tb 1` is free under full GPU offload; `-t 2 -tb 1` is the one bad
shape; two clients nearly double aggregate decode:
**[docs/BENCHMARKS.md](docs/BENCHMARKS.md#threads--t--batch-threads--tb--and-two-concurrent-clients--measured)**.

## The 1M-token context: what works, what doesn't, and what it costs

The 262k servable ceiling, the YaRN cap, what 1M costs in memory, and the
three routes to a real 1M window: **[docs/DEEP-CONTEXT.md](docs/DEEP-CONTEXT.md)**.

### Deep positions: the amdgpu watchdog wall — and how to remove it

The 136,965 "Vulkan wall" was the kernel lockup watchdog — forensics and the
`lockup_timeout=-1` intervention (full window, 254,356, verified):
**[docs/DEEP-CONTEXT.md](docs/DEEP-CONTEXT.md#deep-positions-the-amdgpu-watchdog-wall--and-how-to-remove-it)**.

## Vulkan vs ROCm, which and why?

The measured A/B, speed/stability pictures, the fill-decay duel chart, and
the practical ranking: **[docs/BACKENDS.md](docs/BACKENDS.md)**.

### How this compares with halofpx as of 2026-08-22

The measured-quality-first comparison with the speed-first cousin:
**[docs/BACKENDS.md](docs/BACKENDS.md#how-this-compares-with-halofpx-as-of-2026-08-22)**.

## Stability without the kernel GPU watchdog (lockup_timeout=-1 playbook)

Three-layer unattended stability — hardware TCO, the GPU canary, the scoped
reboot grant: **[docs/DEEP-CONTEXT.md](docs/DEEP-CONTEXT.md#stability-without-the-kernel-gpu-watchdog-lockup_timeout-1-playbook)**.

## Reasoning levels: cost and quality — measured

Levels are style, not cost; only `reasoning_budget_tokens` is a real cap;
thinking inside a bounded budget can starve the answer — and what we run
because of it: **[docs/REASONING.md](docs/REASONING.md)**.

## Models — Unsloth Dynamic GGUFs, aligned with the repo tip

Which GGUFs we run and why, the v3.0 tie-battery, the Q4 drop:
**[docs/BUILDING.md](docs/BUILDING.md#models--unsloth-dynamic-ggufs-aligned-with-the-repo-tip)**.

## Environment · Dependencies · Build from source · The toolbox

Environment notes, the OBSERVED dependency set, building the fork, the
prebuilt toolbox: **[docs/BUILDING.md](docs/BUILDING.md#environment)**.

## Optional: HIP variant (ROCm build)

The no-root TheRock build recipe: **[docs/BACKENDS.md](docs/BACKENDS.md#optional-hip-variant-rocm-build)**.

## Config research (`sweep_llama_configs.sh`)

The staged sweep harness and how every table number was produced:
**[docs/BENCHMARKS.md](docs/BENCHMARKS.md#config-research-sweep_llama_configssh)**.
"""

principles = """
**How we know (the method behind every number):** all benchmarks are
back-to-back interleaved pairs (lesson #1); every battery's raw evidence is
committed under `results/` — CSVs, server logs, kernel journal excerpts;
experiments run under pre-registered decision rules (`docs/PLAN-reasoning-economics.md`)
and the reasoning batteries' answer keys are computed by the graders
themselves; claims carry OBSERVED / INFERRED / REPORTED labels; and when our
own adversarial README audit caught numbers without committed evidence, we
corrected the README rather than the evidence (2026-08-23). If a number here
can't be re-run from this repo, it doesn't belong here.
"""

repo_extra = """
**The detail pages** (each opens from the front page where it's summarized):

- [docs/RUNNING.md](docs/RUNNING.md) — operations: router, alias, pi pairing,
  margin rule, recipe deep-dive, verification
- [docs/DEEP-CONTEXT.md](docs/DEEP-CONTEXT.md) — the 256k/1M window, the
  watchdog wall, unattended stability
- [docs/BACKENDS.md](docs/BACKENDS.md) — Vulkan vs ROCm A/B, halofpx, HIP build
- [docs/REASONING.md](docs/REASONING.md) — reasoning cost/quality batteries
- [docs/BENCHMARKS.md](docs/BENCHMARKS.md) — sweep findings, threads study,
  config research
- [docs/BUILDING.md](docs/BUILDING.md) — models, quants, deps, builds
"""

new_readme = (header + why + principles + "\n" + provenance + tldr + headlines
              + quickstart + repo + repo_extra + recipes_head + stubs + lessons
              + thanks + license_s)
# -- kept-front links whose sections moved: point them at the pages --
def sl(h):
    h = re.sub(r"[^\w\s-]", "", h.strip().lstrip("#").strip().lower())
    return re.sub(r"\s", "-", h)
threads_slug = sl("Threads (`-t`), batch threads (`-tb`) and two concurrent clients — measured")
new_readme = new_readme.replace(
    "](#ud-q4_k_xl-evaluated-and-dropped-2026-08-21--gguf-deleted-locally)",
    "](docs/BUILDING.md#ud-q4_k_xl-evaluated-and-dropped-2026-08-21--gguf-deleted-locally)")
new_readme = new_readme.replace(
    "docs/BENCHMARKS.md#threads--t--batch-threads--tb--and-two-concurrent-clients--measured",
    f"docs/BENCHMARKS.md#{threads_slug}")
open(SRC, "w").write(new_readme)
print("split complete:",
      f"README {new_readme.count(chr(10))} lines;",
      {p: open('docs/'+p).read().count(chr(10)) for p in os.listdir('docs') if p.endswith('.md') and p != 'PLAN-reasoning-economics.md'})

# Why this exists — cloud-free intelligence on a desk

> From [Qwen3.8-27B on Strix Halo](../README.md) — the full pitch, with the
> numbers, the power math, and the philosophy.

If you are a solo developer with an AI agent working around the clock, a
privacy-sensitive operator, or any other entity that wants to be free from
cloud chains — read on. An all-purpose computer that cost **less than €2,000**
(launch offer) now serves a 27-billion-parameter reasoning model, entirely
from your own desk. Which machine? We tested on a **GMKtec EVO-X2** (Ryzen
AI MAX+ 395, 128 GiB) — [amazon.it/dp/B0F6X332N6](https://www.amazon.it/dp/B0F6X332N6/) —
any mini-PC or desktop with the same AMD Strix Halo APU works the same. **Not
affiliated**: no sponsorship, no free hardware, no affiliate links (the
shopping link above is a plain product URL, no referral tag); we paid for
ours. External links in this README point only to the open-source projects,
model publishers, hardware references, and community threads this work builds
on or measures — see
[Acknowledgements](../README.md#-thanks-to-the-authors-of-this-software-stack) — never to
sponsored placements.

- **No API keys, no quotas, no meters.** The model lives in your RAM
  (~122 GiB of it, mlock'd — the box's whole personality is inference).
- **Real speeds, measured**: ~17–21 tokens/s sustained decode of the
  **UD-Q6_K_XL quant** with DFlash2 speculative decoding (Q8_K_XL: ~15–18;
  Q5_K_XL: ~23 — the quant is the speed dial) (content-dependent: acceptance spans
  0.28–0.91, so the same model spans ~15–35 t/s; peaks near the top on
  narrative-style output), ~330 t/s prefill; a five-recipe menu (quality /
  balanced / speed / vision / a context dial to a 256k-token window) you
  switch per request, like a reasoning level.
- **Sips power**: ~85 W sustained at full tilt — order of magnitude under a
  multi-GPU rig; idle draws ~10–15 W — about half the cost of an LED lightbulb
  (~€0.01/night at €0.12/kWh, platform idle measured — vs ~€0.08/night
  if it actually idled at the 85 W full-tilt figure; verify against
  your tariff).
- **Costs cents per million tokens, all-in**: at €0.2/kWh with the €2,000
  box amortized over 3 years and a 12 h/day serving window —
  **~€2.4/Mtok at full generation, ~€9/Mtok at a realistic 25% agentic
  duty cycle** (5 joules per output token; amortization dominates,
  marginal energy is €0.0000003/token). Break-even vs budget-cloud
  output (~€2/Mtok) at ~355 Mtok/yr; vs frontier pricing (~€15/Mtok) any
  moderate agent year pays for the box — and cloud also bills the
  input-heavy side that the halo doesn't meter at all. Full sensitivity:
  `scripts/cost_model.py`.
- **Private by physics**: prompts never leave the machine. No telemetry to
  disable, no retention policy to trust — unplugged is unambiguous.
- **Yours**: no deprecations, no price changes, no terms-of-service updates
  that quietly reshape your workflow. The stack is open source end to end.

The recipes, the numbers, and every trap we hit (there were many) are
documented in this repo — so your agent can run 24/7 on hardware you own
outright.

## External validation — where this model stands (REPORTED)

Third-party datapoint, pinned 2026-08-24, verified against
`artificialanalysis.ai`'s live data: on the **Artificial Analysis
Intelligence Index v4.1.1**, *Qwen3.8 27B (xhigh)* scores **52.0 — #2
overall among listed reasoning models**, behind only its own cloud-scale
sibling *Qwen3.8 2.4T A95B* (57.7 — a 2.4-trillion-parameter MoE that
will never fit on a desk) and **ahead of the previous generation's
flagships** (Qwen3.7 Max 47, Qwen3.7 Plus 39). The same index ranks the
effort ladder we expose via the template kwargs — xhigh 52 / medium 44 /
low 43 — independently confirming that the reasoning-effort knob is a
real quality lever, not just a cost one (our E1/E2 batteries measured the
same lever from the cost and ceiling sides). Not our measurement — the
label stays REPORTED; our own numbers live in
[FINDINGS](FINDINGS.md).

## What's the price of absolute privacy?

Two answers, and both are numbers.

**Answer one — you can buy tokens, at the price of your privacy plus the
money they want.** Cloud metering is simple: ~€0.5–2 per output MegaToken
on budget APIs, ~€5–15 on frontier models (REPORTED, 2026-08 street
prices), *plus* your input tokens at the same or higher rate — and agent
loops are input-heavy (every tool call resends the whole conversation).
And you pay with more than money: every prompt crosses the wire, sits in
someone else's retention policy, and can be repriced, deprecated, or
rate-limited without your consent. Unplugged is unambiguous.

**Answer two — the desk price.** With the €2,000 box amortized over three
years, €0.2/kWh energy, and a 12 h/day × 360 d serving window on the
`balanced` recipe, the all-in cost per output MegaToken is:

| Generation duty | €/day amortization (fixed) | €/Mtok energy (marginal) | €/Mtok total | What that looks like |
|---:|---:|---:|---:|---|
| 100% | 1.85 | 0.28 | **2.42** | a bot generating flat-out |
| 50% | 1.85 | 0.38 | **4.66** | heavy daily driver |
| 25% | 1.85 | 0.57 | **9.14** | a realistic agentic workload |
| 10% | 1.85 | 1.15 | **22.59** | evenings-and-weekends tinkering |

*Read the cost columns as two different kinds of bills. **Amortization
is a subscription: €1.85/day** (€667/yr ÷ 360 serving days), charged
every day whether you generate a million tokens or none — like a $200
/month Claude plan you never open, it still bills daily. **Energy is
the pay-per-use meter**: near-zero and flat (5 J per output token at
any duty). The totals climb as duty falls **only because a fixed daily
bill gets divided by fewer tokens** — a quieter box doesn't pay more
for electricity, it just spreads the same subscription thinner. (The
loaded-wait draw — model resident, GPU initialized, no generation — is
measured at ~35 W wall, so a serving window is never at the 5–10 W
unloaded idle.)*

*But treat the low-duty rows as the **dedicated-box upper bound**, not a
real user's bill. Two corrections that compound: a 128 GiB low-power box
like this realistically serves ~10 years (its post-inference career as a
Proxmox/LXC host included); and a 10%-inference user almost by
definition runs other services on it — inference is a **tenant**, not
the owner (with on-demand loading the model needn't even stay resident;
cold load ≈ 10 s). The same 31 Mtok/year, re-priced:*

| The light 10%-user's real box (31.1 Mtok/yr) — worst scenario | €/Mtok |
|---|---:|
| dedicated 3-year inference box (the table's corner case) | 22.59 |
| 10-year hardware life | 7.58 |
| 10-yr box, inference one tenant among services (~25% of amortization) | **2.76** |
| energy floor (amortization belongs to the other services) | 1.15 |

*And the mirror image for the heavy user — same machine, same 3-year
assumption, but generating flat-out through the whole 12 h window
(311 Mtok/yr **of output**; see the accounting note below the table;
best scenario):*

| The 100%-SOHO real box (311 Mtok/yr out) | €/Mtok |
|---|---:|
| dedicated 3-year inference box (the table's own row) | 2.42 |
| 10-year hardware life | 0.92 |
| 10-yr box, inference the main tenant (~50% of amortization) | **0.60** |
| energy floor (amortization belongs to the other services) | 0.28 |

### The accountant's table — both sides metered, input and output

Cloud meters both directions (input often at output price or higher);
the halo meters them at different physics (input costs ~1/17 the energy
per token). Same heavy year for both — h24 flat-out at ~100 t/s blended
(the pp 200–350 / tg 20–25 reality), i.e. **622 Mtok output +
~2.5 Gtok input** — priced on each side's own tariff:

| Who pays for that year | €/year |
|---|---:|
| **Halo, dedicated 3-yr box** | **839** |
| **Halo, 10-yr box, inference 50% tenant** | **273** |
| **Halo, energy floor** (box amortized by other duties) | **173** |
| Budget API (€0.15/Mtok in · €0.60/Mtok out) | ~746 |
| Budget API + $20/mo subscription | ~1,031 |
| Frontier tier (€3/Mtok in · €15/Mtok out) | ~16,800 |
| **Frontier + $200/mo subscription (the Claude plan)** | **~19,600** |

*(REPORTED cloud street prices 2026-08; subscriptions converted at
12×/yr; usage-based portion is 622×out-price + 2,488×in-price.)*

Read it in one line: **the desk does the whole heavy year for less than
the cheapest metered cloud does it, and for 1–4% of the frontier-subscription
year** — with the input-heavy side, the exact part agent loops multiply,
being the desk's cheapest physics. And the €273 tenant row is the
realistic one: the privacy-critical year costs about one frontier
*week*.

**Accounting note.** All Mtok figures are **output tokens** (the meter
clients feel). Input isn't free but is ~17× cheaper per token here
(prefill ~350 t/s vs decode 20 t/s at similar power): at a 4:1 agent
input:output ratio the energy floor rises only from €0.28 to
€0.34/Mtok-out; at a pathological 10:1, €0.44. And the window matters:
"100% duty" means flat-out through the 12 h/day serving window = 311
Mtok/yr; a never-idle h24×365 box would reach ~622.

> **What the energy floor actually buys.** At ~€0.28–0.44/Mtok, the
> desk matches low-cost cloud inference on price — but that comparison
> misses the point, and the point deserves its own paragraph: **this is
> the price of absolute privacy.** The rational pattern is a hybrid —
> use commodity cloud where privacy genuinely doesn't matter, and keep
> the desk for what must never leave the premises: an attorney's case
> files, medical records, unreleased financials, source code under NDA,
> personal journals. For exactly those workloads the halo isn't
> competing on €/Mtok at all; it's the difference between *possible*
> and *impossible*. Cloud can lower its price to zero and still not
> sell you what this box gives you: the prompt physically never left
> the room.

The physics anchor is duty-independent: **100 W wall ÷ 20 t/s served =
5 joules per output token** — €0.28/Mtok in pure energy, and the box's
amortization (€2.14/Mtok at full duty) costs more than the electricity
at every usage level. Which flips the usual intuition: **owning is
high-fixed / near-zero-marginal (one more token costs €0.0000003),
cloud is zero-fixed / high-marginal.** Run the sensitivity yourself:
[`scripts/cost_model.py`](../scripts/cost_model.py) — every parameter is
documented with its provenance (86 W APU draw is measured; 100 W wall is
inferred pending a wall meter).

**Break-even, honestly stated.** Against €2/Mtok budget output, the halo
needs ~355 Mtok/yr to win — more than a light user generates; at 25% duty
you produce ~78 Mtok/yr, so *budget clouds are cheaper per output token
for light use, and we're not going to pretend otherwise*. Against
frontier pricing (~€15/Mtok), break-even is ~47 Mtok/yr — any moderate
agent year pays for the hardware. Two asymmetries close the rest of the
gap: the halo doesn't meter your input side at all (prefill costs ~1/17
the energy per token), and privacy doesn't appear on either ledger but
only one of them has it.

That's the whole pitch in one sentence: **the privacy is not a premium —
at any serious usage it's a discount.**

## How we know (the method behind every number)

All benchmarks are back-to-back interleaved pairs (lesson #1); every battery's
raw evidence is committed under `results/` — CSVs, server logs, kernel
journal excerpts; experiments run under pre-registered decision rules (see
[PLAN-INDEX](PLAN-INDEX.md); the reasoning plan has landed and is archived
locally) and the reasoning batteries' answer keys are computed by the graders
themselves; claims carry OBSERVED / INFERRED / REPORTED labels; and when our
own adversarial README audit caught numbers without committed evidence, we
corrected the README rather than the evidence (2026-08-23). If a number in
this repo can't be re-run from it, it doesn't belong here.

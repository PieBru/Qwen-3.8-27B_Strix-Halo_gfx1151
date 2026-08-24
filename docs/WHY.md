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

| Generation duty | €/Mtok (all-in) | What that looks like |
|---:|---:|---|
| 100% | €2.42 | a bot generating flat-out |
| 50% | €4.66 | heavy daily driver |
| 25% | €9.14 | a realistic agentic workload |
| 10% | €22.59 | evenings-and-weekends tinkering |

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

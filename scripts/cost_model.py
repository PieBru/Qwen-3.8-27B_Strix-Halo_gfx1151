#!/usr/bin/env python3
"""cost_model — Euro per MegaToken for a serving halo (operator question 2026-08-24).

Model: fixed amortization + wall energy over the operating window, divided
by tokens generated in that window. All parameters below; run to print the
sensitivity table. stdlib only.

Input provenance (OBSERVED / INFERRED):
- P_apu_serving = 86 W   OBSERVED  amdgpu power1_average during active
                         Q6+DFlash2 serving (2026-08-24 session)
- P_wall_serving = 100 W INFERRED  APU + ~15% platform/PSU overhead
                         (mini-PC wall draw under load; measure with a
                         wall meter to tighten)
- P_wall_wait    = 35 W  INFERRED  stack loaded (weights mlocked, GPU
                         initialized), no generation in flight
- decode         = 20 t/s OBSERVED  balanced recipe served range 17-21
- prefill        ≈ 350 t/s ⇒ ~0.29 J/token ≈ 1/17 of decode energy per
  token: prompt tokens are energy-negligible; the model prices OUTPUT
  tokens (agentic loops also prefill, ~4:1 in:out ⇒ +7% energy, ignored)
- idle 24/7 instead of 12h-on: add P_wait × 4320 h × price
  (35 W ⇒ +€30/yr; near-suspend 5 W ⇒ +€4.3/yr)
"""
import os
import sys
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root

# ---- parameters (edit here) ----
PRICE_EUR_KWH = 0.20
HARDWARE_EUR  = 2000.0
YEARS         = 3
HOURS_PER_DAY = 12
DAYS_PER_YEAR = 360
DECODE_TPS    = 20.0          # served, balanced Q6+DFlash2
P_GEN_W       = 100.0         # wall, while generating
P_WAIT_W      = 35.0          # wall, on but not generating
DUTIES        = [1.0, 0.5, 0.25, 0.10, 0.05]   # share of window generating
# --------------------------------

HOURS = HOURS_PER_DAY * DAYS_PER_YEAR            # 4320 h/yr
AMORT = HARDWARE_EUR / YEARS                     # 666.67 €/yr
J_PER_TOK = P_GEN_W / DECODE_TPS                 # 5 J/output token
KWH_PER_MTOK = J_PER_TOK * 1e6 / 3.6e6           # 1.389 kWh/Mtok

print(f"window: {HOURS:.0f} h/yr · amortization {AMORT:.2f} €/yr · "
      f"{J_PER_TOK:.1f} J/token ⇒ {KWH_PER_MTOK:.3f} kWh/Mtok "
      f"(€{KWH_PER_MTOK*PRICE_EUR_KWH:.3f}/Mtok energy-only)")
print(f"{'duty':>5} {'Pavg W':>7} {'energy €/yr':>11} {'Mtok/yr':>9} "
      f"{'€/Mtok ener':>12} {'€/Mtok amort':>12} {'€/Mtok TOTAL':>12}")
for d in DUTIES:
    p_avg = d * P_GEN_W + (1 - d) * P_WAIT_W
    energy = p_avg / 1000 * HOURS * PRICE_EUR_KWH
    mtok = HOURS * 3600 * d * DECODE_TPS / 1e6
    e_per, a_per = energy / mtok, AMORT / mtok
    print(f"{d:>5.0%} {p_avg:>7.1f} {energy:>11.2f} {mtok:>9.1f} "
          f"{e_per:>12.3f} {a_per:>12.4f} {e_per + a_per:>12.3f}")

# sanity: pure decode energy independent of duty (physics, not schedule)
assert abs(J_PER_TOK - 5.0) < 1e-9
assert abs(KWH_PER_MTOK - 1.389) < 0.01
print("cloud reference (REPORTED): budget APIs ~€0.5-2/Mtok out; "
      "frontier ~€5-15/Mtok out")

# break-even: annual cloud spend the halo replaces (fixed €/yr, duty-dependent)
print(f"\nbreak-even vs cloud (annual output Mtok where cloud = halo cost):")
for d in [0.25, 1.0]:
    p_avg = d * P_GEN_W + (1 - d) * P_WAIT_W
    halo_yr = AMORT + p_avg / 1000 * HOURS * PRICE_EUR_KWH
    for cloud in (2.0, 15.0):
        print(f"  duty {d:.0%}: halo {halo_yr:.0f} €/yr  vs cloud €{cloud:.0f}/Mtok "
              f"⇒ break-even {halo_yr / cloud:.0f} Mtok/yr "
              f"(halo generates {HOURS*3600*d*DECODE_TPS/1e6:.0f} Mtok at full duty-hours)")
print("note: cloud also bills input tokens (agent loops are input-heavy); "
      "halo marginal energy per extra token is 5 J ≈ €0.0000003")
sys.exit(0)

#!/usr/bin/env python3
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")  # repo root (script lives in scripts/)
"""E2 quality battery — plan docs/PLAN-reasoning-economics.md.

Deterministic, self-built items (no verbatim public-benchmark content, no LLM
judge). Four categories x 10 items:
  numeric  — multi-step word problems; the LAST number on the last line of the
             reply must equal the expected value (strict extraction contract)
  json     — extract structured JSON from messy text; first JSON object in the
             reply must validate against a per-item checker
  code     — small function spec; reply's code must pass embedded unit tests
             (executed via python3 subprocess, 10 s ceiling)
  multihop — 2-hop questions over the fictional corpus in results/e2_corpus.py;
             last non-empty line must equal the expected string (ci-compare)

Cells (effort x tier): tier-1 = Q6@off, Q6@xhigh, Q8@off, Q8@xhigh, Q8@medium
on items 0-4 of each category; --full adds Q6@low, Q6@medium, Q8@low on all 40.

Usage:
  uv run --with requests python3 e2_quality_battery.py [--cells tier1|full] [--out results/e2-quality.csv]
Self-check (no GPU): --selfcheck verifies every item's expected answer
against its own checker (sabotage guard for the graders).
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys
import tempfile
import time

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "results"))
from e2_corpus import render_directory  # noqa: E402

HOST = "localhost:8080"
MODELS = {"Q8": "Qwen38-27B-quality@64k", "Q6": "Qwen38-27B-balanced"}
MAXTOK = 4096
CORPUS = render_directory()


def _retry(fn, tries=8, backoff=3.0):
    """Tolerate router model-swap reload churn (models-max 1)."""
    import time as _t
    last = None
    for i in range(tries):
        try:
            return fn()
        except requests.HTTPError as e:
            last = e
            if e.response is not None and e.response.status_code < 500 and e.response.status_code != 429:
                raise
            _t.sleep(backoff * (i + 1))
        except (requests.ConnectionError, requests.Timeout) as e:
            last = e
            _t.sleep(backoff * (i + 1))
    raise last

NUMERIC_TAIL = " End your reply with the final numeric answer alone on the last line."
MHOP_TAIL = " End your reply with the exact answer alone on the last line."

NUMERIC = [
    ("A warehouse has 3 aisles with 14 shelves each; each shelf holds 6 boxes "
     "weighing 250 g. Total weight in kg?", "63"),
    ("A phone battery drains 4 percent per hour in standby and 12 percent per "
     "hour in use. Starting from 100%, after 3 hours of use and then 5 hours "
     "of standby, what is the remaining charge in percent?", "44"),
    ("Cinema tickets cost 12 EUR for adults and 7 EUR for children. A family "
     "of 2 adults and 3 children pays with a 50 EUR note. Change in EUR?", "5"),
    ("A machine produces 240 parts per hour and 3.5 percent fail quality "
     "control. How many GOOD parts does it produce in 2.5 hours?", "579"),
    ("A tank holds 1200 L. It drains at 15 L/min for 25 minutes, then fills at "
     "8 L/min for 40 minutes. Final volume in liters?", "1145"),
    ("A monthly salary is 3200 EUR net. Rent takes 38 percent, food 22 "
     "percent, and transport costs 145 EUR. How much is left, in EUR?", "1135"),
    ("A concert hall has 18 rows of 25 seats plus 5 wheelchair spots. Over 3 "
     "shows with 80 percent average occupancy, how many attendees in total?", "1092"),
    ("A recipe for 4 people needs 300 g of flour. How many grams are needed "
     "for 7 people with a 20 percent margin?", "630"),
    ("A train covers 240 km at 80 km/h, waits 15 minutes, then returns the "
     "same distance at 60 km/h. Total travel time in hours (2 decimals)?", "7.25"),
    ("An investment of 5000 EUR earns 4 percent compound interest annually. "
     "Interest earned after 3 full years, in EUR (2 decimals)?", "624.32"),
]

JSON_ITEMS = [
    ("Invoice IN-2093, issued 2026-03-04 by Nordic Tooling Oy to buyer "
     "Sundvik AB, contains 7 line items; goods value 11840.00 EUR, VAT 24% "
     "(2841.60 EUR), grand total 14681.60 EUR, already paid in full.",
     {"invoice_id": "IN-2093", "seller": "Nordic Tooling Oy", "buyer": "Sundvik AB",
      "items_count": 7, "goods_eur": 11840.0, "vat_eur": 2841.6,
      "grand_total_eur": 14681.6, "paid": True}),
    ("Server node het-04: 2 sockets, 32 cores each, 384 GB RAM, 4x 3.84 TB "
     "NVMe, online since 2025-11-02, current state degraded (one NVMe slot "
     "failed).",
     {"node": "het-04", "sockets": 2, "cores": 64, "ram_gb": 384,
      "nvme_count": 4, "nvme_tb": 15.36, "state": "degraded"}),
    ("Order #88117: customer Lena Fischer ordered 3x ceramic mug (9.50 EUR "
     "each) and 2x glass carafe (24.00 EUR each); shipping 6.90 EUR; delivery "
     "to Linz, Austria; payment method invoice.",
     {"order_id": "#88117", "customer": "Lena Fischer", "mugs_qty": 3,
      "carafe_qty": 2, "shipping_eur": 6.9, "city": "Linz",
      "payment": "invoice"}),
    ("Sensor S-42 log summary: uptime 312 hours, 14 warnings, 2 critical "
     "events, mean temperature 21.7 C, max 38.2 C at 2026-02-14T09:31, "
     "battery 61 percent.",
     {"sensor": "S-42", "uptime_h": 312, "warnings": 14, "critical": 2,
      "mean_temp_c": 21.7, "max_temp_c": 38.2, "battery_pct": 61}),
    ("Meeting notes: attendees were Meret Aaltonen (chair), Tobias Greve and "
     "Priya Nair; quorum reached (3 of 5 board members); three action items "
     "recorded; next meeting 2026-04-08; minutes approved unanimously.",
     {"chair": "Meret Aaltonen", "attendees_count": 3, "quorum": True,
      "action_items": 3, "next_meeting": "2026-04-08", "approved": True}),
    ("Shipment TRK-772019: 6 pallets, gross 2140 kg, net 1985 kg, route "
     "Hamburg -> Verona via Brenner, carrier Kessler Freight, ETA 2026-05-17, "
     "one pallet re-wrapped in transit.",
     {"tracking": "TRK-772019", "pallets": 6, "gross_kg": 2140, "net_kg": 1985,
      "origin": "Hamburg", "destination": "Verona", "rewrapped": 1}),
    ("Course 'Applied Topology I': 34 enrolled, 29 present at exam, 24 "
     "passed, top grade 1.0 (Austrian scale), instructor Dr. Weisz, semester "
     "2026S, credits 6 ECTS.",
     {"course": "Applied Topology I", "enrolled": 34, "present": 29,
      "passed": 24, "top_grade": 1.0, "ects": 6}),
    ("Fleet car AI-911-K: odometer 148320 km, fuel type diesel, tank 52 L "
     "(three-quarters full), last service at 140000 km, next inspection due "
     "2026-09-30, assigned to sales team.",
     {"plate": "AI-911-K", "odometer_km": 148320, "fuel": "diesel",
      "tank_l": 52, "last_service_km": 140000, "team": "sales"}),
    ("Experiment run RC-118: 4 groups of 12 samples; incubation 37.5 C for "
     "72 h; 3 contaminated samples discarded; success criterion met in "
     "groups A, B and D but not C; operator Y. Sato.",
     {"run": "RC-118", "groups": 4, "samples_per_group": 12,
      "incubation_c": 37.5, "hours": 72, "discarded": 3, "failed_groups": ["C"],
      "operator": "Y. Sato"}),
    ("Library branch 'Nordport': open 6 days/week, closed Sundays, 41200 "
     "volumes, 18 reading seats, 3 public terminals, membership 5100 adults "
     "plus 900 juniors, renovation planned for 2027.",
     {"branch": "Nordport", "open_days": 6, "volumes": 41200,
      "reading_seats": 18, "terminals": 3, "adults": 5100, "juniors": 900}),
]

CODE_ITEMS = [
    ("def flatten(nested): return a flat list from an arbitrarily nested "
     "list of lists (no imports)",
     "assert flatten([1,[2,[3,[4]],5],[[6]]]) == [1,2,3,4,5,6]\n"
     "assert flatten([]) == []\nassert flatten([[[]]]) == []\n"
     "assert flatten([[[7]]]) == [7]"),
    ("def roman(n): convert integer 1..3999 to Roman numeral string",
     "assert roman(4)=='IV' and roman(9)=='IX' and roman(58)=='LVIII'\n"
     "assert roman(1994)=='MCMXCIV' and roman(3999)=='MMMCMXCIX'\n"
     "assert roman(1)=='I' and roman(40)=='XL' and roman(90)=='XC'"),
    ("def clean_pal(s): True if s is a palindrome ignoring case, spaces and "
     "punctuation",
     "assert clean_pal('A man, a plan, a canal: Panama') is True\n"
     "assert clean_pal('No lemon, no melon') is True\n"
     "assert clean_pal('hello') is False\n"
     "assert clean_pal('Was it a car or a cat I saw?') is True"),
    ("def running_sum(xs): return list of cumulative sums",
     "assert running_sum([1,2,3,4]) == [1,3,6,10]\n"
     "assert running_sum([]) == []\nassert running_sum([5,-5,5]) == [5,0,5]\n"
     "assert running_sum([2.5,2.5]) == [2.5,5.0]"),
    ("def caesar(s, k): Caesar-shift letters by k (wrap z->a, preserve case), "
     "leave other characters",
     "assert caesar('abc',2)=='cde' and caesar('xyz',2)=='zab'\n"
     "assert caesar('Hello!',3)=='Khoor!'\n"
     "assert caesar(caesar('RoundTrip',5),21)=='RoundTrip'"),
    ("def days_in_month(year, month): days in given month, Gregorian leap "
     "rule; return -1 for invalid month",
     "assert days_in_month(2024,2)==29 and days_in_month(1900,2)==28\n"
     "assert days_in_month(2000,2)==29 and days_in_month(2023,4)==30\n"
     "assert days_in_month(2023,12)==31 and days_in_month(2023,0)==-1"),
    ("def bsearch(xs, t): binary search on sorted list, return index of t or "
     "-1",
     "assert bsearch([1,3,5,7,9,11],7)==3 and bsearch([1,3,5,7,9,11],4)==-1\n"
     "assert bsearch([],1)==-1 and bsearch([2],2)==0\n"
     "assert bsearch([1,2,3,4,5,6,7,8],8)==7"),
    ("def anagram(a, b): True if a and b are anagrams, ignoring case and "
     "spaces",
     "assert anagram('Dormitory','Dirty Room') is True\n"
     "assert anagram('The eyes','They see') is True\n"
     "assert anagram('abc','abd') is False\nassert anagram('','') is True"),
    ("def fizzbuzz(n): return list of 1..n where multiples of 3 are 'Fizz', "
     "of 5 'Buzz', of both 'FizzBuzz', else the number",
     "assert fizzbuzz(5)==[1,2,'Fizz',4,'Buzz']\n"
     "assert fizzbuzz(15)[-1]=='FizzBuzz' and fizzbuzz(15)[2]=='Fizz'\n"
     "assert fizzbuzz(1)==[1] and len(fizzbuzz(100))==100"),
    ("def transpose(m): transpose a rectangular matrix given as list of row "
     "lists",
     "assert transpose([[1,2,3],[4,5,6]])==[[1,4],[2,5],[3,6]]\n"
     "assert transpose([[1,2],[3,4],[5,6]])==[[1,3,5],[2,4,6]]\n"
     "assert transpose([[7]])==[[7]]"),
]

MULTIHOP = [
    ("Who manages the retired technician whose primary equipment is kiln K-2?",
     "Mira Deel"),
    ("At which plant is the equipment that Quinn Harada maintains installed?",
     "Southmere Plant"),
    ("Who is the manager of the manager of Gus Ferreira?", "Elin Park"),
    ("Who is the line lead at Westquay Plant, and who do they report to? "
     "Answer as: 'NAME reports to NAME'.", "Kira Blum reports to Ivo Brandt"),
    ("How many ACTIVE technicians work at Eastfold Plant?", "1"),
    ("How many plants have a turbine as the plant director's primary "
     "equipment?", "2"),
    ("Which inspector works at the plant where conveyor C-2 is installed?",
     "Tomas Vela"),
    ("Start at Hana Ito and follow manager links until the top of the "
     "hierarchy. Who is at the top?", "Ivo Brandt"),
    ("What is the role of Dario Kohn's manager?", "plant director"),
    ("What is the year gap between the OLDEST and NEWEST installed equipment "
     "at Southmere Plant?", "8"),
]

FIELDS = ["cell", "model_tier", "effort", "category", "item_id",
          "correct", "expected", "got_tail", "reasoning_tokens",
          "content_tokens", "wall_s", "finish_reason", "ts"]


# ---------------------------------------------------------------- checkers
def last_number(text):
    nums = re.findall(r"-?\d+(?:[.,]\d+)?", text.replace(",", ""))
    return nums[-1].replace(",", ".") if nums else None


def check_numeric(got, expected):
    g = last_number(got or "")
    if g is None:
        return False
    try:
        return abs(float(g) - float(expected)) <= max(0.01, abs(float(expected)) * 0.001)
    except ValueError:
        return False


def extract_json(text):
    text = re.sub(r"```(?:json)?|```", "", text or "")
    depth, start = 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    start = None
    return None


def close(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 0.01
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(close(x, y) for x, y in zip(a, b))
    return a == b


def check_json(got, expected):
    obj = extract_json(got or "")
    if not isinstance(obj, dict):
        return False
    for k, v in expected.items():
        if k not in obj or not close(obj[k], v):
            return False
    return True


def extract_code(text):
    m = re.findall(r"```(?:python)?\n(.*?)```", text or "", re.S)
    return m[0] if m else (text or "")


def check_code(got, tests):
    code = extract_code(got)
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write(code + "\n\n" + tests + "\nprint('ALL TESTS PASSED')\n")
        path = fh.name
    try:
        r = subprocess.run([sys.executable, path], capture_output=True,
                           text=True, timeout=10)
        return r.returncode == 0 and "ALL TESTS PASSED" in r.stdout
    except subprocess.TimeoutExpired:
        return False
    finally:
        os.unlink(path)


def check_multihop(got, expected):
    lines = [l.strip() for l in (got or "").splitlines() if l.strip()]
    return bool(lines) and lines[-1].strip().strip(".").lower() == expected.lower()


CHECKERS = {"numeric": check_numeric, "json": check_json,
            "code": check_code, "multihop": check_multihop}


def selfcheck():
    """Verify each item's expected answer passes its own checker."""
    ok = True
    for i, (_, exp) in enumerate(NUMERIC):
        if not check_numeric(f"blah\n{exp}", exp):
            print(f"SELFCHECK FAIL numeric {i}"); ok = False
    for i, (_, exp) in enumerate(JSON_ITEMS):
        if not check_json(json.dumps(exp), exp):
            print(f"SELFCHECK FAIL json {i}"); ok = False
    for i, (_, tests) in enumerate(CODE_ITEMS):
        pass  # code items checked against reference solutions below
    # code selfcheck: each test block must accept a correct reference solution
    refs = [
        "def flatten(n):\n    out=[]\n    def go(x):\n        for i in x:\n            go(i) if isinstance(i,list) else out.append(i)\n    go(n)\n    return out",
        "def roman(n):\n    v=[(1000,'M'),(900,'CM'),(500,'D'),(400,'CD'),(100,'C'),(90,'XC'),(50,'L'),(40,'XL'),(10,'X'),(9,'IX'),(5,'V'),(4,'IV'),(1,'I')]\n    r=''\n    for x,s in v:\n        while n>=x: r+=s; n-=x\n    return r",
        "import re\ndef clean_pal(s):\n    t=''.join(c.lower() for c in s if c.isalnum())\n    return t==t[::-1]",
        "def running_sum(xs):\n    o=[];a=0\n    for x in xs: a+=x; o.append(a)\n    return o",
        "def caesar(s,k):\n    o=''\n    for c in s:\n        if c.isalpha():\n            b=65 if c.isupper() else 97\n            o+=chr((ord(c)-b+k)%26+b)\n        else: o+=c\n    return o",
        "def days_in_month(y,m):\n    if m<1 or m>12: return -1\n    d=[31,28,31,30,31,30,31,31,30,31,30,31]\n    if m==2 and (y%400==0 or (y%4==0 and y%100!=0)): return 29\n    return d[m-1]",
        "def bsearch(xs,t):\n    lo,hi=0,len(xs)-1\n    while lo<=hi:\n        m=(lo+hi)//2\n        if xs[m]==t: return m\n        if xs[m]<t: lo=m+1\n        else: hi=m-1\n    return -1",
        "def anagram(a,b):\n    x=sorted(c.lower() for c in a if c.isalpha())\n    y=sorted(c.lower() for c in b if c.isalpha())\n    return x==y",
        "def fizzbuzz(n):\n    o=[]\n    for i in range(1,n+1):\n        s=('Fizz' if i%3==0 else '')+('Buzz' if i%5==0 else '')\n        o.append(s or i)\n    return o",
        "def transpose(m):\n    return [list(r) for r in zip(*m)]",
    ]
    for i, (_, tests) in enumerate(CODE_ITEMS):
        if not check_code(f"```python\n{refs[i]}\n```", tests):
            print(f"SELFCHECK FAIL code {i} (reference solution rejected)")
            ok = False
        if check_code("def flatten(n):\n    return []", tests):
            print(f"SELFCHECK FAIL code {i} (trivial wrong code accepted)")
            ok = False
    for i, (_, exp) in enumerate(MULTIHOP):
        if not check_multihop(f"reasoning...\n{exp}.", exp):
            print(f"SELFCHECK FAIL multihop {i}"); ok = False
    print("SELFCHECK", "OK" if ok else "FAILED")
    return ok


# ---------------------------------------------------------------- serving
def chat(model, effort, user):
    body = {"model": model,
            "messages": [{"role": "user", "content": user}],
            "chat_template_kwargs": {"reasoning_effort": effort},
            "temperature": 0.0, "max_tokens": MAXTOK}
    t0 = time.time()
    def _do():
        r = requests.post(f"http://{HOST}/v1/chat/completions", json=body, timeout=300)
        r.raise_for_status()
        return r
    r = _retry(_do)
    wall = time.time() - t0
    d = r.json()
    ch = d["choices"][0]
    msg = ch.get("message", {})
    return {"content": msg.get("content") or "",
            "reasoning": msg.get("reasoning_content") or "",
            "usage": d.get("usage", {}), "finish": ch.get("finish_reason"),
            "wall": wall}


def ntokens(text, model):
    if not text:
        return 0
    def _do():
        r = requests.post(f"http://{HOST}/tokenize",
                          json={"content": text, "model": model}, timeout=120)
        r.raise_for_status()
        return len(r.json()["tokens"])
    return _retry(_do, tries=2)


def items_for(category, tier1):
    n = 5 if tier1 else 10
    if category == "numeric":
        return [(q + NUMERIC_TAIL, exp, exp) for q, exp in NUMERIC[:n]]
    if category == "json":
        return [(q, exp, exp) for q, exp in JSON_ITEMS[:n]]
    if category == "code":
        return [(spec + ". Reply with ONLY the Python function in one code block.",
                 tests, None) for spec, tests in CODE_ITEMS[:n]]
    return [(q + MHOP_TAIL, exp, exp) for q, exp in MULTIHOP[:n]]


JSON_PROMPT = ("Extract the following information as ONE JSON object with "
               "exactly these keys and value types: {keys}. Use plain JSON, "
               "no commentary.\n\n{text}\nJSON:")


def build_prompt(category, item):
    q = item[0]
    if category == "json":
        spec, expected, _ = item
        keys = ", ".join(expected.keys())
        return JSON_PROMPT.format(keys=keys, text=spec)
    if category == "multihop":
        return ("Answer using ONLY the directory below.\n\n"
                + CORPUS + "\n\nQuestion: " + q)
    return q


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", default="tier1", choices=["tier1", "full"])
    ap.add_argument("--out", default="results/e2-quality.csv")
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args()

    if args.selfcheck or True:
        if not selfcheck():
            sys.exit(2)
        if args.selfcheck:
            return

    cells = ([("Q6", "off"), ("Q6", "xhigh"), ("Q8", "off"),
              ("Q8", "xhigh"), ("Q8", "medium")] if args.cells == "tier1" else
             [(t, e) for t in ("Q8", "Q6")
              for e in ("off", "low", "medium", "xhigh")])

    done = set()
    if os.path.exists(args.out):
        with open(args.out) as fh:
            for r in csv.DictReader(fh):
                done.add((r["model_tier"], r["effort"], r["category"], int(r["item_id"])))
    print(f"resume: {len(done)} done")

    header_needed = not os.path.exists(args.out)
    fh = open(args.out, "a", newline="", buffering=1)
    wr = csv.DictWriter(fh, fieldnames=FIELDS)
    if header_needed:
        wr.writeheader()
    for tier, effort in cells:
        for cat in ("numeric", "json", "code", "multihop"):
            for iid, item in enumerate(items_for(cat, args.cells == "tier1")):
                if (tier, effort, cat, iid) in done:
                    continue
                res = chat(MODELS[tier], effort, build_prompt(cat, item))
                correct = CHECKERS[cat](res["content"], item[1])
                row = {"cell": f"{tier}@{effort}", "model_tier": tier,
                       "effort": effort, "category": cat, "item_id": iid,
                       "correct": int(correct), "expected": str(item[1])[:80],
                       "got_tail": (res["content"] or "").strip().splitlines()[-1][:80]
                       if (res["content"] or "").strip() else "",
                       "reasoning_tokens": ntokens(res["reasoning"], MODELS[tier]),
                       "content_tokens": ntokens(res["content"], MODELS[tier]),
                       "wall_s": round(res["wall"], 2),
                       "finish_reason": res["finish"],
                       "ts": time.strftime("%H:%M:%S")}
                wr.writerow(row)
                print(f"[{row['ts']}] {row['cell']:12} {cat:8} i{iid} -> "
                      f"{'PASS' if correct else 'FAIL'} think={row['reasoning_tokens']:5} "
                      f"vis={row['content_tokens']:4} wall={row['wall_s']:6}s", flush=True)
    fh.close()
    print("battery complete")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""E7 — temperature sweep for CODING on Qwen3.8-27B (community claim:
temp 0.6-0.8 beats greedy for coding). Pre-registered 2026-08-24 night.

Design: 10 hard-ish coding items (algorithmically nontrivial, deterministic
unit tests; harder than the routine E2 set so we're OFF the ceiling where
temp differences can show), temps {0, 0.3, 0.6, 0.8, 1.0}, n=1 at temp 0
(greedy = deterministic), n=3 at temp>0 (sampling), served through the
production router on Qwen38-27B-coding (top_p 0.95 default kept — the
community claim is about temp alone).

Metrics per temp: pass rate (items passing >=1 sample and mean-pass),
mean tokens (reasoning+content), and DFlash2 acceptance from the server
journal (spec decode may suffer under sampling).

Verdict rule (pre-registered): claim VERIFIED iff pass(0.6 or 0.8) >
pass(0), or equal pass with >=10% fewer tokens; FALSIFIED if pass drops;
INCONCLUSIVE at ceiling (all temps 10/10) — escalate to e2c-frontier
items in a follow-up.

Run: uv run --with requests python3 scripts/e7_temp_battery.py
"""
import os
import re
import json
import time
import urllib.request

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root

HOST = "http://127.0.0.1:8080"
MODEL = "Qwen38-27B-coding"
TEMPS = [0.0, 0.3, 0.6, 0.8, 1.0]
N_AT_TEMP = {0.0: 1}
N_DEFAULT = 3

# Each item: (task prompt, test-harness source). The harness defines a
# function `check(f)` receiving the model's code block as exec-able source.
ITEMS = [
    ("def longest_pal_sub(s): longest palindromic SUBSTRING (not subsequence), O(n^2) or better, return the string",
     "def check(src):\n"
     "    ns = {}\n"
     "    exec(src, ns)\n"
     "    f = ns['longest_pal_sub']\n"
     "    assert f('babad') in ('bab','aba')\n"
     "    assert f('cbbd') == 'bb'\n"
     "    assert f('a') == 'a'\n"
     "    assert f('') == ''\n"
     "    assert f('forgeeksskeegfor') == 'geeksskeeg'\n"),
    ("def medians(a, b): median of two sorted lists in O(log(m+n)); return float",
     "def check(src):\n"
     "    ns = {}\n"
     "    exec(src, ns)\n"
     "    f = ns['medians']\n"
     "    assert f([1,3],[2]) == 2.0\n"
     "    assert f([1,2],[3,4]) == 2.5\n"
     "    assert f([],[1]) == 1.0\n"
     "    assert f([1,2,3,4,5],[6]) == 3.5\n"),
    ("def word_break(s, words): True if s can be segmented into space-separated words from the list (reuse allowed)",
     "def check(src):\n"
     "    ns = {}\n"
     "    exec(src, ns)\n"
     "    f = ns['word_break']\n"
     "    assert f('leetcode', ['leet','code']) is True\n"
     "    assert f('applepenapple', ['apple','pen']) is True\n"
     "    assert f('catsandog', ['cats','dog','sand','and','cat']) is False\n"
     "    assert f('', ['a']) is True\n"),
    ("def max_subarray(xs): maximum sum of a contiguous subarray (Kadane); return the sum",
     "def check(src):\n"
     "    ns = {}\n"
     "    exec(src, ns)\n"
     "    f = ns['max_subarray']\n"
     "    assert f([-2,1,-3,4,-1,2,1,-5,4]) == 6\n"
     "    assert f([1]) == 1\n"
     "    assert f([5,4,-1,7,8]) == 23\n"
     "    assert f([-1,-2,-3]) == -1\n"),
    ("def lcs(a, b): length of longest common subsequence",
     "def check(src):\n"
     "    ns = {}\n"
     "    exec(src, ns)\n"
     "    f = ns['lcs']\n"
     "    assert f('abcde','ace') == 3\n"
     "    assert f('abc','abc') == 3\n"
     "    assert f('abc','def') == 0\n"
     "    assert f('AGGTAB','GXTXAYB') == 4\n"),
    ("def coin_ways(amount, coins): number of ordered combinations making amount (classic change counting, order-insensitive)",
     "def check(src):\n"
     "    ns = {}\n"
     "    exec(src, ns)\n"
     "    f = ns['coin_ways']\n"
     "    assert f(5,[1,2,5]) == 4\n"
     "    assert f(3,[2]) == 0\n"
     "    assert f(0,[1,2]) == 1\n"
     "    assert f(10,[10]) == 1\n"),
    ("def topk_freq(xs, k): the k most frequent elements, any order for ties",
     "def check(src):\n"
     "    ns = {}\n"
     "    exec(src, ns)\n"
     "    f = ns['topk_freq']\n"
     "    assert sorted(f([1,1,1,2,2,3],2)) == [1,2]\n"
     "    assert f([1],1) == [1]\n"
     "    assert sorted(f([4,4,5,5,6],1)) in ([4],[5])\n"),
    ("def valid_paren_seq(s): True if s is a valid parentheses sequence of ()[]{} ",
     "def check(src):\n"
     "    ns = {}\n"
     "    exec(src, ns)\n"
     "    f = ns['valid_paren_seq']\n"
     "    assert f('()[]{}') is True\n"
     "    assert f('([)]') is False\n"
     "    assert f('{[]}') is True\n"
     "    assert f('(') is False\n"),
    ("def binary_search_rotated(xs, t): index of t in a sorted-then-rotated list, -1 if absent",
     "def check(src):\n"
     "    ns = {}\n"
     "    exec(src, ns)\n"
     "    f = ns['binary_search_rotated']\n"
     "    assert f([4,5,6,7,0,1,2],0) == 4\n"
     "    assert f([4,5,6,7,0,1,2],3) == -1\n"
     "    assert f([1],0) == -1\n"
     "    assert f([5,1,3],5) == 0\n"),
    ("def group_anagrams(words): list of anagram groups, each sorted, groups sorted by first element",
     "def check(src):\n"
     "    ns = {}\n"
     "    exec(src, ns)\n"
     "    f = ns['group_anagrams']\n"
     "    assert f(['eat','tea','tan','ate','nat','bat']) == [['ate','eat','tea'],['bat'],['nat','tan']]\n"
     "    assert f(['']) == [['']]\n"
     "    assert f(['a']) == [['a']]\n"),
]

PROMPT = ("Write a Python function exactly as specified. Reply with ONE "
          "python code block and nothing else.\n\n{spec}")


def extract_code(text):
    m = re.findall(r"```(?:python)?\s*(.*?)```", text or "", re.S)
    return m[0] if m else (text or "")


def run_one(item_spec, harness, temp, tries=5):
    last = None
    for attempt in range(tries):
        try:
            return _run_one(item_spec, harness, temp)
        except Exception as e:
            last = e
            time.sleep(3 * (attempt + 1))  # LRU swap windows pass
    raise last


def _run_one(item_spec, harness, temp):
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPT.format(spec=item_spec)}],
        "max_tokens": 3000, "temperature": temp,
    }).encode()
    req = urllib.request.Request(f"{HOST}/v1/chat/completions", body,
                                 {"Content-Type": "application/json"})
    t0 = time.time()
    r = json.load(urllib.request.urlopen(req, timeout=900))
    dt = time.time() - t0
    m = r["choices"][0]["message"]
    content = m.get("content") or ""
    reasoning = m.get("reasoning_content") or ""
    code = extract_code(content)
    ok = False
    try:
        ns = {}
        exec(harness, {"check": (lambda s: None)}, ns)  # define check
        exec(harness, ns)                                # bind
        ns["check"](code)
        ok = True
    except Exception:
        ok = False
    return ok, len(reasoning.split()), len(content.split()), dt


def main():
    rows = []
    print(f"{'temp':>4} {'item':>4} {'pass':>4} {'tok_r':>5} {'tok_c':>5} {'s':>5}")
    for temp in TEMPS:
        n = N_AT_TEMP.get(temp, N_DEFAULT)
        for i, (spec_, harness) in enumerate(ITEMS):
            for s_i in range(n):
                ok, tr, tc, dt = run_one(spec_, harness, temp)
                rows.append({"temp": temp, "item": i, "sample": s_i,
                             "pass": ok, "reason_w": tr, "content_w": tc, "wall": round(dt, 1)})
                print(f"{temp:>4} {i:>4} {'P' if ok else '.'}   {tr:>5} {tc:>5} {dt:>5.0f}")
    os.makedirs("results", exist_ok=True)
    with open("results/e7-temp.csv", "w") as f:
        f.write("temp,item,sample,pass,reason_w,content_w,wall\n")
        for r_ in rows:
            f.write(f"{r_['temp']},{r_['item']},{r_['sample']},{int(r_['pass'])},"
                    f"{r_['reason_w']},{r_['content_w']},{r_['wall']}\n")
    # summary
    print("\n=== SUMMARY (per temp) ===")
    print(f"{'temp':>4} {'mean-pass':>9} {'any-pass':>8} {'mean tok (r+c)':>14}")
    for temp in TEMPS:
        rs = [r_ for r_ in rows if r_["temp"] == temp]
        mp = sum(r_["pass"] for r_ in rs) / len(rs)
        ap = len({r_["item"] for r_ in rs if r_["pass"]}) / len(ITEMS)
        toks = sum(r_["reason_w"] + r_["content_w"] for r_ in rs) / len(rs)
        print(f"{temp:>4} {mp:>9.2f} {ap:>8.2f} {toks:>14.0f}")


if __name__ == "__main__":
    main()

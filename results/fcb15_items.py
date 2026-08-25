"""FCB-15 — frontier-calibrated coding battery (frozen after calibration).

15 short, deterministic, unit-tested coding tasks. Design contract per
docs/archive/FCB15-CALIBRATION-INTERNAL.md: spec <=40 words with pinned
semantics; machine grading only; implementation-subtle not knowledge-
gated; twisted policies so memorized classics fail; selfcheck requires
every reference solution to pass AND every WRONG probe to fail.

Consumed by scripts/fcb15_run.py. Model-agnostic: any OpenAI-compatible
chat endpoint serving a capable coder can run it unchanged.
"""

# (spec, harness) — harness defines check(src) which exec()s the model's
# code block and asserts behavior. WRONG: per-item plausible-but-broken
# solutions that MUST fail at least one assert (leak probes).

ITEMS = [

 # 1. LFU cache, tie evicts NEWEST (twist on classic)
 ("""Implement class LFU with get(key)->value or -1 and put(key,value), capacity given at init. Eviction: least frequently used; on frequency tie evict the MOST-recently-touched entry. get counts as a use.""",
  "def check(src):\n"
  "    ns={}\n"
  "    exec(src,ns)\n"
  "    LFU=ns['LFU']\n"
  "    c=LFU(2)\n"
  "    c.put('a',1); c.put('b',2)\n"
  "    c.put('c',3)\n"
  "    assert c.get('a')==1, 'tie must evict newest (b), not oldest (a)'\n"
  "    assert c.get('b')==-1 and c.get('c')==3\n"
  "    d=LFU(2)\n"
  "    d.put('x',10); d.put('y',20)\n"
  "    d.get('x'); d.get('x')   # x freq 3, y freq 1\n"
  "    d.put('z',30)            # evict y\n"
  "    assert d.get('y')==-1 and d.get('x')==10 and d.get('z')==30\n"
  "    e=LFU(1)\n"
  "    e.put('p',1); e.put('q',2)\n"
  "    assert e.get('p')==-1 and e.get('q')==2\n"),

 # 2. Wildcard matching DP (proven deterministic frontier-killer)
 ("""def match(s, p): full-string wildcard matching where '*' matches any sequence (including empty) and '.' any single character. Return bool.""",
  "def check(src):\n"
  "    ns={}\n"
  "    exec(src,ns)\n"
  "    f=ns['match']\n"
  "    assert f('aa','a') is False\n"
  "    assert f('aa','a*') is True\n"
  "    assert f('ab','.*') is True\n"
  "    assert f('aab','c*a*b') is True\n"
  "    assert f('mississippi','mis*is*p*.') is False\n"
  "    assert f('','.*') is True\n"
  "    assert f('abcde','a.*e') is True\n"),

 # 3. Glob matcher with character classes
 ("""def glob_match(pattern, s): fnmatch-like. '*' matches any run of non-'/' characters (possibly empty); '?' one non-'/' char; '[abc]', '[a-z0-9]', '[^...]'; class closes at first ']' but a ']' as the first class char is literal. No escapes.""",
  "def check(src):\n"
  "    ns={}\n"
  "    exec(src,ns)\n"
  "    f=ns['glob_match']\n"
  "    assert f('a*c','abc') is True\n"
  "    assert f('a*c','a/c') is False\n"
  "    assert f('a*c','ab/c') is False\n"
  "    assert f('?','/') is False\n"
  "    assert f('?x','ax') is True\n"
  "    assert f('[a-c]x','bx') is True\n"
  "    assert f('[a-c]x','dx') is False\n"
  "    assert f('[^a-c]x','dx') is True\n"
  "    assert f('[^a-c]x','ax') is False\n"
  "    assert f('[]]x',']x') is True\n"
  "    assert f('a[0-9]z','a5z') is True\n"
  "    assert f('a[0-9]z','aXz') is False\n"),

 # 4. Full text justification
 ("""def justify(words, W): greedy line packing to width W. Distribute extra spaces as evenly as possible, earlier gaps get the extras first; the last line and single-word lines are left-justified with single spaces, padded with trailing spaces to W. Return list of lines.""",
  "def check(src):\n"
  "    ns={}\n"
  "    exec(src,ns)\n"
  "    f=ns['justify']\n"
  "    assert f(['This','is','an','example','of','text','justification.'],16)==\\\n"
  "        ['This    is    an','example  of text','justification.  ']\n"
  "    assert f(['What','must','be','acknowledgment','shall','be'],16)==\\\n"
  "        ['What   must   be','acknowledgment  ','shall be        ']\n"
  "    assert f(['a'],3)==['a  ']\n"
  "    assert f(['a','b','c','d'],3)==['a b','c d']\n"),

 # 5. Integer to English words
 ("""def num_words(n): 0 <= n <= 2147483647 to English words, Title Case, words separated by single spaces, hyphenate 21..99 non-multiples of ten (e.g. Forty-Two), no 'and'. Zero is 'Zero'.""",
  "def check(src):\n"
  "    ns={}\n"
  "    exec(src,ns)\n"
  "    f=ns['num_words']\n"
  "    assert f(0)=='Zero'\n"
  "    assert f(5)=='Five'\n"
  "    assert f(13)=='Thirteen'\n"
  "    assert f(42)=='Forty-Two'\n"
  "    assert f(100)=='One Hundred'\n"
  "    assert f(105)=='One Hundred Five'\n"
  "    assert f(1234)=='One Thousand Two Hundred Thirty-Four'\n"
  "    assert f(1000000)=='One Million'\n"
  "    assert f(2147483647)=='Two Billion One Hundred Forty-Seven Million Four Hundred Eighty-Three Thousand Six Hundred Forty-Seven'\n"),

 # 6. Unix path simplification
 ("""def simplify(path): normalize an absolute POSIX path string. Resolve '..' and '.', collapse duplicate slashes; '..' above root stays at root; result is '/'-prefixed, no trailing slash except root itself.""",
  "def check(src):\n"
  "    ns={}\n"
  "    exec(src,ns)\n"
  "    f=ns['simplify']\n"
  "    assert f('/a/b/../c/./d')=='/a/c/d'\n"
  "    assert f('/../../..')=='/'\n"
  "    assert f('/a//b///c')=='/a/b/c'\n"
  "    assert f('/a/../../b')=='/b'\n"
  "    assert f('/')=='/'\n"
  "    assert f('/.')=='/'\n"
  "    assert f('/a/b/c/..')=='/a/b'\n"),

 # 7. Longest valid parentheses substring
 ("""def longest_parens(s): given a string of '(' and ')', return a tuple (length, start_index) of the longest valid (well-formed, contiguous) parentheses substring. Ties: the leftmost. Empty input -> (0, 0).""",
  "def check(src):\n"
  "    ns={}\n"
  "    exec(src,ns)\n"
  "    f=ns['longest_parens']\n"
  "    assert f('(()')==(2,1)\n"
  "    assert f(')()())')==(4,1)\n"
  "    assert f('')==(0,0)\n"
  "    assert f('()(()')==(2,0)\n"
  "    assert f('()(())')==(6,0)\n"
  "    assert f(')(')==(0,0)\n"),

 # 8. Interval merge, touching intervals DO merge
 ("""def merge_intervals(intervals): given a list of [start, end] pairs, return the sorted list of merged non-overlapping intervals as tuples. Touching intervals (next.start == current.end) merge into one. Input may be unsorted; empty list -> empty list.""",
  "def check(src):\n"
  "    ns={}\n"
  "    exec(src,ns)\n"
  "    f=ns['merge_intervals']\n"
  "    assert f([[1,3],[3,5]])==[(1,5)]\n"
  "    assert f([[1,2],[4,5]])==[(1,2),(4,5)]\n"
  "    assert f([[5,7],[1,3],[2,6]])==[(1,7)]\n"
  "    assert f([])==[]\n"
  "    assert f([[2,2],[2,2]])==[(2,2)]\n"),

 # 9. Roman numerals round-trip with canonical rejection
 ("""def int_to_roman(n): 1..3999 to canonical Roman. def roman_to_int(s): parse and return the value; raise ValueError if s contains invalid characters OR is not the canonical encoding of its value (e.g. 'IIII', 'IC', 'VX', 'IM').""",
  "def check(src):\n"
  "    ns={}\n"
  "    exec(src,ns)\n"
  "    it=ns['int_to_roman']; rt=ns['roman_to_int']\n"
  "    assert it(4)=='IV' and it(9)=='IX' and it(40)=='XL' and it(90)=='XC'\n"
  "    assert it(400)=='CD' and it(900)=='CM'\n"
  "    assert it(1994)=='MCMXCIV'\n"
  "    assert it(3888)=='MMMDCCCLXXXVIII'\n"
  "    for v in (1,4,9,40,90,400,900,1994,2026,3888,3999):\n"
  "        assert rt(it(v))==v\n"
  "    for bad in ('IIII','IC','VX','IM','MMM M','abc','IVIV'):\n"
  "        try:\n"
  "            rt(bad); assert False, bad\n"
  "        except ValueError: pass\n"),

 # 10. Sliding-window rate limiter (log method), boundary pinned
 ("""class RateLimiter(n, window): method allow(t, key) -> bool for a per-key limit of n events per window. Window is left-open right-closed: an event at time t-w expires exactly at time t. Timestamps arrive in non-decreasing order.""",
  "def check(src):\n"
  "    ns={}\n"
  "    exec(src,ns)\n"
  "    R=ns['RateLimiter']\n"
  "    r=R(2,10)\n"
  "    v=[r.allow(1,'A'), r.allow(2,'A'), r.allow(11,'A'), r.allow(11.5,'A'), r.allow(12,'A')]\n"
  "    assert v==[True,True,True,False,True], f'got {v}: t=1 expires at t=11'\n"
  "    assert r.allow(1,'B') is True  # separate key independent\n"),

 # 11. RLE round-trip with digit-escape rule
 ("""def rle_encode(s): run-length encode as <count><char>; a digit character is emitted wrapped in single quotes (e.g. '3'). def rle_decode(e): exact inverse; raise ValueError on malformed input (missing atom, bad escape, non-digit inside quotes).""",
  "def check(src):\n"
  "    ns={}\n"
  "    exec(src,ns)\n"
  "    en=ns['rle_encode']; de=ns['rle_decode']\n"
  "    assert en('aaab3311')==\"3a1b2'3'2'1'\"\n"
  "    assert de(\"3a1b2'3'2'1'\")=='aaab3311'\n"
  "    assert en('')=='' and de('')==''\n"
  "    for s in ('aaaa','xx','9','zz99',''):\n"
  "        assert de(en(s))==s\n"
  "    for bad in ('3',\"2'x'\",\"2'\",'2x3'):\n"
  "        try:\n"
  "            de(bad); assert False, bad\n"
  "        except ValueError: pass\n"),

 # 12. N-Queens: count + lexicographically-first solution
 ("""def nqueens_count(n): number of n-queens solutions. def nqueens_first(n): the lexicographically first solution as a list of row strings ('.'*c+'Q'+...), scanning columns left-to-right from row 0.""",
  "def check(src):\n"
  "    ns={}\n"
  "    exec(src,ns)\n"
  "    cnt=ns['nqueens_count']; fst=ns['nqueens_first']\n"
  "    assert cnt(1)==1 and cnt(4)==2 and cnt(5)==10 and cnt(6)==4 and cnt(8)==92\n"
  "    expected8=['Q.......','....Q...','.......Q','.....Q..','..Q.....','......Q.','.Q......','...Q....']\n"
  "    assert fst(8)==expected8\n"),

 # 13. Exact fraction evaluator
 ("""def eval_fraction(expr): evaluate an arithmetic expression of exact fractions ('1/3', operators + - * / and parentheses, optional unary minus, arbitrary spaces). Return lowest terms as tuple (p, q), q > 0. Raise ZeroDivisionError on zero denominators.""",
  "def check(src):\n"
  "    ns={}\n"
  "    exec(src,ns)\n"
  "    f=ns['eval_fraction']\n"
  "    assert f('1/3+1/6')==(1,2)\n"
  "    assert f('2/5*(1/4+1/7)')==(11,70)\n"
  "    assert f('-1/2+1/3')==(-1,6)\n"
  "    assert f('1/2-1/2')==(0,1)\n"
  "    assert f('-(-1/2)')==(1,2)\n"
  "    assert f(' 1/4 / 1/2 ')==(1,2)\n"
  "    try:\n"
  "        f('1/0'); assert False\n"
  "    except ZeroDivisionError: pass\n"),

 # 14. Minimal edit script, replay-graded
 ("""def edit_script(a, b): return a minimal edit script as a list of ops: ('k',ch) keep, ('d',ch) delete from a, ('i',ch) insert from b, ('r',x,y) replace. def apply_script(a, ops) -> resulting string. Grading: replay(a, ops) == b and count of non-'k' ops equals the Levenshtein distance.""",
  "def check(src):\n"
  "    ns={}\n"
  "    exec(src,ns)\n"
  "    es=ns['edit_script']; ap=ns['apply_script']\n"
  "    for a,b,dist in (('kitten','sitting',3),('flaw','lawn',2),('','abc',3),\n"
  "                     ('abc','abc',0),('intention','execution',5),('abcdef','azced',3)):\n"
  "        ops=es(a,b)\n"
  "        assert ap(a,ops)==b\n"
  "        assert sum(1 for o in ops if o[0]!='k')==dist, (a,b)\n"),

 # 15. Josephus survivor by recurrence
 ("""def josephus(n, k): people 0..n-1 in a circle, every k-th is eliminated starting the count at person 0; return the 0-indexed survivor. n up to 10**7 — must not simulate the eliminations.""",
  "def check(src):\n"
  "    ns={}\n"
  "    exec(src,ns)\n"
  "    f=ns['josephus']\n"
  "    assert f(1,1)==0\n"
  "    assert f(2,1)==1\n"
  "    assert f(5,2)==2\n"
  "    assert f(41,3)==30\n"
 "    assert f(100000,7)==27151\n"
 "    assert f(10000000,7)==1400177\n")
]

# Reference solutions (selfcheck must pass all)
REFS = [
"""class LFU:
    def __init__(self, capacity):
        self.cap = capacity; self.d = {}; self.f = {}; self.st = {}; self.t = 0
    def get(self, k):
        if k not in self.d: return -1
        self.t += 1; self.f[k] += 1; self.st[k] = self.t
        return self.d[k]
    def put(self, k, v):
        self.t += 1
        if k in self.d:
            self.d[k] = v; self.f[k] += 1; self.st[k] = self.t; return
        if len(self.d) >= self.cap:
            victim = min(self.d, key=lambda x: (self.f[x], -self.st[x]))
            del self.d[victim]; del self.f[victim]; del self.st[victim]
        self.d[k] = v; self.f[k] = 1; self.st[k] = self.t""",
"""def match(s, p):
    m, n = len(s), len(p)
    dp = [[False] * (n + 1) for _ in range(m + 1)]
    dp[0][0] = True
    for j in range(2, n + 1):
        if p[j-1] == '*': dp[0][j] = dp[0][j-2]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if p[j-1] == '*':
                dp[i][j] = dp[i][j-2] or ((p[j-2] == '.' or p[j-2] == s[i-1]) and dp[i-1][j])
            elif p[j-1] == '.' or p[j-1] == s[i-1]:
                dp[i][j] = dp[i-1][j-1]
    return dp[m][n]""",
"""def glob_match(pat, s):
    toks = []; i = 0
    while i < len(pat):
        c = pat[i]
        if c == '[':
            j = i + 1; neg = False
            if j < len(pat) and pat[j] == '^': neg = True; j += 1
            chars = set(); ranges = []; first = True
            while j < len(pat):
                if pat[j] == ']' and not first: break
                if pat[j] == ']': chars.add(']'); j += 1; first = False; continue
                if j + 2 < len(pat) and pat[j+1] == '-' and pat[j+2] != ']':
                    ranges.append((ord(pat[j]), ord(pat[j+2]))); j += 3
                else:
                    chars.add(pat[j]); j += 1
                first = False
            toks.append(('cls', neg, frozenset(chars), tuple(ranges))); i = j + 1
        elif c == '*': toks.append(('*',)); i += 1
        elif c == '?': toks.append(('?',)); i += 1
        else: toks.append(('lit', c)); i += 1
    from functools import lru_cache
    @lru_cache(maxsize=None)
    def go(ti, si):
        if ti == len(toks): return si == len(s)
        t = toks[ti]
        if t[0] == 'lit':
            return si < len(s) and s[si] == t[1] and go(ti+1, si+1)
        if t[0] == '?':
            return si < len(s) and s[si] != '/' and go(ti+1, si+1)
        if t[0] == '*':
            k = si
            while k <= len(s):
                if go(ti+1, k): return True
                if k == len(s) or s[k] == '/': break
                k += 1
            return False
        _, neg, chars, ranges = t
        if si >= len(s): return False
        ch = s[si]
        hit = ch in chars or any(a <= ord(ch) <= b for a, b in ranges)
        return hit != neg and go(ti+1, si+1)
    return go(0, 0)""",
"""def justify(words, W):
    lines = []; cur = []; cur_len = 0
    for w in words:
        if cur and cur_len + 1 + len(w) > W:
            lines.append(cur); cur = [w]; cur_len = len(w)
        else:
            if cur: cur_len += 1
            cur.append(w); cur_len += len(w)
    lines.append(cur)
    out = []
    for idx, line in enumerate(lines):
        if idx == len(lines) - 1 or len(line) == 1:
            out.append(' '.join(line).ljust(W))
        else:
            total = sum(len(w) for w in line); gaps = len(line) - 1
            spaces = W - total; base = spaces // gaps; extra = spaces % gaps
            parts = []
            for i, w in enumerate(line[:-1]):
                parts.append(w); parts.append(' ' * (base + (1 if i < extra else 0)))
            parts.append(line[-1]); out.append(''.join(parts))
    return out""",
"""def num_words(n):
    if n == 0: return 'Zero'
    ones = ['','One','Two','Three','Four','Five','Six','Seven','Eight','Nine',
            'Ten','Eleven','Twelve','Thirteen','Fourteen','Fifteen','Sixteen',
            'Seventeen','Eighteen','Nineteen']
    tens = ['','','Twenty','Thirty','Forty','Fifty','Sixty','Seventy','Eighty','Ninety']
    def under1000(x):
        parts = []
        if x >= 100: parts.append(ones[x // 100] + ' Hundred'); x %= 100
        if x >= 20:
            t = tens[x // 10]
            if x % 10: t += '-' + ones[x % 10]
            parts.append(t)
        elif x > 0: parts.append(ones[x])
        return parts
    scales = ['', 'Thousand', 'Million', 'Billion']
    groups = []
    while n > 0: groups.append(n % 1000); n //= 1000
    parts = []
    for gi in range(len(groups) - 1, -1, -1):
        g = groups[gi]
        if g == 0: continue
        parts.extend(under1000(g))
        if scales[gi]: parts.append(scales[gi])
    return ' '.join(parts)""",
"""def simplify(path):
    st = []
    for part in path.split('/'):
        if part == '' or part == '.': continue
        if part == '..':
            if st: st.pop()
        else: st.append(part)
    return '/' + '/'.join(st)""",
"""def longest_parens(s):
    st = [-1]; best = 0; bi = 0
    for i, c in enumerate(s):
        if c == '(': st.append(i)
        else:
            st.pop()
            if not st: st.append(i)
            else:
                L = i - st[-1]
                if L > best: best = L; bi = st[-1] + 1
    return best, bi""",
"""def merge_intervals(intervals):
    ivs = sorted(intervals); out = []
    for a, b in ivs:
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else: out.append([a, b])
    return [tuple(x) for x in out]""",
"""VALS = [('M',1000),('CM',900),('D',500),('CD',400),('C',100),('XC',90),
        ('L',50),('XL',40),('X',10),('IX',9),('V',5),('IV',4),('I',1)]
def int_to_roman(n):
    out = []
    for s, v in VALS:
        while n >= v: out.append(s); n -= v
    return ''.join(out)
def roman_to_int(s):
    import re
    if not re.fullmatch(r'[MDCLXVI]+', s): raise ValueError(s)
    total = 0; i = 0
    m = {'I':1,'V':5,'X':10,'L':50,'C':100,'D':500,'M':1000}
    while i < len(s):
        if i + 1 < len(s) and m[s[i]] < m[s[i+1]]:
            total += m[s[i+1]] - m[s[i]]; i += 2
        else:
            total += m[s[i]]; i += 1
    if int_to_roman(total) != s: raise ValueError(s)
    return total""",
"""class RateLimiter:
    def __init__(self, n, window):
        self.n = n; self.w = window; self.log = {}
    def allow(self, t, key):
        q = self.log.setdefault(key, [])
        while q and q[0] <= t - self.w: q.pop(0)
        if len(q) < self.n: q.append(t); return True
        return False""",
"""def rle_encode(s):
    out = []; i = 0
    while i < len(s):
        j = i
        while j < len(s) and s[j] == s[i]: j += 1
        c = s[i]; n = j - i
        out.append(str(n) + (f\"'{c}'\" if c.isdigit() else c))
        i = j
    return ''.join(out)
def rle_decode(e):
    out = []; i = 0
    while i < len(e):
        j = i
        while j < len(e) and e[j].isdigit(): j += 1
        if j == i: raise ValueError(e)
        n = int(e[i:j])
        if j < len(e) and e[j] == \"'\":
            if j + 2 >= len(e) or e[j+2] != \"'\" or not e[j+1].isdigit():
                raise ValueError(e)
            c = e[j+1]; i = j + 3
        elif j < len(e) and not e[j].isdigit():
            c = e[j]; i = j + 1
        else: raise ValueError(e)
        out.append(c * n)
    return ''.join(out)""",
"""def nqueens_count(n):
    cnt = 0
    def go(row, cols, d1, d2):
        nonlocal cnt
        if row == n: cnt += 1; return
        for c in range(n):
            if c in cols or (row - c) in d1 or (row + c) in d2: continue
            go(row + 1, cols | {c}, d1 | {row - c}, d2 | {row + c})
    go(0, set(), set(), set())
    return cnt
def nqueens_first(n):
    def go(row, cols, d1, d2, cur):
        if row == n: return list(cur)
        for c in range(n):
            if c in cols or (row - c) in d1 or (row + c) in d2: continue
            cur.append(c)
            r = go(row + 1, cols | {c}, d1 | {row - c}, d2 | {row + c}, cur)
            if r: return r
            cur.pop()
        return None
    cols = go(0, set(), set(), set(), [])
    return ['.' * c + 'Q' + '.' * (n - 1 - c) for c in cols]""",
"""def eval_fraction(expr):
    import re
    toks = re.findall(r'\\d+/\\d+|[()+\\-*/]', expr.replace(' ', ''))
    pos = [0]
    def peek(): return toks[pos[0]] if pos[0] < len(toks) else None
    def take(): t = toks[pos[0]]; pos[0] += 1; return t
    def gcd(a, b): return a if b == 0 else gcd(b, a % b)
    def add(a, b): return (a[0]*b[1] + b[0]*a[1], a[1]*b[1])
    def sub(a, b): return (a[0]*b[1] - b[0]*a[1], a[1]*b[1])
    def mul(a, b): return (a[0]*b[0], a[1]*b[1])
    def div(a, b):
        if b[0] == 0: raise ZeroDivisionError()
        return (a[0]*b[1], a[1]*b[0])
    def norm(p, q):
        if q < 0: p, q = -p, -q
        g = gcd(abs(p), q) or 1
        return (p // g, q // g)
    def prim():
        t = peek()
        if t == '(':
            take(); v = expr_()
            if peek() != ')': raise ValueError('paren')
            take(); return v
        if t == '-':
            take(); p, q = prim(); return (-p, q)
        t = take(); p, q = t.split('/')
        if q == '0': raise ZeroDivisionError()
        return (int(p), int(q))
    def term():
        v = prim()
        while peek() in ('*', '/'):
            op = take(); r = prim()
            v = mul(v, r) if op == '*' else div(v, r)
        return v
    def expr_():
        v = term()
        while peek() in ('+', '-'):
            op = take(); r = term()
            v = add(v, r) if op == '+' else sub(v, r)
        return v
    p, q = expr_()
    return norm(p, q)""",
"""def edit_script(a, b):
    m, n = len(a), len(b)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1): dp[i][0] = i
    for j in range(n + 1): dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            dp[i][j] = min(dp[i-1][j] + 1, dp[i][j-1] + 1,
                           dp[i-1][j-1] + (a[i-1] != b[j-1]))
    ops = []; i, j = m, n
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i][j] == dp[i-1][j-1] + (a[i-1] != b[j-1]):
            if a[i-1] == b[j-1]: ops.append(('k', a[i-1]))
            else: ops.append(('r', a[i-1], b[j-1]))
            i -= 1; j -= 1
        elif i > 0 and dp[i][j] == dp[i-1][j] + 1:
            ops.append(('d', a[i-1])); i -= 1
        else:
            ops.append(('i', b[j-1])); j -= 1
    ops.reverse()
    return ops
def apply_script(a, ops):
    out = []; ai = 0
    for op in ops:
        t = op[0]
        if t == 'k': out.append(op[1]); ai += 1
        elif t == 'd': ai += 1
        elif t == 'i': out.append(op[1])
        else: out.append(op[2]); ai += 1
    return ''.join(out)""",
"""def josephus(n, k):
    r = 0
    for i in range(2, n + 1):
        r = (r + k) % i
    return r""",
]

# Plausible-but-wrong probes (selfcheck must REJECT all)
WRONG = [
 "class LFU:\n    def __init__(self,c):\n        self.c=c; self.d={}\n    def get(self,k): return self.d.get(k,-1)\n    def put(self,k,v): self.d[k]=v",  # no eviction/freq
 "def match(s,p):\n    return s==p",  # identity
 "def glob_match(p,s):\n    import fnmatch\n    return fnmatch.fnmatch(s,p)",  # fnmatch: * crosses /, no [^ ]
 "def justify(w,W):\n    return [' '.join(w)]",  # no packing
 "def num_words(n): return str(n)",
 "def simplify(p): return p",
 "def longest_parens(s):\n    return (len(s),0)",
 "def merge_intervals(iv): return [tuple(x) for x in sorted(iv)]",  # no merge
 "def int_to_roman(n): return 'I'*n\ndef roman_to_int(s): return s.count('I')",  # no canonical check
 "class RateLimiter:\n    def __init__(self,n,w): self.n=n; self.w=w\n    def allow(self,t,k): return True",
 "def rle_encode(s): return s\ndef rle_decode(e): return e",
 "def nqueens_count(n): return 1\ndef nqueens_first(n): return ['Q'+'.'*(n-1)]*n",
 "def eval_fraction(e): return (1,1)",
 "def edit_script(a,b): return [('r',x,y) for x,y in zip(a,b)]\ndef apply_script(a,ops): return b",
 "def josephus(n,k): return 0",
]
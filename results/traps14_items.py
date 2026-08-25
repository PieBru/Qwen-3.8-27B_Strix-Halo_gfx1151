"""TRAPS-14 — language-edge & gotcha battery (operator-provided set, verified).

13 items (item 2 of the original set DROPPED: repr(sum([0.1]*10)) is
version-dependent - CPython 3.12+ exact float summation prints 1.0, <=3.11
prints 0.9999999999999999; ambiguous items have no place in a deterministic
battery). Every surviving expected value verified by live execution on
CPython 3.11 (2026-08-25). Two flavors mixed: implement-to-spec and
predict-exact-output. Consumed by scripts/fcb15_run.py --battery traps.
"""

# (prompt, expected_output) — grading: run model's code block (or its stated
# answer) and string-match the LAST printed line / final answer token.
ITEMS = [
 ("Write a Python function that counts occurrences of the substring 'aa' in a string, including overlapping occurrences. Apply it to 'aaaa' and print the result.", "3"),
 ("In Python, what does print(7 % -3) output? Write the code and print it.", "-2"),
 ("Write Python code: data = [('a',1),('b',1),('c',2)], then sorted(data, key=lambda x: x[1], reverse=True). Print the result exactly.", "[('c', 2), ('a', 1), ('b', 1)]"),
 ("Write Python code using bisect.bisect_left to find the insertion index of 4 in [1, 2, 4, 4, 4, 6, 8]. Print the index.", "2"),
 ("Write merge_intervals(intervals) where two intervals merge if they overlap or touch at a single point (e.g. [1,4] and [4,5] touch at 4 and should merge). Apply to [[1,4],[4,5],[6,8]] and print the result.", "[[1, 5], [6, 8]]"),
 ("Write a function that returns the 8-bit two's complement binary string for -5. Print it.", "11111011"),
 ("Write Python code using the csv module to parse this single line (as literal text, including the quote characters): a,\"b,c\",d. Print the resulting list of fields.", "['a', 'b,c', 'd']"),
 ("Write a function to compute the Levenshtein edit distance between 'flaw' and 'lawn'. Print the result.", "2"),
 ("Predict the exact output of this Python code (write the code and print what it prints):\ndef f(x, lst=[]):\n    lst.append(x)\n    return lst\nprint(f(1))\nprint(f(2))", "[1, 2]"),
 ("Predict the exact output of this Python code (write the code and print what it prints):\ngrid = [[0]*3]*3\ngrid[0][0] = 1\nprint(grid)", "[[1, 0, 0], [1, 0, 0], [1, 0, 0]]"),
 ("Write Python code: import json; print(json.dumps(0.1 + 0.2)). What is the exact printed output?", "0.30000000000000004"),
 ("Write a function that counts the number of ways to make 11 cents using unlimited coins of denominations 1, 5, and 10 - where order doesn't matter (combinations, not permutations). Print the count.", "4"),
 ("The look-and-say sequence starts 1, 11, 21, 1211, 111221, ... . Write code to compute the 6th term (1-indexed) and print it as a string.", "312211"),
]

# reference solutions (selfcheck: executed, stdout's last non-empty line must match)
REFS = [
 "print(sum(1 for i in range(len('aaaa')-1) if 'aaaa'[i:i+2]=='aa'))",
 "print(7 % -3)",
 "data=[('a',1),('b',1),('c',2)]\nprint(sorted(data,key=lambda x:x[1],reverse=True))",
 "import bisect\nprint(bisect.bisect_left([1,2,4,4,4,6,8],4))",
 "def merge_intervals(iv):\n    iv=sorted(iv); out=[]\n    for a,b in iv:\n        if out and a <= out[-1][1]: out[-1][1]=max(out[-1][1],b)\n        else: out.append([a,b])\n    return out\nprint(merge_intervals([[1,4],[4,5],[6,8]]))",
 "print(format(256-5,'08b'))",
 "import csv, io\nprint(next(csv.reader(io.StringIO('a,\"b,c\",d'))))",
 "def lev(a,b):\n    m,n=len(a),len(b); dp=list(range(n+1))\n    for i in range(1,m+1):\n        prev=dp[0]; dp[0]=i\n        for j in range(1,n+1):\n            cur=dp[j]; dp[j]=min(dp[j]+1,dp[j-1]+1,prev+(a[i-1]!=b[j-1])); prev=cur\n    return dp[n]\nprint(lev('flaw','lawn'))",
 "def f(x, lst=[]):\n    lst.append(x)\n    return lst\nprint(f(1))\nprint(f(2))",
 "grid = [[0]*3]*3\ngrid[0][0] = 1\nprint(grid)",
 "import json\nprint(json.dumps(0.1 + 0.2))",
 "def coins(amount, denoms):\n    dp=[1]+[0]*amount\n    for c in denoms:\n        for a in range(c,amount+1): dp[a]+=dp[a-c]\n    return dp[amount]\nprint(coins(11,[1,5,10]))",
 "def las(s, n):\n    for _ in range(n-1):\n        out=[]; i=0\n        while i < len(s):\n            j=i\n            while j<len(s) and s[j]==s[i]: j+=1\n            out.append(str(j-i)+s[i]); i=j\n        s=''.join(out)\n    return s\nprint(las('1',6))",
]

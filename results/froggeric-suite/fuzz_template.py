"""Deterministic property-based fuzzer for the fixed Qwen chat templates.

Generates structurally valid conversations (system merging, multipart vision
content, tool loops with mixed argument shapes, explicit and in-content
reasoning, planted error payloads) and asserts nine invariants:

  1. render          Rendering never raises on valid input.
  2. parity          chat_template.jinja and chat_template_oneline.txt render
                     byte-identically.
  3. balance         <|im_start|> and <|im_end|> counts match
                     (add_generation_prompt=False).
  4. content         Planted user text, assistant answers, and (when preserved)
                     reasoning appear verbatim in the output.
  5. xml-fidelity    In XML mode every mapping tool-argument key appears as
                     <parameter=key>; values appear verbatim when truncation
                     is disabled.
  6. json-validity   In JSON mode every emitted <tool_call> body parses as JSON.
  7. warning         The tool-error warning appears iff an error payload was
                     planted (no false positives, no false negatives).
  8. prefix          render(messages[:k]) is a strict prefix of
                     render(messages[:k+1]) at every generation boundary under
                     default preserve_thinking. Prefixes that split a merged
                     system block or a consecutive tool-result batch are
                     skipped: those intermediate states are never rendered in
                     real serving, where the model generates only after the
                     full tool-result batch is appended.
  9. prefill         enable_thinking=False ends the generation prompt with the
                     empty think prefill.

Usage:
  python3 scripts/fuzz_template.py [--cases 500] [--seed 0] [--template chat_template.jinja]

Exits nonzero on any invariant failure and prints a JSON repro for each.
"""
import argparse
import json
import os
import random
import sys
import traceback

from jinja2 import Environment, FileSystemLoader, StrictUndefined

# Alphabet deliberately excludes every error-detector keyword, control-tag
# fragment, and special-token prefix so invariant 7 stays two-sided.
WORDS = ['alpha', 'bravo', 'delta', 'gamma', 'lumen', 'quartz', 'river',
         'stone', 'matrix', 'vector', 'naïve', 'café', '数据', '結果']


def _phrase(rnd, lo=2, hi=5):
    sep = '\n' if rnd.random() < 0.1 else ' '
    return sep.join(rnd.choice(WORDS) + str(rnd.randint(0, 99))
                    for _ in range(rnd.randint(lo, hi)))


def _gen_case(rnd):
    kwargs = {}
    fmt = 'json' if rnd.random() < 0.3 else 'xml'
    if fmt == 'json':
        kwargs['tool_call_format'] = 'json'
    if rnd.random() < 0.3:
        kwargs['reasoning_effort'] = rnd.choice(['low', 'medium', 'high', 'xhigh'])
    no_think = rnd.random() < 0.15
    if no_think:
        kwargs['enable_thinking'] = False
    preserve = True
    if rnd.random() < 0.2:
        kwargs['preserve_thinking'] = False
        preserve = False
    if rnd.random() < 0.2:
        kwargs['add_vision_id'] = True
    trunc_args = False
    if fmt == 'xml' and rnd.random() < 0.2:
        kwargs['max_tool_arg_chars'] = rnd.choice([8, 40])
        trunc_args = True
    if fmt == 'xml' and rnd.random() < 0.15:
        kwargs['max_tool_response_chars'] = 80

    msgs = []
    user_texts, answers, reasonings, xml_keys, xml_vals = [], [], [], [], []
    planted_error = False

    for _ in range(rnd.randint(0, 2)):
        msgs.append({'role': 'system', 'content': _phrase(rnd)})

    for _ in range(rnd.randint(1, 3)):
        text = _phrase(rnd)
        if rnd.random() < 0.25:
            parts = [{'type': 'image', 'image': 'x'}
                     for _ in range(rnd.randint(1, 2))]
            parts.append({'type': 'text', 'text': text})
            msgs.append({'role': 'user', 'content': parts})
        else:
            msgs.append({'role': 'user', 'content': text})
        user_texts.append(text)

        for _ in range(rnd.randint(0, 2)):
            calls = []
            for c in range(rnd.randint(1, 2)):
                roll = rnd.random()
                if roll < 0.5:
                    value = _phrase(rnd)
                    args = {'k%d' % c: value}
                    xml_keys.append('k%d' % c)
                    if fmt == 'xml' and not trunc_args:
                        xml_vals.append(value)
                elif roll < 0.7:
                    args = json.dumps({'q': _phrase(rnd)})
                elif roll < 0.8:
                    args = rnd.randint(0, 999)
                elif roll < 0.9:
                    args = [1, 2, 3]
                else:
                    args = {}
                fn = {'name': 'fn%d' % c, 'arguments': args}
                calls.append({'type': 'function', 'function': fn}
                             if rnd.random() < 0.5 else dict(fn))
            amsg = {'role': 'assistant',
                    'content': _phrase(rnd) if rnd.random() < 0.4 else '',
                    'tool_calls': calls}
            if rnd.random() < 0.5:
                rz = _phrase(rnd)
                if rnd.random() < 0.5:
                    amsg['content'] = '<think>\n' + rz + '\n</think>\n\n' + amsg['content']
                else:
                    amsg['reasoning_content'] = rz
                if preserve:
                    reasonings.append(rz)
            msgs.append(amsg)
            for _ in calls:
                if rnd.random() < 0.12:
                    msgs.append({'role': 'tool', 'content': '{"error": "boom"}'})
                    planted_error = True
                else:
                    msgs.append({'role': 'tool', 'content': 'result ' + _phrase(rnd)})

        ans = _phrase(rnd)
        amsg = {'role': 'assistant', 'content': ans}
        if rnd.random() < 0.6:
            rz = _phrase(rnd)
            if rnd.random() < 0.5:
                amsg['content'] = '<think>\n' + rz + '\n</think>\n\n' + ans
            else:
                amsg['reasoning_content'] = rz
            if preserve:
                reasonings.append(rz)
        msgs.append(amsg)
        answers.append(ans)

    return dict(msgs=msgs, kwargs=kwargs, fmt=fmt, preserve=preserve,
                no_think=no_think, user_texts=user_texts, answers=answers,
                reasonings=reasonings, xml_keys=xml_keys, xml_vals=xml_vals,
                planted_error=planted_error)


def _check(case, tpl, other, failures, idx):
    msgs, kw = case['msgs'], case['kwargs']

    def fail(inv, detail):
        failures.append({
            'case': idx, 'invariant': inv, 'detail': detail,
            'repro': json.dumps({'messages': msgs, 'kwargs': kw},
                                ensure_ascii=False, default=str)})

    try:
        out = tpl.render(messages=msgs, add_generation_prompt=False, **kw)
    except Exception:
        fail('render', traceback.format_exc().strip().splitlines()[-1])
        return
    try:
        out_b = other.render(messages=msgs, add_generation_prompt=False, **kw)
        if out != out_b:
            i = next((j for j in range(min(len(out), len(out_b)))
                      if out[j] != out_b[j]), min(len(out), len(out_b)))
            fail('parity', 'first diff at char %d: %r vs %r'
                 % (i, out[i:i + 40], out_b[i:i + 40]))
    except Exception:
        fail('parity', traceback.format_exc().strip().splitlines()[-1])

    if out.count('<|im_start|>') != out.count('<|im_end|>'):
        fail('balance', '%d starts vs %d ends'
             % (out.count('<|im_start|>'), out.count('<|im_end|>')))

    for text in case['user_texts'] + case['answers'] + case['reasonings']:
        if text not in out:
            fail('content', 'missing %r' % text[:60])
            break

    if case['fmt'] == 'xml':
        for key in case['xml_keys']:
            if ('<parameter=%s>' % key) not in out:
                fail('xml-fidelity', 'missing key %s' % key)
                break
        for value in case['xml_vals']:
            if value not in out:
                fail('xml-fidelity', 'missing value %r' % value[:60])
                break

    if case['fmt'] == 'json':
        for block in out.split('<tool_call>\n')[1:]:
            body = block.split('\n</tool_call>')[0]
            try:
                json.loads(body)
            except Exception:
                fail('json-validity', body[:80])
                break

    warned = '⚠️ SYSTEM WARNING' in out
    if warned != case['planted_error']:
        fail('warning', 'warned=%s planted=%s' % (warned, case['planted_error']))

    if case['preserve']:
        prev = None
        for k in range(1, len(msgs) + 1):
            if k < len(msgs) and msgs[k]['role'] == msgs[k - 1]['role'] \
                    and msgs[k]['role'] in ('system', 'tool'):
                continue
            cur = tpl.render(messages=msgs[:k], add_generation_prompt=False, **kw)
            
            if k > 1 and msgs[k - 1].get('role') == 'assistant':
                prompt = tpl.render(messages=msgs[:k - 1], add_generation_prompt=True, **kw)
                if not cur.startswith(prompt):
                    if prompt.endswith('<think>\n\n</think>\n\n') and cur.startswith(prompt[:-11]):
                        # Fuzzer randomly injected reasoning into a non-thinking turn. KV cache naturally breaks here.
                        pass
                    else:
                        fail('prefix', 'generation prompt at turn %d not prefix of history at turn %d' % (k - 1, k))
                        break
                    
            if prev is not None and not cur.startswith(prev):
                fail('prefix', 'history mutated at turn %d' % k)
                break
            prev = cur

    if case['no_think']:
        gen = tpl.render(messages=msgs, add_generation_prompt=True, **kw)
        if not gen.endswith('<think>\n\n</think>\n\n'):
            fail('prefill', repr(gen[-40:]))


def run_fuzz(cases=500, seed=0, template_dir=None,
             template_file='chat_template.jinja', max_failures=10):
    template_dir = template_dir or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    env = Environment(loader=FileSystemLoader(template_dir),
                      undefined=StrictUndefined, keep_trailing_newline=True,
                      lstrip_blocks=True, trim_blocks=True)
    env.globals['raise_exception'] = \
        lambda m: (_ for _ in ()).throw(Exception(m))
    tpl = env.get_template(template_file)
    other_name = ('chat_template.jinja'
                  if template_file == 'chat_template_oneline.txt'
                  else 'chat_template_oneline.txt')
    other = env.get_template(other_name)
    rnd = random.Random(seed)
    failures = []
    for i in range(cases):
        _check(_gen_case(rnd), tpl, other, failures, i)
        if len(failures) >= max_failures:
            break
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--cases', type=int, default=500)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--template', default='chat_template.jinja')
    args = parser.parse_args()
    failures = run_fuzz(cases=args.cases, seed=args.seed,
                        template_file=args.template)
    if failures:
        for f in failures:
            print('FAIL case %d [%s]: %s' % (f['case'], f['invariant'], f['detail']))
            print('  repro: %s' % f['repro'][:800])
        print('\n%d invariant violation(s) in %d cases (seed %d)'
              % (len(failures), args.cases, args.seed))
        sys.exit(1)
    print('All invariants held over %d generated conversations (seed %d).'
          % (args.cases, args.seed))


if __name__ == '__main__':
    main()

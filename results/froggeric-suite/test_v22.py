import os
import sys
import re
import json
import traceback

try:
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
except ImportError:
    print("Error: jinja2 is required to run tests. Please install it using 'pip install jinja2'")
    sys.exit(1)

TEMPLATE_FILE = os.environ.get('QWEN_TEMPLATE_FILE', 'chat_template.jinja')
TEMPLATE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
    lstrip_blocks=True,
    trim_blocks=True
)

def raise_exception(msg):
    raise Exception(msg)

env.globals['raise_exception'] = raise_exception

try:
    template = env.get_template(TEMPLATE_FILE)
except Exception as e:
    print(f"Error loading template: {e}")
    sys.exit(1)

def run_test(name, messages, tools=None, kwargs=None, expected_in=None, expected_not_in=None, expect_error=False):
    if kwargs is None:
        kwargs = {}
    
    print(f"\n--- Running Test: {name} ---")
    
    try:
        render_kwargs = {'messages': messages, 'add_generation_prompt': True}
        if tools is not None:
            render_kwargs['tools'] = tools
        render_kwargs.update(kwargs)
        
        rendered = template.render(**render_kwargs)
        
        if expect_error:
            print("❌ FAILED: Expected an exception but got none.")
            return False
            
        success = True
        
        if expected_in:
            for ex in expected_in:
                if ex not in rendered:
                    print(f"❌ FAILED: Missing expected string:\n'''{ex}'''")
                    print(f"Rendered:\n{rendered}")
                    success = False
        
        if expected_not_in:
            for n_ex in expected_not_in:
                if n_ex in rendered:
                    print(f"❌ FAILED: Found string that should NOT be present:\n'''{n_ex}'''")
                    print(f"Rendered:\n{rendered}")
                    success = False
                    
        if success:
            print("✅ PASSED")
            return True
        return False
        
    except Exception as e:
        if expect_error:
            print(f"✅ PASSED (Caught expected error: {e})")
            return True
        print(f"❌ FAILED with exception:\n{traceback.format_exc()}")
        return False

def run_prefix_test(name, messages, kwargs=None):
    """Asserts render(messages[:k]) is always a strict prefix of render(messages[:k+1]).

    This is the direct verification of the 100% Prefix KV Cache claim: if any past turn
    is mutated when a new turn arrives, the cached prefix is invalidated from that point.
    """
    if kwargs is None:
        kwargs = {}

    print(f"\n--- Running Test: {name} ---")

    previous = None
    for k in range(1, len(messages) + 1):
        # Checkpoint only at generation boundaries: prefixes splitting a merged
        # system block or a consecutive tool-result batch are never rendered in
        # real serving, so they are not required to be stable.
        if k < len(messages) and messages[k].get('role') == messages[k - 1].get('role') \
                and messages[k].get('role') in ('system', 'tool'):
            continue
        try:
            current = template.render(messages=messages[:k], add_generation_prompt=False, **kwargs)
        except Exception:
            print(f"❌ FAILED with exception:\n{traceback.format_exc()}")
            return False

        if previous is not None and not current.startswith(previous):
            idx = min(len(previous), len(current))
            for i in range(min(len(previous), len(current))):
                if previous[i] != current[i]:
                    idx = i
                    break
            print(f"❌ FAILED: turn {k} mutated rendered history at char {idx}.")
            print(f"Before: {previous[max(0, idx - 80):idx + 80]!r}")
            print(f"After:  {current[max(0, idx - 80):idx + 80]!r}")
            return False
        previous = current

    print("✅ PASSED")
    return True


def run_oneline_parity_test(name, cases):
    """Asserts chat_template_oneline.txt renders byte-identically to chat_template.jinja."""
    print(f"\n--- Running Test: {name} ---")

    oneline_path = os.path.join(TEMPLATE_DIR, 'chat_template_oneline.txt')
    if not os.path.exists(oneline_path):
        print(f"❌ FAILED: {oneline_path} not found.")
        return False

    with open(oneline_path, 'r', encoding='utf-8') as f:
        oneline_source = f.read()
    with open(os.path.join(TEMPLATE_DIR, TEMPLATE_FILE), 'r', encoding='utf-8') as f:
        jinja_source = f.read()

    version_pattern = r'template_version\s*=\s*["\']([^"\']+)["\']'
    jinja_version = re.search(version_pattern, jinja_source)
    oneline_version = re.search(version_pattern, oneline_source)
    if not jinja_version or not oneline_version or jinja_version.group(1) != oneline_version.group(1):
        print("❌ FAILED: template_version mismatch between jinja and oneline builds.")
        print("Regenerate with: python3 scripts/minify_jinja.py chat_template.jinja chat_template_oneline.txt")
        return False

    oneline_template = env.from_string(oneline_source)

    for label, messages, kwargs in cases:
        try:
            a = template.render(messages=messages, add_generation_prompt=True, **kwargs)
            b = oneline_template.render(messages=messages, add_generation_prompt=True, **kwargs)
        except Exception:
            print(f"❌ FAILED with exception on case '{label}':\n{traceback.format_exc()}")
            return False
        if a != b:
            print(f"❌ FAILED: oneline output diverges from jinja on case '{label}'.")
            print("Regenerate with: python3 scripts/minify_jinja.py chat_template.jinja chat_template_oneline.txt")
            return False

    print("✅ PASSED")
    return True


tests_passed = 0
tests_total = 0

def execute_test(*args, **kwargs):
    global tests_passed, tests_total
    tests_total += 1
    if run_test(*args, **kwargs):
        tests_passed += 1

def execute_prefix_test(*args, **kwargs):
    global tests_passed, tests_total
    tests_total += 1
    if run_prefix_test(*args, **kwargs):
        tests_passed += 1

def execute_parity_test(*args, **kwargs):
    global tests_passed, tests_total
    tests_total += 1
    if run_oneline_parity_test(*args, **kwargs):
        tests_passed += 1

# ==========================================
# 1. Qwen 3.8 Reasoning Effort Controls (v22.1 Default: medium)
# ==========================================

# 1. Default reasoning_effort="medium" (no system message -> zero system message emitted)
execute_test(
    "1. reasoning_effort='medium' (v22.1 default, no system message)",
    messages=[{"role": "user", "content": "Hello!"}],
    expected_in=[
        "<|im_start|>user\nHello!<|im_end|>\n<|im_start|>assistant\n<think>\n"
    ],
    expected_not_in=[
        "<|im_start|>system\n"
    ]
)

# 2. Explicit reasoning_effort="xhigh"
execute_test(
    "2. reasoning_effort='xhigh'",
    messages=[{"role": "user", "content": "Hello!"}],
    kwargs={"reasoning_effort": "xhigh"},
    expected_in=[
        "<|im_start|>system\nReasoning effort is set to xhigh. Please think carefully through the task, validate key assumptions, consider plausible alternatives, and prioritize correctness, consistency, and clarity in the final answer.<|im_end|>\n",
        "<|im_start|>user\nHello!<|im_end|>\n",
        "<|im_start|>assistant\n<think>\n"
    ]
)

# 3. Explicit reasoning_effort="high" (OpenAI alias -> xhigh)
execute_test(
    "3. reasoning_effort='high' (OpenAI alias)",
    messages=[{"role": "user", "content": "Hello!"}],
    kwargs={"reasoning_effort": "high"},
    expected_in=[
        "<|im_start|>system\nReasoning effort is set to xhigh. Please think carefully through the task, validate key assumptions, consider plausible alternatives, and prioritize correctness, consistency, and clarity in the final answer.<|im_end|>\n"
    ]
)

# 4. Explicit reasoning_effort="max" (API max alias -> xhigh)
execute_test(
    "4. reasoning_effort='max' (API alias)",
    messages=[{"role": "user", "content": "Hello!"}],
    kwargs={"reasoning_effort": "max"},
    expected_in=[
        "<|im_start|>system\nReasoning effort is set to xhigh. Please think carefully through the task, validate key assumptions, consider plausible alternatives, and prioritize correctness, consistency, and clarity in the final answer.<|im_end|>\n"
    ]
)

# 5. Explicit reasoning_effort="low"
execute_test(
    "5. reasoning_effort='low'",
    messages=[{"role": "user", "content": "Hello!"}],
    kwargs={"reasoning_effort": "low"},
    expected_in=[
        "<|im_start|>system\nReasoning effort is set to low. Keep your thinking brief and focused, moving directly to the conclusion without unnecessary elaboration.<|im_end|>\n",
        "<|im_start|>user\nHello!<|im_end|>\n"
    ]
)

# 6. Explicit reasoning_effort="minimal" (API minimal alias -> low)
execute_test(
    "6. reasoning_effort='minimal' (API alias)",
    messages=[{"role": "user", "content": "Hello!"}],
    kwargs={"reasoning_effort": "minimal"},
    expected_in=[
        "<|im_start|>system\nReasoning effort is set to low. Keep your thinking brief and focused, moving directly to the conclusion without unnecessary elaboration.<|im_end|>\n"
    ]
)

# 7. Explicit reasoning_effort="none" (disables thinking)
execute_test(
    "7. reasoning_effort='none' (disables thinking)",
    messages=[{"role": "user", "content": "Hello!"}],
    kwargs={"reasoning_effort": "none"},
    expected_in=[
        "<|im_start|>user\nHello!<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
    ],
    expected_not_in=[
        "Reasoning effort is set to"
    ]
)

# 8. Explicit reasoning_effort="unknown_val" (safe fallback to medium)
execute_test(
    "8. reasoning_effort='unknown_val' (safe fallback to medium)",
    messages=[{"role": "user", "content": "Hello!"}],
    kwargs={"reasoning_effort": "unrecognized_str"},
    expected_in=[
        "<|im_start|>user\nHello!<|im_end|>\n<|im_start|>assistant\n<think>\n"
    ],
    expected_not_in=[
        "Reasoning effort is set to"
    ]
)

# 9. reasoning_effort='xhigh' with user system prompt
execute_test(
    "9. reasoning_effort='xhigh' with user system prompt",
    messages=[
        {"role": "system", "content": "You are an expert coder."},
        {"role": "user", "content": "Write quicksort in C++"}
    ],
    kwargs={"reasoning_effort": "xhigh"},
    expected_in=[
        "<|im_start|>system\nReasoning effort is set to xhigh. Please think carefully through the task, validate key assumptions, consider plausible alternatives, and prioritize correctness, consistency, and clarity in the final answer.\n\nYou are an expert coder.<|im_end|>\n",
        "<|im_start|>user\nWrite quicksort in C++<|im_end|>\n"
    ]
)

# 10. reasoning_effort='xhigh' with tools
tools_sample = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get weather for city",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"]
            }
        }
    }
]

execute_test(
    "10. reasoning_effort='xhigh' with tools",
    messages=[{"role": "user", "content": "What's the weather in Tokyo?"}],
    tools=tools_sample,
    kwargs={"reasoning_effort": "xhigh"},
    expected_in=[
        "<|im_start|>system\nReasoning effort is set to xhigh. Please think carefully through the task, validate key assumptions, consider plausible alternatives, and prioritize correctness, consistency, and clarity in the final answer.\n\n# Tools\n\nYou have access to the following functions:\n\n<tools>\n"
    ]
)

# ==========================================
# 2. Inline Chat Tags for Reasoning Effort Steering (v22.1)
# ==========================================

# 11. Inline <|think_low|> in user message
execute_test(
    "11. Inline <|think_low|> in user string",
    messages=[{"role": "user", "content": "What is 2+2? <|think_low|>"}],
    expected_in=[
        "<|im_start|>system\nReasoning effort is set to low. Keep your thinking brief and focused, moving directly to the conclusion without unnecessary elaboration.<|im_end|>\n",
        "<|im_start|>user\nWhat is 2+2?<|im_end|>\n",
        "<|im_start|>assistant\n<think>\n"
    ],
    expected_not_in=[
        "<|think_low|>"
    ]
)

# 12. Inline <|think_xhigh|> in user message
execute_test(
    "12. Inline <|think_xhigh|> in user string",
    messages=[{"role": "user", "content": "Prove Fermat's Last Theorem <|think_xhigh|>"}],
    expected_in=[
        "<|im_start|>system\nReasoning effort is set to xhigh. Please think carefully through the task, validate key assumptions, consider plausible alternatives, and prioritize correctness, consistency, and clarity in the final answer.<|im_end|>\n",
        "<|im_start|>user\nProve Fermat's Last Theorem<|im_end|>\n",
        "<|im_start|>assistant\n<think>\n"
    ],
    expected_not_in=[
        "<|think_xhigh|>"
    ]
)

# 13. Inline <|think_medium|> in user message
execute_test(
    "13. Inline <|think_medium|> in user string",
    messages=[{"role": "user", "content": "Hello <|think_medium|>"}],
    expected_in=[
        "<|im_start|>user\nHello<|im_end|>\n",
        "<|im_start|>assistant\n<think>\n"
    ],
    expected_not_in=[
        "<|think_medium|>",
        "<|im_start|>system\n"
    ]
)

# 14. Inline <|think_off|> in user message
execute_test(
    "14. Inline <|think_off|> in user string",
    messages=[{"role": "user", "content": "Quick answer: what is capital of France? <|think_off|>"}],
    expected_in=[
        "<|im_start|>user\nQuick answer: what is capital of France?<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
    ],
    expected_not_in=[
        "<|think_off|>",
        "Reasoning effort is set to"
    ]
)

# 15. Inline <|think_low|> in multi-part list[dict]
execute_test(
    "15. Inline <|think_low|> in multi-part list[dict]",
    messages=[
        {"role": "user", "content": [{"type": "text", "text": "Solve this riddle <|think_low|>"}]}
    ],
    expected_in=[
        "<|im_start|>system\nReasoning effort is set to low. Keep your thinking brief and focused, moving directly to the conclusion without unnecessary elaboration.<|im_end|>\n",
        "<|im_start|>user\nSolve this riddle<|im_end|>\n"
    ],
    expected_not_in=[
        "<|think_low|>"
    ]
)

# 16. Inline <|think_xhigh|> in multi-part list[str]
execute_test(
    "16. Inline <|think_xhigh|> in multi-part list[str]",
    messages=[
        {"role": "user", "content": ["Solve this deeply", "<|think_xhigh|>"]}
    ],
    expected_in=[
        "<|im_start|>system\nReasoning effort is set to xhigh. Please think carefully through the task, validate key assumptions, consider plausible alternatives, and prioritize correctness, consistency, and clarity in the final answer.<|im_end|>\n",
        "<|im_start|>user\nSolve this deeply<|im_end|>\n"
    ],
    expected_not_in=[
        "<|think_xhigh|>"
    ]
)

# 17. Clean tag stripping across multiple tags in same string
execute_test(
    "17. Clean tag stripping across multiple tags in same string",
    messages=[
        {"role": "user", "content": "Hello <|think_on|> <|think_minimal|> world"}
    ],
    expected_in=[
        "<|im_start|>user\nHello   world<|im_end|>\n"
    ],
    expected_not_in=[
        "<|think_on|>",
        "<|think_minimal|>"
    ]
)

# ==========================================
# 3. Thinking Toggles & Preserves
# ==========================================

# 18. enable_thinking=false kwarg
execute_test(
    "18. enable_thinking=false kwarg",
    messages=[{"role": "user", "content": "Hello!"}],
    kwargs={"enable_thinking": False},
    expected_in=[
        "<|im_start|>user\nHello!<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
    ]
)

# 19. auto_disable_thinking_with_tools=true
execute_test(
    "19. auto_disable_thinking_with_tools=true",
    messages=[{"role": "user", "content": "What's the weather?"}],
    tools=tools_sample,
    kwargs={"auto_disable_thinking_with_tools": True},
    expected_in=[
        "<|im_start|>assistant\n<think>\n\n</think>\n\n"
    ]
)

# 20. preserve_reasoning=True preserves thinking
execute_test(
    "20. preserve_reasoning=True preserves thinking",
    messages=[
        {"role": "user", "content": "Question 1"},
        {"role": "assistant", "content": "<think>\nThinking 1\n</think>\n\nAnswer 1"},
        {"role": "user", "content": "Question 2"}
    ],
    kwargs={"preserve_reasoning": True},
    expected_in=[
        "<|im_start|>assistant\n<think>\nThinking 1\n</think>\n\nAnswer 1<|im_end|>\n"
    ]
)

# 21. preserve_reasoning=False strips past thinking
execute_test(
    "21. preserve_reasoning=False strips past thinking",
    messages=[
        {"role": "user", "content": "Question 1"},
        {"role": "assistant", "content": "<think>\nThinking 1\n</think>\n\nAnswer 1"},
        {"role": "user", "content": "Question 2"}
    ],
    kwargs={"preserve_reasoning": False},
    expected_in=[
        "<|im_start|>assistant\nAnswer 1<|im_end|>\n"
    ],
    expected_not_in=[
        "Thinking 1"
    ]
)

# 22. In-content <think> parsing (Curing official 3.8 empty think poisoning)
execute_test(
    "22. In-content <think> parsing (Curing official 3.8 empty think poisoning)",
    messages=[
        {"role": "user", "content": "Solve 1+1"},
        {"role": "assistant", "content": "<think>\n1+1 is 2\n</think>\n\nResult is 2"},
        {"role": "user", "content": "Now 2+2"}
    ],
    kwargs={"preserve_thinking": True},
    expected_in=[
        "<|im_start|>assistant\n<think>\n1+1 is 2\n</think>\n\nResult is 2<|im_end|>\n"
    ],
    expected_not_in=[
        "<think>\n\n</think>\n\n<think>"
    ]
)

# 23. OpenAI reasoning_content field
execute_test(
    "23. OpenAI reasoning_content field",
    messages=[
        {"role": "user", "content": "Question 1"},
        {"role": "assistant", "content": "Answer 1", "reasoning_content": "Deep thought 1"},
        {"role": "user", "content": "Question 2"}
    ],
    kwargs={"preserve_thinking": True},
    expected_in=[
        "<|im_start|>assistant\n<think>\nDeep thought 1\n</think>\n\nAnswer 1<|im_end|>\n"
    ]
)

# 24. Anthropic message.thinking field
execute_test(
    "24. Anthropic message.thinking field",
    messages=[
        {"role": "user", "content": "Question 1"},
        {"role": "assistant", "content": "Answer 1", "thinking": "Anthropic thought 1"},
        {"role": "user", "content": "Question 2"}
    ],
    kwargs={"preserve_thinking": True},
    expected_in=[
        "<|im_start|>assistant\n<think>\nAnthropic thought 1\n</think>\n\nAnswer 1<|im_end|>\n"
    ]
)

# ==========================================
# 4. Tool Calling (XML & JSON)
# ==========================================

# 25. Tool calling with dict arguments (XML)
execute_test(
    "25. Tool calling with dict arguments (XML)",
    messages=[
        {"role": "user", "content": "Weather in Paris?"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "arguments": {"city": "Paris"}
                    }
                }
            ]
        }
    ],
    expected_in=[
        "<|im_start|>assistant\n<think>\n\n</think>\n\n<tool_call>\n<function=get_weather>\n<parameter=city>\nParis\n</parameter>\n</function>\n</tool_call><|im_end|>\n"
    ]
)

# 26. Tool calling with JSON string arguments (XML)
execute_test(
    "26. Tool calling with JSON string arguments (XML)",
    messages=[
        {"role": "user", "content": "Weather in Paris?"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "arguments": '{"city": "Paris"}'
                    }
                }
            ]
        }
    ],
    kwargs={"tool_call_format": "xml"},
    expected_in=[
        "<|im_start|>assistant\n<think>\n\n</think>\n\n<tool_call>\n<function=get_weather>\n{\"city\": \"Paris\"}</function>\n</tool_call><|im_end|>\n"
    ]
)

# 27. Tool calling with dict arguments (JSON format)
execute_test(
    "27. Tool calling with dict arguments (JSON format)",
    messages=[
        {"role": "user", "content": "Weather in Paris?"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "arguments": {"city": "Paris"}
                    }
                }
            ]
        }
    ],
    kwargs={"tool_call_format": "json"},
    expected_in=[
        '<|im_start|>assistant\n<think>\n\n</think>\n\n<tool_call>\n{"name": "get_weather", "arguments": {"city": "Paris"}}\n</tool_call><|im_end|>\n'
    ]
)

# 28. Tool calling with JSON string arguments (JSON format)
execute_test(
    "28. Tool calling with JSON string arguments (JSON format)",
    messages=[
        {"role": "user", "content": "Weather in Paris?"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "arguments": '{"city": "Paris"}'
                    }
                }
            ]
        }
    ],
    kwargs={"tool_call_format": "json"},
    expected_in=[
        '<|im_start|>assistant\n<think>\n\n</think>\n\n<tool_call>\n{"name": "get_weather", "arguments": {"city": "Paris"}}\n</tool_call><|im_end|>\n'
    ]
)

# 29. Tool calling with empty arguments string
execute_test(
    "29. Tool calling with empty arguments string",
    messages=[
        {"role": "user", "content": "Call tool without args"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "type": "function",
                    "function": {
                        "name": "no_arg_tool",
                        "arguments": ""
                    }
                }
            ]
        }
    ],
    expected_in=[
        "<|im_start|>assistant\n<think>\n\n</think>\n\n<tool_call>\n<function=no_arg_tool>\n</function>\n</tool_call><|im_end|>\n"
    ]
)

# ==========================================
# 5. Payload Truncation & Error Escalation
# ==========================================

# 30. Dynamic parameter truncation (max_tool_arg_chars)
execute_test(
    "30. Dynamic parameter truncation (max_tool_arg_chars)",
    messages=[
        {"role": "user", "content": "Execute SQL"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "type": "function",
                    "function": {
                        "name": "run_sql",
                        "arguments": {"query": "SELECT * FROM users WHERE id = 1234567890 AND active = true"}
                    }
                }
            ]
        }
    ],
    kwargs={"max_tool_arg_chars": 20},
    expected_in=[
        "[TRUNCATED - original length"
    ]
)

# 31. Dynamic response truncation (max_tool_response_chars)
execute_test(
    "31. Dynamic response truncation (max_tool_response_chars)",
    messages=[
        {"role": "user", "content": "Search files"},
        {"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {"name": "search", "arguments": {}}}]},
        {"role": "tool", "content": "A" * 200}
    ],
    kwargs={"max_tool_response_chars": 50},
    expected_in=[
        "[TRUNCATED - original length 200 chars]"
    ]
)

# 32. Consecutive tool error warning 1
execute_test(
    "32. Consecutive tool error warning 1",
    messages=[
        {"role": "user", "content": "Run tool"},
        {"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {"name": "run", "arguments": {}}}]},
        {"role": "tool", "content": '{"error": "file not found"}'}
    ],
    expected_in=[
        "⚠️ SYSTEM WARNING: The previous tool call returned an error. Diagnose the failure and retry with completely corrected arguments."
    ]
)

# 33. Consecutive tool error warning 2 (retaining reasoning for error correction)
execute_test(
    "33. Consecutive tool error warning 2 (retaining reasoning for error correction)",
    messages=[
        {"role": "user", "content": "Run tool"},
        {"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {"name": "run", "arguments": {}}}]},
        {"role": "tool", "content": '{"error": "file not found"}'},
        {"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {"name": "run", "arguments": {}}}]},
        {"role": "tool", "content": '{"error": "permission denied"}'}
    ],
    expected_in=[
        "⚠️ SYSTEM WARNING: 2 consecutive tool errors detected. Your previous approach is incorrect. You MUST use a fundamentally different approach or corrected arguments.",
        "<|im_start|>assistant\n<think>\n"
    ]
)

# 34. Mid-conversation system & developer messages
execute_test(
    "34. Mid-conversation system & developer messages",
    messages=[
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi"},
        {"role": "developer", "content": "Mid-conversation update: user changed context."},
        {"role": "user", "content": "Continue"}
    ],
    expected_in=[
        "<|im_start|>system\nMid-conversation update: user changed context.<|im_end|>\n",
        "<|im_start|>user\nContinue<|im_end|>\n"
    ]
)

# ==========================================
# 3. v22.2 Enhancements & Community Fixes
# ==========================================

# 35. reasoning_effort='ultracode' (Discussion #78)
execute_test(
    "35. reasoning_effort='ultracode'",
    messages=[{"role": "user", "content": "Analyze algorithm"}],
    kwargs={"reasoning_effort": "ultracode"},
    expected_in=[
        "<|im_start|>system\nReasoning effort is set to xhigh. Please think carefully through the task, validate key assumptions, consider plausible alternatives, and prioritize correctness, consistency, and clarity in the final answer.<|im_end|>\n"
    ]
)

# 36. reasoning_effort='extreme'
execute_test(
    "36. reasoning_effort='extreme'",
    messages=[{"role": "user", "content": "Analyze algorithm"}],
    kwargs={"reasoning_effort": "extreme"},
    expected_in=[
        "<|im_start|>system\nReasoning effort is set to xhigh. Please think carefully through the task, validate key assumptions, consider plausible alternatives, and prioritize correctness, consistency, and clarity in the final answer.<|im_end|>\n"
    ]
)

# 37. Inline <|think_ultracode|> in user message
execute_test(
    "37. Inline <|think_ultracode|> in user message",
    messages=[{"role": "user", "content": "Optimize this shader <|think_ultracode|>"}],
    expected_in=[
        "<|im_start|>system\nReasoning effort is set to xhigh. Please think carefully through the task, validate key assumptions, consider plausible alternatives, and prioritize correctness, consistency, and clarity in the final answer.<|im_end|>\n",
        "<|im_start|>user\nOptimize this shader<|im_end|>\n"
    ],
    expected_not_in=[
        "<|think_ultracode|>"
    ]
)

# 38. Multiple leading system and developer messages merging
execute_test(
    "38. Multiple leading system and developer messages merging",
    messages=[
        {"role": "system", "content": "Base instructions."},
        {"role": "developer", "content": "Developer constraints."},
        {"role": "system", "content": "Additional guidelines."},
        {"role": "user", "content": "Hello"}
    ],
    expected_in=[
        "<|im_start|>system\nBase instructions.\n\nDeveloper constraints.\n\nAdditional guidelines.<|im_end|>\n",
        "<|im_start|>user\nHello<|im_end|>\n"
    ]
)

# 39. Grep code search with throw Error not false-positiving on tool error (Discussion #66)
execute_test(
    "39. Grep code search with throw Error not false-positiving on tool error (Discussion #66)",
    messages=[
        {"role": "user", "content": "Search for error handlers"},
        {"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {"name": "grep", "arguments": {"pattern": "failed to"}}}]},
        {"role": "tool", "content": "src/lib/api.ts:42: throw new Error('failed to fetch');"},
        {"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {"name": "grep", "arguments": {"pattern": "failed to"}}}]},
        {"role": "tool", "content": "src/lib/auth.ts:18: throw new Error('failed to authenticate');"}
    ],
    expected_not_in=[
        "⚠️ SYSTEM WARNING"
    ]
)

# 40. Grep code search with console.error not false-positiving
execute_test(
    "40. Grep code search with console.error not false-positiving",
    messages=[
        {"role": "user", "content": "Search for error logging"},
        {"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {"name": "grep", "arguments": {"pattern": "console.error"}}}]},
        {"role": "tool", "content": "src/utils.js:5: console.error('failed to load config');"}
    ],
    expected_not_in=[
        "⚠️ SYSTEM WARNING"
    ]
)

# 41. Python Traceback legitimately triggers tool error warning
execute_test(
    "41. Python Traceback legitimately triggers tool error warning",
    messages=[
        {"role": "user", "content": "Run script"},
        {"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {"name": "python", "arguments": {"code": "1/0"}}}]},
        {"role": "tool", "content": "Traceback (most recent call last):\n  File 'test.py', line 1\nZeroDivisionError: division by zero"}
    ],
    expected_in=[
        "⚠️ SYSTEM WARNING: The previous tool call returned an error. Diagnose the failure and retry with completely corrected arguments."
    ]
)

# 42. Safe XML parameter formatting for booleans, nulls, and numbers
execute_test(
    "42. Safe XML parameter formatting for booleans, nulls, and numbers",
    messages=[
        {"role": "user", "content": "Call config tool"},
        {"role": "assistant", "content": "", "tool_calls": [{
            "type": "function",
            "function": {
                "name": "set_config",
                "arguments": {
                    "is_active": True,
                    "is_debug": False,
                    "retries": 5,
                    "metadata": None
                }
            }
        }]}
    ],
    expected_in=[
        "<parameter=is_active>\ntrue\n</parameter>",
        "<parameter=is_debug>\nfalse\n</parameter>",
        "<parameter=retries>\n5\n</parameter>",
        "<parameter=metadata>\nnull\n</parameter>"
    ]
)

# 43. KV Cache Stability: History with JSON string arguments preserves canonical XML system prompt
execute_test(
    "43. KV Cache Stability: History with JSON string arguments preserves canonical XML system prompt",
    messages=[
        {"role": "user", "content": "What's the weather?"},
        {"role": "assistant", "content": "", "tool_calls": [{
            "type": "function",
            "function": {
                "name": "get_weather",
                "arguments": '{"city": "Paris", "unit": "celsius"}'
            }
        }]},
        {"role": "tool", "content": '{"temp": 22}'}
    ],
    tools=tools_sample,
    expected_in=[
        "<function=example_function_name>",
        "<tool_call>\n<function=get_weather>\n{\"city\": \"Paris\", \"unit\": \"celsius\"}</function>\n</tool_call>"
    ]
)

# ==========================================
# 6. Control Tag & Alias Completeness (v22.3)
# ==========================================

# 45. Inline <|think_high|>
execute_test(
    "45. Inline <|think_high|>",
    messages=[{"role": "user", "content": "Analyze this <|think_high|>"}],
    expected_in=[
        "<|im_start|>system\nReasoning effort is set to xhigh."
    ],
    expected_not_in=[
        "<|think_high|>"
    ]
)

# 46. Inline <|think_extreme|>
execute_test(
    "46. Inline <|think_extreme|>",
    messages=[{"role": "user", "content": "Analyze this <|think_extreme|>"}],
    expected_in=[
        "<|im_start|>system\nReasoning effort is set to xhigh."
    ],
    expected_not_in=[
        "<|think_extreme|>"
    ]
)

# 47. Inline <|think_max|>
execute_test(
    "47. Inline <|think_max|>",
    messages=[{"role": "user", "content": "Analyze this <|think_max|>"}],
    expected_in=[
        "<|im_start|>system\nReasoning effort is set to xhigh."
    ],
    expected_not_in=[
        "<|think_max|>"
    ]
)

# 48. Inline <|think_minimal|> injects low reasoning instructions
execute_test(
    "48. Inline <|think_minimal|> injects low reasoning instructions",
    messages=[{"role": "user", "content": "Answer fast <|think_minimal|>"}],
    expected_in=[
        "<|im_start|>system\nReasoning effort is set to low."
    ],
    expected_not_in=[
        "<|think_minimal|>"
    ]
)

# 49. Inline <|think_on|> overrides enable_thinking=False
execute_test(
    "49. Inline <|think_on|> overrides enable_thinking=False",
    messages=[{"role": "user", "content": "Think about this <|think_on|>"}],
    kwargs={"enable_thinking": False},
    expected_in=[
        "<|im_start|>assistant\n<think>\n"
    ],
    expected_not_in=[
        "<think>\n\n</think>",
        "<|think_on|>"
    ]
)

# 50. reasoning_effort is case-insensitive
execute_test(
    "50. reasoning_effort is case-insensitive",
    messages=[{"role": "user", "content": "Hello!"}],
    kwargs={"reasoning_effort": "XHigh"},
    expected_in=[
        "<|im_start|>system\nReasoning effort is set to xhigh."
    ]
)

# 51. reasoning_effort='off' disables thinking
execute_test(
    "51. reasoning_effort='off' disables thinking",
    messages=[{"role": "user", "content": "Hello!"}],
    kwargs={"reasoning_effort": "off"},
    expected_in=[
        "<|im_start|>assistant\n<think>\n\n</think>\n\n"
    ],
    expected_not_in=[
        "Reasoning effort is set to"
    ]
)

# 52. reasoning_effort=None falls back to medium
execute_test(
    "52. reasoning_effort=None falls back to medium",
    messages=[{"role": "user", "content": "Hello!"}],
    kwargs={"reasoning_effort": None},
    expected_in=[
        "<|im_start|>assistant\n<think>\n"
    ],
    expected_not_in=[
        "Reasoning effort is set to"
    ]
)

# 53. Non-string reasoning_effort does not crash
execute_test(
    "53. Non-string reasoning_effort does not crash",
    messages=[{"role": "user", "content": "Hello!"}],
    kwargs={"reasoning_effort": 3},
    expected_in=[
        "<|im_start|>assistant\n<think>\n"
    ],
    expected_not_in=[
        "Reasoning effort is set to"
    ]
)

# 54. Control tag inside a system message is honored and stripped
execute_test(
    "54. Control tag inside a system message is honored and stripped",
    messages=[
        {"role": "system", "content": "You are terse. <|think_low|>"},
        {"role": "user", "content": "Hello"}
    ],
    expected_in=[
        "Reasoning effort is set to low.",
        "You are terse."
    ],
    expected_not_in=[
        "<|think_low|>"
    ]
)

# 55. Most recent control tag wins across turns
execute_test(
    "55. Most recent control tag wins across turns",
    messages=[
        {"role": "user", "content": "First <|think_xhigh|>"},
        {"role": "assistant", "content": "Ok"},
        {"role": "user", "content": "Second <|think_low|>"}
    ],
    expected_in=[
        "Reasoning effort is set to low."
    ],
    expected_not_in=[
        "Reasoning effort is set to xhigh."
    ]
)

# 56. enable_thinking=False suppresses reasoning effort injection
execute_test(
    "56. enable_thinking=False suppresses reasoning effort injection",
    messages=[{"role": "user", "content": "Hello!"}],
    kwargs={"enable_thinking": False, "reasoning_effort": "xhigh"},
    expected_in=[
        "<|im_start|>assistant\n<think>\n\n</think>\n\n"
    ],
    expected_not_in=[
        "Reasoning effort is set to"
    ]
)

# 57. <|think_off|> takes precedence over an effort tag in the same message
execute_test(
    "57. <|think_off|> takes precedence over an effort tag in the same message",
    messages=[{"role": "user", "content": "Quick <|think_xhigh|> <|think_off|>"}],
    expected_in=[
        "<|im_start|>assistant\n<think>\n\n</think>\n\n"
    ],
    expected_not_in=[
        "Reasoning effort is set to",
        "<|think_"
    ]
)

# ==========================================
# 7. Malformed Input & Exception Paths (v22.3)
# ==========================================

# 58. Empty message list raises
execute_test(
    "58. Empty message list raises",
    messages=[],
    expect_error=True
)

# 59. Image inside a leading system message raises
execute_test(
    "59. Image inside a leading system message raises",
    messages=[
        {"role": "system", "content": [{"type": "image", "image": "data"}]},
        {"role": "user", "content": "Hello"}
    ],
    expect_error=True
)

# 60. Scalar (non-string, non-list) content raises
execute_test(
    "60. Scalar content raises",
    messages=[{"role": "user", "content": 12345}],
    expect_error=True
)

# 61. Unknown multi-part item type raises
execute_test(
    "61. Unknown multi-part item type raises",
    messages=[{"role": "user", "content": [{"type": "audio", "audio": "data"}]}],
    expect_error=True
)

# ==========================================
# 8. Vision & Multi-Part Content (v22.3)
# ==========================================

# 62. Image part renders vision tokens inline with text
execute_test(
    "62. Image part renders vision tokens inline with text",
    messages=[{"role": "user", "content": [
        {"type": "image", "image": "data"},
        {"type": "text", "text": "What is this?"}
    ]}],
    expected_in=[
        "<|im_start|>user\n<|vision_start|><|image_pad|><|vision_end|>What is this?<|im_end|>\n"
    ]
)

# 63. add_vision_id numbers images across turns
execute_test(
    "63. add_vision_id numbers images across turns",
    messages=[
        {"role": "user", "content": [{"type": "image", "image": "a"}]},
        {"role": "assistant", "content": "Ok"},
        {"role": "user", "content": [{"type": "image", "image": "b"}]}
    ],
    kwargs={"add_vision_id": True},
    expected_in=[
        "Picture 1: <|vision_start|><|image_pad|><|vision_end|>",
        "Picture 2: <|vision_start|><|image_pad|><|vision_end|>"
    ]
)

# 64. Video part renders video tokens
execute_test(
    "64. Video part renders video tokens",
    messages=[{"role": "user", "content": [{"type": "video", "video": "data"}]}],
    expected_in=[
        "<|vision_start|><|video_pad|><|vision_end|>"
    ]
)

# ==========================================
# 9. Agentic Structure & Wire Format Shapes (v22.3)
# ==========================================

# 65. Assistant text combined with a tool call
execute_test(
    "65. Assistant text combined with a tool call",
    messages=[
        {"role": "user", "content": "Weather?"},
        {"role": "assistant", "content": "Let me check.", "tool_calls": [
            {"type": "function", "function": {"name": "get_weather", "arguments": {"city": "Paris"}}}
        ]}
    ],
    expected_in=[
        "<|im_start|>assistant\n<think>\n\n</think>\n\nLet me check.\n\n<tool_call>\n<function=get_weather>\n"
    ]
)

# 66. Parallel tool calls in a single assistant message
execute_test(
    "66. Parallel tool calls in a single assistant message",
    messages=[
        {"role": "user", "content": "Compare"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"type": "function", "function": {"name": "f1", "arguments": {"a": "1"}}},
            {"type": "function", "function": {"name": "f2", "arguments": {"b": "2"}}}
        ]}
    ],
    expected_in=[
        "<|im_start|>assistant\n<think>\n\n</think>\n\n<tool_call>\n<function=f1>\n",
        "</tool_call>\n\n<tool_call>\n<function=f2>\n"
    ]
)

# 67. Consecutive tool results collapse into a single user turn
execute_test(
    "67. Consecutive tool results collapse into a single user turn",
    messages=[
        {"role": "user", "content": "Compare"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"type": "function", "function": {"name": "f1", "arguments": {}}},
            {"type": "function", "function": {"name": "f2", "arguments": {}}}
        ]},
        {"role": "tool", "content": "result one"},
        {"role": "tool", "content": "result two"},
        {"role": "user", "content": "Thanks"}
    ],
    expected_in=[
        "<|im_start|>user\n<tool_response>\nresult one\n</tool_response>\n<tool_response>\nresult two\n</tool_response><|im_end|>\n"
    ]
)

# 68. Flat tool_call shape without a 'function' wrapper
execute_test(
    "68. Flat tool_call shape without a 'function' wrapper",
    messages=[
        {"role": "user", "content": "Weather?"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"name": "get_weather", "arguments": {"city": "Paris"}}
        ]}
    ],
    expected_in=[
        "<tool_call>\n<function=get_weather>\n<parameter=city>\nParis\n</parameter>\n</function>\n</tool_call>"
    ]
)

# 69. OpenAI tool_call id/index fields are tolerated
execute_test(
    "69. OpenAI tool_call id/index fields are tolerated",
    messages=[
        {"role": "user", "content": "Weather?"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "call_abc", "index": 0, "type": "function",
             "function": {"name": "get_weather", "arguments": {"city": "Paris"}}}
        ]},
        {"role": "tool", "tool_call_id": "call_abc", "content": "22C"}
    ],
    expected_in=[
        "<function=get_weather>",
        "<tool_response>\n22C\n</tool_response>"
    ]
)

# 70. Unknown roles fall back to a labelled user turn
execute_test(
    "70. Unknown roles fall back to a labelled user turn",
    messages=[
        {"role": "user", "content": "Hello"},
        {"role": "critic", "content": "Needs work"}
    ],
    expected_in=[
        "<|im_start|>user\n[critic]: Needs work<|im_end|>\n"
    ]
)

# 71. add_generation_prompt=False emits no assistant header
execute_test(
    "71. add_generation_prompt=False emits no assistant header",
    messages=[{"role": "user", "content": "Hello"}],
    kwargs={"add_generation_prompt": False},
    expected_in=[
        "<|im_start|>user\nHello<|im_end|>\n"
    ],
    expected_not_in=[
        "<|im_start|>assistant"
    ]
)

# 72. Empty tools list emits no tool system block
execute_test(
    "72. Empty tools list emits no tool system block",
    messages=[{"role": "user", "content": "Hello"}],
    tools=[],
    expected_not_in=[
        "# Tools"
    ]
)

# 73. Assistant content=None does not crash
execute_test(
    "73. Assistant content=None does not crash",
    messages=[
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": None},
        {"role": "user", "content": "Again"}
    ],
    expected_in=[
        "<|im_start|>assistant\n<think>\n\n</think>\n\n<|im_end|>\n"
    ]
)

# 74. Scalar tool arguments are serialized, not dropped
execute_test(
    "74. Scalar tool arguments are serialized, not dropped",
    messages=[
        {"role": "user", "content": "Call"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"type": "function", "function": {"name": "f", "arguments": 42}}
        ]}
    ],
    expected_in=[
        "<tool_call>\n<function=f>\n42</function>\n</tool_call>"
    ]
)

# ==========================================
# 10. Reasoning Extraction Edge Cases (v22.3)
# ==========================================

# 75. <thinking> variant is extracted and normalized
execute_test(
    "75. <thinking> variant is extracted and normalized",
    messages=[
        {"role": "user", "content": "Q"},
        {"role": "assistant", "content": "<thinking>\nT\n</thinking>\n\nA"},
        {"role": "user", "content": "Q2"}
    ],
    expected_in=[
        "<|im_start|>assistant\n<think>\nT\n</think>\n\nA<|im_end|>\n"
    ]
)

# 76. Spaced </think > variant is extracted
execute_test(
    "76. Spaced </think > variant is extracted",
    messages=[
        {"role": "user", "content": "Q"},
        {"role": "assistant", "content": "<think>\nT\n</think >\n\nA"},
        {"role": "user", "content": "Q2"}
    ],
    expected_in=[
        "<|im_start|>assistant\n<think>\nT\n</think>\n\nA<|im_end|>\n"
    ]
)

# 77. Single-line think block is extracted
execute_test(
    "77. Single-line think block is extracted",
    messages=[
        {"role": "user", "content": "Q"},
        {"role": "assistant", "content": "<think>T</think>A"},
        {"role": "user", "content": "Q2"}
    ],
    expected_in=[
        "<|im_start|>assistant\n<think>\nT\n</think>\n\nA<|im_end|>\n"
    ]
)

# 78. reasoning_content plus in-content tags must not duplicate think blocks
execute_test(
    "78. reasoning_content plus in-content tags must not duplicate think blocks",
    messages=[
        {"role": "user", "content": "Q"},
        {"role": "assistant", "reasoning_content": "R", "content": "<think>\nT\n</think>\n\nA"},
        {"role": "user", "content": "Q2"}
    ],
    expected_in=[
        "<|im_start|>assistant\n<think>\nR\n</think>\n\nA<|im_end|>\n"
    ],
    expected_not_in=[
        "</think>\n\n<think>"
    ]
)

# 79. preserve_thinking=False retains reasoning inside the active tool loop
execute_test(
    "79. preserve_thinking=False retains reasoning inside the active tool loop",
    messages=[
        {"role": "user", "content": "Fix it"},
        {"role": "assistant", "content": "<think>\nplan the fix\n</think>\n\n", "tool_calls": [
            {"type": "function", "function": {"name": "run", "arguments": {}}}
        ]},
        {"role": "tool", "content": "output"}
    ],
    kwargs={"preserve_thinking": False},
    expected_in=[
        "plan the fix"
    ]
)

# 80. preserve_thinking=False strips reasoning once a new user turn starts
execute_test(
    "80. preserve_thinking=False strips reasoning once a new user turn starts",
    messages=[
        {"role": "user", "content": "Fix it"},
        {"role": "assistant", "content": "<think>\nplan the fix\n</think>\n\n", "tool_calls": [
            {"type": "function", "function": {"name": "run", "arguments": {}}}
        ]},
        {"role": "tool", "content": "output"},
        {"role": "assistant", "content": "<think>\nwrap up\n</think>\n\nDone."},
        {"role": "user", "content": "Thanks"}
    ],
    kwargs={"preserve_thinking": False},
    expected_not_in=[
        "plan the fix",
        "wrap up"
    ]
)

# 81. Explicit reasoning preserves literal think tags inside the final answer
execute_test(
    "81. Explicit reasoning preserves literal think tags inside the final answer",
    messages=[
        {"role": "user", "content": "How do I close the think block?"},
        {"role": "assistant", "reasoning_content": "R",
         "content": "Use this closing tag:\n```\n</think>\n```\nDone."},
        {"role": "user", "content": "thanks"}
    ],
    expected_in=[
        "<|im_start|>assistant\n<think>\nR\n</think>\n\nUse this closing tag:\n```\n</think>\n```\nDone.<|im_end|>\n"
    ]
)

# ==========================================
# 11. Tool Error Detection Precision (v22.3)
# ==========================================

# 82. Structural error signal fires regardless of payload length
execute_test(
    "82. Structural error signal fires regardless of payload length",
    messages=[
        {"role": "user", "content": "Run"},
        {"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {"name": "f", "arguments": {}}}]},
        {"role": "tool", "content": '{"error": "boom"}\n' + "detail line\n" * 80}
    ],
    expected_in=[
        "⚠️ SYSTEM WARNING: The previous tool call returned an error."
    ]
)

# 83. Long traceback beyond the weak-signal length gate still fires
execute_test(
    "83. Long traceback beyond the weak-signal length gate still fires",
    messages=[
        {"role": "user", "content": "Run"},
        {"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {"name": "f", "arguments": {}}}]},
        {"role": "tool", "content": "Traceback (most recent call last):\n" +
            '  File "/app/handler.py", line 118, in process\n    result = self.client.fetch(payload)\n' * 6 +
            "ConnectionResetError: [Errno 104] Connection reset by peer"}
    ],
    expected_in=[
        "⚠️ SYSTEM WARNING: The previous tool call returned an error."
    ]
)

# 84. Shell-echoed command output still reports a real failure
execute_test(
    "84. Shell-echoed command output still reports a real failure",
    messages=[
        {"role": "user", "content": "Build"},
        {"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {"name": "bash", "arguments": {}}}]},
        {"role": "tool", "content": "$ npm run build\nError: command not found"}
    ],
    expected_in=[
        "⚠️ SYSTEM WARNING: The previous tool call returned an error."
    ]
)

# 85. Timing metadata does not suppress a structural error
execute_test(
    "85. Timing metadata does not suppress a structural error",
    messages=[
        {"role": "user", "content": "Query"},
        {"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {"name": "db", "arguments": {}}}]},
        {"role": "tool", "content": '{"error": "db timeout", "note": "took 3ms"}'}
    ],
    expected_in=[
        "⚠️ SYSTEM WARNING: The previous tool call returned an error."
    ]
)

# 86. Successful exit code report does not trigger an error warning
execute_test(
    "86. Successful exit code report does not trigger an error warning",
    messages=[
        {"role": "user", "content": "Run"},
        {"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {"name": "bash", "arguments": {}}}]},
        {"role": "tool", "content": "Command completed successfully.\nExit code: 0\n" + "log line\n" * 40}
    ],
    expected_not_in=[
        "⚠️ SYSTEM WARNING"
    ]
)

# 87. Nonzero exit code escalates regardless of payload length
execute_test(
    "87. Nonzero exit code escalates regardless of payload length",
    messages=[
        {"role": "user", "content": "Run"},
        {"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {"name": "bash", "arguments": {}}}]},
        {"role": "tool", "content": "Exit code: 1\n" + "stack frame\n" * 60}
    ],
    expected_in=[
        "⚠️ SYSTEM WARNING: The previous tool call returned an error."
    ]
)

# 88. Failure counter resets after a successful call
execute_test(
    "88. Failure counter resets after a successful call",
    messages=[
        {"role": "user", "content": "Run"},
        {"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {"name": "f", "arguments": {}}}]},
        {"role": "tool", "content": '{"error": "e1"}'},
        {"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {"name": "f", "arguments": {}}}]},
        {"role": "tool", "content": '{"ok": true}'},
        {"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {"name": "f", "arguments": {}}}]},
        {"role": "tool", "content": '{"error": "e2"}'}
    ],
    expected_not_in=[
        "2 consecutive tool errors"
    ]
)

# 89. Failure counter resets on a new user turn
execute_test(
    "89. Failure counter resets on a new user turn",
    messages=[
        {"role": "user", "content": "Run"},
        {"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {"name": "f", "arguments": {}}}]},
        {"role": "tool", "content": '{"error": "e1"}'},
        {"role": "user", "content": "Try again"},
        {"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {"name": "f", "arguments": {}}}]},
        {"role": "tool", "content": '{"error": "e2"}'}
    ],
    expected_not_in=[
        "2 consecutive tool errors"
    ]
)

# 90. Tool response truncation is bypassed in JSON format
execute_test(
    "90. Tool response truncation is bypassed in JSON format",
    messages=[
        {"role": "user", "content": "Query"},
        {"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {"name": "f", "arguments": {}}}]},
        {"role": "tool", "content": json.dumps({"rows": ["x"] * 200})}
    ],
    kwargs={"tool_call_format": "json", "max_tool_response_chars": 50},
    expected_not_in=[
        "[TRUNCATED"
    ]
)

# 91. max_tool_arg_chars applies to serialized JSON string arguments
execute_test(
    "91. max_tool_arg_chars applies to serialized JSON string arguments",
    messages=[
        {"role": "user", "content": "Query"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"type": "function", "function": {"name": "f", "arguments": json.dumps({"q": "S" * 400})}}
        ]}
    ],
    kwargs={"max_tool_arg_chars": 20},
    expected_in=[
        "[TRUNCATED - original length"
    ]
)

# ==========================================
# 12. KV Cache Prefix Stability & Build Parity (v22.3)
# ==========================================

agentic_session = [
    {"role": "system", "content": "You are a coding agent."},
    {"role": "user", "content": "Fix the build"},
    {"role": "assistant", "content": "<think>\ninspect the logs\n</think>\n\n", "tool_calls": [
        {"type": "function", "function": {"name": "run", "arguments": {"cmd": "make"}}}
    ]},
    {"role": "tool", "content": "Error: missing header"},
    {"role": "assistant", "content": "<think>\nadd the include\n</think>\n\nAdding it now.", "tool_calls": [
        {"type": "function", "function": {"name": "edit", "arguments": {"file": "main.c"}}}
    ]},
    {"role": "tool", "content": "ok"},
    {"role": "assistant", "content": "<think>\nverify\n</think>\n\nBuild fixed."},
    {"role": "user", "content": "Thanks"},
]

# 92. Prefix KV cache stability across a full agentic session (default settings)
execute_prefix_test(
    "92. Prefix KV cache stability across a full agentic session (default settings)",
    messages=agentic_session
)

# 93. Prefix KV cache stability with tools and xhigh reasoning
execute_prefix_test(
    "93. Prefix KV cache stability with tools and xhigh reasoning",
    messages=agentic_session,
    kwargs={"tools": tools_sample, "reasoning_effort": "xhigh"}
)

# 94. chat_template_oneline.txt renders identically to chat_template.jinja
execute_parity_test(
    "94. chat_template_oneline.txt renders identically to chat_template.jinja",
    cases=[
        ("plain", [{"role": "user", "content": "Hello"}], {}),
        ("system + tools", [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Weather?"}
        ], {"tools": tools_sample}),
        ("agentic session", agentic_session, {}),
        ("json format", [
            {"role": "user", "content": "Call"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"type": "function", "function": {"name": "f", "arguments": {"a": "1"}}}
            ]}
        ], {"tool_call_format": "json"}),
    ]
)

# ==========================================
# 13. Success Envelopes & Input Shapes (v22.3)
# ==========================================

# 95. JSON success envelope with error:null does not trigger a warning
execute_test(
    "95. JSON success envelope with error:null does not trigger a warning",
    messages=[
        {"role": "user", "content": "Query"},
        {"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {"name": "api", "arguments": {}}}]},
        {"role": "tool", "content": '{"error": null, "data": {"rows": [1, 2, 3]}}\n' + "x" * 700}
    ],
    expected_not_in=[
        "⚠️ SYSTEM WARNING"
    ]
)

# 96. JSON success envelope with error:false does not trigger a warning
execute_test(
    "96. JSON success envelope with error:false does not trigger a warning",
    messages=[
        {"role": "user", "content": "Query"},
        {"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {"name": "api", "arguments": {}}}]},
        {"role": "tool", "content": '{"error": false, "result": "done"}'}
    ],
    expected_not_in=[
        "⚠️ SYSTEM WARNING"
    ]
)

# 97. Inline effort tag overrides the reasoning_effort kwarg
execute_test(
    "97. Inline effort tag overrides the reasoning_effort kwarg",
    messages=[{"role": "user", "content": "Answer fast <|think_low|>"}],
    kwargs={"reasoning_effort": "xhigh"},
    expected_in=[
        "Reasoning effort is set to low."
    ],
    expected_not_in=[
        "Reasoning effort is set to xhigh."
    ]
)

# 98. Tool result with multipart text content is flattened
execute_test(
    "98. Tool result with multipart text content is flattened",
    messages=[
        {"role": "user", "content": "Query"},
        {"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {"name": "api", "arguments": {}}}]},
        {"role": "tool", "content": [{"type": "text", "text": "RESULT_42"}]}
    ],
    expected_in=[
        "<tool_response>\nRESULT_42\n</tool_response>"
    ]
)

# 99. Argument exactly at max_tool_arg_chars is not truncated
execute_test(
    "99. Argument exactly at max_tool_arg_chars is not truncated",
    messages=[
        {"role": "user", "content": "Query"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"type": "function", "function": {"name": "f", "arguments": {"k": "A" * 40}}}]}
    ],
    kwargs={"max_tool_arg_chars": 40},
    expected_in=[
        "A" * 40
    ],
    expected_not_in=[
        "[TRUNCATED"
    ]
)

# 100. Multiple images in a single message get sequential vision ids
execute_test(
    "100. Multiple images in a single message get sequential vision ids",
    messages=[{"role": "user", "content": [
        {"type": "image", "image": "a"},
        {"type": "image", "image": "b"},
        {"type": "text", "text": "compare these"}
    ]}],
    kwargs={"add_vision_id": True},
    expected_in=[
        "Picture 1: <|vision_start|><|image_pad|><|vision_end|>",
        "Picture 2: <|vision_start|><|image_pad|><|vision_end|>"
    ]
)

# ==========================================
# 14. Property-Based Fuzzing (v22.3)
# ==========================================

def run_fuzz_property_test(name, cases, seed):
    print(f"\n--- Running Test: {name} ---")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import fuzz_template
        failures = fuzz_template.run_fuzz(cases=cases, seed=seed,
                                          template_dir=TEMPLATE_DIR,
                                          template_file=TEMPLATE_FILE)
    except Exception:
        print(f"❌ FAILED with exception:\n{traceback.format_exc()}")
        return False
    if failures:
        first = failures[0]
        print(f"❌ FAILED: {len(failures)} invariant violation(s); "
              f"first: [{first['invariant']}] {first['detail']}")
        print(f"Repro (seed {seed}, case {first['case']}): {first['repro'][:600]}")
        return False
    print(f"✅ PASSED ({cases} generated conversations, seed {seed})")
    return True

def execute_fuzz_property_test(*args, **kwargs):
    global tests_passed, tests_total
    tests_total += 1
    if run_fuzz_property_test(*args, **kwargs):
        tests_passed += 1

# 101. Property fuzz: generated conversations uphold all structural invariants
execute_fuzz_property_test(
    "101. Property fuzz: generated conversations uphold all structural invariants",
    cases=300,
    seed=20260820
)

print("\n==========================================")
print(f"Results: {tests_passed} / {tests_total} tests passed ({tests_passed/tests_total*100:.1f}%)")
print("==========================================")

if tests_passed != tests_total:
    sys.exit(1)

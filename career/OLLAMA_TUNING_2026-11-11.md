# Ollama and test-suite tuning, 2026-11-11

Measured on this PC (i7-1355U, 31.7 GB RAM, Intel Iris Xe via Vulkan, MX550 2 GB, Ollama 0.40.15).
The benchmarks ran while other work was going on (test suites, a second loaded model), so read
the speed figures as "same conditions, before and after", not as absolute numbers.

"Fine-tuning" here means what Ollama can do: choosing the base model, the baked-in prompt and
examples, the context size and the server settings. No model weights were trained; a 2 GB GPU
cannot do that.

## What was wrong

1. **Two 5 GB models were loaded at once.** The Ext agent kept `qwen2.5:7b-instruct` loaded
   forever, and `jobbot-answers` (the screening-answer model of the Naukri screener) sat on
   `qwen3:8b`. Together 10.4 GB of shared memory, about 5 GB RAM left free, and each slowed the
   other down.
2. **`jobbot-answers` did not fit its own context window.** Its Modelfile was 120,131 characters
   (about 30,000 tokens) against a 4,096-token window. One baked-in example was a 3,302-option
   dropdown, 105,545 characters on its own. Ollama cut examples off the front on every call and
   re-read a full window each time.
3. **Some baked-in examples were wrong**: answers that were not among the question's own options
   (a "Yes" saved against a list of visa choices), and "free text" placeholders.

## What changed

| Change | Where |
|---|---|
| Examples are filtered (answer must be one of the options, no placeholders, no entry over 400 characters, latest answer per question) and capped at 3,000 characters in total; `num_ctx 4096` is stated in the Modelfile | `Claude_P/Profile_Naukri_Screener-main/naukri/jobs/ai_train.py` (`select_examples`), 7 tests in `tests/test_ai_train.py` |
| `jobbot-answers` rebuilt on `qwen2.5:7b-instruct`, the same weights the Ext agent uses, so Ollama serves both names from one loaded copy (checked: second name loads in 0.1 s) | `OLLAMA_MODEL=qwen2.5:7b-instruct` in `Claude_P/.env` |
| One loaded model at a time, one request at a time | user environment: `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NUM_PARALLEL=1` (applies from the next Ollama restart) |
| The old model is kept | `jobbot-pretune-20261111` (`ollama cp jobbot-pretune-20261111 jobbot-answers` restores it) |

`qwen3:8b` and `qwen2.5:3b-instruct` are still installed and untouched.

## Screening answers: accuracy and time

15 questions asked exactly the way `jobbot.localai.answer_from_facts` asks them: 11 with the
answer in the facts sheet, 4 that must come back UNKNOWN (passport number, Rust experience,
salary in EUR, German work permit).

| Model | Correct | First call | Each later call | All 15 |
|---|---|---|---|---|
| `jobbot-answers` before (qwen3:8b, 80 unfiltered examples) | 15 / 15 | 169 s | 69.8 s | 1,147 s |
| cleaned examples on qwen3:8b | 15 / 15 | 123 s | 15.3 s | 337 s |
| cleaned examples on qwen2.5:7b-instruct | 15 / 15 | 58 s | 19.6 s | 332 s |
| cleaned examples on qwen2.5:3b-instruct | 12 / 15 | 81 s | 8.8 s | 203 s |
| **`jobbot-answers` now** (qwen2.5:7b-instruct, rebuilt by `ai_train`) | 15 / 15 | 74 s | 21.0 s | 368 s |

The 3B model returned the prompt's own placeholder text for three questions, so it was not used.
The final row was measured while the Ext test suite was running.

## Raw speed (tokens per second, 3 short prompts, 48 output tokens)

| Model and placement | Reading the prompt | Generating |
|---|---|---|
| qwen2.5:7b-instruct, iGPU (default) | 32.8 | 4.0 |
| qwen2.5:7b-instruct, CPU 10 threads | 15.1 | 5.5 |
| qwen2.5:7b-instruct, CPU 6 threads | 6.2 | 3.3 |
| qwen3:8b, iGPU | 19.8 | 2.7 |
| qwen2.5:3b-instruct, iGPU | 37.6 | 4.4 |
| qwen2.5:3b-instruct, CPU 10 threads | 39.5 | 6.8 |

Reading the prompt dominates these workloads (long facts sheets, short answers), so the 7B model
stays on the iGPU, as before. CPU with 10 threads generates a little faster but reads prompts at
half the speed. The MX550 holds none of these models (2 GB) and `scripts/gpu_compare.ps1` already
showed that spreading layers onto it is slower.

Free RAM with one model policy in place: 17.2 GB (was 5.0 GB with two models loaded).

## Test suites

| Suite | Before | After |
|---|---|---|
| Ext agent (`agent/tests`, 297 tests) | serial; the slowest 40 tests alone take about 21 minutes | 6 min 13 s on 4 workers (`pytest -n 4`, now in `scripts/test.ps1` / `test.sh`) |
| Ext extension | 36 passed; typecheck had 3 errors | 36 passed; typecheck clean |
| Ext dashboard | 9 passed, typecheck clean | unchanged |
| Claude_P job-hunt | 212 s, 1 failure (the suite talked to the live Ollama server) | 15 s, 152 passed, 2 skipped (tests no longer reach a running Ollama) |
| Claude_P site | 15 passed | unchanged |
| Naukri screener | 260 passed, 1 failed (a test with a hard-coded September date outside its own 30-day window) | 268 passed in 40 s (date fixed, 7 new tests) |
| linkedin-outreach-pipeline | no tests | 30 passed |

## Not done

- No clean idle-machine benchmark; rerun `scripts/gpu_compare.ps1` on a quiet machine for that.
- The Ext agent's own eval harness (`benchmarks/configure_model.py`, 9 cases, 5 to 8 minutes per
  model) was not rerun; its last recorded scores are 0.53 for the 7B model and 0.32 for the 3B.
- Ollama was not restarted, so the one-model limit is not active yet. After the changes
  `ollama ps` still showed `qwen3:8b` loaded next to the 7B model: a process that was already
  running had picked `qwen3:8b` before `OLLAMA_MODEL` was set. Restarting Ollama and the
  screener's background jobs clears it.

# Silent errors in agent memory

[Русская версия](./README.ru.md)

A small, reproducible comparison of two memory systems on facts that change over time.

In a 50-step test, both systems answered most questions correctly. The real difference was elsewhere: in **silent errors**, where the memory ends up in a wrong state and says nothing about it.

| | Eva (memory core) | Mem0 2.2.1, default settings |
|---|---|---|
| Correct, set A (30 steps) | 30 | 26 |
| Correct, set B (20 steps) | 19 | 17 |
| **Correct, total** | **49 / 50** | **43 / 50** |
| **Silent errors** | **1** \* | **7** |
| Wall time, both sets | 81 s | 117 s |
| API cost, both sets | $0.10 | $0.76 |

\* The judge counted 0 silent errors for Eva. I re-read the raw output of step B17 and counted it as silent, because the system itself gave no warning. When in doubt, the stricter count goes against my own system.

Run date: 20 October 2026. Author: Ole Rein.

## Why silent errors

Most memory benchmarks report the share of correct answers. That is useful, but it hides the failure that hurts most in daily use.

When a memory says "I don't know", you ask again or look it up. When it confidently returns last month's price as today's price, you act on it. I run this memory every day in a small repair business, with real customers and real prices, and the expensive mistakes have always been the confident ones.

A step counts as a **silent error** when the system ends up in a wrong state (lost a fact, kept an outdated fact as current, turned a guess into a fact) and neither its answer nor its stored data warns about it. A silent error does not have to produce a wrong answer straight away. Often it waits.

## What Mem0's silent errors have in common

Six of the seven are steps where a new statement **changes** an earlier one: a price goes down, a delivery date moves, a correction ("not 1F, but 5F"), a price that changes from a given date.

In each case Mem0 stores the new statement as a new memory (event `ADD`). Its text often even mentions the old value, for example: *"User now sells the Walker for 19,900 as of October 19, 2026, which differs from the previously noted Walker 6F PREMIUM EX price of 21,500 crowns including VAT"*. But the old memory stays as it was, still current. Across both sets Mem0 made 28 writes, and every one was `ADD`: no `UPDATE`, no `DELETE`.

The memory knows in words that the price changed. Its structure does not.

To be fair to Mem0: in this run **every follow-up question still got the right answer**, because the newer text mentions the change. All seven silent errors are in the stored state, not yet in an answer. They are latent. Nothing in the stored state says which price is current, so whether a later answer is right depends on which memory the search happens to return, and a short test like this one does not show how often that goes wrong.

The seventh (B14) is a related fact rather than a change, and the judge disagreed with itself on it between the two runs.

## Eva's one failure

Step B17: a fact that switches **back**. Dog food from store X, then from store Y, then "since last Wednesday, back to X". Eva parsed the date correctly, but linked the change to the wrong earlier record and gave it an end date nobody had said, so "back to X" had already expired the day before it was written. It gave no warning. Switching back to a previous value is the hardest case for a two-time-axis memory, and this is where mine broke.

## Why Eva behaves this way

Eva's memory core is not published here, but you don't have to take its design on trust. Every write in `сырые_*_эва.json` returns the decision the memory made, so the mechanism is visible in the raw data. Mem0's write returns one thing every time: `ADD`.

| Step | What was said | Eva's recorded decision | Mem0 |
|---|---|---|---|
| A7 | "I now sell the Walker for 19,900" | Replaces record #1 from 19.10. The old price stays in history, no longer current. | `ADD`, old price still current (silent error) |
| A19 | "Correction: not 1F, but 5F" | Record #12 retired with reason "correction", pointing to its successor #13. | `ADD`, old record still current (silent error) |
| A11 | "This Saturday, 24 October, the workshop is closed" | An exception for one day. "General rule untouched": Saturdays stay open the rest of the time. | `ADD` |
| A16 | "Ingrid got the machine" (Latin spelling) | Complements record #3 about "Ингрид" (Cyrillic). Same person, both records alive. | `ADD` |
| A26 | "Eva said the call-out is 850" | Stored as Eva's own note, not a fact. The user's 700 stays true. | `ADD` as an assistant message |

Step A26 shows the core idea best. Inside Eva, the language model that classifies each new statement suggested treating "850" as a replacement for the user's "700". The structure overruled it: a statement whose source is Eva herself cannot replace what the user said. The model proposes, the structure decides.

These are the mechanisms described in the prior-art disclosure published in March 2026, [EVA Memory Bank](https://github.com/violira/eva-memory-bank), items 31 (an append-only ledger where a new fact explicitly supersedes an old one, with source and validity dates) and 33 (one identity for all spellings and transliterations of a name). This test is the first time I measured them against another system.

The same mechanisms are also where Eva broke: in B17 the replacement was linked to the wrong earlier record. Explicit structure makes errors visible, but it does not make them impossible.

## Conditions

- **Mem0** 2.2.1 (`pip install mem0ai`, nothing extra), default configuration. LLM `claude-sonnet-5-5`, embeddings OpenAI `text-embedding-3-small`, default local storage (qdrant), telemetry off. A fresh store per set.
- **Eva** memory core, called over MCP/HTTP as a live client, with a fresh temporary database and "today" fixed at 19 October 2026.
- **Same model** for both systems' internal calls (`claude-sonnet-5-5`).
- **Mapping for Mem0**, since its interface differs: the user's words are a user message; "Eva said" is an assistant message; "correct this" is an ordinary new message; questions go to `search` as written; "what changed today" uses `get_all` (Mem0 has no direct equivalent).
- **One judge** (`claude-sonnet-5-5`), the same prompts for both systems, and the judge is not told which system it is judging. Step 1: the judge describes what the system did, from its raw data, without seeing the expected answer. Step 2: the judge compares that with the expected answer.
- **One run** per system per set. The judge was run twice; both runs are published.

## Limitations

Read these before quoting the numbers.

- **Home field.** 50 steps, written by the author of one of the two systems, in Russian. This is not LongMemEval or LoCoMo. A difference of 49 vs 43 on 50 steps is small. The silent-error count is the more interesting signal, and it too comes from a small set.
- **Mem0 was not tuned.** Default settings only. A tuned Mem0, or a different mapping of "correct this" and "what changed", may do better.
- **The judge is a language model.** It wavered once between runs (B14). Its full reasoning for every step is published so you can disagree with it.
- **Eva's memory core is not in this repository.** You can re-run the Mem0 side and the judge from scratch. The Eva side you can only check from its recorded raw outputs.
- **Anonymised after the run.** Names of people, places, companies and all prices were replaced, consistently across every file. `отчёт.py` regenerates `отчёт.md` from the anonymised data byte for byte, so the published files agree with each other.
- **The first judge run had bugs in my test harness.** Its numbers are in `отчёт.md` next to the main run: Eva 47/50 with 2 silent, Mem0 44/50 with 6 silent.

## Files

The code and data are in Russian, as they were run.

| File | What it is |
|---|---|
| `наборы.py` | The two test sets (A: 30 steps, B: 20 steps), with the expected result of each step and the exact calls made to each system |
| `прогон.py` | Runs one system on one set: `python прогон.py mem0 А` |
| `судья.py` | The judge: reads raw outputs of both systems, writes verdicts |
| `отчёт.py` | Builds the summary report from the judge's verdicts |
| `отчёт.md` | The summary report: every step, both systems, both judge runs |
| `сырые_А_эва.json` and three others | Raw outputs: every call, every reply, cost and timing |
| `судья_А.json`, `судья_Б.json` | Main judge run: what each system did, the verdict and why |
| `судья_*_прогон1.json` | First judge run |

## Re-running

Python 3.11. `pip install mem0ai==2.2.1 anthropic openai`.

The scripts read API keys from `C:\EVA_MEMORY\.env` (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`); change that path at the top of `прогон.py` and `судья.py`. The code is published exactly as it ran.

```
python прогон.py mem0 А
python прогон.py mem0 Б
python судья.py
python отчёт.py
```

The simplest check needs no Mem0 at all: run `судья.py` on the published raw outputs and see whether your verdicts match mine. It overwrites `судья_А.json` and `судья_Б.json`, so copy them aside first.

## License

MIT, see `LICENSE`.

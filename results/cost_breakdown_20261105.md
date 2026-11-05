# Cost breakdown: gpt-4o, gpt-5 (minimal) and gemini-3.5-flash

Models taken forward: **gpt-4o** (current baseline), **gpt-5** with `reasoningEffort: minimal` and
**gemini-3.5-flash** with `reasoningEffort: minimal`. **claude-opus-4-8** is shown for comparison, to decide
whether its higher price pays for itself.

Business target: cost per contact from EUR 7.37 to EUR 6.26, a saving of EUR 1.11 per contact.

## 1. Token prices

List prices in USD per million tokens, from third-party price pages (November 2026). Not yet confirmed against
the providers' own pages or the gateway's billing; the gateway may charge differently.

| Model | Input | Output | Note |
|---|---|---|---|
| gpt-4o | $2.50 | $10.00 | Legacy model; may be retired by OpenAI |
| gpt-5 | $1.25 | $10.00 | Output includes hidden reasoning tokens; `minimal` keeps them low |
| gemini-3.5-flash | $1.50 | $9.00 | Output includes reasoning tokens. Some sources report an introductory $0.75 / $3.75 until 31 Dec 2026 |
| claude-opus-4-8 | $5.00 | $25.00 | Its tokenizer counts about 55% more input tokens for the same text |

## 2. Cost per answer (one question, golden set)

Measured averages over the 20 golden questions, enriched search, evaluation settings (no conversation memory).

| Model | Input tokens | Output tokens | Input cost | Output cost | **Cost per answer** |
|---|---|---|---|---|---|
| gpt-4o | 1,046 | 176 | $0.00262 | $0.00176 | **$0.0044** |
| gpt-5 (minimal) | 1,069 | 229 | $0.00134 | $0.00229 | **$0.0036** |
| gemini-3.5-flash | 1,057 | 200 | $0.00159 | $0.00180 | **$0.0034** |
| claude-opus-4-8 | 1,650 | 223 | $0.00825 | $0.00558 | **$0.0138** |

## 3. Cost per conversation (3 turns)

Measured on 5 troubleshooting conversations per model with the production preset (`baseline`: temperature 0.2,
max 600 tokens, 10 turns of memory), enriched search, **with the follow-up search fix**. Turns: the question,
"I tried that but it didn't help. What else can I do?", "OK, that fixed it. Thanks!". Each turn resends the
system prompt and the history.

| Model | Tokens in / out (turn 1 · 2 · 3) | Total in / out | **Cost per conversation** | Per 1,000 conversations | Per 100,000 conversations |
|---|---|---|---|---|---|
| gpt-4o | 974/157 · 1001/127 · 1174/25 | 3,149 / 308 | **$0.0110** | $10.95 | $1,095 |
| gpt-5 (minimal) | 997/261 · 1024/293 · 1286/73 | 3,307 / 627 | **$0.0104** | $10.40 | $1,040 |
| gemini-3.5-flash | 982/138 · 1006/124 · 1152/53 | 3,140 / 316 | **$0.0076** | $7.55 | $755 |
| claude-opus-4-8 | 1537/145 · 1545/318 · 1709/57 | 4,791 / 520 | **$0.0370** | $36.96 | $3,696 |

Contact volumes are not in the project data; the last two columns only show how the cost scales. Before the fix
the conversations were cheaper ($0.0065 to $0.0319) only because every model handed over on the second turn
instead of continuing to help.

Compared with the EUR 1.11 saving per contact, the model costs about 0.7% (Gemini) to 1% (gpt-4o) of the target
saving per conversation, and Claude about 3.3%. All three chosen models fit easily.

## 4. Quality

| | gpt-4o | gpt-5 (minimal) | gemini-3.5-flash | claude-opus-4-8 |
|---|---|---|---|---|
| Golden set, enriched: correct / partly / hand-over | 18 / 1 / 1 | 18 / 1 / 1 | 18 / 1 / 1 | 18 / 1 / 1 |
| Invented content, enriched golden | 0 | 1 (Q12 Anynet+ path) | 0 | 0 |
| Invented content, raw golden | 1 (Q14 batteries) | 1 (Q13 pairing code) | 1 wrong (Q14 misdiagnosis) | 0 |
| Out-of-scope probe handed over | 8/8 | 8/8 | 8/8 | 8/8 |
| Conversation follow-up ("didn't help"), after the fix | Continues 4/5; hands over on Q14 | Continues 5/5, but used an unrelated voice-remote passage on Q14 | Continues 4/5; hands over on Q14 | Continues 4/5; hands over on Q14 |
| Median answer time | 2.8 s | 4.0 s | 2.6 s | 3.5 s |
| Average answer length | 131 words | 156 words | 143 words | 105 words |
| Style issues | None major | Long answers | Says "I am an AI" in 12/20 answers; promises a hand-over | None |

## 5. Value ranking of the three chosen models

| Rank | Model | Cost per conversation | Why |
|---|---|---|---|
| 1 | **gemini-3.5-flash** | $0.0076 | Cheapest, fastest, no invented content with the enriched search. Style issues can be fixed in the prompt. |
| 2 | **gpt-5** (minimal) | $0.0104 | Slightly cheaper than gpt-4o, same accuracy, but adds its own knowledge more often and writes the longest answers. |
| 3 | **gpt-4o** | $0.0110 | Most expensive of the three, no better, legacy model. Keep as the baseline for comparison. |

## 6. Is Claude Opus 4.8 worth its price?

Not on the current evidence.

- Claude costs about $0.029 more per conversation than Gemini 3.5 Flash (about 5 times as much).
- That extra pays for itself if Claude prevents one extra human contact (EUR 7.37) in about every 250
  conversations, for example by not giving a wrong answer that makes the customer contact support again.
- With the raw search Claude was clearly safer (no guesses). With the enriched search, Gemini 3.5 Flash
  matched it on the golden set, the out-of-scope probe and the follow-up turns. On 20 questions and 5
  conversations, no gap of 1 in 250 can be measured either way.
- The held-out ticket run would settle it: if Gemini or gpt-5 give wrong or invented answers on tickets where
  Claude does not, Claude pays for itself.

## 7. The bigger cost lever: follow-up search (fixed)

Before the fix, when the customer replied "I tried that but it didn't help", the search used only that sentence,
found unrelated passages (p0044, p0082, p0007) and **every model handed over on the second turn, in all 20 test
conversations**. Each hand-over is a human contact at EUR 7.37, about a thousand times the model difference.

Now a message that matches the manual poorly (best search score below 8.5) is searched together with the
customer's earlier messages. Result in the same 20 conversations:

| | Before | After |
|---|---|---|
| Second turn hands over | 20 / 20 | 3 / 20 (all on Q14, where the needed passages are not found) |
| Second turn keeps troubleshooting with the right passages | 0 / 20 | 16 / 20 (plus gpt-5 on Q14 with an unrelated passage) |

Offline search check (no model calls): follow-ups find the right passage in 103 of 120 cases (was 3), and a
change of topic in the second message is not affected (361 of 380, same as before).

## Files and method

- Golden runs: `results/corpus-enriched_golden_<model>_20261105-1016.csv` (tokens per answer).
- Conversation measurement: 5 golden troubleshooting questions (Q04, Q05, Q14, Q15, Q20) x 3 turns per model,
  run through `assistant.run_turn`, not written to the conversation log.
- Model settings: gpt-5 `{"temperature": 1, "reasoningEffort": "minimal"}`, gemini-3.5-flash
  `{"reasoningEffort": "minimal"}`, gpt-4o and claude-opus-4-8 as in the preset.
- Quality: one scorer, small samples; see `results/model_comparison_20261105.md`.

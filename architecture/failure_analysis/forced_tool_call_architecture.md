
# Production Tool-Calling Architecture (LLM-Guided, Not Rule-Based)

If you move to **Llama-3.3-70B** and want reliable tool use **without turning it into a rigid rule engine**, the sweet spot is:

> 🎯 **LLM-guided planning + enforced execution contract**

This keeps context awareness, avoids brittle keyword routing, and still guarantees tools are used when useful.

---

## Architecture Flow

```
User Query
    ↓
Tool Planner LLM
    ↓
Tool Call Validation & Enforcer
    ↓
Tool Execution (parallel)
    ↓
Tool Summaries
    ↓
Response LLM (synthesis)
```

### Key Idea
We guide the LLM but enforce execution.

Not deterministic. Not blind trust.

Think: film director + editor 🎬

---

## STEP 1 — Planner LLM (multi-tool aware)

### Responsibilities
✔ understand intent  
✔ select relevant tools  
✔ propose multiple tools when useful  
✔ produce structured JSON  

---

### Production Planner Prompt (multi-tool capable)

Use this with **Llama-3.3-70B**.

```text
You are an intelligent tool planner.

Your task:
Analyze the user's query and decide which tools should be used.

IMPORTANT:
• Prefer using multiple tools when they provide complementary information.
• Use tools when they improve accuracy, freshness, or completeness.
• Do NOT rely only on general knowledge if tools can improve the answer.

TOOLS:

imdb
→ movie metadata, ratings, cast, release info

watchmode
→ streaming availability by region

wikipedia
→ biographies, filmographies, historical context

similarity
→ recommendations & similar films

web_search
→ latest news, trends, recent releases, public reception

WHEN TO USE MULTIPLE TOOLS:

Movie overview → imdb + wikipedia  
Where to watch → imdb + watchmode  
Reception & reviews → imdb + web_search  
Recommendations → imdb + similarity  
Trending films → web_search (+ imdb if details needed)

Return ONLY valid JSON:

{
  "tool_calls": [
    {
      "name": "tool_name",
      "arguments": { "key": "value" }
    }
  ]
}

Rules:
• Return 1–3 tools when useful.
• If no tools needed, return {"tool_calls":[]}
• Never include explanations.
```

---

## STEP 2 — Tool Enforcement Layer

This prevents the “LLM forgot to call tools” problem.

### Logic

```python
if not tool_calls:
    tool_calls = fallback_tool_selection(message)
```

---

### Soft Enforcement (recommended)

Instead of rigid rules, use intent fallback:

```python
def fallback_tool_selection(message: str):
    text = message.lower()

    if "movie" in text or "film" in text:
        return [{"name":"imdb","arguments":{"title":message}}]

    if "watch" in text or "stream" in text:
        return [
            {"name":"imdb","arguments":{"title":message}},
            {"name":"watchmode","arguments":{"title":message}},
        ]

    if "recommend" in text or "similar" in text:
        return [
            {"name":"imdb","arguments":{"title":message}},
            {"name":"similarity","arguments":{"title":message}},
        ]

    return []
```

👉 This is a safety net, not a routing engine.

---

## STEP 3 — Parallel Tool Execution

Your engine already runs tools concurrently:

```python
results = await asyncio.gather(*tasks)
```

Parallel tools = huge speed win ⚡

---

## STEP 4 — Tool-Aware Response Synthesis

### Response Model Prompt

```text
You are a cinematic intelligence assistant.

Use tool results as factual truth.

Guidelines:
• Integrate tool data naturally.
• Combine insights from multiple tools.
• If tools disagree, prefer the most recent data.
• Provide structured, insightful responses.
• Maintain continuity with prior conversation context.
```

---

## When Should 2–3 Tools Be Used?

### Movie overview
User:
“Give overview of Kottukkali”

Tools:
✔ imdb  
✔ wikipedia  

---

### Streaming + details
User:
“Where can I watch Vikram and is it good?”

Tools:
✔ imdb  
✔ watchmode  
✔ web_search  

---

### Reception & trends
User:
“How is Leo performing with audiences?”

Tools:
✔ imdb  
✔ web_search  

---

### Recommendations
User:
“I liked Super Deluxe. Suggest similar films.”

Tools:
✔ imdb  
✔ similarity  

---

## Encourage Multi-Tool Usage

Add this line to planner prompt:

```
Prefer combining tools when they provide richer understanding.
```

Without this, models tend to pick only one.

---

## Optional: Confidence-Based Tool Expansion

If planner returns only imdb:

```python
if "imdb" in tools and "review" in message:
    tools.append(web_search)
```

This feels intelligent without hard rules.

---

## Why This Architecture Works

✔ Context aware  
✔ Reliable fallback safety net  
✔ Rich multi-source answers  
✔ Production proven  

---

## Model Configuration Tips (70B)

### Planner
temperature = 0  
(max reliability)

### Final response
temperature = 0.3–0.6  
(natural writing)

---

## Example Agent Flow

User:
“Is Kottukkali worth watching and where is it streaming?”

Planner returns:

```json
[
  {"name": "imdb"},
  {"name": "watchmode"},
  {"name": "web_search"}
]
```

Tools execute → synthesis → cinematic response.

Feels intelligent. Not mechanical.

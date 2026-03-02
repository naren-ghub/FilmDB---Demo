# 🚨 Critical Architecture Correction: The "Lazy Agent" & Governance Conflict

**Date:** 2026-03-01
**Status:** URGENT ACTION REQUIRED

## 1. The Diagnosis: Architectural Contradiction

The system is failing because of a direct contradiction between the **Architecture Upgrade** and the **Failure Analysis**:

1.  **Upgrade Doc (Section 3.1):** "Remove Keyword-Based Intent Classification... Governance must no longer rely on keyword intent filtering."
2.  **Failure Analysis (Section 5.3):** Recommends "Expand Web Search Governance Keywords".

**Result:** The system is likely running a "Planner Agent" (Upgrade) that feeds into a "Legacy Governance Layer" (Failure Analysis).
- If the Planner is "lazy" (returns `[]`), no tools run.
- If the Planner proposes a tool, the Legacy Governance likely blocks it because the keywords don't match perfectly.

## 2. The "Lazy Agent" Loophole

The current prompt allows the LLM an escape route:
> *"If no tools needed, return `{"tool_calls": []}`."*

A 70B model is confident. It will often choose this path to save effort, resulting in hallucinated or outdated answers. **Prompts alone cannot fix this.** You need code-level enforcement.

## 3. Implementation Plan: The Enforcement Layer

You must implement a **Rule-Based Fallback** (Safety Net) that runs *after* the Planner but *before* execution. This was proposed in `forced_tool_call_architecture.md` but likely never implemented.

### 3.1 Step 1: Purge Legacy Governance
**Action:** In your Governance code, **DELETE** the `_is_relevant(tool, query)` check that relies on keywords.
*   **New Logic:** If the Planner proposes a valid tool (schema match), **ALLOW IT**. Do not second-guess the Planner with regex.

### 3.2 Step 2: Implement Forced Fallback
**Action:** Insert this logic immediately after the Planner returns.

```python
def enforce_tool_usage(user_query: str, proposed_tools: list) -> list:
    """
    Safety Net: If LLM is lazy (returns empty tools) for obvious 
    informational queries, FORCE the tools.
    """
    if proposed_tools:
        return proposed_tools

    query_lower = user_query.lower()
    forced_tools = []

    # 1. Force Web Search for "Current/Trending" queries
    # Triggers: trending, news, latest, today, now, current, box office
    freshness_triggers = [
        "trending", "news", "latest", "today", "now", "current", 
        "box office", "reviews", "reception"
    ]
    if any(t in query_lower for t in freshness_triggers):
        forced_tools.append({
            "name": "web_search",
            "arguments": {"query": user_query}
        })

    # 2. Force IMDb/Watchmode for "Where to watch" queries
    # Triggers: stream, watch, netflix, hulu, prime, where can i
    streaming_triggers = ["stream", "watch", "netflix", "hulu", "prime", "disney"]
    if any(t in query_lower for t in streaming_triggers):
        # Note: We might need to extract the entity, but for now, 
        # passing the full query to search is better than nothing.
        forced_tools.append({
            "name": "web_search", 
            "arguments": {"query": user_query + " streaming availability"}
        })

    return forced_tools
```

### 3.3 Step 3: Update Orchestrator Flow

**Current Flow (Broken):**
`User -> Planner -> (Empty?) -> Governance(Block?) -> Execution`

**New Flow (Fixed):**
1. `User -> Planner`
2. `tools = Planner.output`
3. `tools = enforce_tool_usage(user_query, tools)`  <-- **MISSING LINK**
4. `Governance.validate_schema(tools)` (No keyword checks!)
5. `Execution`

### 3.4 Step 4: Planner LLM Configuration

To prevent "creative drift" where the model ignores instructions to use tools, you must enforce strict sampling parameters for the Planner call.

**Recommended Settings:**
*   **Temperature:** `0.2` (Crucial: keeps output deterministic)
*   **Top_P:** `0.9`
*   **Max Tokens:** `300-400` (Planner only needs to output JSON, not essays)
*   **Streaming:** `False` (Wait for full JSON before parsing)

## 4. Conclusion

Stop tuning keywords. **Remove them.**
Stop trusting the LLM to call tools. **Force it.**
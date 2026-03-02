# FilmDB - Demo: Database Schema Documentation

------------------------------------------------------------------------

# 1️⃣ Introduction

This document defines the complete database schema for the FilmDB - Demo
project.

The database is responsible for:

-   Session memory (short-term context)
-   User profile (long-term personalization)
-   Tool call logs (observability + debugging)
-   Caching layer (cost & latency control)
-   Optional analytics layer

For a demo internship project, a simple relational database SQLite is sufficient.

------------------------------------------------------------------------

# 2️⃣ Design Principles

Before creating tables, understand the philosophy:

-   LLM does NOT store memory
-   Backend owns all memory
-   Session memory and profile memory are separated
-   Tools are stateless
-   Caching reduces API cost
-   Observability helps debugging

Keep schema simple, normalized, and scalable.

------------------------------------------------------------------------

# 3️⃣ Core Tables

------------------------------------------------------------------------

## 3.1 Users Table

Stores persistent user information.

``` sql
CREATE TABLE users (
    id UUID PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Keep this minimal. Profile data lives in a separate table.

------------------------------------------------------------------------

## 3.2 User Profiles Table

Stores personalization data.

``` sql
CREATE TABLE user_profiles (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    region VARCHAR(100),
    preferred_language VARCHAR(100),
    subscribed_platforms TEXT[],
    favorite_genres TEXT[],
    favorite_movies TEXT[],
    response_style VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Notes:

-   Arrays can be JSON if DB does not support arrays.
-   Keep this flexible.
-   Update gradually through progressive profiling.

------------------------------------------------------------------------

## 3.3 Sessions Table

Each chat thread has a session.

``` sql
CREATE TABLE sessions (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

The title can be auto-generated from first message.

------------------------------------------------------------------------

## 3.4 Messages Table

Stores conversation history.

``` sql
CREATE TABLE messages (
    id UUID PRIMARY KEY,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    role VARCHAR(20),  -- 'user' or 'assistant'
    content TEXT,
    token_count INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Important:

-   Only inject last 8 messages into LLM
-   Keep full history for UI rendering

------------------------------------------------------------------------

# 4️⃣ Tool Logging & Observability

------------------------------------------------------------------------

## 4.1 Tool Calls Table

Tracks every tool call for debugging and cost monitoring.

``` sql
CREATE TABLE tool_calls (
    id UUID PRIMARY KEY,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    tool_name VARCHAR(100),
    request_payload JSONB,
    response_status VARCHAR(20),
    execution_time_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

This helps:

-   Detect over-calling
-   Monitor latency
-   Debug failures
-   Track cost patterns

------------------------------------------------------------------------

# 5️⃣ Caching Layer Tables

Caching reduces API cost and latency.

------------------------------------------------------------------------

## 5.1 Movie Metadata Cache

``` sql
CREATE TABLE movie_metadata_cache (
    title VARCHAR(255) PRIMARY KEY,
    imdb_data JSONB,
    wikipedia_data JSONB,
    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

TTL Strategy:

-   Refresh every 24 hours
-   Overwrite stale data

------------------------------------------------------------------------

## 5.2 Streaming Cache

``` sql
CREATE TABLE streaming_cache (
    title VARCHAR(255),
    region VARCHAR(100),
    streaming_data JSONB,
    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (title, region)
);
```

TTL Strategy:

-   24-hour expiration

------------------------------------------------------------------------

## 5.3 Similarity Cache

``` sql
CREATE TABLE similarity_cache (
    title VARCHAR(255) PRIMARY KEY,
    recommendations JSONB,
    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Similarity rarely changes --- safe to cache longer.

------------------------------------------------------------------------

# 6️⃣ Analytics

------------------------------------------------------------------------

## 6.1 Query Analytics Table

``` sql
CREATE TABLE query_analytics (
    id UUID PRIMARY KEY,
    user_id UUID,
    session_id UUID,
    query_text TEXT,
    tools_used TEXT[],
    response_time_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Useful for:

-   Understanding user behavior
-   Identifying popular queries
-   Improving performance

Optional for demo but impressive in interviews.

------------------------------------------------------------------------

# 7️⃣ Memory Injection Strategy

When handling request:

1.  Fetch user profile
2.  Fetch last 8 messages
3.  Fetch cached data if exists
4.  Execute tools if needed
5.  Store tool logs
6.  Save assistant response

Database is source of truth.

------------------------------------------------------------------------

# 8️⃣ Indexing Strategy

Add indexes for performance:

``` sql
CREATE INDEX idx_sessions_user ON sessions(user_id);
CREATE INDEX idx_messages_session ON messages(session_id);
CREATE INDEX idx_tool_calls_session ON tool_calls(session_id);
CREATE INDEX idx_metadata_cache_title ON movie_metadata_cache(title);
```

Indexes improve scalability.

------------------------------------------------------------------------

# 9️⃣ Data Flow Summary

User → API → Conversation Engine

Conversation Engine:

-   Reads session memory
-   Reads profile
-   Checks cache
-   Executes tools
-   Logs tool calls
-   Stores assistant message

Database ensures persistence, personalization, and cost control.

------------------------------------------------------------------------

# 🔟 Scalability Considerations

For demo:

-   SQLite is fine
-   Add Redis for session memory cache
-   Add TTL eviction jobs

------------------------------------------------------------------------

# 1️⃣1️⃣ Final Design Philosophy

The database:

-   Owns memory
-   Owns personalization
-   Owns observability
-   Supports cost control
-   Enables scalability

LLM is stateless.

Backend + Database hold system intelligence continuity.

------------------------------------------------------------------------

# 🎯 Closing Note

Build schema cleanly.

Do not over-normalize for demo.

Keep tables modular.

Make caching explicit.

Separate session memory from user identity.

This database is the backbone of your conversational intelligence
system.

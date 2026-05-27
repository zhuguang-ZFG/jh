"""SQLite connection + schema migration (WAL mode)."""
import sqlite3
import math
import os
import logging
from typing import Optional
from . import config

logger = logging.getLogger("evo.db")

_conn = None  # type: Optional[sqlite3.Connection]

SCHEMA_SQL = """
-- L0: immutable rules
CREATE TABLE IF NOT EXISTS meta_rules (
    id INTEGER PRIMARY KEY,
    rule_key TEXT UNIQUE NOT NULL,
    rule_value TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    created_at REAL NOT NULL
);

-- L1: skills with EMA weighting
CREATE TABLE IF NOT EXISTS skills (
    id INTEGER PRIMARY KEY,
    skill_key TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    domain TEXT NOT NULL,
    pattern TEXT NOT NULL,
    weight REAL DEFAULT 1.0,
    use_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    created_at REAL NOT NULL,
    last_used REAL DEFAULT 0,
    source TEXT DEFAULT 'session'
);

-- L2: patterns learned from open-source
CREATE TABLE IF NOT EXISTS patterns (
    id INTEGER PRIMARY KEY,
    pattern_key TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    domain TEXT NOT NULL,
    description TEXT NOT NULL,
    code_example TEXT DEFAULT '',
    source_repo TEXT DEFAULT '',
    confidence REAL DEFAULT 0.5,
    use_count INTEGER DEFAULT 0,
    created_at REAL NOT NULL,
    last_used REAL DEFAULT 0
);

-- L3: session summaries
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    session_id TEXT UNIQUE NOT NULL,
    tool TEXT NOT NULL,
    goal TEXT NOT NULL,
    outcome TEXT DEFAULT '',
    changed_files TEXT DEFAULT '[]',
    lessons TEXT DEFAULT '',
    duration_sec INTEGER DEFAULT 0,
    created_at REAL NOT NULL
);

-- L4: evolution proposals
CREATE TABLE IF NOT EXISTS evolutions (
    id INTEGER PRIMARY KEY,
    evo_key TEXT UNIQUE NOT NULL,
    category TEXT NOT NULL,
    summary TEXT NOT NULL,
    evidence_ids TEXT DEFAULT '[]',
    confidence REAL DEFAULT 0.0,
    status TEXT DEFAULT 'proposed',
    created_at REAL NOT NULL,
    resolved_at REAL DEFAULT 0
);

-- unified event log
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    event_id TEXT UNIQUE NOT NULL,
    source TEXT NOT NULL,
    event_type TEXT NOT NULL,
    outcome TEXT DEFAULT '',
    details TEXT DEFAULT '{}',
    recorded_at REAL NOT NULL
);

-- Quality snapshots (pre/post change analysis)
CREATE TABLE IF NOT EXISTS quality_snapshots (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    phase TEXT NOT NULL,           -- "before" or "after"
    snapshot TEXT DEFAULT '{}',    -- JSON: filepath -> metrics
    delta TEXT DEFAULT '{}',       -- JSON: quality delta (after phase only)
    created_at REAL NOT NULL
);

-- Failure patterns (lessons from mistakes)
CREATE TABLE IF NOT EXISTS failure_patterns (
    id INTEGER PRIMARY KEY,
    pattern_key TEXT UNIQUE NOT NULL,
    domain TEXT NOT NULL,
    error_type TEXT NOT NULL,      -- syntax/import/logic/config/performance
    description TEXT NOT NULL,
    file_context TEXT DEFAULT '',  -- which file/area this applies to
    fix_suggestion TEXT DEFAULT '',
    occurrences INTEGER DEFAULT 1,
    created_at REAL NOT NULL,
    last_seen REAL NOT NULL
);

-- Code conventions (extracted from project codebase)
CREATE TABLE IF NOT EXISTS conventions (
    id INTEGER PRIMARY KEY,
    convention_key TEXT UNIQUE NOT NULL,
    category TEXT NOT NULL,        -- naming/error_handling/structure/style
    rule TEXT NOT NULL,
    example TEXT DEFAULT '',
    confidence REAL DEFAULT 0.5,
    created_at REAL NOT NULL
);

-- Git patterns (learned from commit history)
CREATE TABLE IF NOT EXISTS git_patterns (
    id INTEGER PRIMARY KEY,
    pattern_key TEXT UNIQUE NOT NULL,
    pattern_type TEXT NOT NULL,    -- commit_style/code_pattern/refactor
    description TEXT NOT NULL,
    example TEXT DEFAULT '',
    repo TEXT DEFAULT '',
    confidence REAL DEFAULT 0.5,
    created_at REAL NOT NULL
);

-- Briefings (pre-session knowledge injection)
CREATE TABLE IF NOT EXISTS briefings (
    id INTEGER PRIMARY KEY,
    task_summary TEXT NOT NULL,
    relevant_skills TEXT DEFAULT '[]',
    relevant_patterns TEXT DEFAULT '[]',
    relevant_failures TEXT DEFAULT '[]',
    warnings TEXT DEFAULT '[]',
    created_at REAL NOT NULL
);

-- Prompt outcomes (prompt→result correlation tracking)
CREATE TABLE IF NOT EXISTS prompt_outcomes (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    prompt_type TEXT NOT NULL,
    prompt_text TEXT DEFAULT '',
    strategy TEXT DEFAULT '',
    outcome TEXT NOT NULL,
    duration_sec INTEGER DEFAULT 0,
    created_at REAL NOT NULL
);

-- Quality weekly (aggregated quality reports)
CREATE TABLE IF NOT EXISTS quality_weekly (
    id INTEGER PRIMARY KEY,
    week_start TEXT NOT NULL,
    avg_score REAL DEFAULT 0,
    total_sessions INTEGER DEFAULT 0,
    success_rate REAL DEFAULT 0,
    top_improvements TEXT DEFAULT '[]',
    top_regressions TEXT DEFAULT '[]',
    snapshot_json TEXT DEFAULT '{}',
    created_at REAL NOT NULL
);

-- Memories (cross-session vectorized knowledge)
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    domain TEXT DEFAULT 'general',
    confidence REAL DEFAULT 0.5,
    use_count INTEGER DEFAULT 0,
    weight REAL DEFAULT 1.0,
    created_at REAL NOT NULL,
    last_used REAL DEFAULT 0
);

-- Shared knowledge (cross-project sharing)
CREATE TABLE IF NOT EXISTS shared_knowledge (
    id INTEGER PRIMARY KEY,
    share_key TEXT UNIQUE NOT NULL,
    project_name TEXT NOT NULL,
    knowledge_type TEXT NOT NULL,
    name TEXT NOT NULL,
    domain TEXT NOT NULL,
    content TEXT NOT NULL,
    confidence REAL DEFAULT 0.5,
    imported_by TEXT DEFAULT '',
    created_at REAL NOT NULL
);

-- Vector tables for semantic search (sqlite-vec)
-- These are created after sqlite-vec extension is loaded

-- indexes
CREATE INDEX IF NOT EXISTS idx_skills_domain ON skills(domain);
CREATE INDEX IF NOT EXISTS idx_skills_weight ON skills(weight DESC);
CREATE INDEX IF NOT EXISTS idx_patterns_domain ON patterns(domain);
CREATE INDEX IF NOT EXISTS idx_sessions_tool ON sessions(tool);
CREATE INDEX IF NOT EXISTS idx_sessions_created ON sessions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_evolutions_status ON evolutions(status);
CREATE INDEX IF NOT EXISTS idx_events_source ON events(source);
CREATE INDEX IF NOT EXISTS idx_events_recorded ON events(recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_quality_session ON quality_snapshots(session_id);
CREATE INDEX IF NOT EXISTS idx_failure_domain ON failure_patterns(domain);
CREATE INDEX IF NOT EXISTS idx_failure_type ON failure_patterns(error_type);
CREATE INDEX IF NOT EXISTS idx_conventions_category ON conventions(category);
CREATE INDEX IF NOT EXISTS idx_git_patterns_type ON git_patterns(pattern_type);
CREATE INDEX IF NOT EXISTS idx_briefings_created ON briefings(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_prompt_outcomes_type ON prompt_outcomes(prompt_type);
CREATE INDEX IF NOT EXISTS idx_prompt_outcomes_session ON prompt_outcomes(session_id);
CREATE INDEX IF NOT EXISTS idx_quality_weekly_week ON quality_weekly(week_start);
CREATE INDEX IF NOT EXISTS idx_shared_knowledge_type ON shared_knowledge(knowledge_type);
CREATE INDEX IF NOT EXISTS idx_shared_knowledge_project ON shared_knowledge(project_name);
CREATE INDEX IF NOT EXISTS idx_memories_domain ON memories(domain);
CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);

-- Composite indexes for common queries
CREATE INDEX IF NOT EXISTS idx_prompt_outcomes_strategy_created ON prompt_outcomes(strategy, created_at);
CREATE INDEX IF NOT EXISTS idx_sessions_outcome_created ON sessions(outcome, created_at);
CREATE INDEX IF NOT EXISTS idx_quality_phase_created ON quality_snapshots(phase, created_at);
"""


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
        _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
        _conn.execute("PRAGMA busy_timeout=5000")
        _conn.row_factory = sqlite3.Row
        _conn.create_function("exp", 1, math.exp)  # needed for EMA calculations
        _conn.executescript(SCHEMA_SQL)
        # ALTER TABLE: add columns if missing (SQLite no IF NOT EXISTS for ADD COLUMN)
        for col, typedef in [
            ("fix_suggestion", "TEXT DEFAULT ''"),
            ("fix_code", "TEXT DEFAULT ''"),
            ("fix_type", "TEXT DEFAULT ''"),
        ]:
            try:
                _conn.execute(f"ALTER TABLE failure_patterns ADD COLUMN {col} {typedef}")
            except Exception:
                pass  # column already exists

        # Phase 2: git_diff on sessions, code_example on skills
        for table, col, typedef in [
            ("sessions", "git_diff", "TEXT DEFAULT ''"),
            ("skills", "code_example", "TEXT DEFAULT ''"),
        ]:
            try:
                _conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
            except Exception:
                pass

        # Load sqlite-vec extension + create vec tables
        _init_vec_tables(_conn)
    return _conn


def close_conn():
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


def _init_vec_tables(conn: sqlite3.Connection):
    """Load sqlite-vec extension and create vector tables."""
    dim = config.EMBEDDING_DIM
    try:
        conn.enable_load_extension(True)
        import sqlite_vec
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        logger.info(f"sqlite-vec loaded (dim={dim})")
    except ImportError:
        logger.warning("sqlite-vec not installed — vector search disabled")
        return
    except Exception as e:
        logger.warning(f"sqlite-vec load failed: {e} — vector search disabled")
        return

    # Create vec tables for each content table
    for vec_table, content_table in [
        ("skills_vec", "skills"),
        ("patterns_vec", "patterns"),
        ("failures_vec", "failure_patterns"),
        ("memories_vec", "memories"),
    ]:
        try:
            conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {vec_table} "
                f"USING vec0(id INTEGER PRIMARY KEY, embedding float[{dim}])"
            )
        except Exception as e:
            logger.warning(f"Create {vec_table} failed: {e}")

    conn.commit()

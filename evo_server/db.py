"""SQLite connection + schema migration (WAL mode)."""
import sqlite3
import os
from typing import Optional
from . import config

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

-- FTS index for skills + patterns
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    name, domain, pattern, description,
    content='skills', content_rowid='id',
    tokenize='unicode61'
);

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
        _conn.executescript(SCHEMA_SQL)
    return _conn


def close_conn():
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None

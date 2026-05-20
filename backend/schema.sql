PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  occurred_on TEXT NOT NULL,
  narrator TEXT NOT NULL CHECK (narrator IN ('male', 'female', 'both', 'unknown')),
  title TEXT NOT NULL,
  amount_cents INTEGER NOT NULL DEFAULT 0,
  currency TEXT NOT NULL DEFAULT 'CNY',
  emotion_score INTEGER NOT NULL DEFAULT 0,
  content TEXT NOT NULL,
  tags TEXT NOT NULL DEFAULT '[]',
  analysis_json TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS event_edges (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_event_id INTEGER NOT NULL,
  target_event_id INTEGER NOT NULL,
  relation_type TEXT NOT NULL DEFAULT 'related',
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (source_event_id) REFERENCES events(id) ON DELETE CASCADE,
  FOREIGN KEY (target_event_id) REFERENCES events(id) ON DELETE CASCADE,
  UNIQUE (source_event_id, target_event_id, relation_type)
);

CREATE TABLE IF NOT EXISTS memories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id INTEGER,
  scope TEXT NOT NULL DEFAULT 'relationship',
  summary TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_events_occurred_on ON events(occurred_on);
CREATE INDEX IF NOT EXISTS idx_events_narrator ON events(narrator);
CREATE INDEX IF NOT EXISTS idx_edges_source ON event_edges(source_event_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON event_edges(target_event_id);


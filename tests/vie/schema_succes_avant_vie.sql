-- Le schéma de succes.db tel que le code d'AVANT le renommage des tables le
-- créait : dumpé de sqlite_master d'une base construite par VieSyncStore au
-- commit 7eecc67 (25/09/2026), sans une retouche. Les tests de la migration
-- succes_* → vie_* (tests/vie/test_emplacement.py) comparent à lui la base
-- héritée qu'ils fabriquent : sans ce témoin, une fabrique fausse aurait pu
-- faire passer une migration qui ne sait pas traiter la vraie base.
CREATE TABLE succes_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE succes_tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    priority TEXT NOT NULL DEFAULT 'medium',
    scheduled_date TEXT NOT NULL DEFAULT '',
    scheduled_time TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    journal TEXT NOT NULL DEFAULT '',
    emoji TEXT NOT NULL DEFAULT '',
    template_id TEXT NOT NULL DEFAULT '',
    group_id TEXT NOT NULL DEFAULT '',
    order_index INTEGER NOT NULL DEFAULT 0,
    created_date TEXT NOT NULL,
    completed_date TEXT NOT NULL DEFAULT '',
    postponed_count INTEGER NOT NULL DEFAULT 0,
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER,
    owner_id TEXT NOT NULL DEFAULT 'local-owner'
, parent_task_id TEXT NOT NULL DEFAULT '', stage TEXT NOT NULL DEFAULT '', cadence TEXT NOT NULL DEFAULT '', estimate_days INTEGER NOT NULL DEFAULT 0);
CREATE TABLE succes_subtasks (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES succes_tasks(id),
    parent_id TEXT,
    title TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    is_group INTEGER NOT NULL DEFAULT 0,
    order_index INTEGER NOT NULL DEFAULT 0,
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER,
    owner_id TEXT NOT NULL DEFAULT 'local-owner'
);
CREATE TABLE succes_projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '#6366f1',
    icon TEXT NOT NULL DEFAULT '',
    start_date TEXT NOT NULL DEFAULT '',
    end_date TEXT NOT NULL DEFAULT '',
    created_date TEXT NOT NULL DEFAULT '',
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER,
    order_index INTEGER NOT NULL DEFAULT 0
, structure TEXT NOT NULL DEFAULT 'flat', structure_config TEXT NOT NULL DEFAULT '{}');
CREATE TABLE succes_operations (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    op_id TEXT NOT NULL UNIQUE,
    device_id TEXT NOT NULL,
    entity TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    request_json TEXT NOT NULL DEFAULT '{}',
    payload_json TEXT NOT NULL,
    timestamp_ms INTEGER NOT NULL,
    created_at_ms INTEGER NOT NULL
);
CREATE TABLE succes_imports (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    sha256 TEXT NOT NULL UNIQUE,
    snapshot_json TEXT NOT NULL,
    imported_at_ms INTEGER NOT NULL,
    summary_json TEXT NOT NULL
);
CREATE TABLE succes_task_edges (
                project_id TEXT NOT NULL,
                from_task_id TEXT NOT NULL,
                to_task_id TEXT NOT NULL,
                updated_at_ms INTEGER NOT NULL,
                PRIMARY KEY (from_task_id, to_task_id)
            );
CREATE TABLE succes_habits (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    icon TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '#6366f1',
    frequency TEXT NOT NULL DEFAULT 'daily',
    created_date TEXT NOT NULL,
    start_date TEXT NOT NULL DEFAULT '',
    end_date TEXT NOT NULL DEFAULT '',
    weekly_days_json TEXT NOT NULL DEFAULT '[]',
    month_week_slots_json TEXT NOT NULL DEFAULT '[]',
    month_week_day INTEGER NOT NULL DEFAULT 1,
    reminder_time TEXT NOT NULL DEFAULT '',
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER
);
CREATE TABLE succes_habit_logs (
    habit_id TEXT NOT NULL REFERENCES succes_habits(id),
    log_date TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY(habit_id, log_date)
);
CREATE TABLE succes_notes (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER,
    page_format TEXT NOT NULL DEFAULT 'a4',
    page_size TEXT NOT NULL DEFAULT 'a4',
    page_orientation TEXT NOT NULL DEFAULT 'portrait',
    page_margins TEXT NOT NULL DEFAULT 'normales',
    page_background TEXT NOT NULL DEFAULT 'default',
    font_family TEXT NOT NULL DEFAULT 'Special Elite',
    doc_lang TEXT NOT NULL DEFAULT 'fr',
    color TEXT NOT NULL DEFAULT '#6366f1',
    reading_mark INTEGER NOT NULL DEFAULT 0,
    category TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT '',
    order_index INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE succes_note_categories (
    name TEXT PRIMARY KEY,
    order_index INTEGER NOT NULL DEFAULT 0,
    updated_at_ms INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE succes_task_templates (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    emoji TEXT NOT NULL DEFAULT '',
    frequency TEXT NOT NULL DEFAULT 'weekly',
    days_of_week_json TEXT NOT NULL DEFAULT '[]',
    weekly_days_json TEXT NOT NULL DEFAULT '[]',
    month_week_slots_json TEXT NOT NULL DEFAULT '[]',
    month_week_dow INTEGER NOT NULL DEFAULT 1,
    project_id TEXT NOT NULL DEFAULT '',
    priority TEXT NOT NULL DEFAULT 'medium',
    template_kind TEXT NOT NULL DEFAULT 'task',
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    linked_habit_id TEXT NOT NULL DEFAULT '',
    created_date TEXT NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER
);
CREATE TABLE succes_quotes (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'autre',
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER
);
CREATE TABLE succes_settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at_ms INTEGER NOT NULL
);
CREATE TABLE succes_accounts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    account_type TEXT NOT NULL DEFAULT 'checking',
    currency TEXT NOT NULL DEFAULT 'CAD',
    opening_balance_cents INTEGER NOT NULL DEFAULT 0,
    color TEXT NOT NULL DEFAULT '#6366f1',
    icon TEXT NOT NULL DEFAULT '🏦',
    archived INTEGER NOT NULL DEFAULT 0,
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER
);
CREATE TABLE succes_finance_categories (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'expense',
    color TEXT NOT NULL DEFAULT '#6366f1',
    icon TEXT NOT NULL DEFAULT '📦',
    system INTEGER NOT NULL DEFAULT 0,
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER
);
CREATE TABLE succes_transactions (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    category_id TEXT NOT NULL DEFAULT '',
    txn_type TEXT NOT NULL DEFAULT 'expense',
    amount_cents INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'CAD',
    txn_date TEXT NOT NULL,
    payee TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    transfer_account_id TEXT NOT NULL DEFAULT '',
    subscription_id TEXT NOT NULL DEFAULT '',
    import_hash TEXT NOT NULL DEFAULT '',
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER
);
CREATE TABLE succes_subscriptions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'CAD',
    cadence TEXT NOT NULL DEFAULT 'monthly',
    next_due_date TEXT NOT NULL,
    account_id TEXT NOT NULL DEFAULT '',
    category_id TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    reminder_days INTEGER NOT NULL DEFAULT 3,
    notes TEXT NOT NULL DEFAULT '',
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER
);
CREATE TABLE succes_budgets (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL DEFAULT 'global',
    category_id TEXT NOT NULL DEFAULT '',
    year_month TEXT NOT NULL,
    limit_cents INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'CAD',
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER
);
CREATE TABLE succes_savings_goals (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    target_cents INTEGER NOT NULL,
    current_cents INTEGER NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'CAD',
    account_id TEXT NOT NULL DEFAULT '',
    deadline TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '#6366f1',
    icon TEXT NOT NULL DEFAULT '🎯',
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER
);
CREATE TABLE succes_photo_piles (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    cover_photo_id TEXT NOT NULL DEFAULT '',
    order_index INTEGER NOT NULL DEFAULT 0,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER
);
CREATE TABLE succes_photos (
    id TEXT PRIMARY KEY,
    pile_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    file_name TEXT NOT NULL,
    mime TEXT NOT NULL,
    bytes INTEGER NOT NULL,
    width INTEGER NOT NULL DEFAULT 0,
    height INTEGER NOT NULL DEFAULT 0,
    tint TEXT NOT NULL DEFAULT '',
    caption TEXT NOT NULL DEFAULT '',
    task_id TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL DEFAULT 0,
    file_path TEXT NOT NULL,
    thumb_path TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    deleted_at_ms INTEGER
, rotation INTEGER NOT NULL DEFAULT 0, crop_json TEXT NOT NULL DEFAULT '', annotations_json TEXT NOT NULL DEFAULT '', ocr_text TEXT NOT NULL DEFAULT '');
CREATE TABLE succes_sync_pairings (
    token_hash TEXT PRIMARY KEY,
    device_name TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    expires_at_ms INTEGER NOT NULL,
    redeemed_at_ms INTEGER
);
CREATE TABLE succes_sync_peers (
    id TEXT PRIMARY KEY,
    device_name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at_ms INTEGER NOT NULL,
    last_seen_at_ms INTEGER,
    last_pull_cursor INTEGER NOT NULL DEFAULT 0,
    last_push_at_ms INTEGER,
    revoked_at_ms INTEGER
, device_id TEXT);
CREATE TABLE succes_sync_clocks (
    entity TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    timestamp_ms INTEGER NOT NULL,
    op_id TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(entity, entity_id)
);
CREATE TABLE succes_sync_tombstones (
    entity TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    deleted_at_ms INTEGER NOT NULL,
    op_id TEXT NOT NULL,
    PRIMARY KEY(entity, entity_id)
);
CREATE INDEX succes_tasks_date_idx
    ON succes_tasks(scheduled_date, done, order_index);
CREATE INDEX succes_subtasks_task_idx
    ON succes_subtasks(task_id, parent_id, order_index);
CREATE INDEX succes_operations_cursor_idx
    ON succes_operations(seq);
CREATE INDEX succes_tasks_parent_idx ON succes_tasks(project_id, parent_task_id, order_index);
CREATE INDEX succes_task_edges_project_idx ON succes_task_edges(project_id);
CREATE INDEX succes_habits_active_idx
    ON succes_habits(deleted_at_ms, updated_at_ms);
CREATE INDEX succes_habit_logs_date_idx
    ON succes_habit_logs(log_date, done);
CREATE INDEX succes_notes_active_idx
    ON succes_notes(deleted_at_ms, updated_at_ms DESC);
CREATE INDEX succes_templates_active_idx
    ON succes_task_templates(deleted_at_ms, active, start_date, end_date);
CREATE INDEX succes_quotes_active_idx
    ON succes_quotes(deleted_at_ms, category, updated_at_ms DESC);
CREATE INDEX idx_succes_txn_date
    ON succes_transactions(txn_date);
CREATE INDEX idx_succes_txn_account
    ON succes_transactions(account_id, txn_date);
CREATE INDEX idx_succes_txn_category
    ON succes_transactions(category_id, txn_date);
CREATE INDEX succes_photo_piles_project_idx
    ON succes_photo_piles(project_id, deleted_at_ms);
CREATE INDEX succes_photos_pile_idx
    ON succes_photos(pile_id, deleted_at_ms, created_at_ms);
CREATE INDEX succes_photos_task_idx
    ON succes_photos(project_id, task_id, deleted_at_ms);
CREATE INDEX succes_photos_ordre_idx ON succes_photos(pile_id, deleted_at_ms, position, created_at_ms);
CREATE INDEX succes_sync_peers_active_idx
    ON succes_sync_peers(revoked_at_ms, last_seen_at_ms);

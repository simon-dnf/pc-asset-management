-- PC 자산관리 시스템 v1 스키마 (PRD-Master.md §8 기준)
-- SQLite. 모든 시각은 Asia/Seoul 기준 문자열(YYYY-MM-DD HH:MM:SS)로 저장한다. (NFR-14)

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- 관리자 계정
CREATE TABLE IF NOT EXISTS admin_user (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT    NOT NULL UNIQUE,
    password_hash   TEXT    NOT NULL,
    name            TEXT    NOT NULL,
    role            TEXT    NOT NULL DEFAULT 'ADMIN',   -- v1은 항상 ADMIN (PRD-v1 §2)
    is_active       INTEGER NOT NULL DEFAULT 1,
    failed_count    INTEGER NOT NULL DEFAULT 0,
    locked_until    TEXT,
    must_change_pw  INTEGER NOT NULL DEFAULT 0,
    last_login_at   TEXT,
    created_at      TEXT    NOT NULL,
    created_by      TEXT
);

CREATE TABLE IF NOT EXISTS session (
    token       TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES admin_user(id),
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);

-- 관리자 개인 화면 설정 (03-8 표시 컬럼, 05-8 저장된 검색 조건)
-- 계정에 귀속되므로 다른 PC·브라우저에서 접속해도 그대로 따라온다.
CREATE TABLE IF NOT EXISTS user_pref (
    user_id    INTEGER NOT NULL REFERENCES admin_user(id) ON DELETE CASCADE,
    pref_key   TEXT    NOT NULL,
    value_json TEXT    NOT NULL,
    updated_at TEXT    NOT NULL,
    PRIMARY KEY (user_id, pref_key)
);

-- ---------------------------------------------------------------- 공통코드 (FR-13)
CREATE TABLE IF NOT EXISTS code (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    group_code  TEXT NOT NULL,
    code        TEXT NOT NULL,
    label       TEXT NOT NULL,
    parent_code TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    is_active   INTEGER NOT NULL DEFAULT 1,
    is_system   INTEGER NOT NULL DEFAULT 0,
    UNIQUE (group_code, code)
);
CREATE INDEX IF NOT EXISTS idx_code_group ON code(group_code, sort_order);

-- ---------------------------------------------------------------- 임직원 마스터 (FR-14)
CREATE TABLE IF NOT EXISTS employee (
    emp_no        TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    dept_code     TEXT,
    position_code TEXT,
    site_code     TEXT,
    employ_status TEXT NOT NULL DEFAULT '재직',
    email         TEXT,
    phone         TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_emp_name ON employee(name);
CREATE INDEX IF NOT EXISTS idx_emp_dept ON employee(dept_code);

-- ---------------------------------------------------------------- 자산 (DM-ASSET / DM-HW / DM-OPS)
CREATE TABLE IF NOT EXISTS asset (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_no              TEXT NOT NULL UNIQUE,
    asset_type            TEXT NOT NULL,
    manufacturer          TEXT NOT NULL,
    model_name            TEXT NOT NULL,
    serial_no             TEXT,
    purchase_date         TEXT NOT NULL,
    service_start_date    TEXT,
    status                TEXT NOT NULL DEFAULT '대기',
    purchase_amount       INTEGER,
    useful_life_years     INTEGER,
    remark                TEXT,
    site                  TEXT NOT NULL,
    location              TEXT,
    manager_emp_no        TEXT NOT NULL,
    hostname              TEXT,
    ip_address            TEXT,
    ip_type               TEXT,
    mac_address           TEXT,
    cpu                   TEXT,
    ram_gb                INTEGER,
    disk_type             TEXT,
    disk_gb               INTEGER,
    os                    TEXT,
    os_eol_date           TEXT,
    disposal_date         TEXT,
    disposal_method       TEXT,
    current_assignment_id INTEGER,
    created_at            TEXT NOT NULL,
    created_by            TEXT NOT NULL,
    created_method        TEXT NOT NULL DEFAULT '수동',
    import_batch_id       INTEGER,
    updated_at            TEXT NOT NULL,
    updated_by            TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_asset_serial ON asset(serial_no) WHERE serial_no IS NOT NULL AND serial_no <> '';
CREATE INDEX IF NOT EXISTS idx_asset_status ON asset(status);
CREATE INDEX IF NOT EXISTS idx_asset_site   ON asset(site);
CREATE INDEX IF NOT EXISTS idx_asset_type   ON asset(asset_type);
CREATE INDEX IF NOT EXISTS idx_asset_host   ON asset(hostname);
CREATE INDEX IF NOT EXISTS idx_asset_ip     ON asset(ip_address);

-- ---------------------------------------------------------------- 배정 (DM-ASSIGN)
CREATE TABLE IF NOT EXISTS assignment (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id        INTEGER NOT NULL REFERENCES asset(id) ON DELETE CASCADE,
    emp_no          TEXT,
    user_name       TEXT NOT NULL,
    dept_code       TEXT,
    position_code   TEXT,
    site            TEXT,
    location        TEXT,
    issue_date      TEXT NOT NULL,
    due_return_date TEXT,
    return_date     TEXT,
    return_reason   TEXT,
    assign_reason   TEXT,
    is_current      INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    created_by      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_asg_asset ON assignment(asset_id, is_current);
CREATE INDEX IF NOT EXISTS idx_asg_emp   ON assignment(emp_no, is_current);
CREATE UNIQUE INDEX IF NOT EXISTS idx_asg_one_current ON assignment(asset_id) WHERE is_current = 1;

-- ---------------------------------------------------------------- 이력 (DM-HIST) append-only
CREATE TABLE IF NOT EXISTS asset_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id    INTEGER NOT NULL REFERENCES asset(id) ON DELETE CASCADE,
    asset_no    TEXT NOT NULL,
    hist_type   TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    actor       TEXT NOT NULL,
    reason      TEXT,
    before_json TEXT NOT NULL DEFAULT '{}',
    after_json  TEXT NOT NULL DEFAULT '{}',
    extra_json  TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_hist_asset ON asset_history(asset_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_hist_time  ON asset_history(occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_hist_type  ON asset_history(hist_type);

-- 이력 임의 수정 불가 (NFR-13, FR-10-4). 삭제는 자산 물리삭제(FR-04-7) 캐스케이드만 허용.
CREATE TRIGGER IF NOT EXISTS trg_hist_no_update
BEFORE UPDATE ON asset_history
BEGIN SELECT RAISE(ABORT, '이력은 수정할 수 없습니다.'); END;

-- ---------------------------------------------------------------- 엑셀 가져오기 배치 (FR-06)
CREATE TABLE IF NOT EXISTS import_batch (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_no     TEXT NOT NULL UNIQUE,
    kind         TEXT NOT NULL,
    file_name    TEXT NOT NULL,
    mode         TEXT NOT NULL,
    dup_policy   TEXT NOT NULL,
    total_rows   INTEGER NOT NULL DEFAULT 0,
    success_rows INTEGER NOT NULL DEFAULT 0,
    failed_rows  INTEGER NOT NULL DEFAULT 0,
    skipped_rows INTEGER NOT NULL DEFAULT 0,
    updated_rows INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    created_by   TEXT NOT NULL,
    reverted_at  TEXT,
    reverted_by  TEXT,
    revert_note  TEXT
);

-- ---------------------------------------------------------------- 로그 (FR-04-9, FR-07-7)
CREATE TABLE IF NOT EXISTS delete_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_no      TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    reason        TEXT NOT NULL,
    deleted_by    TEXT NOT NULL,
    deleted_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS export_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    actor       TEXT NOT NULL,
    executed_at TEXT NOT NULL,
    scope       TEXT NOT NULL,
    row_count   INTEGER NOT NULL,
    filter_json TEXT NOT NULL DEFAULT '{}'
);

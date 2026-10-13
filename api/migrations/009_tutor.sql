-- Tutor phase 2 (docs/tutor.md sections 8 and 16): remote records
-- of tutor sessions and problem reports. Purely additive.
--
-- A session is addressed by `uid`, the id the session host chose
-- locally, so creating it is idempotent. Reporter, category and
-- status are open value sets: VARCHAR validated by the API.
-- MEDIUMTEXT because the API limits text in characters, and a
-- 20000-character report can exceed the 64 KB of TEXT in utf8mb4.

CREATE TABLE tutor_sessions (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    uid VARCHAR(64) NOT NULL,
    goal JSON NULL,
    teacher VARCHAR(128) NULL,
    started_at DATETIME(3) NOT NULL,
    ended_at DATETIME(3) NULL,
    summary_md MEDIUMTEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    UNIQUE KEY uq_tutor_sessions_uid (user_id, uid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE reports (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    session_uid VARCHAR(64) NULL,
    seq INT NULL,
    reporter VARCHAR(32) NOT NULL,
    category VARCHAR(32) NOT NULL,
    text_md MEDIUMTEXT NOT NULL,
    context JSON NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'new',
    issue_ref VARCHAR(255) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    KEY idx_reports_status (user_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

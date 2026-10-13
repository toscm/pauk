-- Knowledge profile (docs/tutor.md, issues/0014): items with an
-- identity (space/key), aliases, links, per-user memory states
-- derived from an append-only interaction log, subject and card
-- links, merges, and user settings. Purely additive.
--
-- Open value sets (kind, rel, mode, source, best_mode, grader,
-- merge status) are VARCHAR validated by the API, so new values
-- need no migration; ENUM only for the closed sets outcome/status.
-- The log tables have no ON DELETE CASCADE from items: items are
-- archived, never deleted, so evidence is never lost.

CREATE TABLE items (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    space VARCHAR(16) NOT NULL,
    `key` VARCHAR(191) COLLATE utf8mb4_bin NOT NULL,
    key_base VARCHAR(191) COLLATE utf8mb4_bin AS (SUBSTRING_INDEX(`key`, '.', 1)) STORED,
    kind VARCHAR(32) NOT NULL,
    label_md VARCHAR(512) NOT NULL,
    label_norm VARCHAR(191) NOT NULL,
    gloss_md TEXT NOT NULL,
    body_md TEXT NOT NULL,
    attrs JSON NOT NULL,
    doi VARCHAR(191) AS (JSON_VALUE(attrs, '$.doi')) STORED,
    isbn VARCHAR(32) AS (JSON_VALUE(attrs, '$.isbn')) STORED,
    wikidata VARCHAR(32) AS (JSON_VALUE(attrs, '$.wikidata')) STORED,
    priority TINYINT UNSIGNED NOT NULL DEFAULT 50,
    level TINYINT UNSIGNED NULL,
    archived_at DATETIME NULL,
    merged_into BIGINT UNSIGNED NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (merged_into) REFERENCES items (id),
    UNIQUE KEY uq_items (user_id, space, `key`),
    UNIQUE KEY uq_items_doi (user_id, doi),
    UNIQUE KEY uq_items_isbn (user_id, isbn),
    UNIQUE KEY uq_items_wikidata (user_id, wikidata),
    KEY idx_items_norm (user_id, space, label_norm),
    KEY idx_items_base (user_id, space, key_base)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Old keys and alternate names of an item, in key form (slug).
CREATE TABLE item_aliases (
    user_id BIGINT UNSIGNED NOT NULL,
    space VARCHAR(16) NOT NULL,
    alias VARCHAR(191) COLLATE utf8mb4_bin NOT NULL,
    label_md VARCHAR(512) NULL,
    item_id BIGINT UNSIGNED NOT NULL,
    origin VARCHAR(32) NOT NULL,
    reason TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, space, alias),
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (item_id) REFERENCES items (id),
    KEY idx_item_aliases_item (item_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE item_links (
    from_id BIGINT UNSIGNED NOT NULL,
    to_id BIGINT UNSIGNED NOT NULL,
    rel VARCHAR(32) NOT NULL,
    note VARCHAR(255) NULL,
    PRIMARY KEY (from_id, to_id, rel),
    FOREIGN KEY (from_id) REFERENCES items (id),
    FOREIGN KEY (to_id) REFERENCES items (id),
    KEY idx_item_links_to (to_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Cache of the memory model over the log, plus the two per-learner
-- flags (status, note) that are not derived. stability NULL = the
-- item has flags but no evidence yet (unseen).
CREATE TABLE item_states (
    user_id BIGINT UNSIGNED NOT NULL,
    item_id BIGINT UNSIGNED NOT NULL,
    model VARCHAR(32) NOT NULL,
    stability DOUBLE NULL,
    difficulty DOUBLE NULL,
    first_seen_at DATETIME(3) NULL,
    last_seen_at DATETIME(3) NULL,
    reps INT NOT NULL DEFAULT 0,
    lapses INT NOT NULL DEFAULT 0,
    best_mode VARCHAR(32) NULL,
    status ENUM('active', 'focus', 'suspended') NOT NULL DEFAULT 'active',
    note TEXT NOT NULL,
    PRIMARY KEY (user_id, item_id),
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (item_id) REFERENCES items (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- One observable learner event. Raw evidence (exercise with key,
-- structured response, grader version, true time) is kept so
-- outcomes and states can be recomputed by future versions.
CREATE TABLE interactions (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    uuid CHAR(36) NOT NULL UNIQUE,
    user_id BIGINT UNSIGNED NOT NULL,
    session_id VARCHAR(64) NULL,
    card_id BIGINT UNSIGNED NULL,
    review_id BIGINT UNSIGNED NULL,
    source VARCHAR(32) NOT NULL,
    mode VARCHAR(32) NOT NULL,
    exercise JSON NULL,
    response JSON NULL,
    grader VARCHAR(32) NULL,
    graded_match VARCHAR(16) NULL,
    prompt_md TEXT NULL,
    response_md TEXT NULL,
    feedback_md TEXT NULL,
    hinted TINYINT(1) NOT NULL DEFAULT 0,
    occurred_at DATETIME(3) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (card_id) REFERENCES cards (id) ON DELETE SET NULL,
    UNIQUE KEY uq_interactions_review (review_id),
    KEY idx_interactions_user_time (user_id, occurred_at),
    KEY idx_interactions_session (user_id, session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Per-item outcome of an interaction. origin_item_id is the item the
-- evidence was recorded against; it differs from item_id only after
-- a merge, which makes merges reversible.
CREATE TABLE interaction_items (
    interaction_id BIGINT UNSIGNED NOT NULL,
    item_id BIGINT UNSIGNED NOT NULL,
    origin_item_id BIGINT UNSIGNED NOT NULL,
    outcome ENUM('fail', 'hard', 'good', 'easy') NULL,
    note TEXT NULL,
    PRIMARY KEY (interaction_id, item_id),
    FOREIGN KEY (interaction_id) REFERENCES interactions (id),
    FOREIGN KEY (item_id) REFERENCES items (id),
    FOREIGN KEY (origin_item_id) REFERENCES items (id),
    KEY idx_interaction_items_item (item_id, interaction_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Corrections never update the log in place; replay applies the
-- latest amendment per (interaction, origin item).
CREATE TABLE interaction_amendments (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    interaction_id BIGINT UNSIGNED NOT NULL,
    item_id BIGINT UNSIGNED NOT NULL,
    outcome ENUM('fail', 'hard', 'good', 'easy') NULL,
    reason TEXT NOT NULL,
    amended_by VARCHAR(32) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (interaction_id) REFERENCES interactions (id),
    FOREIGN KEY (item_id) REFERENCES items (id),
    KEY idx_amendments_interaction (interaction_id, item_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE card_items (
    card_id BIGINT UNSIGNED NOT NULL,
    item_id BIGINT UNSIGNED NOT NULL,
    PRIMARY KEY (card_id, item_id),
    FOREIGN KEY (card_id) REFERENCES cards (id) ON DELETE CASCADE,
    FOREIGN KEY (item_id) REFERENCES items (id),
    KEY idx_card_items_item (item_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Subjects: the existing directories now hold items as well as cards.
CREATE TABLE dir_items (
    dir_id BIGINT UNSIGNED NOT NULL,
    item_id BIGINT UNSIGNED NOT NULL,
    PRIMARY KEY (dir_id, item_id),
    FOREIGN KEY (dir_id) REFERENCES dirs (id) ON DELETE CASCADE,
    FOREIGN KEY (item_id) REFERENCES items (id),
    KEY idx_dir_items_item (item_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Suggested and executed merges. `moved` records what the merge
-- moved so that unmerge can restore it exactly.
CREATE TABLE item_merges (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    into_id BIGINT UNSIGNED NOT NULL,
    from_id BIGINT UNSIGNED NOT NULL,
    status VARCHAR(32) NOT NULL,
    reason TEXT NOT NULL,
    suggested_by VARCHAR(32) NOT NULL,
    session_id VARCHAR(64) NULL,
    moved JSON NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    decided_at DATETIME NULL,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (into_id) REFERENCES items (id),
    FOREIGN KEY (from_id) REFERENCES items (id),
    KEY idx_item_merges_status (user_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE user_settings (
    user_id BIGINT UNSIGNED NOT NULL,
    name VARCHAR(64) NOT NULL,
    value JSON NOT NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, name),
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

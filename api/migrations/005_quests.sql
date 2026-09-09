-- Quest cards: a scenario the user solves by dialog with an LLM
-- playing a role. The dialog and judging happen client-side (the
-- CLI drives the chosen provider). The API stores the definition
-- and records runs for highscores.
ALTER TABLE cards MODIFY COLUMN type ENUM('mc', 'text', 'match', 'quest') NOT NULL;

CREATE TABLE quest_specs (
    card_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
    scenario_md TEXT NOT NULL,
    role_prompt TEXT NOT NULL,
    success_criteria TEXT NOT NULL,
    max_messages INT NOT NULL DEFAULT 10,
    lang VARCHAR(32) NOT NULL DEFAULT '',
    FOREIGN KEY (card_id) REFERENCES cards (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- A finished quest attempt. success + messages_used drive the
-- highscore (fewest messages among successful runs).
CREATE TABLE quest_runs (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    card_id BIGINT UNSIGNED NOT NULL,
    success TINYINT(1) NOT NULL,
    messages_used INT NOT NULL,
    finished_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (card_id) REFERENCES cards (id) ON DELETE CASCADE,
    KEY idx_quest_runs_card_user (card_id, user_id, success)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE quiz_runs (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    dir_id BIGINT UNSIGNED NULL,
    total INT NOT NULL,
    correct INT NULL,
    started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at DATETIME NULL,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (dir_id) REFERENCES dirs (id) ON DELETE SET NULL,
    KEY idx_quiz_runs_user_dir (user_id, dir_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

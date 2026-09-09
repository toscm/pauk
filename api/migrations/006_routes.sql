-- Route tasks: navigate a named graph (e.g. the German autobahn
-- network) from a start node to a goal node. The user picks edges
-- (multiple choice, so it stays pleasant); pauk sums kilometres
-- DETERMINISTICALLY from the bundled graph. Highscore is the
-- fewest kilometres among successful routes.
ALTER TABLE cards MODIFY COLUMN type ENUM('mc', 'text', 'match', 'quest', 'route') NOT NULL;

CREATE TABLE route_specs (
    card_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
    graph_name VARCHAR(64) NOT NULL,
    start_node VARCHAR(64) NOT NULL,
    goal_node VARCHAR(64) NOT NULL,
    FOREIGN KEY (card_id) REFERENCES cards (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE route_runs (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    card_id BIGINT UNSIGNED NOT NULL,
    success TINYINT(1) NOT NULL,
    km INT NOT NULL,
    finished_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (card_id) REFERENCES cards (id) ON DELETE CASCADE,
    KEY idx_route_runs_card_user (card_id, user_id, success)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

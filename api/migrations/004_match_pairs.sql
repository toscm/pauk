-- Matching cards connect each left item to its right item
-- (e.g. a pronoun to the correct verb form). The shared row id
-- is the correct connection, and quiz mode shuffles the right.
ALTER TABLE cards MODIFY COLUMN type ENUM('mc', 'text', 'match') NOT NULL;

CREATE TABLE match_pairs (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    card_id BIGINT UNSIGNED NOT NULL,
    position INT NOT NULL,
    left_md VARCHAR(512) NOT NULL,
    right_md VARCHAR(512) NOT NULL,
    FOREIGN KEY (card_id) REFERENCES cards (id) ON DELETE CASCADE,
    KEY idx_match_pairs_card (card_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

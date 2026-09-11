-- Recall cards: a self-graded free-recall prompt. The learner reads
-- a (possibly long) question, thinks or writes an answer, then reveals
-- the stored reference answer and decides for themselves whether they
-- were right. No server-side grading; the verdict arrives via
-- POST /cards/{id}/self-grade and is logged to reviews like any answer.
ALTER TABLE cards MODIFY COLUMN type ENUM('mc', 'text', 'match', 'quest', 'route', 'recall') NOT NULL;

CREATE TABLE recall_cards (
    card_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
    answer_md TEXT NOT NULL,
    FOREIGN KEY (card_id) REFERENCES cards (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

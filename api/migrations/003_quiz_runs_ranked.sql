-- Repeat / repeat-wrong runs are practice, not highscores: only
-- ranked runs count toward best-run and top-3. Best is tracked
-- per (dir, total) so n=5 and n=20 have separate leaderboards.
ALTER TABLE quiz_runs ADD COLUMN ranked TINYINT(1) NOT NULL DEFAULT 1;

-- serve the per-(dir, total) leaderboard lookup from an index
-- instead of a filesort
CREATE INDEX idx_quiz_runs_leaderboard
    ON quiz_runs (user_id, dir_id, ranked, total);


<?php

declare(strict_types=1);

namespace Pauk\Repo;

use Pauk\ApiError;

final class QuizRuns
{
    public function __construct(private readonly \PDO $pdo)
    {
    }

    public function start(int $userId, ?int $dirId, int $total): int
    {
        if ($dirId !== null) {
            $stmt = $this->pdo->prepare('SELECT id FROM dirs WHERE id = ? AND user_id = ?');
            $stmt->execute([$dirId, $userId]);
            if ($stmt->fetch() === false) {
                throw new ApiError(404, 'not_found', "Directory $dirId not found");
            }
        }
        $stmt = $this->pdo->prepare(
            'INSERT INTO quiz_runs (user_id, dir_id, total) VALUES (?, ?, ?)'
        );
        $stmt->execute([$userId, $dirId, $total]);
        return (int) $this->pdo->lastInsertId();
    }

    /** @return array<string, mixed> */
    public function finish(int $userId, int $runId, int $correct, int $total): array
    {
        $stmt = $this->pdo->prepare(
            'SELECT id, dir_id, finished_at FROM quiz_runs WHERE id = ? AND user_id = ?'
        );
        $stmt->execute([$runId, $userId]);
        $run = $stmt->fetch();
        if ($run === false) {
            throw new ApiError(404, 'not_found', "Run $runId not found");
        }
        if ($run['finished_at'] !== null) {
            throw new ApiError(409, 'conflict', 'Run already finished');
        }
        if ($correct < 0 || $total < 0 || $correct > $total) {
            throw new ApiError(400, 'validation', 'invalid correct/total');
        }
        $stmt = $this->pdo->prepare(
            'UPDATE quiz_runs SET correct = ?, total = ?, finished_at = NOW() WHERE id = ?'
        );
        $stmt->execute([$correct, $total, $runId]);

        $top = $this->topRuns($userId, $run['dir_id'] === null ? null : (int) $run['dir_id']);
        $rank = null;
        foreach ($top as $i => $t) {
            if ($t['id'] === $runId) {
                $rank = $i + 1;
                break;
            }
        }
        return [
            'id' => $runId,
            'correct' => $correct,
            'total' => $total,
            'rank' => $rank,
            'top' => array_map(
                fn ($t) => [
                    'correct' => $t['correct'],
                    'total' => $t['total'],
                    'finished_at' => str_replace(' ', 'T', $t['finished_at']) . 'Z',
                ],
                $top
            ),
        ];
    }

    /**
     * Top three finished runs for a directory (or the all-cards
     * group when $dirId is null): best score, then larger run,
     * then earlier finish.
     *
     * @return list<array<string, mixed>>
     */
    public function topRuns(int $userId, ?int $dirId): array
    {
        $dirCond = $dirId === null ? 'dir_id IS NULL' : 'dir_id = ?';
        $params = $dirId === null ? [$userId] : [$userId, $dirId];
        $stmt = $this->pdo->prepare(
            "SELECT id, correct, total, finished_at FROM quiz_runs
             WHERE user_id = ? AND $dirCond
               AND finished_at IS NOT NULL AND total > 0
             ORDER BY correct / total DESC, total DESC, finished_at ASC
             LIMIT 3"
        );
        $stmt->execute($params);
        return array_map(
            fn ($r) => [
                'id' => (int) $r['id'],
                'correct' => (int) $r['correct'],
                'total' => (int) $r['total'],
                'finished_at' => $r['finished_at'],
            ],
            $stmt->fetchAll()
        );
    }

    /**
     * Flat quiz-picker listing: every dir with canonical path,
     * transitive card count, run count, and best finished run.
     *
     * @return list<array<string, mixed>>
     */
    public function pickerDirs(int $userId, Dirs $dirs): array
    {
        $stmt = $this->pdo->prepare('SELECT id, name FROM dirs WHERE user_id = ?');
        $stmt->execute([$userId]);
        $all = $stmt->fetchAll();
        $names = [];
        foreach ($all as $row) {
            $names[(int) $row['id']] = $row['name'];
        }
        $stmt = $this->pdo->prepare(
            'SELECT dd.parent_id, dd.child_id FROM dir_dirs dd
             JOIN dirs d ON d.id = dd.parent_id WHERE d.user_id = ?'
        );
        $stmt->execute([$userId]);
        $parents = [];
        foreach ($stmt->fetchAll() as $edge) {
            $parents[(int) $edge['child_id']][] = (int) $edge['parent_id'];
        }
        $paths = [];
        $resolve = function (int $id) use (&$resolve, &$paths, $names, $parents): string {
            if (isset($paths[$id])) {
                return $paths[$id];
            }
            $paths[$id] = $names[$id]; // guard against cycles
            if (!empty($parents[$id])) {
                $candidates = array_map(
                    fn ($p) => $resolve($p) . '/' . $names[$id],
                    $parents[$id]
                );
                sort($candidates);
                $paths[$id] = $candidates[0];
            }
            return $paths[$id];
        };

        $stmt = $this->pdo->prepare(
            'SELECT dir_id, COUNT(*) AS runs FROM quiz_runs
             WHERE user_id = ? AND dir_id IS NOT NULL GROUP BY dir_id'
        );
        $stmt->execute([$userId]);
        $runCounts = [];
        foreach ($stmt->fetchAll() as $row) {
            $runCounts[(int) $row['dir_id']] = (int) $row['runs'];
        }

        $items = [];
        foreach ($names as $id => $name) {
            $top = $this->topRuns($userId, $id);
            $subtree = $dirs->subtreeIds($id);
            $placeholders = implode(',', array_fill(0, count($subtree), '?'));
            $countStmt = $this->pdo->prepare(
                "SELECT COUNT(DISTINCT card_id) FROM dir_cards WHERE dir_id IN ($placeholders)"
            );
            $countStmt->execute($subtree);
            $items[] = [
                'id' => $id,
                'path' => $resolve($id),
                'name' => $name,
                'cards_total' => (int) $countStmt->fetchColumn(),
                'runs' => $runCounts[$id] ?? 0,
                'best' => $top === []
                    ? null
                    : ['correct' => $top[0]['correct'], 'total' => $top[0]['total']],
            ];
        }
        usort($items, fn ($a, $b) => [$b['runs'], $a['path']] <=> [$a['runs'], $b['path']]);
        return $items;
    }
}

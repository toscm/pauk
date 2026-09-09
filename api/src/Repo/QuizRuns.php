<?php

declare(strict_types=1);

namespace Pauk\Repo;

use Pauk\ApiError;

final class QuizRuns
{
    public function __construct(private readonly \PDO $pdo)
    {
    }

    public function start(int $userId, ?int $dirId, int $total, bool $ranked): int
    {
        if ($dirId !== null) {
            $stmt = $this->pdo->prepare('SELECT id FROM dirs WHERE id = ? AND user_id = ?');
            $stmt->execute([$dirId, $userId]);
            if ($stmt->fetch() === false) {
                throw new ApiError(404, 'not_found', "Directory $dirId not found");
            }
        }
        $stmt = $this->pdo->prepare(
            'INSERT INTO quiz_runs (user_id, dir_id, total, ranked) VALUES (?, ?, ?, ?)'
        );
        $stmt->execute([$userId, $dirId, $total, $ranked ? 1 : 0]);
        return (int) $this->pdo->lastInsertId();
    }

    /** Best ranked run for (dir, total), as an accuracy fraction. */
    public function bestForN(int $userId, ?int $dirId, int $total): ?array
    {
        $top = $this->topRuns($userId, $dirId, $total);
        return $top[0] ?? null;
    }

    /** @return array<string, mixed> */
    public function finish(int $userId, int $runId, int $correct, int $total): array
    {
        $stmt = $this->pdo->prepare(
            'SELECT id, dir_id, total, ranked, finished_at
             FROM quiz_runs WHERE id = ? AND user_id = ?'
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

        $ranked = (int) $run['ranked'] === 1;
        $dirId = $run['dir_id'] === null ? null : (int) $run['dir_id'];
        // Only ranked runs have a leaderboard; the leaderboard is
        // per (dir, total) so a repeat of a subset never competes
        // with a full run (and a "1/1" practice run is unranked).
        $top = $ranked ? $this->topRuns($userId, $dirId, (int) $total) : [];
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
            'ranked' => $ranked,
            'rank' => $rank,
            'top' => array_map(fn ($t) => $this->public($t), $top),
        ];
    }

    /**
     * Top three ranked finished runs for (dir, total): best
     * accuracy, ties broken by earlier finish.
     *
     * @return list<array<string, mixed>>
     */
    public function topRuns(int $userId, ?int $dirId, int $total): array
    {
        $dirCond = $dirId === null ? 'dir_id IS NULL' : 'dir_id = ?';
        $params = [$userId, $total];
        if ($dirId !== null) {
            $params[] = $dirId;
        }
        $stmt = $this->pdo->prepare(
            "SELECT id, correct, total, finished_at FROM quiz_runs
             WHERE user_id = ? AND ranked = 1 AND total = ? AND $dirCond
               AND finished_at IS NOT NULL AND total > 0
             ORDER BY correct / total DESC, finished_at ASC
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
     * transitive card count, run count, and best ranked accuracy.
     * Batched — a fixed number of queries regardless of dir count.
     *
     * @return list<array<string, mixed>>
     */
    public function pickerDirs(int $userId): array
    {
        // 1) all dirs
        $stmt = $this->pdo->prepare('SELECT id, name FROM dirs WHERE user_id = ?');
        $stmt->execute([$userId]);
        $names = [];
        foreach ($stmt->fetchAll() as $row) {
            $names[(int) $row['id']] = $row['name'];
        }
        if ($names === []) {
            return [];
        }
        // 2) nesting edges
        $stmt = $this->pdo->prepare(
            'SELECT dd.parent_id, dd.child_id FROM dir_dirs dd
             JOIN dirs d ON d.id = dd.parent_id WHERE d.user_id = ?'
        );
        $stmt->execute([$userId]);
        $children = [];
        $parents = [];
        foreach ($stmt->fetchAll() as $edge) {
            $children[(int) $edge['parent_id']][] = (int) $edge['child_id'];
            $parents[(int) $edge['child_id']][] = (int) $edge['parent_id'];
        }
        // 3) direct card memberships
        $stmt = $this->pdo->prepare(
            'SELECT dc.dir_id, dc.card_id FROM dir_cards dc
             JOIN dirs d ON d.id = dc.dir_id WHERE d.user_id = ?'
        );
        $stmt->execute([$userId]);
        $directCards = [];
        foreach ($stmt->fetchAll() as $row) {
            $directCards[(int) $row['dir_id']][] = (int) $row['card_id'];
        }
        // 4) started-run counts and best ranked accuracy, per dir
        $stmt = $this->pdo->prepare(
            'SELECT dir_id, COUNT(*) AS runs,
                    MAX(CASE WHEN ranked = 1 AND finished_at IS NOT NULL AND total > 0
                             THEN correct / total END) AS best_acc
             FROM quiz_runs WHERE user_id = ? AND dir_id IS NOT NULL
             GROUP BY dir_id'
        );
        $stmt->execute([$userId]);
        $runCounts = [];
        $bestAcc = [];
        foreach ($stmt->fetchAll() as $row) {
            $id = (int) $row['dir_id'];
            $runCounts[$id] = (int) $row['runs'];
            $bestAcc[$id] = $row['best_acc'] === null ? null : (float) $row['best_acc'];
        }

        // transitive card counts, computed in PHP (memoized DFS) so
        // there is no recursive CTE per directory
        $descendantCards = [];
        $resolveCards = function (int $id, array $seen = []) use (
            &$resolveCards, &$descendantCards, $children, $directCards
        ): array {
            if (isset($descendantCards[$id])) {
                return $descendantCards[$id];
            }
            if (isset($seen[$id])) {
                return [];
            }
            $seen[$id] = true;
            $cards = $directCards[$id] ?? [];
            foreach ($children[$id] ?? [] as $child) {
                $cards = array_merge($cards, $resolveCards($child, $seen));
            }
            $unique = array_values(array_unique($cards));
            $descendantCards[$id] = $unique;
            return $unique;
        };

        // canonical (alphabetically first) path per dir
        $paths = [];
        $resolvePath = function (int $id, array $seen = []) use (
            &$resolvePath, &$paths, $names, $parents
        ): string {
            if (isset($paths[$id])) {
                return $paths[$id];
            }
            if (isset($seen[$id]) || empty($parents[$id])) {
                return $names[$id];
            }
            $seen[$id] = true;
            $candidates = [];
            foreach ($parents[$id] as $parent) {
                $candidates[] = $resolvePath($parent, $seen) . '/' . $names[$id];
            }
            sort($candidates);
            $paths[$id] = $candidates[0];
            return $paths[$id];
        };

        $items = [];
        foreach ($names as $id => $name) {
            $best = $bestAcc[$id] ?? null;
            $items[] = [
                'id' => $id,
                'path' => $resolvePath($id),
                'name' => $name,
                'cards_total' => count($resolveCards($id)),
                'runs' => $runCounts[$id] ?? 0,
                'best' => $best === null ? null : ['accuracy' => round($best, 3)],
            ];
        }
        usort($items, fn ($a, $b) => [$b['runs'], $a['path']] <=> [$a['runs'], $b['path']]);
        return $items;
    }

    /** @param array<string, mixed> $t */
    private function public(array $t): array
    {
        return [
            'correct' => $t['correct'],
            'total' => $t['total'],
            'accuracy' => round($t['correct'] / $t['total'], 3),
            'finished_at' => str_replace(' ', 'T', $t['finished_at']) . 'Z',
        ];
    }
}

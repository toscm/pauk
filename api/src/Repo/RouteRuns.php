<?php

declare(strict_types=1);

namespace Pauk\Repo;

use Pauk\ApiError;

final class RouteRuns
{
    public function __construct(private readonly \PDO $pdo)
    {
    }

    /**
     * Record a finished route attempt. Kilometres are computed
     * client-side from the bundled graph (deterministic); we only
     * store them. Highscore is the fewest km among successful runs.
     *
     * @return array<string, mixed>
     */
    public function record(int $userId, int $cardId, bool $success, int $km): array
    {
        $stmt = $this->pdo->prepare(
            "SELECT id FROM cards WHERE id = ? AND user_id = ? AND type = 'route'"
        );
        $stmt->execute([$cardId, $userId]);
        if ($stmt->fetch() === false) {
            throw new ApiError(404, 'not_found', "Route $cardId not found");
        }
        if ($km < 0) {
            throw new ApiError(400, 'validation', 'km must be >= 0');
        }
        $this->pdo->beginTransaction();
        try {
            $stmt = $this->pdo->prepare(
                'INSERT INTO reviews (card_id, user_id, was_correct) VALUES (?, ?, ?)'
            );
            $stmt->execute([$cardId, $userId, $success ? 1 : 0]);
            $stmt = $this->pdo->prepare(
                'INSERT INTO route_runs (user_id, card_id, success, km) VALUES (?, ?, ?, ?)'
            );
            $stmt->execute([$userId, $cardId, $success ? 1 : 0, $km]);
            $runId = (int) $this->pdo->lastInsertId();
            $this->pdo->commit();
        } catch (\Throwable $e) {
            $this->pdo->rollBack();
            throw $e;
        }

        $top = $this->topRuns($userId, $cardId);
        $rank = null;
        foreach ($top as $i => $t) {
            if ($t['id'] === $runId) {
                $rank = $i + 1;
                break;
            }
        }
        return [
            'success' => $success,
            'km' => $km,
            'best_km' => $top[0]['km'] ?? null,
            'rank' => $rank,
            'top' => array_map(
                fn ($t) => [
                    'km' => $t['km'],
                    'finished_at' => str_replace(' ', 'T', $t['finished_at']) . 'Z',
                ],
                $top
            ),
        ];
    }

    /** @return list<array<string, mixed>> */
    public function topRuns(int $userId, int $cardId): array
    {
        $stmt = $this->pdo->prepare(
            'SELECT id, km, finished_at FROM route_runs
             WHERE user_id = ? AND card_id = ? AND success = 1
             ORDER BY km ASC, finished_at ASC LIMIT 3'
        );
        $stmt->execute([$userId, $cardId]);
        return array_map(
            fn ($r) => ['id' => (int) $r['id'], 'km' => (int) $r['km'], 'finished_at' => $r['finished_at']],
            $stmt->fetchAll()
        );
    }
}

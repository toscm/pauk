<?php

declare(strict_types=1);

namespace Pauk\Repo;

use Pauk\ApiError;

final class QuestRuns
{
    public function __construct(private readonly \PDO $pdo)
    {
    }

    /**
     * Record a finished quest attempt: log it to reviews (so quests
     * feed the weighted selection and stats) and to quest_runs (for
     * the fewest-messages highscore).
     *
     * @return array<string, mixed>
     */
    public function record(int $userId, int $cardId, bool $success, int $messagesUsed): array
    {
        $stmt = $this->pdo->prepare(
            "SELECT id FROM cards WHERE id = ? AND user_id = ? AND type = 'quest'"
        );
        $stmt->execute([$cardId, $userId]);
        if ($stmt->fetch() === false) {
            throw new ApiError(404, 'not_found', "Quest $cardId not found");
        }
        if ($messagesUsed < 0) {
            throw new ApiError(400, 'validation', 'messages_used must be >= 0');
        }
        $this->pdo->beginTransaction();
        try {
            $stmt = $this->pdo->prepare(
                'INSERT INTO reviews (card_id, user_id, was_correct) VALUES (?, ?, ?)'
            );
            $stmt->execute([$cardId, $userId, $success ? 1 : 0]);
            $stmt = $this->pdo->prepare(
                'INSERT INTO quest_runs (user_id, card_id, success, messages_used)
                 VALUES (?, ?, ?, ?)'
            );
            $stmt->execute([$userId, $cardId, $success ? 1 : 0, $messagesUsed]);
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
            'messages_used' => $messagesUsed,
            'best_messages' => $top[0]['messages_used'] ?? null,
            'rank' => $rank,
            'top' => array_map(
                fn ($t) => [
                    'messages_used' => $t['messages_used'],
                    'finished_at' => str_replace(' ', 'T', $t['finished_at']) . 'Z',
                ],
                $top
            ),
        ];
    }

    /**
     * Best three successful runs for a quest: fewest messages, ties
     * broken by earlier finish.
     *
     * @return list<array<string, mixed>>
     */
    public function topRuns(int $userId, int $cardId): array
    {
        $stmt = $this->pdo->prepare(
            'SELECT id, messages_used, finished_at FROM quest_runs
             WHERE user_id = ? AND card_id = ? AND success = 1
             ORDER BY messages_used ASC, finished_at ASC
             LIMIT 3'
        );
        $stmt->execute([$userId, $cardId]);
        return array_map(
            fn ($r) => [
                'id' => (int) $r['id'],
                'messages_used' => (int) $r['messages_used'],
                'finished_at' => $r['finished_at'],
            ],
            $stmt->fetchAll()
        );
    }
}

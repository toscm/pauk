<?php

declare(strict_types=1);

namespace Pauk\Repo;

final class Stats
{
    public function __construct(private readonly \PDO $pdo)
    {
    }

    /**
     * Per-card and summary statistics for a candidate set
     * (docs/api.md, "Statistics").
     *
     * @param list<int> $cardIds
     * @return array{summary: array<string, mixed>, items: list<array<string, mixed>>}
     */
    public function forCards(int $userId, array $cardIds): array
    {
        $empty = [
            'summary' => [
                'cards' => count($cardIds),
                'asked_cards' => 0,
                'reviews' => 0,
                'correct' => 0,
                'accuracy' => null,
            ],
            'items' => [],
        ];
        if ($cardIds === []) {
            return $empty;
        }
        $placeholders = implode(',', array_fill(0, count($cardIds), '?'));
        $stmt = $this->pdo->prepare(
            "SELECT r.card_id, c.question_md,
                    COUNT(*) AS asked,
                    SUM(r.was_correct) AS correct,
                    MAX(r.answered_at) AS last_answered
             FROM reviews r
             JOIN cards c ON c.id = r.card_id
             WHERE r.user_id = ? AND r.card_id IN ($placeholders)
             GROUP BY r.card_id, c.question_md"
        );
        $stmt->execute([$userId, ...$cardIds]);
        $items = [];
        $reviews = 0;
        $correctTotal = 0;
        foreach ($stmt->fetchAll() as $row) {
            $asked = (int) $row['asked'];
            $correct = (int) $row['correct'];
            $reviews += $asked;
            $correctTotal += $correct;
            $items[] = [
                'id' => (int) $row['card_id'],
                'question_md' => $row['question_md'],
                'asked' => $asked,
                'correct' => $correct,
                'accuracy' => round($correct / $asked, 3),
                'last_answered' => str_replace(' ', 'T', $row['last_answered']) . 'Z',
            ];
        }
        usort(
            $items,
            fn ($a, $b) => [$a['accuracy'], $b['last_answered']] <=> [$b['accuracy'], $a['last_answered']]
        );
        return [
            'summary' => [
                'cards' => count($cardIds),
                'asked_cards' => count($items),
                'reviews' => $reviews,
                'correct' => $correctTotal,
                'accuracy' => $reviews === 0 ? null : round($correctTotal / $reviews, 3),
            ],
            'items' => array_slice($items, 0, 200),
        ];
    }
}

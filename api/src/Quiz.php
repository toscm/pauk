<?php

declare(strict_types=1);

namespace Pauk;

final class Quiz
{
    public function __construct(private readonly \PDO $pdo)
    {
    }

    /**
     * Weight formula per docs/api.md, "Quiz selection":
     *   error_rate = (wrong + 1) / (asked + 2)
     *   staleness  = 1 if never asked else min(days, 30) / 30
     *   weight     = error_rate * (1 + staleness)
     */
    public static function weight(int $asked, int $wrong, ?float $days): float
    {
        $errorRate = ($wrong + 1) / ($asked + 2);
        $staleness = $days === null ? 1.0 : min($days, 30.0) / 30.0;
        return $errorRate * (1 + $staleness);
    }

    /**
     * Weighted sample without replacement: up to $n keys of
     * $weights, higher weight = more likely to be drawn early.
     *
     * @param array<int, float> $weights
     * @return list<int>
     */
    public static function sample(array $weights, int $n, \Random\Randomizer $rng): array
    {
        $picked = [];
        while (count($picked) < $n && $weights !== []) {
            $total = array_sum($weights);
            $roll = $rng->getFloat(0, $total);
            $acc = 0.0;
            $chosen = array_key_last($weights);
            foreach ($weights as $id => $weight) {
                $acc += $weight;
                if ($roll <= $acc) {
                    $chosen = $id;
                    break;
                }
            }
            $picked[] = $chosen;
            unset($weights[$chosen]);
        }
        return $picked;
    }

    /**
     * Select up to $n card ids from the candidates, weighted by
     * the user's review history.
     *
     * @param list<int> $candidateIds
     * @return list<int>
     */
    public function select(int $userId, array $candidateIds, int $n, ?int $seed = null): array
    {
        if ($candidateIds === [] || $n <= 0) {
            return [];
        }
        $stats = $this->stats($userId, $candidateIds);
        $weights = [];
        foreach ($candidateIds as $id) {
            $weights[$id] = self::weight(
                $stats[$id]['asked'] ?? 0,
                $stats[$id]['wrong'] ?? 0,
                $stats[$id]['days'] ?? null,
            );
        }
        $rng = $seed === null
            ? new \Random\Randomizer()
            : new \Random\Randomizer(new \Random\Engine\Mt19937($seed));
        return self::sample($weights, $n, $rng);
    }

    /** @param list<int> $cardIds
     *  @return array<int, array{asked: int, wrong: int, days: ?float}> */
    private function stats(int $userId, array $cardIds): array
    {
        $placeholders = implode(',', array_fill(0, count($cardIds), '?'));
        $stmt = $this->pdo->prepare(
            "SELECT card_id,
                    COUNT(*) AS asked,
                    SUM(was_correct = 0) AS wrong,
                    TIMESTAMPDIFF(SECOND, MAX(answered_at), NOW()) / 86400 AS days
             FROM reviews
             WHERE user_id = ? AND card_id IN ($placeholders)
             GROUP BY card_id"
        );
        $stmt->execute([$userId, ...$cardIds]);
        $stats = [];
        foreach ($stmt->fetchAll() as $row) {
            $stats[(int) $row['card_id']] = [
                'asked' => (int) $row['asked'],
                'wrong' => (int) $row['wrong'],
                'days' => $row['days'] === null ? null : (float) $row['days'],
            ];
        }
        return $stats;
    }
}

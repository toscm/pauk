<?php

declare(strict_types=1);

namespace Pauk\Repo;

use Pauk\Knowledge\MemoryModel;
use Pauk\Knowledge\Time;

/**
 * Profile summary and "what to practise next" (docs/tutor.md 4.7,
 * 4.9). Selection is server-side so every teacher behaves alike.
 */
final class Profile
{
    private const TARGET = 0.9;

    public function __construct(
        private readonly \PDO $pdo,
        private readonly Items $items,
    ) {
    }

    /** @param array<string, mixed> $filters */
    public function summary(int $userId, array $filters): array
    {
        $now = Time::now();
        $byMastery = array_fill_keys(['0', '1', '2', '3', '4', '5'], 0);
        $weighted = 0.0;
        $weights = 0.0;
        $due = 0;
        $lapses = [];
        $rows = $this->items->rows($userId, $filters);
        foreach ($rows as $row) {
            $state = Items::stateView($row, $now);
            $mastery = $state['mastery'] ?? 0;
            $byMastery[(string) $mastery]++;
            $weights += (int) $row['priority'];
            $weighted += (int) $row['priority'] * ($state['recall'] ?? 0.0);
            if ($state !== null && $state['recall'] !== null && $state['recall'] < self::TARGET && $state['status'] !== 'suspended') {
                $due++;
            }
            if ($state !== null && $state['lapses'] > 0) {
                $lapses[] = ['ref' => $row['space'] . '/' . $row['key'], 'label_md' => $row['label_md'], 'lapses' => $state['lapses']];
            }
        }
        usort($lapses, fn ($a, $b) => $b['lapses'] <=> $a['lapses'] ?: strcmp($a['ref'], $b['ref']));
        return [
            'items' => count($rows),
            'by_mastery' => (object) $byMastery,   // keys 0..5 would otherwise encode as a list
            'coverage' => $weights > 0 ? round($weighted / $weights, 3) : null,
            'due' => $due,
            'most_lapses' => array_slice($lapses, 0, 5),
        ];
    }

    /**
     * @param array<string, mixed> $filters
     * @return array{review: list<array<string, mixed>>, new: list<array<string, mixed>>}
     */
    public function next(int $userId, array $filters, int $n, int $newLimit): array
    {
        $now = Time::now();
        $rows = $this->items->rows($userId, $filters);

        // mastery of every item the user has a state for (prerequisites
        // may lie outside the requested subject)
        $stmt = $this->pdo->prepare('SELECT item_id, stability, best_mode FROM item_states WHERE user_id = ?');
        $stmt->execute([$userId]);
        $mastery = [];
        foreach ($stmt->fetchAll() as $s) {
            $mastery[(int) $s['item_id']] = MemoryModel::mastery($s['stability'] === null ? null : (float) $s['stability'], $s['best_mode']);
        }
        $stmt = $this->pdo->prepare(
            "SELECT l.from_id, l.to_id FROM item_links l JOIN items i ON i.id = l.from_id
             JOIN items t ON t.id = l.to_id
             WHERE l.rel = 'requires' AND i.user_id = ? AND t.archived_at IS NULL"
        );
        $stmt->execute([$userId]);
        $requires = [];
        foreach ($stmt->fetchAll() as $l) {
            $requires[(int) $l['from_id']][] = (int) $l['to_id'];
        }

        $review = [];
        $new = [];
        foreach ($rows as $row) {
            $state = Items::stateView($row, $now);
            if (($state['status'] ?? 'active') === 'suspended') {
                continue;
            }
            $focus = ($state['status'] ?? null) === 'focus' ? 2 : 1;
            $priority = (int) $row['priority'];
            if ($state !== null && $state['recall'] !== null) {
                $target = $state['lapses'] >= 2 ? 0.95 : self::TARGET;
                if ($state['recall'] < $target) {
                    $review[] = [
                        'score' => ($target - $state['recall']) * (0.5 + $priority / 100) * $focus,
                        'entry' => $this->entry($row, $state, sprintf('due: R=%.2f', $state['recall'])
                            . ($state['lapses'] >= 2 ? ", {$state['lapses']} lapses" : '')
                            . ($focus === 2 ? ', focus' : '')),
                    ];
                }
                continue;
            }
            $blocked = array_filter($requires[(int) $row['id']] ?? [], fn ($pre) => ($mastery[$pre] ?? 0) < 3);
            if ($blocked !== []) {
                continue;
            }
            $level = $row['level'] === null ? null : (int) $row['level'];
            $new[] = [
                'sort' => [-$priority * $focus, $level ?? 99, $row['key']],
                'entry' => $this->entry($row, $state, "new: priority $priority"
                    . ($level === null ? '' : ", level $level") . ($focus === 2 ? ', focus' : '')),
            ];
        }
        usort($review, fn ($a, $b) => $b['score'] <=> $a['score']);
        usort($new, fn ($a, $b) => $a['sort'] <=> $b['sort']);
        return [
            'review' => array_map(fn ($r) => $r['entry'], array_slice($review, 0, $n)),
            'new' => array_map(fn ($r) => $r['entry'], array_slice($new, 0, min($n, $newLimit))),
        ];
    }

    /**
     * @param array<string, mixed> $row
     * @param array<string, mixed>|null $state
     * @return array<string, mixed>
     */
    private function entry(array $row, ?array $state, string $reason): array
    {
        return [
            'ref' => $row['space'] . '/' . $row['key'],
            'kind' => $row['kind'],
            'label_md' => $row['label_md'],
            'gloss_md' => $row['gloss_md'],
            'priority' => (int) $row['priority'],
            'level' => $row['level'] === null ? null : (int) $row['level'],
            'state' => $state,
            'reason' => $reason,
        ];
    }
}

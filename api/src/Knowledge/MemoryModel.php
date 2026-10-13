<?php

declare(strict_types=1);

namespace Pauk\Knowledge;

/**
 * The memory model, v1 (docs/tutor.md 4.6): a pure function from
 * (state, event) to state. States are a cache of this function
 * folded over the interaction log in (occurred_at, id) order, so
 * a new model version only needs a rebuild.
 *
 * Times are UNIX seconds (float, millisecond precision).
 */
final class MemoryModel
{
    public const VERSION = 'pauk-mm@1';

    public const MODES = ['introduce', 'recognize', 'recall', 'produce', 'explain', 'self_report'];

    public const OUTCOMES = ['fail', 'hard', 'good', 'easy'];

    private const MODE_FACTOR = [
        'recognize' => 0.6, 'recall' => 1.0, 'produce' => 1.2, 'explain' => 1.0, 'self_report' => 0.5,
    ];

    /** Strength order for best_mode; self_report never counts as a demonstration. */
    private const MODE_RANK = ['recognize' => 1, 'recall' => 2, 'explain' => 2, 'produce' => 3];

    private const FIRST_S = ['hard' => 1.0, 'good' => 3.0, 'easy' => 8.0];
    private const FIRST_D = ['fail' => 7.0, 'hard' => 6.0, 'good' => 5.0, 'easy' => 3.0];
    private const GROWTH_K = ['hard' => 4.0, 'good' => 10.0, 'easy' => 16.0];
    private const D_DELTA = ['fail' => 1.0, 'hard' => 0.5, 'good' => 0.0, 'easy' => -0.5];
    private const MIN_S = 0.2;

    /**
     * @param array{stability: float, difficulty: float, first_seen_at: float,
     *              last_seen_at: float, reps: int, lapses: int, best_mode: ?string}|null $state
     * @return array{stability: float, difficulty: float, first_seen_at: float,
     *               last_seen_at: float, reps: int, lapses: int, best_mode: ?string}
     */
    public static function step(?array $state, string $mode, ?string $outcome, float $at): array
    {
        if ($mode === 'introduce') {
            // presenting an item tests nothing: it creates a state, but
            // never changes an existing one (that would fake recency)
            return $state ?? [
                'stability' => self::MIN_S, 'difficulty' => 5.0,
                'first_seen_at' => $at, 'last_seen_at' => $at,
                'reps' => 0, 'lapses' => 0, 'best_mode' => null,
            ];
        }
        if ($outcome === null) {
            throw new \InvalidArgumentException("mode $mode needs an outcome");
        }
        $m = self::MODE_FACTOR[$mode];
        $success = $outcome !== 'fail';

        if ($state === null) {
            $s = $success ? $m * self::FIRST_S[$outcome] : self::MIN_S;
            $d = self::FIRST_D[$outcome];
            $state = [
                'stability' => $s, 'difficulty' => $d,
                'first_seen_at' => $at, 'last_seen_at' => $at,
                'reps' => 1, 'lapses' => $success ? 0 : 1,
                'best_mode' => null,
            ];
        } else {
            $s = $state['stability'];
            $d = $state['difficulty'];
            $r = self::recall($s, max(0.0, $at - $state['last_seen_at']) / 86400);
            if ($success) {
                $growth = 1 + $m * self::GROWTH_K[$outcome] * ((11 - $d) / 10)
                    * $s ** -0.15 * (exp(2 * (1 - $r)) - 1);
                $s = $s * $growth;
            } else {
                $s = max(self::MIN_S, min($s / 2, 0.5 + 0.1 * $s));
                $state['lapses']++;
            }
            $d = 0.9 * ($d + self::D_DELTA[$outcome]) + 0.1 * 5;
            $state['stability'] = $s;
            $state['difficulty'] = max(1.0, min(10.0, $d));
            $state['last_seen_at'] = max($state['last_seen_at'], $at);
            $state['reps']++;
        }
        if ($success && isset(self::MODE_RANK[$mode])) {
            $best = $state['best_mode'];
            if ($best === null || self::MODE_RANK[$mode] > self::MODE_RANK[$best]) {
                $state['best_mode'] = $mode;
            }
        }
        return $state;
    }

    /** Recall probability after $days with stability $s: R(S) = 0.9. */
    public static function recall(float $s, float $days): float
    {
        return 1 / (1 + $days / (9 * $s));
    }

    /**
     * Mastery level 0..5 (docs/tutor.md 4.7). 1 = seen but never
     * answered correctly (best_mode null) or very unstable.
     */
    public static function mastery(?float $stability, ?string $bestMode): int
    {
        if ($stability === null) {
            return 0;
        }
        if ($bestMode === null || $stability < 0.5) {
            return 1;
        }
        if ($stability < 3) {
            return 2;
        }
        if ($stability < 21) {
            return 3;
        }
        if ($stability >= 90 && self::MODE_RANK[$bestMode] >= 2) {
            return 5;
        }
        return 4;
    }

    /** A hinted answer counts at most as hard. */
    public static function capHinted(?string $outcome, bool $hinted): ?string
    {
        if ($hinted && ($outcome === 'good' || $outcome === 'easy')) {
            return 'hard';
        }
        return $outcome;
    }
}

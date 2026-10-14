<?php

declare(strict_types=1);

namespace Pauk\Knowledge;

/**
 * Calibration of the memory model against an interaction log
 * (bin/calibrate.php, docs/development.md): replay the events, predict
 * the recall probability before every test of an item that already has
 * a state, and score the predictions against the observed outcomes.
 * Pure functions, no I/O.
 *
 * An event is ['item' => string, 'mode' => string, 'outcome' => ?string,
 * 'hinted' => bool (optional), 'at' => float UNIX seconds].
 * A prediction is ['p' => float, 'y' => 0|1, 'gap_days' => float, 'mode' => string].
 */
final class Calibration
{
    private const EPS = 1e-6;

    /**
     * Replay $events in time order (stable, so ties keep their given
     * order) and return one prediction per scorable event: a test
     * (not introduce, not self_report) of an item with a prior state.
     * Which events are scorable does not depend on $params, so the
     * prediction lists of two parameter sets align index by index.
     *
     * @param list<array<string, mixed>> $events
     * @param array<string, mixed>|null $params default MemoryModel::PARAMS
     * @return list<array{p: float, y: int, gap_days: float, mode: string}>
     */
    public static function predictions(array $events, ?array $params = null): array
    {
        $params ??= MemoryModel::PARAMS;
        usort($events, fn ($a, $b) => $a['at'] <=> $b['at']);
        $states = [];
        $out = [];
        foreach ($events as $e) {
            $outcome = MemoryModel::capHinted($e['outcome'], (bool) ($e['hinted'] ?? false));
            if ($e['mode'] !== 'introduce' && $outcome === null) {
                continue;   // voided by an amendment
            }
            $state = $states[$e['item']] ?? null;
            if ($state !== null && $e['mode'] !== 'introduce' && $e['mode'] !== 'self_report') {
                $gap = max(0.0, $e['at'] - $state['last_seen_at']) / 86400;
                $out[] = [
                    'p' => MemoryModel::recall($state['stability'], $gap, $params['curve']),
                    'y' => $outcome === 'fail' ? 0 : 1,
                    'gap_days' => $gap,
                    'mode' => $e['mode'],
                ];
            }
            $states[$e['item']] = MemoryModel::step($state, $e['mode'], $outcome, $e['at'], $params);
        }
        return $out;
    }

    /** @param list<array{p: float, y: int}> $preds */
    public static function logLoss(array $preds): float
    {
        if ($preds === []) {
            return NAN;
        }
        $sum = 0.0;
        foreach ($preds as $x) {
            $sum += self::pointLogLoss($x['p'], $x['y']);
        }
        return $sum / count($preds);
    }

    /** @param list<array{p: float, y: int}> $preds */
    public static function brier(array $preds): float
    {
        if ($preds === []) {
            return NAN;
        }
        $sum = 0.0;
        foreach ($preds as $x) {
            $sum += ($x['p'] - $x['y']) ** 2;
        }
        return $sum / count($preds);
    }

    /** @param list<array{y: int}> $preds */
    public static function successRate(array $preds): float
    {
        return $preds === [] ? NAN : array_sum(array_column($preds, 'y')) / count($preds);
    }

    /**
     * The same predictions with p replaced by the observed success rate:
     * the trivial baseline a useful model has to beat. It is fitted on
     * the very data it is scored on, so it is a slightly optimistic bar.
     *
     * @param list<array{p: float, y: int}> $preds
     * @return list<array{p: float, y: int}>
     */
    public static function baseline(array $preds): array
    {
        $rate = self::successRate($preds);
        return array_map(fn ($x) => ['p' => $rate] + $x, $preds);
    }

    /**
     * Reliability table: $bins equal-width bins of predicted p over
     * [0, 1] (p = 1 falls into the last bin), each with its count, mean
     * prediction and observed success rate (null when empty).
     *
     * @param list<array{p: float, y: int}> $preds
     * @return list<array{lo: float, hi: float, n: int, mean_p: ?float, observed: ?float}>
     */
    public static function reliability(array $preds, int $bins = 10): array
    {
        $acc = array_fill(0, $bins, ['n' => 0, 'p' => 0.0, 'y' => 0]);
        foreach ($preds as $x) {
            $i = min($bins - 1, max(0, (int) floor($x['p'] * $bins)));
            $acc[$i]['n']++;
            $acc[$i]['p'] += $x['p'];
            $acc[$i]['y'] += $x['y'];
        }
        $table = [];
        foreach ($acc as $i => $b) {
            $table[] = [
                'lo' => $i / $bins, 'hi' => ($i + 1) / $bins, 'n' => $b['n'],
                'mean_p' => $b['n'] > 0 ? $b['p'] / $b['n'] : null,
                'observed' => $b['n'] > 0 ? $b['y'] / $b['n'] : null,
            ];
        }
        return $table;
    }

    /**
     * Paired comparison of two aligned prediction lists: mean per-event
     * log-loss difference (B minus A; negative = B better) and its
     * standard error. A difference within about two standard errors of
     * zero is not evidence for either.
     *
     * @param list<array{p: float, y: int}> $a
     * @param list<array{p: float, y: int}> $b
     * @return array{diff: float, se: float}
     */
    public static function pairedLogLossDiff(array $a, array $b): array
    {
        $n = count($a);
        if ($n !== count($b)) {
            throw new \InvalidArgumentException('prediction lists are not aligned');
        }
        if ($n < 2) {
            return ['diff' => NAN, 'se' => NAN];
        }
        $d = [];
        for ($i = 0; $i < $n; $i++) {
            $d[] = self::pointLogLoss($b[$i]['p'], $b[$i]['y']) - self::pointLogLoss($a[$i]['p'], $a[$i]['y']);
        }
        $mean = array_sum($d) / $n;
        $var = array_sum(array_map(fn ($x) => ($x - $mean) ** 2, $d)) / ($n - 1);
        return ['diff' => $mean, 'se' => sqrt($var / $n)];
    }

    /**
     * Alternative parameter sets: v1 with first_s, growth_k and the
     * curve each scaled by 0.5, 1 or 2 (27 sets, v1 included).
     *
     * @return array<string, array<string, mixed>> label => params
     */
    public static function grid(): array
    {
        $grid = [];
        foreach ([0.5, 1.0, 2.0] as $fs) {
            foreach ([0.5, 1.0, 2.0] as $gk) {
                foreach ([0.5, 1.0, 2.0] as $cv) {
                    $p = MemoryModel::PARAMS;
                    $p['first_s'] = array_map(fn ($v) => $v * $fs, $p['first_s']);
                    $p['growth_k'] = array_map(fn ($v) => $v * $gk, $p['growth_k']);
                    $p['curve'] *= $cv;
                    $grid[sprintf('first_s x%s, growth_k x%s, curve x%s', $fs, $gk, $cv)] = $p;
                }
            }
        }
        return $grid;
    }

    /**
     * Events from a pauk export (JSONL lines, docs/tutor.md 6). Item
     * identity is the current ref; the latest amendment per origin
     * overrides the outcome, as in the server-side replay.
     *
     * @param iterable<string> $lines
     * @return list<array<string, mixed>>
     */
    public static function eventsFromExport(iterable $lines, bool $includeSimulation = false): array
    {
        $events = [];
        foreach ($lines as $line) {
            $line = trim($line);
            if ($line === '') {
                continue;
            }
            $row = json_decode($line, true, 512, JSON_THROW_ON_ERROR);
            if (($row['type'] ?? null) !== 'interaction') {
                continue;
            }
            if (!$includeSimulation && ($row['source'] ?? null) === 'simulation') {
                continue;
            }
            $amended = [];
            foreach ($row['amendments'] ?? [] as $a) {
                $amended[$a['origin']] = $a['outcome'];
            }
            $at = Time::parseIso($row['occurred_at'], 'occurred_at');
            foreach ($row['items'] ?? [] as $item) {
                $origin = $item['origin'] ?? $item['ref'];
                $events[] = [
                    'item' => $item['ref'],
                    'mode' => $row['mode'],
                    'outcome' => array_key_exists($origin, $amended) ? $amended[$origin] : $item['outcome'],
                    'hinted' => (bool) ($row['hinted'] ?? false),
                    'at' => $at,
                ];
            }
        }
        return $events;
    }

    private static function pointLogLoss(float $p, int $y): float
    {
        $p = min(1 - self::EPS, max(self::EPS, $p));
        return $y === 1 ? -log($p) : -log(1 - $p);
    }
}

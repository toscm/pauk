<?php

declare(strict_types=1);

// Score the memory model against a recorded log (docs/development.md,
// "Calibrating the memory model"). Read-only.
//
// Usage: php bin/calibrate.php [--source=log|reviews] [--export=FILE]
//                              [--min-gap-hours=H] [--bins=N] [--top=N]
//   --source=log      the interaction log (default; env PAUK_DB_* as for the API)
//   --source=reviews  the legacy card reviews table (good/fail only)
//   --export=FILE     a pauk export JSONL instead of a database
//   --min-gap-hours   score only predictions made at least H hours after
//                     the previous event of the item (all events are replayed)
require dirname(__DIR__) . '/vendor/autoload.php';

use Pauk\Knowledge\Calibration;
use Pauk\Knowledge\MemoryModel;
use Pauk\Knowledge\Time;
use Pauk\Repo\Interactions;

$opts = getopt('', ['source:', 'export:', 'min-gap-hours:', 'bins:', 'top:', 'help']);
if (isset($opts['help'])) {
    fwrite(STDOUT, "Usage: php bin/calibrate.php [--source=log|reviews] [--export=FILE] [--min-gap-hours=H] [--bins=N] [--top=N]\n");
    exit(0);
}
$source = $opts['source'] ?? 'log';
$minGap = (float) ($opts['min-gap-hours'] ?? 0) / 24;
$bins = (int) ($opts['bins'] ?? 10);
$top = (int) ($opts['top'] ?? 5);

if (isset($opts['export'])) {
    $file = new SplFileObject($opts['export']);
    $events = Calibration::eventsFromExport($file);
    $label = 'export ' . basename($opts['export']);
} else {
    $pdo = Pauk\Db::connect();
    $events = [];
    if ($source === 'log') {
        $rows = $pdo->query(
            "SELECT i.user_id, ii.item_id, i.mode, i.hinted, i.occurred_at, ii.outcome,
                    (SELECT COUNT(*) FROM interaction_amendments a
                     WHERE a.interaction_id = ii.interaction_id AND a.item_id = ii.origin_item_id) AS amended,
                    (SELECT a.outcome FROM interaction_amendments a
                     WHERE a.interaction_id = ii.interaction_id AND a.item_id = ii.origin_item_id
                     ORDER BY a.id DESC LIMIT 1) AS amended_outcome
             FROM interaction_items ii JOIN interactions i ON i.id = ii.interaction_id
             WHERE i.source <> 'simulation'
             ORDER BY i.occurred_at, i.id"
        );
        foreach ($rows as $r) {
            $events[] = [
                'item' => $r['user_id'] . ':' . $r['item_id'],
                'mode' => $r['mode'],
                'outcome' => (int) $r['amended'] > 0 ? $r['amended_outcome'] : $r['outcome'],
                'hinted' => (bool) $r['hinted'],
                'at' => Time::fromDb($r['occurred_at']),
            ];
        }
    } elseif ($source === 'reviews') {
        $rows = $pdo->query(
            'SELECT r.user_id, r.card_id, c.type, r.was_correct, r.answered_at
             FROM reviews r JOIN cards c ON c.id = r.card_id ORDER BY r.answered_at, r.id'
        );
        foreach ($rows as $r) {
            $events[] = [
                'item' => $r['user_id'] . ':' . $r['card_id'],
                'mode' => Interactions::cardMode($r['type']),
                'outcome' => $r['was_correct'] ? 'good' : 'fail',
                'at' => Time::fromDb($r['answered_at']),
            ];
        }
    } else {
        fwrite(STDERR, "--source must be log or reviews\n");
        exit(1);
    }
    $label = "$source table of database " . Pauk\Env::get('PAUK_DB_NAME');
}

$keep = fn (array $preds) => array_values(array_filter($preds, fn ($x) => $x['gap_days'] >= $minGap));
$f = fn (float $x) => is_nan($x) ? '-' : sprintf('%.3f', $x);

$tests = array_filter($events, fn ($e) => $e['mode'] !== 'introduce' && $e['outcome'] !== null);
$all = Calibration::predictions($events);
$v1 = $keep($all);

printf("source: %s\nmodel: %s\n", $label, MemoryModel::VERSION);
printf(
    "events: %d (%d tests) on %d items; %d tests follow an earlier event of the item; scored%s: %d\n",
    count($events), count($tests), count(array_unique(array_column($events, 'item'))), count($all),
    $minGap > 0 ? sprintf(' (gap >= %s h)', $minGap * 24) : '', count($v1),
);

echo "\nscored predictions by gap since the item's previous event:\n";
$buckets = ['< 1 h' => [0, 1 / 24], '1 h - 1 d' => [1 / 24, 1], '1 - 7 d' => [1, 7], '>= 7 d' => [7, INF]];
foreach ($buckets as $name => [$lo, $hi]) {
    $b = array_values(array_filter($v1, fn ($x) => $x['gap_days'] >= $lo && $x['gap_days'] < $hi));
    printf("  %-9s  n %4d   observed %s   mean predicted %s\n", $name, count($b), $f(Calibration::successRate($b)),
        $b === [] ? '-' : $f(array_sum(array_column($b, 'p')) / count($b)));
}

if ($v1 === []) {
    echo "\nnothing to score\n";
    exit(0);
}
$base = Calibration::baseline($v1);
printf("\n%-40s  log loss  Brier\n", '');
printf("%-40s  %8s  %5s\n", MemoryModel::VERSION . ' (current constants)', $f(Calibration::logLoss($v1)), $f(Calibration::brier($v1)));
printf("%-40s  %8s  %5s\n", sprintf('constant p = %.3f (observed rate)', Calibration::successRate($v1)),
    $f(Calibration::logLoss($base)), $f(Calibration::brier($base)));

echo "\nreliability of " . MemoryModel::VERSION . ":\n  predicted       n   mean p  observed\n";
foreach (Calibration::reliability($v1, $bins) as $row) {
    if ($row['n'] === 0) {
        continue;
    }
    printf("  %.2f - %.2f  %5d   %s   %s\n", $row['lo'], $row['hi'], $row['n'], $f($row['mean_p']), $f($row['observed']));
}

$results = [];
foreach (Calibration::grid() as $name => $params) {
    $preds = $keep(Calibration::predictions($events, $params));
    $results[$name] = ['ll' => Calibration::logLoss($preds), 'brier' => Calibration::brier($preds),
        'cmp' => Calibration::pairedLogLossDiff($v1, $preds)];
}
uasort($results, fn ($a, $b) => $a['ll'] <=> $b['ll']);
printf("\ngrid (v1 with first_s, growth_k, curve scaled), best %d by log loss:\n", $top);
printf("  %-40s  log loss  Brier  vs v1 (+- 1 se)\n", '');
foreach (array_slice($results, 0, $top, true) as $name => $r) {
    printf("  %-40s  %8s  %5s  %+.3f (+- %.3f)\n", $name, $f($r['ll']), $f($r['brier']), $r['cmp']['diff'], $r['cmp']['se']);
}

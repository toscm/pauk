<?php

declare(strict_types=1);

namespace Pauk\Tests\unit;

use Pauk\Knowledge\Calibration;
use Pauk\Knowledge\MemoryModel;
use PHPUnit\Framework\TestCase;

final class CalibrationTest extends TestCase
{
    private const DAY = 86400.0;

    public function testLogLossAndBrier(): void
    {
        $preds = [['p' => 0.8, 'y' => 1], ['p' => 0.8, 'y' => 0], ['p' => 0.5, 'y' => 1]];
        $this->assertEqualsWithDelta((-log(0.8) - log(0.2) - log(0.5)) / 3, Calibration::logLoss($preds), 1e-12);
        $this->assertEqualsWithDelta((0.04 + 0.64 + 0.25) / 3, Calibration::brier($preds), 1e-12);
    }

    public function testLogLossClipsCertainMistakes(): void
    {
        $loss = Calibration::logLoss([['p' => 1.0, 'y' => 0]]);
        $this->assertTrue(is_finite($loss));
        $this->assertEqualsWithDelta(-log(1e-6), $loss, 1e-9);
        $this->assertNan(Calibration::logLoss([]));
    }

    public function testBaselineUsesObservedRate(): void
    {
        $preds = [['p' => 0.9, 'y' => 1], ['p' => 0.9, 'y' => 1], ['p' => 0.9, 'y' => 1], ['p' => 0.9, 'y' => 0]];
        $base = Calibration::baseline($preds);
        $this->assertSame([0.75, 0.75, 0.75, 0.75], array_column($base, 'p'));
        $this->assertSame([1, 1, 1, 0], array_column($base, 'y'));
    }

    public function testReliabilityBins(): void
    {
        $preds = [
            ['p' => 0.05, 'y' => 0], ['p' => 0.15, 'y' => 1],
            ['p' => 0.92, 'y' => 1], ['p' => 0.98, 'y' => 0], ['p' => 1.0, 'y' => 1],
        ];
        $table = Calibration::reliability($preds, 5);
        $this->assertCount(5, $table);
        $this->assertSame([2, 0, 0, 0, 3], array_column($table, 'n'));
        $this->assertEqualsWithDelta(0.1, $table[0]['mean_p'], 1e-12);
        $this->assertEqualsWithDelta(0.5, $table[0]['observed'], 1e-12);
        $this->assertNull($table[1]['mean_p']);
        $this->assertEqualsWithDelta((0.92 + 0.98 + 1.0) / 3, $table[4]['mean_p'], 1e-12);
        $this->assertEqualsWithDelta(2 / 3, $table[4]['observed'], 1e-12);
        $this->assertSame(0.8, $table[4]['lo']);
    }

    public function testPairedDifference(): void
    {
        $a = [['p' => 0.5, 'y' => 1], ['p' => 0.5, 'y' => 0]];
        $b = [['p' => 0.9, 'y' => 1], ['p' => 0.1, 'y' => 0]];
        $cmp = Calibration::pairedLogLossDiff($a, $b);
        $this->assertEqualsWithDelta(log(0.5) - log(0.9), $cmp['diff'], 1e-12, 'negative: B is better');
        $this->assertEqualsWithDelta(0.0, $cmp['se'], 1e-12);
        $this->expectException(\InvalidArgumentException::class);
        Calibration::pairedLogLossDiff($a, [$b[0]]);
    }

    public function testPredictionsReplayTheModel(): void
    {
        $events = [
            // out of order on purpose: predictions() sorts by time
            ['item' => 'x', 'mode' => 'recall', 'outcome' => 'fail', 'at' => 10 * self::DAY],
            ['item' => 'x', 'mode' => 'recall', 'outcome' => 'good', 'at' => 0.0],
            ['item' => 'y', 'mode' => 'introduce', 'outcome' => null, 'at' => 1 * self::DAY],
            ['item' => 'y', 'mode' => 'recognize', 'outcome' => 'easy', 'hinted' => true, 'at' => 2 * self::DAY],
            ['item' => 'y', 'mode' => 'self_report', 'outcome' => 'good', 'at' => 3 * self::DAY],
            ['item' => 'y', 'mode' => 'recall', 'outcome' => null, 'at' => 4 * self::DAY],   // voided
        ];
        $preds = Calibration::predictions($events);
        $this->assertCount(2, $preds, 'first contact, self_report and voided events are not scored');

        // in time order: y first (day 2), then x (day 10)
        // y: introduced (S = 0.2), recognized one day later; the hint caps easy at hard
        $this->assertEqualsWithDelta(MemoryModel::recall(0.2, 1.0), $preds[0]['p'], 1e-12);
        $this->assertSame(1, $preds[0]['y']);
        $this->assertSame('recognize', $preds[0]['mode']);

        // x: S = 3 after the first good recall, then 10 days later
        $this->assertEqualsWithDelta(MemoryModel::recall(3.0, 10.0), $preds[1]['p'], 1e-12);
        $this->assertSame(0, $preds[1]['y']);
        $this->assertEqualsWithDelta(10.0, $preds[1]['gap_days'], 1e-12);
    }

    public function testParamsChangePredictionsButNotWhichEventsAreScored(): void
    {
        $events = [
            ['item' => 'x', 'mode' => 'recall', 'outcome' => 'good', 'at' => 0.0],
            ['item' => 'x', 'mode' => 'recall', 'outcome' => 'good', 'at' => 5 * self::DAY],
            ['item' => 'x', 'mode' => 'recall', 'outcome' => 'fail', 'at' => 30 * self::DAY],
        ];
        $grid = Calibration::grid();
        $this->assertCount(27, $grid);
        $this->assertSame(MemoryModel::PARAMS, $grid['first_s x1, growth_k x1, curve x1']);
        $v1 = Calibration::predictions($events);
        $alt = Calibration::predictions($events, $grid['first_s x2, growth_k x1, curve x1']);
        $this->assertCount(count($v1), $alt);
        $this->assertGreaterThan($v1[0]['p'], $alt[0]['p'], 'larger first stability predicts better recall');
    }

    public function testEventsFromExport(): void
    {
        $lines = [
            json_encode(['format' => 'pauk-export', 'version' => 1]),
            json_encode(['type' => 'item', 'ref' => 'it/a']),
            json_encode([
                'type' => 'interaction', 'occurred_at' => '2026-09-09T12:00:00.000Z', 'source' => 'tutor',
                'mode' => 'recall', 'hinted' => true,
                'items' => [
                    ['ref' => 'it/a', 'origin' => 'it/a', 'outcome' => 'good'],
                    ['ref' => 'it/b', 'origin' => 'it/old-b', 'outcome' => 'fail'],
                ],
                'amendments' => [
                    ['origin' => 'it/old-b', 'outcome' => 'hard'],
                    ['origin' => 'it/old-b', 'outcome' => 'easy'],
                ],
            ]),
            json_encode([
                'type' => 'interaction', 'occurred_at' => '2026-09-10T12:00:00Z', 'source' => 'simulation',
                'mode' => 'recall', 'items' => [['ref' => 'it/a', 'origin' => 'it/a', 'outcome' => 'fail']],
            ]),
            '',
        ];
        $events = Calibration::eventsFromExport($lines);
        $this->assertCount(2, $events);
        $this->assertSame(['it/a', 'it/b'], array_column($events, 'item'));
        $this->assertSame(['good', 'easy'], array_column($events, 'outcome'), 'latest amendment per origin wins');
        $this->assertTrue($events[0]['hinted']);
        $this->assertEqualsWithDelta(1788955200.0, $events[0]['at'], 1e-3);
        $this->assertCount(3, Calibration::eventsFromExport($lines, includeSimulation: true));
    }
}

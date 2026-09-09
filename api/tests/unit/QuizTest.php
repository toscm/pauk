<?php

declare(strict_types=1);

namespace Pauk\Tests\unit;

use Pauk\Quiz;
use PHPUnit\Framework\TestCase;

final class QuizTest extends TestCase
{
    public function testWeightNewCardIsMaximal(): void
    {
        // never asked: error_rate 0.5, staleness 1 → weight 1.0
        $this->assertEqualsWithDelta(1.0, Quiz::weight(0, 0, null), 1e-9);
    }

    public function testWeightOrdering(): void
    {
        $new = Quiz::weight(0, 0, null);
        $freshCorrect = Quiz::weight(10, 0, 0.0);
        $freshWrong = Quiz::weight(10, 8, 0.0);
        $staleCorrect = Quiz::weight(10, 0, 30.0);
        $this->assertGreaterThan($freshCorrect, $new);
        $this->assertGreaterThan($freshCorrect, $freshWrong);
        $this->assertGreaterThan($freshCorrect, $staleCorrect);
        // staleness caps at 30 days
        $this->assertEqualsWithDelta(
            Quiz::weight(10, 0, 30.0),
            Quiz::weight(10, 0, 300.0),
            1e-9
        );
    }

    public function testSampleIsDeterministicWithSeed(): void
    {
        $weights = [1 => 1.0, 2 => 0.5, 3 => 0.1, 4 => 1.0];
        $a = Quiz::sample($weights, 3, new \Random\Randomizer(new \Random\Engine\Mt19937(42)));
        $b = Quiz::sample($weights, 3, new \Random\Randomizer(new \Random\Engine\Mt19937(42)));
        $this->assertSame($a, $b);
        $this->assertCount(3, $a);
        $this->assertSame($a, array_values(array_unique($a)));
    }

    public function testSampleWithoutReplacementExhausts(): void
    {
        $weights = [7 => 0.2, 9 => 0.9];
        $picked = Quiz::sample($weights, 10, new \Random\Randomizer(new \Random\Engine\Mt19937(1)));
        sort($picked);
        $this->assertSame([7, 9], $picked);
    }

    public function testHeavyWeightsAreDrawnMoreOften(): void
    {
        $weights = [1 => 1.0, 2 => 0.05];
        $firstPicks = [1 => 0, 2 => 0];
        for ($seed = 0; $seed < 200; $seed++) {
            $rng = new \Random\Randomizer(new \Random\Engine\Mt19937($seed));
            $firstPicks[Quiz::sample($weights, 1, $rng)[0]]++;
        }
        $this->assertGreaterThan(150, $firstPicks[1]);
    }
}

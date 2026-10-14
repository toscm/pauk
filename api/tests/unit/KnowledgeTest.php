<?php

declare(strict_types=1);

namespace Pauk\Tests\unit;

use Pauk\ApiError;
use Pauk\Knowledge\Grader;
use Pauk\Knowledge\MemoryModel;
use Pauk\Knowledge\Norm;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\TestCase;

final class KnowledgeTest extends TestCase
{
    #[DataProvider('normCases')]
    public function testNorm(string $label, string $expected): void
    {
        $this->assertSame($expected, Norm::norm($label));
    }

    public static function normCases(): array
    {
        return [
            'markdown emphasis' => ['**parlare**', 'parlare'],
            'link' => ['[FastRet](https://doi.org/x)', 'fastret'],
            'parenthetical' => ['FastRet (Schmidt et al. 2024)', 'fastret'],
            'image dropped' => ['![m](https://x/m.png) Mitochondrium', 'mitochondrium'],
            'latin diacritics' => ['Perché', 'perche'],
            'greek tonos' => ['Άλφα', 'αλφα'],
            'punctuation' => ["T-cell's role", 't cell s role'],
        ];
    }

    #[DataProvider('slugCases')]
    public function testSlug(string $label, string $expected): void
    {
        $this->assertSame($expected, Norm::slug($label));
    }

    public static function slugCases(): array
    {
        return [
            'word' => ['parlare', 'parlare'],
            'phrase' => ['In bocca al lupo!', 'in-bocca-al-lupo'],
            'accented' => ['perché', 'perche'],
            'greek letter name' => ['α', 'alpha'],
            'greek capital letter' => ['Ω', 'omega'],
            'greek word transliterated' => ['καλημέρα', 'kalimera'],
            'term' => ['T-cell', 't-cell'],
        ];
    }

    #[DataProvider('keyCases')]
    public function testKeyGrammar(string $key, bool $valid): void
    {
        $this->assertSame($valid, Norm::keyError($key) === null, (string) Norm::keyError($key));
    }

    public static function keyCases(): array
    {
        return [
            'plain' => ['parlare', true],
            'form' => ['essere.pres.1sg', true],
            'sense' => ['pesca.fishing', true],
            'paper' => ['park-2006-flow-cytometry-gating', true],
            'kind prefix' => ['term.retention-time', false],
            'pos suffix' => ['farfalla.noun', false],
            'uppercase' => ['Parlare', false],
            'unicode' => ['α', false],
            'double dash' => ['a--b', false],
            'trailing dot' => ['a.', false],
        ];
    }

    public function testMemoryFirstContact(): void
    {
        $s = MemoryModel::step(null, 'introduce', null, 0.0);
        $this->assertSame(0.2, $s['stability']);
        $this->assertNull($s['best_mode']);
        $this->assertSame(1, MemoryModel::mastery($s['stability'], $s['best_mode']));

        $good = MemoryModel::step(null, 'recall', 'good', 0.0);
        $this->assertEqualsWithDelta(3.0, $good['stability'], 1e-9);
        $this->assertSame('recall', $good['best_mode']);

        $recognized = MemoryModel::step(null, 'recognize', 'good', 0.0);
        $this->assertEqualsWithDelta(1.8, $recognized['stability'], 1e-9, 'recognition is weaker evidence');
    }

    public function testIntroduceNeverChangesExistingState(): void
    {
        $s = MemoryModel::step(null, 'recall', 'good', 0.0);
        $this->assertSame($s, MemoryModel::step($s, 'introduce', null, 86400.0 * 5));
    }

    public function testSameSessionRepetitionDoesNotFakeStability(): void
    {
        $s = MemoryModel::step(null, 'recall', 'good', 0.0);
        $again = MemoryModel::step($s, 'recall', 'good', 60.0);
        $this->assertLessThan(1.01, $again['stability'] / $s['stability']);
    }

    public function testSuccessAtDueRoughlyDoublesAndOverdueGrowsMore(): void
    {
        $s = MemoryModel::step(null, 'recall', 'good', 0.0);   // S = 3, D = 5
        $atDue = MemoryModel::step($s, 'recall', 'good', 3 * 86400.0);
        $this->assertEqualsWithDelta(2.13, $atDue['stability'] / 3.0, 0.05);
        $late = MemoryModel::step($s, 'recall', 'good', 27 * 86400.0);  // R = 0.5
        $this->assertGreaterThan(5, $late['stability'] / 3.0);
    }

    public function testFailureShrinksStabilityAndCountsLapse(): void
    {
        $s = ['stability' => 100.0, 'difficulty' => 5.0, 'first_seen_at' => 0.0, 'last_seen_at' => 0.0,
              'reps' => 5, 'lapses' => 0, 'best_mode' => 'recall'];
        $failed = MemoryModel::step($s, 'recall', 'fail', 50 * 86400.0);
        $this->assertEqualsWithDelta(10.5, $failed['stability'], 1e-9);
        $this->assertSame(1, $failed['lapses']);
        $this->assertGreaterThan(5.0, $failed['difficulty']);
    }

    public function testMasteryLevels(): void
    {
        $this->assertSame(0, MemoryModel::mastery(null, null));
        $this->assertSame(1, MemoryModel::mastery(5.0, null));
        $this->assertSame(2, MemoryModel::mastery(2.0, 'recognize'));
        $this->assertSame(3, MemoryModel::mastery(10.0, 'recognize'));
        $this->assertSame(4, MemoryModel::mastery(100.0, 'recognize'), 'level 5 needs recall');
        $this->assertSame(5, MemoryModel::mastery(100.0, 'recall'));
    }

    public function testHintCapsAtHard(): void
    {
        $this->assertSame('hard', MemoryModel::capHinted('easy', true));
        $this->assertSame('fail', MemoryModel::capHinted('fail', true));
        $this->assertSame('good', MemoryModel::capHinted('good', false));
    }

    public function testGraderKinds(): void
    {
        $mc = ['kind' => 'mc', 'options' => [['id' => 'a'], ['id' => 'b']], 'correct' => ['a']];
        $this->assertSame('good', Grader::grade($mc, ['selected' => ['a']])['outcome']);
        $this->assertSame('fail', Grader::grade($mc, ['selected' => ['a', 'b']])['outcome']);

        $text = ['kind' => 'text', 'accepted' => ['farfalla']];
        $this->assertSame('typo', Grader::grade($text, ['text' => 'farfala'])['match']);
        $this->assertSame('hard', Grader::grade($text, ['text' => 'farfala'])['outcome']);
        $this->assertSame('text@2', Grader::grade($text, ['text' => 'farfalla'])['grader']);

        $match = ['kind' => 'match', 'pairs' => [['left_md' => 'io', 'right_md' => 'parlo'], ['left_md' => 'tu', 'right_md' => 'parli']]];
        $this->assertSame('good', Grader::grade($match, ['matches' => ['0' => 0, '1' => 1]])['outcome']);
        $this->assertSame('fail', Grader::grade($match, ['matches' => ['0' => 1, '1' => 0]])['outcome']);
    }

    public function testGraderRejectsBrokenKeys(): void
    {
        $this->expectException(ApiError::class);
        Grader::grade(['kind' => 'mc', 'options' => [['id' => 'a']], 'correct' => ['z']], ['selected' => ['a']]);
    }
}

<?php

declare(strict_types=1);

namespace Pauk\Tests\unit;

use Pauk\Text;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\TestCase;

final class TextTest extends TestCase
{
    #[DataProvider('normalizeCases')]
    public function testNormalize(string $input, string $expected): void
    {
        $this->assertSame($expected, Text::normalize($input));
    }

    public static function normalizeCases(): array
    {
        return [
            'lowercase' => ['Mitochondrium', 'mitochondrium'],
            'trim and collapse' => ["  la   casa \n", 'la casa'],
            'accents' => ['perché è così', 'perche e cosi'],
            'punctuation' => ['Buon giorno!', 'buon giorno'],
            'apostrophe' => ["l'amica", 'l amica'],
            'german sz' => ['Straße', 'strasse'],
            'symbols' => ['a + b = c', 'a b c'],
            'empty' => ['   ', ''],
            'greek untouched' => ['αλφα', 'αλφα'],
        ];
    }

    public function testLevenshteinUtf8(): void
    {
        $this->assertSame(0, Text::levenshtein('casa', 'casa'));
        $this->assertSame(1, Text::levenshtein('casa', 'cesa'));
        $this->assertSame(1, Text::levenshtein('casa', 'cas'));
        $this->assertSame(4, Text::levenshtein('', 'casa'));
        // codepoints, not bytes: two-byte umlauts count as one edit
        $this->assertSame(1, Text::levenshtein('über', 'uber'));
        $this->assertSame(2, Text::levenshtein('αβγ', 'αδδ'));
    }

    #[DataProvider('gradeCases')]
    public function testGrade(string $answer, array $accepted, string $expected): void
    {
        $this->assertSame($expected, Text::grade($answer, $accepted));
    }

    public static function gradeCases(): array
    {
        return [
            'exact' => ['essere', ['essere'], 'exact'],
            'exact after normalize' => ['  Essere! ', ['essere'], 'exact'],
            'accents fold' => ['perche', ['perché'], 'exact'],
            'second accepted' => ['auto', ['la macchina', 'auto'], 'exact'],
            'typo short word' => ['esere', ['essere'], 'typo'],
            'two edits short word' => ['esre', ['essere'], 'wrong'],
            'long word one edit' => ['mitochondrum', ['Mitochondrium'], 'typo'],
            'wrong' => ['avere', ['essere'], 'wrong'],
            'empty answer' => ['', ['essere'], 'wrong'],
            'whitespace answer' => ['   ', ['essere'], 'wrong'],
            'article variant exact' => ['casa', ['la casa', 'casa'], 'exact'],
            'short answers need exact match' => ['b', ['a'], 'wrong'],
            'three letters no typo budget' => ['unn', ['uno'], 'wrong'],
            'four letters allow one edit' => ['cesa', ['casa'], 'typo'],
        ];
    }

    public function testTypoThresholdScalesWithLength(): void
    {
        // accepted answer of length 16 → threshold ⌊16/8⌋ = 2 edits
        $this->assertSame('typo', Text::grade('abcdefghijklmnxx', ['abcdefghijklmnop']));
        $this->assertSame('wrong', Text::grade('abcdefghijklmxxx', ['abcdefghijklmnop']));
        // accepted answer of length 6 → threshold max(1, 0) = 1 edit
        $this->assertSame('typo', Text::grade('esserx', ['essere']));
        $this->assertSame('wrong', Text::grade('essexx', ['essere']));
    }

    public function testIsValidName(): void
    {
        $this->assertTrue(Text::isValidName('italian-core-verbs'));
        $this->assertTrue(Text::isValidName('a1'));
        $this->assertFalse(Text::isValidName(''));
        $this->assertFalse(Text::isValidName('Café'));
        $this->assertFalse(Text::isValidName('with space'));
        $this->assertFalse(Text::isValidName('Upper'));
        $this->assertFalse(Text::isValidName(str_repeat('a', 65)));
    }
}

<?php

declare(strict_types=1);

namespace Pauk;

final class Text
{
    /**
     * Diacritic folding for Latin letters. A fixed table instead of
     * intl/iconv so behavior is identical on every PHP build
     * (static local binary, IONOS, CI).
     */
    private const DIACRITICS = [
        'à' => 'a', 'á' => 'a', 'â' => 'a', 'ã' => 'a', 'ä' => 'a', 'å' => 'a',
        'è' => 'e', 'é' => 'e', 'ê' => 'e', 'ë' => 'e',
        'ì' => 'i', 'í' => 'i', 'î' => 'i', 'ï' => 'i',
        'ò' => 'o', 'ó' => 'o', 'ô' => 'o', 'õ' => 'o', 'ö' => 'o',
        'ù' => 'u', 'ú' => 'u', 'û' => 'u', 'ü' => 'u',
        'ç' => 'c', 'ñ' => 'n', 'ý' => 'y', 'ÿ' => 'y',
        'æ' => 'ae', 'œ' => 'oe', 'ß' => 'ss',
    ];

    /**
     * Vowels after normalization (Latin, Greek with and without
     * tonos). Swapping one for another changes the word or its form
     * in the languages pauk teaches (fare/faro, per/por, la/le), so
     * it is not a typo (issues/0016).
     */
    private const VOWELS = 'aeiouαεηιουωάέήίόύώϊϋΐΰ';

    /**
     * Normalize a free-text answer for comparison: lowercase,
     * fold Latin diacritics, drop punctuation/symbols, collapse
     * whitespace. See docs/api.md, "Answering".
     */
    public static function normalize(string $s): string
    {
        $s = mb_strtolower(trim($s), 'UTF-8');
        $s = strtr($s, self::DIACRITICS);
        $s = (string) preg_replace('/[\p{P}\p{S}]+/u', ' ', $s);
        $s = (string) preg_replace('/\s+/u', ' ', $s);
        return trim($s);
    }

    /** Levenshtein distance over UTF-8 codepoints (the builtin is byte-based). */
    public static function levenshtein(string $a, string $b): int
    {
        $sa = mb_str_split($a, 1, 'UTF-8');
        $sb = mb_str_split($b, 1, 'UTF-8');
        $la = count($sa);
        $lb = count($sb);
        if ($la === 0) {
            return $lb;
        }
        if ($lb === 0) {
            return $la;
        }
        $prev = range(0, $lb);
        for ($i = 1; $i <= $la; $i++) {
            $cur = [$i];
            for ($j = 1; $j <= $lb; $j++) {
                $cost = $sa[$i - 1] === $sb[$j - 1] ? 0 : 1;
                $cur[$j] = min($prev[$j] + 1, $cur[$j - 1] + 1, $prev[$j - 1] + $cost);
            }
            $prev = $cur;
        }
        return $prev[$lb];
    }

    /**
     * Grade a free-text answer against accepted answers.
     * Returns "exact", "typo", or "wrong" (docs/api.md).
     *
     * @param list<string> $accepted
     */
    public static function grade(string $answer, array $accepted): string
    {
        $answer = self::normalize($answer);
        if ($answer === '') {
            return 'wrong';
        }
        foreach ($accepted as $candidate) {
            if (self::normalize($candidate) === $answer) {
                return 'exact';
            }
        }
        foreach ($accepted as $candidate) {
            $norm = self::normalize($candidate);
            // Answers shorter than 4 chars must match exactly: with
            // a 1-edit budget, any single letter would pass as a
            // "typo" for any other.
            $len = mb_strlen($norm, 'UTF-8');
            if ($len < 4) {
                continue;
            }
            $threshold = max(1, intdiv($len, 8));
            if (self::typoDistance($answer, $norm) <= $threshold) {
                return 'typo';
            }
        }
        return 'wrong';
    }

    /**
     * Levenshtein distance in which replacing a vowel by another
     * vowel costs two edits: within the one-edit budget of words
     * shorter than 16 characters it is never a typo.
     */
    public static function typoDistance(string $a, string $b): int
    {
        $sa = mb_str_split($a, 1, 'UTF-8');
        $sb = mb_str_split($b, 1, 'UTF-8');
        $prev = range(0, count($sb));
        foreach ($sa as $i => $ca) {
            $cur = [$i + 1];
            foreach ($sb as $j => $cb) {
                $cost = 0;
                if ($ca !== $cb) {
                    $vowels = mb_strpos(self::VOWELS, $ca, 0, 'UTF-8') !== false
                        && mb_strpos(self::VOWELS, $cb, 0, 'UTF-8') !== false;
                    $cost = $vowels ? 2 : 1;
                }
                $cur[$j + 1] = min($prev[$j + 1] + 1, $cur[$j] + 1, $prev[$j] + $cost);
            }
            $prev = $cur;
        }
        return $prev[count($sb)];
    }

    public static function isValidName(string $name): bool
    {
        return preg_match('/^[a-z0-9-]{1,64}$/D', $name) === 1;   // D: no trailing newline
    }
}

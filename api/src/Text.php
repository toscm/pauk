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
            if (self::levenshtein($answer, $norm) <= $threshold) {
                return 'typo';
            }
        }
        return 'wrong';
    }

    public static function isValidName(string $name): bool
    {
        return preg_match('/^[a-z0-9-]{1,64}$/', $name) === 1;
    }
}

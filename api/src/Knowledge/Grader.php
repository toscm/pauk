<?php

declare(strict_types=1);

namespace Pauk\Knowledge;

use Pauk\ApiError;
use Pauk\Text;

/**
 * Generic grader for keyed exercises (docs/tutor.md 9.1): one
 * entry point, the exercise is plain JSON, so a new keyed kind is
 * a new branch here and needs no migration. Versioned names are
 * stored with every graded interaction.
 */
final class Grader
{
    public const KEYED = ['mc', 'match', 'text'];

    /**
     * @param array<string, mixed> $exercise
     * @param array<string, mixed> $response
     * @return array{grader: string, match: string, outcome: string, expected: array<string, mixed>}
     */
    public static function grade(array $exercise, array $response): array
    {
        $kind = $exercise['kind'] ?? null;
        [$grader, $match, $expected] = match ($kind) {
            'mc' => self::mc($exercise, $response),
            'match' => self::matchPairs($exercise, $response),
            'text' => self::text($exercise, $response),
            default => throw new ApiError(400, 'validation', 'exercise.kind must be mc, match or text to be graded'),
        };
        $outcome = ['exact' => 'good', 'typo' => 'hard', 'wrong' => 'fail'][$match];
        return ['grader' => $grader, 'match' => $match, 'outcome' => $outcome, 'expected' => $expected];
    }

    /** @return array{0: string, 1: string, 2: array<string, mixed>} */
    private static function mc(array $exercise, array $response): array
    {
        $correct = $exercise['correct'] ?? null;
        $optionIds = array_map(fn ($o) => is_array($o) ? ($o['id'] ?? null) : null, $exercise['options'] ?? []);
        if (!is_array($correct) || $correct === [] || array_diff($correct, $optionIds) !== []) {
            throw new ApiError(400, 'validation', 'mc exercise needs options and correct option ids among them');
        }
        $selected = $response['selected'] ?? null;
        if (!is_array($selected)) {
            throw new ApiError(400, 'validation', 'response.selected must be a list of option ids');
        }
        $a = array_map('strval', $selected);
        $b = array_map('strval', $correct);
        sort($a);
        sort($b);
        return ['mc@1', $a === array_values(array_unique($b)) ? 'exact' : 'wrong', ['correct' => array_values($correct)]];
    }

    /**
     * Pairs are listed in their correct order; response.matches maps
     * each left index to the chosen pair index.
     *
     * @return array{0: string, 1: string, 2: array<string, mixed>}
     */
    private static function matchPairs(array $exercise, array $response): array
    {
        $pairs = $exercise['pairs'] ?? null;
        if (!is_array($pairs) || count($pairs) < 2) {
            throw new ApiError(400, 'validation', 'match exercise needs at least two pairs');
        }
        $matches = $response['matches'] ?? null;
        if (!is_array($matches)) {
            throw new ApiError(400, 'validation', 'response.matches must map left index to right index');
        }
        $ok = true;
        foreach (array_keys($pairs) as $i) {
            $chosen = $matches[(string) $i] ?? ($matches[$i] ?? null);
            $ok = $ok && $chosen !== null && (int) $chosen === $i;
        }
        return ['match@1', $ok ? 'exact' : 'wrong', ['pairs' => $pairs]];
    }

    /** @return array{0: string, 1: string, 2: array<string, mixed>} */
    private static function text(array $exercise, array $response): array
    {
        $accepted = $exercise['accepted'] ?? null;
        if (!is_array($accepted) || $accepted === [] || array_filter($accepted, fn ($a) => !is_string($a)) !== []) {
            throw new ApiError(400, 'validation', 'text exercise needs accepted answers');
        }
        $text = $response['text'] ?? null;
        if (!is_string($text)) {
            throw new ApiError(400, 'validation', 'response.text must be a string');
        }
        return ['text@2', Text::grade($text, array_values($accepted)), ['accepted' => array_values($accepted)]];
    }
}

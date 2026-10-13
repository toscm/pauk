<?php

declare(strict_types=1);

namespace Pauk\Knowledge;

use Pauk\Text;

/**
 * Item identity helpers (docs/tutor.md 4.1, 4.10): label
 * normalization for candidate search, key slugs, key grammar.
 * One implementation, shared by every write path, so a lexicon
 * import and a teacher-added item derive the same key.
 */
final class Norm
{
    public const KINDS = ['word', 'form', 'phrase', 'rule', 'symbol', 'term', 'fact', 'paper', 'skill', 'other'];

    /** Kinds whose key may be derived from the label. */
    public const DERIVABLE = ['word', 'phrase', 'term'];

    /** Kinds that are language-bound vocabulary; fuzzy matching is too noisy for them. */
    public const LEXICAL = ['word', 'form', 'phrase', 'symbol'];

    private const KEY_RE = '/^[a-z0-9]+(-[a-z0-9]+)*(\.[a-z0-9]+(-[a-z0-9]+)*)*$/';

    private const POS_SUFFIXES = ['noun', 'verb', 'adj', 'adjective', 'adv', 'adverb', 'pron', 'prep'];

    private const GREEK_TONOS = [
        'ά' => 'α', 'έ' => 'ε', 'ή' => 'η', 'ί' => 'ι', 'ό' => 'ο', 'ύ' => 'υ', 'ώ' => 'ω',
        'ϊ' => 'ι', 'ϋ' => 'υ', 'ΐ' => 'ι', 'ΰ' => 'υ',
    ];

    private const GREEK_NAMES = [
        'α' => 'alpha', 'β' => 'beta', 'γ' => 'gamma', 'δ' => 'delta', 'ε' => 'epsilon',
        'ζ' => 'zeta', 'η' => 'eta', 'θ' => 'theta', 'ι' => 'iota', 'κ' => 'kappa',
        'λ' => 'lambda', 'μ' => 'mu', 'ν' => 'nu', 'ξ' => 'xi', 'ο' => 'omicron',
        'π' => 'pi', 'ρ' => 'rho', 'σ' => 'sigma', 'ς' => 'sigma', 'τ' => 'tau',
        'υ' => 'upsilon', 'φ' => 'phi', 'χ' => 'chi', 'ψ' => 'psi', 'ω' => 'omega',
    ];

    private const GREEK_TRANSLIT = [
        'α' => 'a', 'β' => 'v', 'γ' => 'g', 'δ' => 'd', 'ε' => 'e', 'ζ' => 'z',
        'η' => 'i', 'θ' => 'th', 'ι' => 'i', 'κ' => 'k', 'λ' => 'l', 'μ' => 'm',
        'ν' => 'n', 'ξ' => 'x', 'ο' => 'o', 'π' => 'p', 'ρ' => 'r', 'σ' => 's',
        'ς' => 's', 'τ' => 't', 'υ' => 'y', 'φ' => 'f', 'χ' => 'ch', 'ψ' => 'ps', 'ω' => 'o',
    ];

    /**
     * Normalize a label for comparison: strip Markdown and
     * parentheticals, then Text::normalize (lowercase, Latin
     * diacritics, punctuation to spaces) plus Greek tonos folding.
     */
    public static function norm(string $label): string
    {
        $s = (string) preg_replace('/!\[[^\]]*\]\([^)]*\)/u', ' ', $label);   // images
        $s = (string) preg_replace('/\[([^\]]*)\]\([^)]*\)/u', '$1', $s);     // links
        $s = (string) preg_replace('/\([^)]*\)/u', ' ', $s);                  // parentheticals
        $s = strtr(mb_strtolower($s, 'UTF-8'), self::GREEK_TONOS);
        return mb_substr(Text::normalize($s), 0, 191, 'UTF-8');
    }

    /** ASCII key slug of a label (`α` → `alpha`, `La farfalla` → `la-farfalla`). */
    public static function slug(string $label): string
    {
        $s = self::norm($label);
        if (isset(self::GREEK_NAMES[$s])) {
            return self::GREEK_NAMES[$s];
        }
        $s = strtr($s, self::GREEK_TRANSLIT);
        $s = (string) preg_replace('/[^a-z0-9]+/', '-', $s);
        return substr(trim($s, '-'), 0, 191);
    }

    /** The key up to the first dot (mirrors the generated column). */
    public static function keyBase(string $key): string
    {
        return explode('.', $key, 2)[0];
    }

    /** Null if valid, else the reason. */
    public static function keyError(string $key): ?string
    {
        if (strlen($key) > 191 || preg_match(self::KEY_RE, $key) !== 1) {
            return 'key must be lowercase ASCII slugs separated by dots, e.g. essere.pres.1sg';
        }
        $parts = explode('.', $key);
        if (count($parts) > 1 && in_array($parts[0], self::KINDS, true)) {
            return "key must not start with a kind prefix ('{$parts[0]}.'); kind is a field";
        }
        if (count($parts) > 1 && in_array(end($parts), self::POS_SUFFIXES, true)) {
            return 'key must not end with a part-of-speech suffix; use attrs.pos';
        }
        return null;
    }

    public static function isValidSpace(string $space): bool
    {
        return preg_match('/^[a-z][a-z0-9-]{0,15}$/', $space) === 1;
    }
}

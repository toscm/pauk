<?php

declare(strict_types=1);

namespace Pauk\Knowledge;

use Pauk\ApiError;

/**
 * Millisecond UTC timestamps for the interaction log. The memory
 * model works on float UNIX seconds; the DB stores DATETIME(3).
 */
final class Time
{
    public static function now(): float
    {
        return round(microtime(true), 3);
    }

    public static function toDb(float $t): string
    {
        $dt = \DateTimeImmutable::createFromFormat('U.u', sprintf('%.6F', $t), new \DateTimeZone('UTC'));
        return $dt->format('Y-m-d H:i:s.v');
    }

    public static function fromDb(string $db): float
    {
        $dt = new \DateTimeImmutable($db, new \DateTimeZone('UTC'));
        return (float) $dt->format('U.v');
    }

    public static function iso(?string $db): ?string
    {
        if ($db === null) {
            return null;
        }
        $dt = new \DateTimeImmutable($db, new \DateTimeZone('UTC'));
        return $dt->format(str_contains($db, '.') ? 'Y-m-d\TH:i:s.v\Z' : 'Y-m-d\TH:i:s\Z');
    }

    /** Parse an ISO 8601 timestamp (any offset) to UNIX seconds. */
    public static function parseIso(mixed $value, string $field): float
    {
        if (!is_string($value)) {
            throw new ApiError(400, 'validation', "$field must be an ISO 8601 timestamp");
        }
        try {
            $dt = new \DateTimeImmutable($value);
        } catch (\Exception) {
            throw new ApiError(400, 'validation', "$field must be an ISO 8601 timestamp");
        }
        return (float) $dt->format('U.v');
    }
}

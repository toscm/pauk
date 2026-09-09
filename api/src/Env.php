<?php

declare(strict_types=1);

namespace Pauk;

final class Env
{
    /**
     * Load KEY=VALUE lines from the file named by PAUK_ENV_FILE
     * into the process environment (used on shared hosting where
     * per-request env vars cannot be set). Existing variables win.
     */
    public static function loadFile(): void
    {
        $file = getenv('PAUK_ENV_FILE');
        if ($file === false || $file === '' || !is_readable($file)) {
            return;
        }
        foreach (file($file, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
            $line = trim($line);
            if ($line === '' || str_starts_with($line, '#')) {
                continue;
            }
            [$key, $value] = array_pad(explode('=', $line, 2), 2, '');
            $key = trim($key);
            if ($key !== '' && getenv($key) === false) {
                putenv($key . '=' . trim($value));
            }
        }
    }

    public static function get(string $key, ?string $default = null): string
    {
        $value = getenv($key);
        if ($value === false || $value === '') {
            if ($default === null) {
                throw new \RuntimeException("Missing required environment variable: $key");
            }
            return $default;
        }
        return $value;
    }
}

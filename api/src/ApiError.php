<?php

declare(strict_types=1);

namespace Pauk;

/** Exception carrying an HTTP status and stable error code. */
final class ApiError extends \RuntimeException
{
    public function __construct(
        public readonly int $status,
        public readonly string $errorCode,
        string $message,
        /** Extra top-level response fields, e.g. duplicate candidates. */
        public readonly array $details = [],
    ) {
        parent::__construct($message);
    }
}

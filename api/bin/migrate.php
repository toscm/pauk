<?php

declare(strict_types=1);

// Apply pending migrations. Usage:
//   php bin/migrate.php            (env vars already set)
//   PAUK_ENV_FILE=~/pauk.env php bin/migrate.php
require dirname(__DIR__) . '/vendor/autoload.php';

$pdo = Pauk\Db::connect();
$applied = Pauk\Db::migrate($pdo, dirname(__DIR__) . '/migrations');
echo $applied === []
    ? "No pending migrations.\n"
    : 'Applied: ' . implode(', ', $applied) . "\n";

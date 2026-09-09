<?php

declare(strict_types=1);

// Create a user (if needed) and an API token for it.
// Usage: php bin/create-token.php <username> [label]
require dirname(__DIR__) . '/vendor/autoload.php';

$username = $argv[1] ?? null;
$label = $argv[2] ?? 'cli';
if ($username === null || !preg_match('/^[a-z0-9-]{1,64}$/', $username)) {
    fwrite(STDERR, "Usage: php bin/create-token.php <username> [label]\n");
    exit(1);
}

$pdo = Pauk\Db::connect();
$stmt = $pdo->prepare('SELECT id FROM users WHERE name = ?');
$stmt->execute([$username]);
$userId = $stmt->fetchColumn();
if ($userId === false) {
    $stmt = $pdo->prepare('INSERT INTO users (name) VALUES (?)');
    $stmt->execute([$username]);
    $userId = $pdo->lastInsertId();
}

$token = bin2hex(random_bytes(32));
$stmt = $pdo->prepare(
    'INSERT INTO api_tokens (user_id, token_hash, label) VALUES (?, ?, ?)'
);
$stmt->execute([$userId, hash('sha256', $token), $label]);

echo "user: $username (id $userId)\ntoken: $token\n";

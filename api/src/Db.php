<?php

declare(strict_types=1);

namespace Pauk;

final class Db
{
    public static function connect(): \PDO
    {
        Env::loadFile();
        $dsn = sprintf(
            'mysql:host=%s;port=%s;dbname=%s;charset=utf8mb4',
            Env::get('PAUK_DB_HOST'),
            Env::get('PAUK_DB_PORT', '3306'),
            Env::get('PAUK_DB_NAME'),
        );
        return new \PDO($dsn, Env::get('PAUK_DB_USER'), Env::get('PAUK_DB_PASS', ''), [
            \PDO::ATTR_ERRMODE => \PDO::ERRMODE_EXCEPTION,
            \PDO::ATTR_DEFAULT_FETCH_MODE => \PDO::FETCH_ASSOC,
            \PDO::ATTR_EMULATE_PREPARES => false,
        ]);
    }

    /**
     * Apply pending migrations from $dir (NNN_name.sql, sorted).
     * Returns the names of the migrations that were applied.
     */
    public static function migrate(\PDO $pdo, string $dir): array
    {
        $pdo->exec(
            'CREATE TABLE IF NOT EXISTS migrations (
                name VARCHAR(255) NOT NULL PRIMARY KEY,
                applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'
        );
        $done = $pdo->query('SELECT name FROM migrations')->fetchAll(\PDO::FETCH_COLUMN);
        $files = glob(rtrim($dir, '/') . '/[0-9][0-9][0-9]_*.sql');
        sort($files);
        $applied = [];
        foreach ($files as $file) {
            $name = basename($file);
            if (in_array($name, $done, true)) {
                continue;
            }
            // PDO::exec handles multiple ;-separated statements for
            // mysql, but errors in later statements surface lazily —
            // run statements one by one instead.
            foreach (self::splitStatements((string) file_get_contents($file)) as $sql) {
                $pdo->exec($sql);
            }
            $stmt = $pdo->prepare('INSERT INTO migrations (name) VALUES (?)');
            $stmt->execute([$name]);
            $applied[] = $name;
        }
        return $applied;
    }

    /** @return list<string> */
    private static function splitStatements(string $sql): array
    {
        // Strip full-line -- comments first (a semicolon inside a
        // comment would otherwise split a statement in two), then
        // split on ';'. Migrations hold no string literals with
        // semicolons, so this simple split is sufficient.
        $lines = array_filter(
            explode("\n", $sql),
            fn ($line) => !str_starts_with(ltrim($line), '--')
        );
        $parts = array_map('trim', explode(';', implode("\n", $lines)));
        return array_values(array_filter($parts, fn ($p) => $p !== ''));
    }
}

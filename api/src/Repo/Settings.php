<?php

declare(strict_types=1);

namespace Pauk\Repo;

use Pauk\ApiError;

/**
 * Per-user settings (docs/tutor.md 4.11): one JSON value per name,
 * defaults from the registry below, so a new setting needs no
 * migration.
 */
final class Settings
{
    /** name => [default, validator] */
    private static function registry(): array
    {
        $oneOf = fn (array $values) => fn ($v) => in_array($v, $values, true);
        return [
            'tutor.language' => ['de', fn ($v) => is_string($v) && preg_match('/^[a-zA-Z]{2,3}(-[A-Za-z0-9]{2,8})*$/', $v) === 1],
            'tutor.immersion' => [[], fn ($v) => is_array($v) && ($v === [] || !array_is_list($v))
                && array_filter($v, fn ($level) => !in_array($level, ['off', 'partial', 'full'], true)) === []],
            'tutor.item_creation' => ['propose', $oneOf(['off', 'propose', 'on_request', 'free'])],
            'tutor.merge' => ['propose', $oneOf(['propose', 'free'])],
            'tutor.new_items_per_15min' => [8, fn ($v) => is_int($v) && $v >= 0 && $v <= 50],
            'tutor.model' => ['sonnet', fn ($v) => is_string($v) && preg_match('/^[a-z][a-z0-9.\[\]-]{1,63}$/', $v) === 1],
            'review.after_session' => [true, 'is_bool'],
            'review.auto_triage' => [false, 'is_bool'],
        ];
    }

    public function __construct(private readonly \PDO $pdo)
    {
    }

    /** @return array<string, mixed> */
    public function all(int $userId): array
    {
        $values = [];
        foreach (self::registry() as $name => [$default]) {
            $values[$name] = $default;
        }
        $stmt = $this->pdo->prepare('SELECT name, value FROM user_settings WHERE user_id = ?');
        $stmt->execute([$userId]);
        foreach ($stmt->fetchAll() as $row) {
            if (array_key_exists($row['name'], $values)) {
                $values[$row['name']] = json_decode($row['value'], true);
            }
        }
        if ($values['tutor.immersion'] === []) {
            $values['tutor.immersion'] = new \stdClass();
        }
        return $values;
    }

    /** @param array<string, mixed> $changes */
    public function update(int $userId, array $changes): array
    {
        $registry = self::registry();
        foreach ($changes as $name => $value) {
            if (!isset($registry[$name])) {
                throw new ApiError(400, 'validation', "Unknown setting '$name'");
            }
            if (!($registry[$name][1])($value)) {
                throw new ApiError(400, 'validation', "Invalid value for '$name'");
            }
        }
        foreach ($changes as $name => $value) {
            $json = json_encode($value === [] && $name === 'tutor.immersion' ? new \stdClass() : $value, JSON_THROW_ON_ERROR);
            $this->pdo->prepare(
                'INSERT INTO user_settings (user_id, name, value) VALUES (?, ?, ?)
                 ON DUPLICATE KEY UPDATE value = VALUES(value)'
            )->execute([$userId, $name, $json]);
        }
        return $this->all($userId);
    }
}

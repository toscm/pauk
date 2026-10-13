<?php

declare(strict_types=1);

namespace Pauk\Repo;

use Pauk\ApiError;
use Pauk\Knowledge\Time;
use Pauk\Text;

/**
 * Remote records of tutor sessions (docs/tutor.md section 8). A
 * session is addressed by its `uid`, chosen by the session host,
 * so creating it is idempotent.
 */
final class TutorSessions
{
    private const MAX_SUMMARY = 100000;

    public function __construct(private readonly \PDO $pdo)
    {
    }

    /**
     * Create a session, or return the stored one when the uid exists.
     *
     * @param array<string, mixed> $body
     * @return array{0: int, 1: array<string, mixed>} [status, session]
     */
    public function create(int $userId, array $body): array
    {
        $uid = $body['uid'] ?? null;
        if (!is_string($uid) || !Text::isValidName($uid)) {
            throw new ApiError(400, 'validation', 'uid must match ^[a-z0-9-]{1,64}$');
        }
        $existing = $this->find($userId, $uid);
        if ($existing !== null) {
            return [200, self::view($existing)];
        }
        $fields = $this->validate($body, ['goal', 'teacher']);
        $startedAt = isset($body['started_at'])
            ? Time::parseIso($body['started_at'], 'started_at')
            : Time::now();
        try {
            $this->pdo->prepare(
                'INSERT INTO tutor_sessions (user_id, uid, goal, teacher, started_at) VALUES (?, ?, ?, ?, ?)'
            )->execute([$userId, $uid, $fields['goal'] ?? null, $fields['teacher'] ?? null, Time::toDb($startedAt)]);
        } catch (\PDOException $e) {
            // a concurrent create with the same uid won the race
            if (($e->errorInfo[1] ?? null) === 1062) {
                return [200, $this->get($userId, $uid)];
            }
            throw $e;
        }
        return [201, $this->get($userId, $uid)];
    }

    /** @return array<string, mixed> */
    public function get(int $userId, string $uid): array
    {
        $row = $this->find($userId, $uid);
        if ($row === null) {
            throw new ApiError(404, 'not_found', "Tutor session $uid not found");
        }
        return self::view($row);
    }

    /** @return array{items: list<array<string, mixed>>, next_cursor: ?string} */
    public function list(int $userId, int $limit, ?string $cursor): array
    {
        $where = 'user_id = ?';
        $params = [$userId];
        if ($cursor !== null) {
            $where .= ' AND id < ?';
            $params[] = self::decodeCursor($cursor);
        }
        $stmt = $this->pdo->prepare("SELECT * FROM tutor_sessions WHERE $where ORDER BY id DESC LIMIT " . ($limit + 1));
        $stmt->execute($params);
        $rows = $stmt->fetchAll();
        $next = null;
        if (count($rows) > $limit) {
            $rows = array_slice($rows, 0, $limit);
            $next = base64_encode((string) end($rows)['id']);
        }
        return ['items' => array_map(fn ($r) => self::view($r), $rows), 'next_cursor' => $next];
    }

    /** @param array<string, mixed> $body */
    public function update(int $userId, string $uid, array $body): array
    {
        $row = $this->find($userId, $uid);
        if ($row === null) {
            throw new ApiError(404, 'not_found', "Tutor session $uid not found");
        }
        $fields = $this->validate($body, ['goal', 'teacher', 'ended_at', 'summary_md']);
        if ($fields !== []) {
            $set = implode(', ', array_map(fn ($name) => "$name = ?", array_keys($fields)));
            $this->pdo->prepare("UPDATE tutor_sessions SET $set WHERE id = ?")
                ->execute([...array_values($fields), $row['id']]);
        }
        return $this->get($userId, $uid);
    }

    /**
     * Validate the given optional fields that are present in $body;
     * returns them as column => DB value.
     *
     * @param array<string, mixed> $body
     * @param list<string> $allowed
     * @return array<string, mixed>
     */
    private function validate(array $body, array $allowed): array
    {
        $fields = [];
        foreach ($allowed as $name) {
            if (!array_key_exists($name, $body)) {
                continue;
            }
            $value = $body[$name];
            if ($value === null) {
                $fields[$name] = null;
                continue;
            }
            $fields[$name] = match ($name) {
                'goal' => is_array($value) && ($value === [] || !array_is_list($value))
                    ? Items::jsonObject($value)
                    : throw new ApiError(400, 'validation', 'goal must be an object or null'),
                'teacher' => is_string($value) && mb_strlen($value) <= 128
                    ? $value
                    : throw new ApiError(400, 'validation', 'teacher must be a string of at most 128 characters'),
                'ended_at' => Time::toDb(Time::parseIso($value, 'ended_at')),
                'summary_md' => is_string($value) && mb_strlen($value) <= self::MAX_SUMMARY
                    ? $value
                    : throw new ApiError(400, 'validation', 'summary_md must be a string of at most ' . self::MAX_SUMMARY . ' characters'),
            };
        }
        return $fields;
    }

    /** @return array<string, mixed>|null */
    private function find(int $userId, string $uid): ?array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM tutor_sessions WHERE user_id = ? AND uid = ?');
        $stmt->execute([$userId, $uid]);
        $row = $stmt->fetch();
        return $row === false ? null : $row;
    }

    public static function decodeCursor(string $cursor): int
    {
        $decoded = base64_decode($cursor, true);
        if ($decoded === false || filter_var($decoded, FILTER_VALIDATE_INT) === false) {
            throw new ApiError(400, 'validation', 'Invalid cursor');
        }
        return (int) $decoded;
    }

    /**
     * @param array<string, mixed> $row
     * @return array<string, mixed>
     */
    private static function view(array $row): array
    {
        $goal = $row['goal'] === null ? null : json_decode($row['goal'], true);
        return [
            'uid' => $row['uid'],
            'goal' => $goal === [] ? new \stdClass() : $goal,
            'teacher' => $row['teacher'],
            'started_at' => Time::iso($row['started_at']),
            'ended_at' => Time::iso($row['ended_at']),
            'summary_md' => $row['summary_md'],
            'created_at' => Time::iso($row['created_at']),
            'updated_at' => Time::iso($row['updated_at']),
        ];
    }
}

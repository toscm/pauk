<?php

declare(strict_types=1);

namespace Pauk\Repo;

use Pauk\ApiError;
use Pauk\Knowledge\Time;
use Pauk\Text;

/**
 * Problem reports from learners, teachers, observers and simulated
 * learners (docs/tutor.md section 16), triaged into issues/.
 */
final class Reports
{
    public const REPORTERS = ['learner', 'teacher', 'observer', 'simulation'];

    public const CATEGORIES = ['bug', 'content', 'teacher', 'ux', 'idea'];

    public const STATUSES = ['new', 'triaged', 'closed'];

    private const MAX_TEXT = 20000;

    private const MAX_CONTEXT_BYTES = 200 * 1024;

    public function __construct(private readonly \PDO $pdo)
    {
    }

    /** @param array<string, mixed> $body */
    public function create(int $userId, array $body): array
    {
        $sessionUid = $body['session_uid'] ?? null;
        if ($sessionUid !== null && (!is_string($sessionUid) || !Text::isValidName($sessionUid))) {
            throw new ApiError(400, 'validation', 'session_uid must be null or match ^[a-z0-9-]{1,64}$');
        }
        $seq = $body['seq'] ?? null;
        if ($seq !== null && (!is_int($seq) || $seq < 0 || $seq > 2147483647)) {
            throw new ApiError(400, 'validation', 'seq must be null or a non-negative integer');
        }
        $reporter = $body['reporter'] ?? null;
        if (!in_array($reporter, self::REPORTERS, true)) {
            throw new ApiError(400, 'validation', 'reporter must be one of ' . implode(', ', self::REPORTERS));
        }
        $category = $body['category'] ?? null;
        if (!in_array($category, self::CATEGORIES, true)) {
            throw new ApiError(400, 'validation', 'category must be one of ' . implode(', ', self::CATEGORIES));
        }
        $text = $body['text_md'] ?? null;
        if (!is_string($text) || trim($text) === '') {
            throw new ApiError(400, 'validation', 'text_md must be a non-empty string');
        }
        if (mb_strlen($text) > self::MAX_TEXT) {
            throw new ApiError(413, 'too_large', 'text_md is longer than ' . self::MAX_TEXT . ' characters');
        }
        $context = $body['context'] ?? [];
        if (!is_array($context) || ($context !== [] && array_is_list($context))) {
            throw new ApiError(400, 'validation', 'context must be an object');
        }
        $contextJson = Items::jsonObject($context);
        if (strlen($contextJson) > self::MAX_CONTEXT_BYTES) {
            throw new ApiError(413, 'too_large', 'context is larger than 200 KB');
        }
        $this->pdo->prepare(
            'INSERT INTO reports (user_id, session_uid, seq, reporter, category, text_md, context)
             VALUES (?, ?, ?, ?, ?, ?, ?)'
        )->execute([$userId, $sessionUid, $seq, $reporter, $category, $text, $contextJson]);
        return $this->get($userId, (int) $this->pdo->lastInsertId());
    }

    /** @return array<string, mixed> */
    public function get(int $userId, int $id): array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM reports WHERE user_id = ? AND id = ?');
        $stmt->execute([$userId, $id]);
        $row = $stmt->fetch();
        if ($row === false) {
            throw new ApiError(404, 'not_found', "Report $id not found");
        }
        return self::view($row);
    }

    /**
     * Newest first.
     *
     * @param array{status?: string, category?: string, session_uid?: string} $filters
     * @return array{items: list<array<string, mixed>>, next_cursor: ?string}
     */
    public function list(int $userId, array $filters, int $limit, ?string $cursor): array
    {
        $where = ['user_id = ?'];
        $params = [$userId];
        foreach (['status', 'category', 'session_uid'] as $name) {
            if (isset($filters[$name])) {
                $where[] = "$name = ?";
                $params[] = $filters[$name];
            }
        }
        if ($cursor !== null) {
            $where[] = 'id < ?';
            $params[] = TutorSessions::decodeCursor($cursor);
        }
        $stmt = $this->pdo->prepare(
            'SELECT * FROM reports WHERE ' . implode(' AND ', $where) . ' ORDER BY id DESC LIMIT ' . ($limit + 1)
        );
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
    public function update(int $userId, int $id, array $body): array
    {
        $this->get($userId, $id);
        $fields = [];
        if (array_key_exists('status', $body)) {
            if (!in_array($body['status'], self::STATUSES, true)) {
                throw new ApiError(400, 'validation', 'status must be one of ' . implode(', ', self::STATUSES));
            }
            $fields['status'] = $body['status'];
        }
        if (array_key_exists('issue_ref', $body)) {
            $ref = $body['issue_ref'];
            if ($ref !== null && (!is_string($ref) || mb_strlen($ref) > 255)) {
                throw new ApiError(400, 'validation', 'issue_ref must be null or a string of at most 255 characters');
            }
            $fields['issue_ref'] = $ref;
        }
        if ($fields !== []) {
            $set = implode(', ', array_map(fn ($name) => "$name = ?", array_keys($fields)));
            $this->pdo->prepare("UPDATE reports SET $set WHERE id = ?")->execute([...array_values($fields), $id]);
        }
        return $this->get($userId, $id);
    }

    /**
     * @param array<string, mixed> $row
     * @return array<string, mixed>
     */
    private static function view(array $row): array
    {
        $context = json_decode($row['context'], true);
        return [
            'id' => (int) $row['id'],
            'session_uid' => $row['session_uid'],
            'seq' => $row['seq'] === null ? null : (int) $row['seq'],
            'reporter' => $row['reporter'],
            'category' => $row['category'],
            'text_md' => $row['text_md'],
            'context' => $context === [] ? new \stdClass() : $context,
            'status' => $row['status'],
            'issue_ref' => $row['issue_ref'],
            'created_at' => Time::iso($row['created_at']),
            'updated_at' => Time::iso($row['updated_at']),
        ];
    }
}

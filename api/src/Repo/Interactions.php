<?php

declare(strict_types=1);

namespace Pauk\Repo;

use Pauk\ApiError;
use Pauk\Knowledge\Grader;
use Pauk\Knowledge\MemoryModel;
use Pauk\Knowledge\Time;

/**
 * The append-only interaction log and the memory states derived
 * from it (docs/tutor.md 4.5, 4.6). States are a cache: replay()
 * recomputes an item's state from its log, rebuild() all of them.
 */
final class Interactions
{
    public const SOURCES = ['tutor', 'card', 'import', 'activity', 'simulation'];

    public const AMENDERS = ['teacher', 'observer', 'human'];

    private const UUID_RE = '/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/';

    public function __construct(
        private readonly \PDO $pdo,
        private readonly Items $items,
    ) {
    }

    /**
     * Record one interaction. Idempotent on uuid. For keyed exercises
     * the outcomes may be omitted: the API grades `exercise` against
     * `response` and applies the outcome to every listed item.
     *
     * @param array<string, mixed> $body
     * @return array{0: int, 1: array<string, mixed>} [status, payload]
     */
    public function record(int $userId, array $body): array
    {
        $uuid = $body['uuid'] ?? self::uuid();
        if (!is_string($uuid) || preg_match(self::UUID_RE, $uuid) !== 1) {
            throw new ApiError(400, 'validation', 'uuid must be a lowercase RFC 4122 UUID');
        }
        $stmt = $this->pdo->prepare('SELECT id, user_id, graded_match FROM interactions WHERE uuid = ?');
        $stmt->execute([$uuid]);
        $existing = $stmt->fetch();
        if ($existing !== false) {
            if ((int) $existing['user_id'] !== $userId) {
                throw new ApiError(409, 'conflict', 'uuid already used');
            }
            return [200, $this->result($userId, (int) $existing['id'], $uuid, false, $existing['graded_match'], [])];
        }

        $mode = $body['mode'] ?? null;
        if (!in_array($mode, MemoryModel::MODES, true)) {
            throw new ApiError(400, 'validation', 'mode must be one of ' . implode(', ', MemoryModel::MODES));
        }
        $source = $body['source'] ?? 'tutor';
        if (!in_array($source, self::SOURCES, true)) {
            throw new ApiError(400, 'validation', 'source must be one of ' . implode(', ', self::SOURCES));
        }
        $at = isset($body['occurred_at']) ? Time::parseIso($body['occurred_at'], 'occurred_at') : Time::now();
        $sessionId = $body['session_id'] ?? null;
        if ($sessionId !== null && (!is_string($sessionId) || strlen($sessionId) > 64)) {
            throw new ApiError(400, 'validation', 'session_id must be a string of at most 64 characters');
        }
        $cardId = $body['card_id'] ?? null;
        if ($cardId !== null) {
            if (!is_int($cardId)) {
                throw new ApiError(400, 'validation', 'card_id must be an integer');
            }
            $stmt = $this->pdo->prepare('SELECT id FROM cards WHERE id = ? AND user_id = ?');
            $stmt->execute([$cardId, $userId]);
            if ($stmt->fetch() === false) {
                throw new ApiError(404, 'not_found', "Card $cardId not found");
            }
        }
        $hinted = $body['hinted'] ?? false;
        if (!is_bool($hinted)) {
            throw new ApiError(400, 'validation', 'hinted must be a boolean');
        }
        $exercise = $body['exercise'] ?? null;
        $response = $body['response'] ?? null;
        foreach (['exercise' => $exercise, 'response' => $response] as $name => $value) {
            if ($value !== null && (!is_array($value) || ($value !== [] && array_is_list($value)))) {
                throw new ApiError(400, 'validation', "$name must be an object");
            }
        }
        $callerGrader = $body['grader'] ?? null;
        if ($callerGrader !== null && (!is_string($callerGrader) || preg_match('/^[a-z0-9@._-]{1,32}$/', $callerGrader) !== 1)) {
            throw new ApiError(400, 'validation', 'grader must be a short label such as teacher or self');
        }
        foreach (['prompt_md', 'response_md', 'feedback_md'] as $field) {
            if (isset($body[$field]) && !is_string($body[$field])) {
                throw new ApiError(400, 'validation', "$field must be a string");
            }
        }

        $entries = $this->itemEntries($userId, $body['items'] ?? null);
        $grade = null;
        $needsGrade = array_filter($entries, fn ($e) => $e['outcome'] === null) !== [];
        if ($mode === 'introduce') {
            if (array_filter($entries, fn ($e) => $e['outcome'] !== null) !== []) {
                throw new ApiError(400, 'validation', 'introduce records no outcomes');
            }
        } elseif ($needsGrade) {
            if ($exercise === null || $response === null || !in_array($exercise['kind'] ?? null, Grader::KEYED, true)) {
                throw new ApiError(400, 'validation',
                    'every item needs an outcome, unless a keyed exercise (mc, match, text) and its response are given');
            }
            $grade = Grader::grade($exercise, $response);
            foreach ($entries as &$entry) {
                $entry['outcome'] ??= $grade['outcome'];
            }
            unset($entry);
        }

        $before = [];
        $this->pdo->beginTransaction();
        try {
            $this->pdo->prepare(
                'INSERT INTO interactions (uuid, user_id, session_id, card_id, source, mode, exercise, response,
                        grader, graded_match, prompt_md, response_md, feedback_md, hinted, occurred_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'
            )->execute([
                $uuid, $userId, $sessionId, $cardId, $source, $mode,
                $exercise === null ? null : Items::jsonObject($exercise),
                $response === null ? null : Items::jsonObject($response),
                $grade['grader'] ?? $callerGrader, $grade['match'] ?? null,
                $body['prompt_md'] ?? null, $body['response_md'] ?? null, $body['feedback_md'] ?? null,
                $hinted ? 1 : 0, Time::toDb($at),
            ]);
            $interactionId = (int) $this->pdo->lastInsertId();
            foreach ($entries as $entry) {
                $before[$entry['id']] = $this->mastery($userId, $entry['id']);
                $this->pdo->prepare(
                    'INSERT INTO interaction_items (interaction_id, item_id, origin_item_id, outcome, note) VALUES (?, ?, ?, ?, ?)'
                )->execute([$interactionId, $entry['id'], $entry['id'], $entry['outcome'], $entry['note']]);
                $this->apply($userId, $entry['id'], $mode, $entry['outcome'], $hinted, $at);
            }
            $this->pdo->commit();
        } catch (\Throwable $e) {
            $this->pdo->rollBack();
            throw $e;
        }
        $payload = $this->result($userId, $interactionId, $uuid, true, $grade['match'] ?? null, $before);
        if ($grade !== null) {
            $payload['correct'] = $grade['match'] !== 'wrong';
            $payload['expected'] = $grade['expected'];
        }
        return [201, $payload];
    }

    /**
     * Append amendments (corrections never edit the log) and replay
     * the affected items.
     *
     * @param array<string, mixed> $body
     */
    public function amend(int $userId, string $uuid, array $body): array
    {
        $stmt = $this->pdo->prepare('SELECT id, graded_match FROM interactions WHERE uuid = ? AND user_id = ?');
        $stmt->execute([$uuid, $userId]);
        $interaction = $stmt->fetch();
        if ($interaction === false) {
            throw new ApiError(404, 'not_found', "Interaction $uuid not found");
        }
        $reason = $body['reason'] ?? null;
        $by = $body['by'] ?? null;
        if (!is_string($reason) || trim($reason) === '') {
            throw new ApiError(400, 'validation', 'reason is required');
        }
        if (!in_array($by, self::AMENDERS, true)) {
            throw new ApiError(400, 'validation', 'by must be one of ' . implode(', ', self::AMENDERS));
        }
        $entries = $this->itemEntries($userId, $body['items'] ?? null);
        $before = [];
        $this->pdo->beginTransaction();
        try {
            foreach ($entries as $entry) {
                $stmt = $this->pdo->prepare('SELECT origin_item_id FROM interaction_items WHERE interaction_id = ? AND item_id = ?');
                $stmt->execute([$interaction['id'], $entry['id']]);
                $origin = $stmt->fetchColumn();
                if ($origin === false) {
                    throw new ApiError(400, 'validation', "Interaction $uuid has no outcome for {$entry['ref']}");
                }
                $before[$entry['id']] = $this->mastery($userId, $entry['id']);
                $this->pdo->prepare(
                    'INSERT INTO interaction_amendments (interaction_id, item_id, outcome, reason, amended_by) VALUES (?, ?, ?, ?, ?)'
                )->execute([$interaction['id'], (int) $origin, $entry['outcome'], $reason, $by]);
                $this->replay($userId, $entry['id']);
            }
            $this->pdo->commit();
        } catch (\Throwable $e) {
            $this->pdo->rollBack();
            throw $e;
        }
        return $this->result($userId, (int) $interaction['id'], $uuid, false, $interaction['graded_match'], $before);
    }

    /**
     * Card answers feed the profile: one interaction per review, for
     * every item linked to the card.
     */
    public function recordCardReview(int $userId, int $cardId, string $cardType, int $reviewId, string $match): void
    {
        $stmt = $this->pdo->prepare('SELECT item_id FROM card_items WHERE card_id = ?');
        $stmt->execute([$cardId]);
        $itemIds = array_map('intval', $stmt->fetchAll(\PDO::FETCH_COLUMN));
        if ($itemIds === []) {
            return;
        }
        $at = Time::now();
        $mode = self::cardMode($cardType);
        $outcome = ['exact' => 'good', 'typo' => 'hard', 'wrong' => 'fail'][$match];
        $interactionId = $this->insertCardInteraction($userId, $cardId, $reviewId, $mode, $match, $at);
        foreach ($itemIds as $itemId) {
            $itemId = $this->currentId($itemId);
            $this->pdo->prepare(
                'INSERT IGNORE INTO interaction_items (interaction_id, item_id, origin_item_id, outcome) VALUES (?, ?, ?, ?)'
            )->execute([$interactionId, $itemId, $itemId, $outcome]);
            $this->apply($userId, $itemId, $mode, $outcome, false, $at);
        }
    }

    /**
     * Link a card to an item; the first link backfills the card's past
     * reviews as interactions with their original time.
     */
    public function linkCard(int $userId, int $cardId, string|int $ref): void
    {
        $stmt = $this->pdo->prepare('SELECT type FROM cards WHERE id = ? AND user_id = ?');
        $stmt->execute([$cardId, $userId]);
        $type = $stmt->fetchColumn();
        if ($type === false) {
            throw new ApiError(404, 'not_found', "Card $cardId not found");
        }
        $itemId = (int) $this->items->resolve($userId, $ref)['id'];
        $this->pdo->beginTransaction();
        try {
            $stmt = $this->pdo->prepare('INSERT IGNORE INTO card_items (card_id, item_id) VALUES (?, ?)');
            $stmt->execute([$cardId, $itemId]);
            if ($stmt->rowCount() > 0) {
                $this->backfill($userId, $cardId, (string) $type, $itemId);
            }
            $this->pdo->commit();
        } catch (\Throwable $e) {
            $this->pdo->rollBack();
            throw $e;
        }
    }

    public function unlinkCard(int $userId, int $cardId, string|int $ref): void
    {
        $itemId = (int) $this->items->resolve($userId, $ref)['id'];
        $stmt = $this->pdo->prepare('DELETE ci FROM card_items ci JOIN cards c ON c.id = ci.card_id WHERE ci.card_id = ? AND ci.item_id = ? AND c.user_id = ?');
        $stmt->execute([$cardId, $itemId, $userId]);
    }

    /**
     * @param array{item?: string, session_id?: string, since?: string} $filters
     * @return array{items: list<array<string, mixed>>, next_cursor: ?string}
     */
    public function history(int $userId, array $filters, int $limit, ?string $cursor): array
    {
        $where = ['i.user_id = ?'];
        $params = [$userId];
        if (isset($filters['item'])) {
            $where[] = 'i.id IN (SELECT interaction_id FROM interaction_items WHERE item_id = ?)';
            $params[] = (int) $this->items->resolve($userId, $filters['item'])['id'];
        }
        if (isset($filters['session_id'])) {
            $where[] = 'i.session_id = ?';
            $params[] = $filters['session_id'];
        }
        if (isset($filters['since'])) {
            $where[] = 'i.occurred_at >= ?';
            $params[] = Time::toDb(Time::parseIso($filters['since'], 'since'));
        }
        if ($cursor !== null) {
            $decoded = base64_decode($cursor, true);
            if ($decoded === false || filter_var($decoded, FILTER_VALIDATE_INT) === false) {
                throw new ApiError(400, 'validation', 'Invalid cursor');
            }
            $where[] = 'i.id > ?';
            $params[] = (int) $decoded;
        }
        $stmt = $this->pdo->prepare('SELECT i.* FROM interactions i WHERE ' . implode(' AND ', $where) . ' ORDER BY i.id LIMIT ' . ($limit + 1));
        $stmt->execute($params);
        $rows = $stmt->fetchAll();
        $next = null;
        if (count($rows) > $limit) {
            $rows = array_slice($rows, 0, $limit);
            $next = base64_encode((string) end($rows)['id']);
        }
        return ['items' => array_map(fn ($r) => $this->view($r), $rows), 'next_cursor' => $next];
    }

    /**
     * Full export view of one interaction (raw evidence, per-item
     * outcomes with their origin, amendments).
     *
     * @param array<string, mixed> $row
     * @return array<string, mixed>
     */
    public function view(array $row): array
    {
        $stmt = $this->pdo->prepare(
            "SELECT CONCAT(it.space, '/', it.`key`) AS ref, CONCAT(o.space, '/', o.`key`) AS origin, ii.outcome, ii.note
             FROM interaction_items ii JOIN items it ON it.id = ii.item_id JOIN items o ON o.id = ii.origin_item_id
             WHERE ii.interaction_id = ? ORDER BY ref"
        );
        $stmt->execute([$row['id']]);
        $items = $stmt->fetchAll();
        $stmt = $this->pdo->prepare(
            "SELECT CONCAT(o.space, '/', o.`key`) AS origin, a.outcome, a.reason, a.amended_by, a.created_at
             FROM interaction_amendments a JOIN items o ON o.id = a.item_id WHERE a.interaction_id = ? ORDER BY a.id"
        );
        $stmt->execute([$row['id']]);
        $amendments = array_map(fn ($a) => [
            'origin' => $a['origin'], 'outcome' => $a['outcome'], 'reason' => $a['reason'],
            'by' => $a['amended_by'], 'created_at' => Time::iso($a['created_at']),
        ], $stmt->fetchAll());
        return [
            'uuid' => $row['uuid'],
            'occurred_at' => Time::iso($row['occurred_at']),
            'session_id' => $row['session_id'],
            'card_id' => $row['card_id'] === null ? null : (int) $row['card_id'],
            'source' => $row['source'],
            'mode' => $row['mode'],
            'exercise' => $row['exercise'] === null ? null : json_decode($row['exercise']),
            'response' => $row['response'] === null ? null : json_decode($row['response']),
            'grader' => $row['grader'],
            'match' => $row['graded_match'],
            'prompt_md' => $row['prompt_md'],
            'response_md' => $row['response_md'],
            'feedback_md' => $row['feedback_md'],
            'hinted' => (bool) $row['hinted'],
            'items' => $items,
            'amendments' => $amendments,
        ];
    }

    // --- states ---------------------------------------------------------

    /**
     * Recompute one item's state from its log (latest amendment per
     * (interaction, origin item) wins). Flags are kept.
     */
    public function replay(int $userId, int $itemId): void
    {
        $stmt = $this->pdo->prepare(
            'SELECT i.occurred_at, i.mode, i.hinted, ii.outcome,
                    (SELECT COUNT(*) FROM interaction_amendments a
                     WHERE a.interaction_id = ii.interaction_id AND a.item_id = ii.origin_item_id) AS amended,
                    (SELECT a.outcome FROM interaction_amendments a
                     WHERE a.interaction_id = ii.interaction_id AND a.item_id = ii.origin_item_id
                     ORDER BY a.id DESC LIMIT 1) AS amended_outcome
             FROM interaction_items ii JOIN interactions i ON i.id = ii.interaction_id
             WHERE ii.item_id = ? AND i.user_id = ?
             ORDER BY i.occurred_at, i.id'
        );
        $stmt->execute([$itemId, $userId]);
        $state = null;
        foreach ($stmt->fetchAll() as $event) {
            $outcome = (int) $event['amended'] > 0 ? $event['amended_outcome'] : $event['outcome'];
            if ($event['mode'] !== 'introduce' && $outcome === null) {
                continue;   // an amendment can void an outcome
            }
            $state = MemoryModel::step(
                $state,
                $event['mode'],
                MemoryModel::capHinted($outcome, (bool) $event['hinted']),
                Time::fromDb($event['occurred_at'])
            );
        }
        $this->writeState($userId, $itemId, $state);
    }

    /** Recompute every state of the user; returns the number of items replayed. */
    public function rebuild(int $userId): int
    {
        $stmt = $this->pdo->prepare(
            'SELECT DISTINCT ii.item_id FROM interaction_items ii JOIN interactions i ON i.id = ii.interaction_id WHERE i.user_id = ?
             UNION SELECT item_id FROM item_states WHERE user_id = ?'
        );
        $stmt->execute([$userId, $userId]);
        $ids = array_map('intval', $stmt->fetchAll(\PDO::FETCH_COLUMN));
        $this->pdo->beginTransaction();
        try {
            foreach ($ids as $id) {
                $this->replay($userId, $id);
            }
            $this->pdo->commit();
        } catch (\Throwable $e) {
            $this->pdo->rollBack();
            throw $e;
        }
        return count($ids);
    }

    /** Apply one event incrementally, or replay when it arrives out of order. */
    private function apply(int $userId, int $itemId, string $mode, ?string $outcome, bool $hinted, float $at): void
    {
        $stmt = $this->pdo->prepare('SELECT * FROM item_states WHERE user_id = ? AND item_id = ?');
        $stmt->execute([$userId, $itemId]);
        $row = $stmt->fetch();
        $state = null;
        if ($row !== false && $row['stability'] !== null) {
            if ($row['model'] !== MemoryModel::VERSION || Time::fromDb($row['last_seen_at']) > $at) {
                $this->replay($userId, $itemId);
                return;
            }
            $state = [
                'stability' => (float) $row['stability'], 'difficulty' => (float) $row['difficulty'],
                'first_seen_at' => Time::fromDb($row['first_seen_at']), 'last_seen_at' => Time::fromDb($row['last_seen_at']),
                'reps' => (int) $row['reps'], 'lapses' => (int) $row['lapses'], 'best_mode' => $row['best_mode'],
            ];
        }
        $this->writeState($userId, $itemId, MemoryModel::step($state, $mode, MemoryModel::capHinted($outcome, $hinted), $at));
    }

    /** @param array<string, mixed>|null $state */
    private function writeState(int $userId, int $itemId, ?array $state): void
    {
        if ($state === null) {
            $this->pdo->prepare(
                'UPDATE item_states SET model = ?, stability = NULL, difficulty = NULL, first_seen_at = NULL,
                        last_seen_at = NULL, reps = 0, lapses = 0, best_mode = NULL
                 WHERE user_id = ? AND item_id = ?'
            )->execute([MemoryModel::VERSION, $userId, $itemId]);
            return;
        }
        $values = [
            MemoryModel::VERSION, $state['stability'], $state['difficulty'],
            Time::toDb($state['first_seen_at']), Time::toDb($state['last_seen_at']),
            $state['reps'], $state['lapses'], $state['best_mode'],
        ];
        $this->pdo->prepare(
            "INSERT INTO item_states (user_id, item_id, model, stability, difficulty, first_seen_at, last_seen_at,
                    reps, lapses, best_mode, note)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '')
             ON DUPLICATE KEY UPDATE model = ?, stability = ?, difficulty = ?, first_seen_at = ?, last_seen_at = ?,
                    reps = ?, lapses = ?, best_mode = ?"
        )->execute([$userId, $itemId, ...$values, ...$values]);
    }

    private function mastery(int $userId, int $itemId): int
    {
        $stmt = $this->pdo->prepare('SELECT stability, best_mode FROM item_states WHERE user_id = ? AND item_id = ?');
        $stmt->execute([$userId, $itemId]);
        $row = $stmt->fetch();
        if ($row === false) {
            return 0;
        }
        return MemoryModel::mastery($row['stability'] === null ? null : (float) $row['stability'], $row['best_mode']);
    }

    // --- helpers ------------------------------------------------------------

    /**
     * @return list<array{id: int, ref: string, outcome: ?string, note: ?string}>
     */
    private function itemEntries(int $userId, mixed $items): array
    {
        if (!is_array($items) || $items === [] || !array_is_list($items)) {
            throw new ApiError(400, 'validation', 'items must be a non-empty list of {ref, outcome?, note?}');
        }
        $entries = [];
        $seen = [];
        foreach ($items as $entry) {
            $ref = $entry['ref'] ?? null;
            $outcome = $entry['outcome'] ?? null;
            $note = $entry['note'] ?? null;
            if (!is_string($ref) && !is_int($ref)) {
                throw new ApiError(400, 'validation', 'each item needs a ref');
            }
            if ($outcome !== null && !in_array($outcome, MemoryModel::OUTCOMES, true)) {
                throw new ApiError(400, 'validation', 'outcome must be one of ' . implode(', ', MemoryModel::OUTCOMES));
            }
            if ($note !== null && !is_string($note)) {
                throw new ApiError(400, 'validation', 'note must be a string');
            }
            $row = $this->items->resolve($userId, $ref);
            $id = (int) $row['id'];
            if (isset($seen[$id])) {
                throw new ApiError(400, 'validation', "Item $ref is listed twice");
            }
            $seen[$id] = true;
            $entries[] = ['id' => $id, 'ref' => $row['space'] . '/' . $row['key'], 'outcome' => $outcome, 'note' => $note];
        }
        return $entries;
    }

    /**
     * @param array<int, int> $before mastery before, by item id
     * @return array<string, mixed>
     */
    private function result(int $userId, int $interactionId, string $uuid, bool $created, ?string $match, array $before): array
    {
        $stmt = $this->pdo->prepare(
            'SELECT ii.item_id, ii.outcome, i.hinted,
                    (SELECT a.outcome FROM interaction_amendments a
                     WHERE a.interaction_id = ii.interaction_id AND a.item_id = ii.origin_item_id
                     ORDER BY a.id DESC LIMIT 1) AS amended_outcome,
                    (SELECT COUNT(*) FROM interaction_amendments a
                     WHERE a.interaction_id = ii.interaction_id AND a.item_id = ii.origin_item_id) AS amended
             FROM interaction_items ii JOIN interactions i ON i.id = ii.interaction_id
             WHERE ii.interaction_id = ? ORDER BY ii.item_id'
        );
        $stmt->execute([$interactionId]);
        $items = [];
        foreach ($stmt->fetchAll() as $r) {
            $row = $this->items->resolve($userId, (int) $r['item_id'], false);
            $state = Items::stateView($row, Time::now());
            $entry = [
                'ref' => $row['space'] . '/' . $row['key'],
                // the effective outcome: a hinted answer counts at most as hard
                'outcome' => MemoryModel::capHinted(
                    (int) $r['amended'] > 0 ? $r['amended_outcome'] : $r['outcome'],
                    (bool) $r['hinted']
                ),
                'state' => $state,
            ];
            if (isset($before[(int) $r['item_id']])) {
                $entry['mastery_before'] = $before[(int) $r['item_id']];
            }
            $items[] = $entry;
        }
        return ['uuid' => $uuid, 'created' => $created, 'match' => $match, 'items' => $items];
    }

    private function backfill(int $userId, int $cardId, string $type, int $itemId): void
    {
        $stmt = $this->pdo->prepare('SELECT id, was_correct, answered_at FROM reviews WHERE card_id = ? AND user_id = ? ORDER BY answered_at, id');
        $stmt->execute([$cardId, $userId]);
        $mode = self::cardMode($type);
        foreach ($stmt->fetchAll() as $review) {
            $outcome = $review['was_correct'] ? 'good' : 'fail';
            $find = $this->pdo->prepare('SELECT id FROM interactions WHERE review_id = ?');
            $find->execute([$review['id']]);
            $interactionId = $find->fetchColumn();
            if ($interactionId === false) {
                $interactionId = $this->insertCardInteraction(
                    $userId, $cardId, (int) $review['id'], $mode, null, Time::fromDb($review['answered_at'])
                );
            }
            $this->pdo->prepare(
                'INSERT IGNORE INTO interaction_items (interaction_id, item_id, origin_item_id, outcome) VALUES (?, ?, ?, ?)'
            )->execute([(int) $interactionId, $itemId, $itemId, $outcome]);
        }
        $this->replay($userId, $itemId);
    }

    private function insertCardInteraction(int $userId, int $cardId, int $reviewId, string $mode, ?string $match, float $at): int
    {
        $this->pdo->prepare(
            "INSERT INTO interactions (uuid, user_id, card_id, review_id, source, mode, grader, graded_match, occurred_at)
             VALUES (?, ?, ?, ?, 'card', ?, 'card', ?, ?)"
        )->execute([self::uuid(), $userId, $cardId, $reviewId, $mode, $match, Time::toDb($at)]);
        return (int) $this->pdo->lastInsertId();
    }

    private function currentId(int $itemId): int
    {
        for ($hops = 0; $hops < 20; $hops++) {
            $stmt = $this->pdo->prepare('SELECT merged_into FROM items WHERE id = ?');
            $stmt->execute([$itemId]);
            $next = $stmt->fetchColumn();
            if ($next === null || $next === false) {
                break;
            }
            $itemId = (int) $next;
        }
        return $itemId;
    }

    private static function cardMode(string $cardType): string
    {
        return in_array($cardType, ['mc', 'match'], true) ? 'recognize' : 'recall';
    }

    public static function uuid(): string
    {
        $b = random_bytes(16);
        $b[6] = chr((ord($b[6]) & 0x0f) | 0x40);
        $b[8] = chr((ord($b[8]) & 0x3f) | 0x80);
        return vsprintf('%s%s-%s-%s-%s-%s%s%s', str_split(bin2hex($b), 4));
    }
}

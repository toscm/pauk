<?php

declare(strict_types=1);

namespace Pauk\Repo;

use Pauk\ApiError;
use Pauk\Knowledge\MemoryModel;
use Pauk\Knowledge\Norm;
use Pauk\Knowledge\Time;
use Pauk\Text;

/**
 * Knowledge items (docs/tutor.md section 4): identity, duplicate
 * protocol, aliases, links, subjects, flags. Evidence and memory
 * states live in Interactions; merges in Merges.
 */
final class Items
{
    public const RELS = ['form_of', 'requires', 'part_of', 'related'];

    private const STRONG_IDS = ['doi', 'isbn', 'wikidata'];

    private const MAX_CANDIDATES = 10;

    private const SELECT = 'SELECT i.*, s.model, s.stability, s.difficulty, s.first_seen_at, s.last_seen_at,
                s.reps, s.lapses, s.best_mode, s.status, s.note,
                CONCAT(m.space, \'/\', m.`key`) AS merged_ref
         FROM items i
         LEFT JOIN item_states s ON s.item_id = i.id AND s.user_id = i.user_id
         LEFT JOIN items m ON m.id = i.merged_into';

    public function __construct(
        private readonly \PDO $pdo,
        private readonly Dirs $dirs,
    ) {
    }

    // --- lookup ---------------------------------------------------------

    /**
     * Resolve a ref (`space/key`, an alias in that space, or a numeric
     * id) to an item row; merged items resolve to the item they were
     * merged into.
     *
     * @return array<string, mixed>
     */
    public function resolve(int $userId, string|int $ref, bool $followMerges = true): array
    {
        $row = null;
        if (is_int($ref) || ctype_digit($ref)) {
            $row = $this->fetchOne('i.user_id = ? AND i.id = ?', [$userId, (int) $ref]);
        } else {
            [$space, $key] = self::parseRef($ref);
            $row = $this->fetchOne('i.user_id = ? AND i.space = ? AND i.`key` = ?', [$userId, $space, $key]);
            if ($row === null) {
                $stmt = $this->pdo->prepare(
                    'SELECT item_id FROM item_aliases WHERE user_id = ? AND space = ? AND alias = ?'
                );
                $stmt->execute([$userId, $space, $key]);
                $id = $stmt->fetchColumn();
                if ($id !== false) {
                    $row = $this->fetchOne('i.id = ?', [(int) $id]);
                }
            }
        }
        if ($row === null) {
            throw new ApiError(404, 'not_found', "Item $ref not found");
        }
        $hops = 0;
        while ($followMerges && $row['merged_into'] !== null && $hops++ < 20) {
            $row = $this->fetchOne('i.id = ?', [(int) $row['merged_into']]);
        }
        return $row;
    }

    /** @return array{0: string, 1: string} */
    public static function parseRef(string $ref): array
    {
        $parts = explode('/', $ref, 2);
        if (count($parts) !== 2 || !Norm::isValidSpace($parts[0]) || $parts[1] === '') {
            throw new ApiError(400, 'validation', "Invalid item ref '$ref' (expected space/key)");
        }
        return [$parts[0], $parts[1]];
    }

    /** @return array<string, mixed> */
    public function get(int $userId, string|int $ref): array
    {
        return $this->detail($userId, $this->resolve($userId, $ref));
    }

    /**
     * @param array{space?: string, dir?: int, recursive?: bool, kind?: string, q?: string,
     *              status?: string, archived?: bool} $filters
     * @return array{items: list<array<string, mixed>>, next_cursor: ?string}
     */
    public function list(int $userId, array $filters, int $limit, ?string $cursor): array
    {
        [$where, $params] = $this->filterSql($userId, $filters);
        if ($cursor !== null) {
            $decoded = base64_decode($cursor, true);
            if ($decoded === false || filter_var($decoded, FILTER_VALIDATE_INT) === false) {
                throw new ApiError(400, 'validation', 'Invalid cursor');
            }
            $where[] = 'i.id > ?';
            $params[] = (int) $decoded;
        }
        $stmt = $this->pdo->prepare(
            self::SELECT . ' WHERE ' . implode(' AND ', $where) . ' ORDER BY i.id LIMIT ' . ($limit + 1)
        );
        $stmt->execute($params);
        $rows = $stmt->fetchAll();
        $next = null;
        if (count($rows) > $limit) {
            $rows = array_slice($rows, 0, $limit);
            $next = base64_encode((string) end($rows)['id']);
        }
        $now = Time::now();
        return ['items' => array_map(fn ($r) => self::view($r, $now), $rows), 'next_cursor' => $next];
    }

    /**
     * All matching item rows (no pagination), for profile and selection.
     *
     * @return list<array<string, mixed>>
     */
    public function rows(int $userId, array $filters): array
    {
        [$where, $params] = $this->filterSql($userId, $filters);
        $stmt = $this->pdo->prepare(self::SELECT . ' WHERE ' . implode(' AND ', $where) . ' ORDER BY i.id');
        $stmt->execute($params);
        return $stmt->fetchAll();
    }

    // --- create (duplicate protocol) -------------------------------------

    /**
     * Create an item, or return the existing one (exact identity), or
     * refuse with 409 possible_duplicates until every candidate is
     * answered with same_as or distinct_from (docs/tutor.md 4.10).
     *
     * @param array<string, mixed> $body
     * @return array{0: int, 1: array<string, mixed>} [status, payload]
     */
    public function create(int $userId, array $body): array
    {
        $item = $this->validate($body, false);
        $space = $item['space'];
        // dry_run runs the whole protocol but keeps nothing: same_as
        // skips the aliases, a create is rolled back after the preview
        $dryRun = $body['dry_run'] ?? false;
        if (!is_bool($dryRun)) {
            throw new ApiError(400, 'validation', 'dry_run must be a boolean');
        }

        $existing = $this->exactIdentity($userId, $item);
        if ($existing !== null) {
            [$row, $via] = $existing;
            return [200, ['created' => false, 'via' => $via, 'item' => $this->detail($userId, $row)]];
        }

        if (isset($body['same_as'])) {
            if (!is_string($body['same_as'])) {
                throw new ApiError(400, 'validation', 'same_as must be an item ref');
            }
            $target = $this->resolve($userId, $body['same_as']);
            $reason = is_string($body['reason'] ?? null) ? $body['reason'] : null;
            if (!$dryRun) {
                $this->addAlias($userId, $space, $item['key'], $item['label_md'], (int) $target['id'], 'same_as', $reason);
            }
            $slug = Norm::slug($item['label_md']);
            if (!$dryRun && $slug !== '' && $slug !== $item['key']) {
                $this->addAlias($userId, $space, $slug, $item['label_md'], (int) $target['id'], 'same_as', $reason);
            }
            $target = $this->resolve($userId, (int) $target['id']);
            return [200, ['created' => false, 'via' => 'same_as', 'item' => $this->detail($userId, $target)]];
        }

        $distinct = [];
        foreach ($this->listOfStrings($body, 'distinct_from') as $ref) {
            $distinct[(int) $this->resolve($userId, $ref)['id']] = true;
        }
        $candidates = array_values(array_filter(
            $this->candidates($userId, $item),
            fn ($c) => !isset($distinct[$c['id']])
        ));
        if ($candidates !== []) {
            throw new ApiError(409, 'possible_duplicates',
                'Similar items exist; resend with same_as or distinct_from (+ reason) covering every candidate',
                ['candidates' => array_map(fn ($c) => [
                    'ref' => $c['space'] . '/' . $c['key'],
                    'kind' => $c['kind'],
                    'label_md' => $c['label_md'],
                    'gloss_md' => $c['gloss_md'],
                    'reason' => $c['reason'],
                ], $candidates)]);
        }
        if ($distinct !== [] && !is_string($body['reason'] ?? null)) {
            throw new ApiError(400, 'validation', 'distinct_from needs a reason');
        }

        $this->pdo->beginTransaction();
        try {
            $id = $this->insert($userId, $item);
            foreach (array_keys($distinct) as $otherId) {
                $this->insertLink($id, $otherId, 'related', mb_substr((string) $body['reason'], 0, 255));
            }
            $this->applyRelations($userId, $id, $item, $body);
            if ($dryRun) {
                $preview = $this->get($userId, $id);
                unset($preview['id']);
                $this->pdo->rollBack();
                return [200, ['created' => false, 'would_create' => true, 'item' => $preview]];
            }
            $this->pdo->commit();
        } catch (\Throwable $e) {
            $this->pdo->rollBack();
            throw $e;
        }
        return [201, ['created' => true, 'item' => $this->get($userId, $id)]];
    }

    /**
     * Upsert many items by exact identity; never blocks on fuzzy
     * candidates (a lexicon has thousands of legitimate neighbours).
     *
     * @param mixed $items
     * @return array<string, mixed>
     */
    public function bulk(int $userId, mixed $items): array
    {
        if (!is_array($items) || !array_is_list($items) || count($items) > 500) {
            throw new ApiError(400, 'validation', 'items must be a list of at most 500 items');
        }
        $validated = [];
        foreach ($items as $i => $body) {
            if (!is_array($body)) {
                throw new ApiError(400, 'validation', "items[$i] must be an object");
            }
            try {
                $validated[] = [$this->validate($body, false), $body];
            } catch (ApiError $e) {
                throw new ApiError($e->status, $e->errorCode, "items[$i]: " . $e->getMessage());
            }
        }
        $result = ['created' => 0, 'updated' => 0, 'unchanged' => 0, 'refs' => [],
                   'conflicts' => [], 'possible_duplicates' => [], 'unresolved_links' => []];
        $this->pdo->beginTransaction();
        try {
            $ids = [];
            foreach ($validated as [$item, $body]) {
                $existing = $this->exactIdentity($userId, $item);
                if ($existing === null) {
                    $id = $this->insert($userId, $item);
                    $result['created']++;
                    foreach ($this->teacherTwins($userId, $item, $id) as $ref) {
                        $result['possible_duplicates'][] = ['ref' => "{$item['space']}/{$item['key']}", 'similar' => $ref];
                    }
                } else {
                    $row = $existing[0];
                    $id = (int) $row['id'];
                    $origin = json_decode($row['attrs'], true)['origin'] ?? null;
                    if ($origin === 'teacher' && Norm::norm($row['gloss_md']) !== Norm::norm($item['gloss_md'])) {
                        $result['conflicts'][] = [
                            'ref' => "{$row['space']}/{$row['key']}",
                            'existing_gloss' => $row['gloss_md'],
                            'import_gloss' => $item['gloss_md'],
                        ];
                        $ids[] = [$id, $item, $body];
                        $result['refs'][] = "{$row['space']}/{$row['key']}";
                        continue;
                    }
                    $result[$this->updateFields($row, $item) ? 'updated' : 'unchanged']++;
                }
                $ids[] = [$id, $item, $body];
                $result['refs'][] = "{$item['space']}/{$item['key']}";
            }
            // relations after all rows exist, so items may link forward
            foreach ($ids as [$id, $item, $body]) {
                $result['unresolved_links'] = array_merge(
                    $result['unresolved_links'],
                    $this->applyRelations($userId, $id, $item, $body, false)
                );
                foreach ($body['aliases'] ?? [] as $alias) {
                    $slug = is_string($alias) ? Norm::slug($alias) : '';
                    if ($slug !== '' && $slug !== $item['key']) {
                        $this->addAlias($userId, $item['space'], $slug, $alias, $id, 'import', null);
                    }
                }
            }
            $this->pdo->commit();
        } catch (\Throwable $e) {
            $this->pdo->rollBack();
            throw $e;
        }
        return $result;
    }

    // --- update ---------------------------------------------------------

    /** @param array<string, mixed> $body */
    public function update(int $userId, string|int $ref, array $body): array
    {
        $row = $this->resolve($userId, $ref);
        $merged = [
            'space' => $row['space'],
            'key' => $body['key'] ?? $row['key'],
            'kind' => $body['kind'] ?? $row['kind'],
            'label_md' => $body['label_md'] ?? $row['label_md'],
            'gloss_md' => $body['gloss_md'] ?? $row['gloss_md'],
            'body_md' => $body['body_md'] ?? $row['body_md'],
            'attrs' => $body['attrs'] ?? json_decode($row['attrs'], true),
            'priority' => $body['priority'] ?? (int) $row['priority'],
            'level' => array_key_exists('level', $body) ? $body['level'] : ($row['level'] === null ? null : (int) $row['level']),
        ];
        $item = $this->validate($merged, true);
        $this->pdo->beginTransaction();
        try {
            if ($item['key'] !== $row['key']) {
                $stmt = $this->pdo->prepare('SELECT id FROM items WHERE user_id = ? AND space = ? AND `key` = ?');
                $stmt->execute([$userId, $row['space'], $item['key']]);
                if ($stmt->fetchColumn() !== false) {
                    throw new ApiError(409, 'conflict', "Key {$row['space']}/{$item['key']} already exists");
                }
                $this->pdo->prepare('DELETE FROM item_aliases WHERE user_id = ? AND space = ? AND alias = ?')
                    ->execute([$userId, $row['space'], $item['key']]);
                $this->pdo->prepare('UPDATE items SET `key` = ? WHERE id = ?')->execute([$item['key'], $row['id']]);
                $this->addAlias($userId, $row['space'], $row['key'], $row['label_md'], (int) $row['id'], 'rename', null);
            }
            $this->updateFields($row, $item);
            $this->pdo->commit();
        } catch (\Throwable $e) {
            $this->pdo->rollBack();
            throw $e;
        }
        return $this->get($userId, (int) $row['id']);
    }

    public function setArchived(int $userId, string|int $ref, bool $archived): array
    {
        $row = $this->resolve($userId, $ref, false);
        if (!$archived && $row['merged_into'] !== null) {
            throw new ApiError(409, 'conflict', 'Item was merged; use unmerge instead');
        }
        $this->pdo->prepare('UPDATE items SET archived_at = ' . ($archived ? 'COALESCE(archived_at, NOW())' : 'NULL') . ' WHERE id = ?')
            ->execute([$row['id']]);
        return $this->get($userId, (int) $row['id']);
    }

    /** @param array<string, mixed> $body */
    public function setFlags(int $userId, string|int $ref, array $body): array
    {
        $row = $this->resolve($userId, $ref);
        $status = $body['status'] ?? null;
        $note = $body['note'] ?? null;
        if ($status !== null && !in_array($status, ['active', 'focus', 'suspended'], true)) {
            throw new ApiError(400, 'validation', 'status must be active, focus or suspended');
        }
        if ($note !== null && !is_string($note)) {
            throw new ApiError(400, 'validation', 'note must be a string');
        }
        $this->pdo->prepare(
            "INSERT INTO item_states (user_id, item_id, model, status, note)
             VALUES (?, ?, ?, COALESCE(?, 'active'), COALESCE(?, ''))
             ON DUPLICATE KEY UPDATE status = COALESCE(?, status), note = COALESCE(?, note)"
        )->execute([$userId, $row['id'], MemoryModel::VERSION, $status, $note, $status, $note]);
        return $this->get($userId, (int) $row['id']);
    }

    // --- links, subjects --------------------------------------------------

    public function link(int $userId, string|int $ref, mixed $rel, mixed $to, mixed $note): void
    {
        if (!in_array($rel, self::RELS, true)) {
            throw new ApiError(400, 'validation', 'rel must be one of ' . implode(', ', self::RELS));
        }
        if (!is_string($to) && !is_int($to)) {
            throw new ApiError(400, 'validation', 'to must be an item ref');
        }
        $from = (int) $this->resolve($userId, $ref)['id'];
        $toId = (int) $this->resolve($userId, $to)['id'];
        if ($from === $toId) {
            throw new ApiError(400, 'validation', 'An item cannot link to itself');
        }
        $this->insertLink($from, $toId, $rel, is_string($note) ? mb_substr($note, 0, 255) : null);
    }

    public function unlink(int $userId, string|int $ref, string $rel, string $to): void
    {
        $from = (int) $this->resolve($userId, $ref)['id'];
        $toId = (int) $this->resolve($userId, $to)['id'];
        $this->pdo->prepare('DELETE FROM item_links WHERE from_id = ? AND to_id = ? AND rel = ?')
            ->execute([$from, $toId, $rel]);
    }

    public function linkDir(int $userId, int $dirId, string|int $ref): void
    {
        $this->dirs->get($userId, $dirId);
        $id = (int) $this->resolve($userId, $ref)['id'];
        $this->pdo->prepare('INSERT IGNORE INTO dir_items (dir_id, item_id) VALUES (?, ?)')->execute([$dirId, $id]);
    }

    public function unlinkDir(int $userId, int $dirId, string|int $ref): void
    {
        $this->dirs->get($userId, $dirId);
        $id = (int) $this->resolve($userId, $ref)['id'];
        $this->pdo->prepare('DELETE FROM dir_items WHERE dir_id = ? AND item_id = ?')->execute([$dirId, $id]);
    }

    public function addAlias(int $userId, string $space, string $alias, ?string $labelMd, int $itemId, string $origin, ?string $reason): bool
    {
        // an alias never shadows a live key
        $stmt = $this->pdo->prepare('SELECT id FROM items WHERE user_id = ? AND space = ? AND `key` = ?');
        $stmt->execute([$userId, $space, $alias]);
        if ($stmt->fetchColumn() !== false) {
            return false;
        }
        $stmt = $this->pdo->prepare(
            'INSERT IGNORE INTO item_aliases (user_id, space, alias, label_md, item_id, origin, reason)
             VALUES (?, ?, ?, ?, ?, ?, ?)'
        );
        $stmt->execute([$userId, $space, $alias, $labelMd === null ? null : mb_substr($labelMd, 0, 512), $itemId, $origin, $reason]);
        return $stmt->rowCount() > 0;
    }

    // --- views ------------------------------------------------------------

    /**
     * @param array<string, mixed> $row
     * @return array<string, mixed>
     */
    public static function view(array $row, float $now): array
    {
        $attrs = json_decode($row['attrs'], true);
        return [
            'id' => (int) $row['id'],
            'ref' => $row['space'] . '/' . $row['key'],
            'space' => $row['space'],
            'key' => $row['key'],
            'kind' => $row['kind'],
            'label_md' => $row['label_md'],
            'gloss_md' => $row['gloss_md'],
            'body_md' => $row['body_md'],
            'attrs' => $attrs === [] ? new \stdClass() : $attrs,
            'priority' => (int) $row['priority'],
            'level' => $row['level'] === null ? null : (int) $row['level'],
            'archived' => $row['archived_at'] !== null,
            'merged_into' => $row['merged_ref'] ?? null,
            'state' => self::stateView($row, $now),
            'created_at' => Time::iso($row['created_at']),
            'updated_at' => Time::iso($row['updated_at']),
        ];
    }

    /**
     * The learner-facing state (docs/tutor.md 4.6–4.8); null when the
     * item has neither evidence nor flags.
     *
     * @param array<string, mixed> $row
     * @return array<string, mixed>|null
     */
    public static function stateView(array $row, float $now): ?array
    {
        if (($row['model'] ?? null) === null) {
            return null;
        }
        $s = $row['stability'] === null ? null : (float) $row['stability'];
        $recall = null;
        if ($s !== null) {
            $recall = round(MemoryModel::recall($s, max(0.0, $now - Time::fromDb($row['last_seen_at'])) / 86400), 3);
        }
        return [
            'mastery' => MemoryModel::mastery($s, $row['best_mode']),
            'recall' => $recall,
            'stability' => $s === null ? null : round($s, 3),
            'difficulty' => $row['difficulty'] === null ? null : round((float) $row['difficulty'], 3),
            'reps' => (int) $row['reps'],
            'lapses' => (int) $row['lapses'],
            'best_mode' => $row['best_mode'],
            'first_seen_at' => Time::iso($row['first_seen_at']),
            'last_seen_at' => Time::iso($row['last_seen_at']),
            'status' => $row['status'],
            'note' => $row['note'],
            'model' => $row['model'],
        ];
    }

    /**
     * @param array<string, mixed> $row
     * @return array<string, mixed>
     */
    public function detail(int $userId, array $row): array
    {
        $id = (int) $row['id'];
        $item = self::view($row, Time::now());

        $stmt = $this->pdo->prepare('SELECT alias, label_md, origin, reason FROM item_aliases WHERE item_id = ? ORDER BY alias');
        $stmt->execute([$id]);
        $item['aliases'] = $stmt->fetchAll();

        $stmt = $this->pdo->prepare('SELECT d.id, d.name FROM dirs d JOIN dir_items di ON di.dir_id = d.id WHERE di.item_id = ? ORDER BY d.name');
        $stmt->execute([$id]);
        $item['dirs'] = array_map(fn ($r) => ['id' => (int) $r['id'], 'name' => $r['name']], $stmt->fetchAll());

        $stmt = $this->pdo->prepare(
            "SELECT 'out' AS direction, l.rel, l.note, CONCAT(o.space, '/', o.`key`) AS ref, o.label_md
             FROM item_links l JOIN items o ON o.id = l.to_id WHERE l.from_id = ?
             UNION ALL
             SELECT 'in', l.rel, l.note, CONCAT(o.space, '/', o.`key`), o.label_md
             FROM item_links l JOIN items o ON o.id = l.from_id WHERE l.to_id = ?
             ORDER BY rel, ref"
        );
        $stmt->execute([$id, $id]);
        $item['links'] = $stmt->fetchAll();

        $stmt = $this->pdo->prepare('SELECT card_id FROM card_items WHERE item_id = ? ORDER BY card_id');
        $stmt->execute([$id]);
        $item['cards'] = array_map('intval', $stmt->fetchAll(\PDO::FETCH_COLUMN));

        $stmt = $this->pdo->prepare(
            'SELECT i.uuid, i.occurred_at, i.mode, i.source, i.hinted, i.prompt_md, i.response_md,
                    COALESCE((SELECT a.outcome FROM interaction_amendments a
                              WHERE a.interaction_id = ii.interaction_id AND a.item_id = ii.origin_item_id
                              ORDER BY a.id DESC LIMIT 1), ii.outcome) AS outcome,
                    ii.note
             FROM interaction_items ii JOIN interactions i ON i.id = ii.interaction_id
             WHERE ii.item_id = ? ORDER BY i.occurred_at DESC, i.id DESC LIMIT 10'
        );
        $stmt->execute([$id]);
        $item['interactions'] = array_map(fn ($r) => [
            'uuid' => $r['uuid'],
            'occurred_at' => Time::iso($r['occurred_at']),
            'mode' => $r['mode'],
            'source' => $r['source'],
            'outcome' => $r['outcome'],
            'hinted' => (bool) $r['hinted'],
            'prompt_md' => $r['prompt_md'],
            'response_md' => $r['response_md'],
            'note' => $r['note'],
        ], $stmt->fetchAll());
        unset($userId);
        return $item;
    }

    // --- internals ----------------------------------------------------------

    /**
     * Validate and normalize an item body. Derives the key for
     * word/phrase/term items when it is missing.
     *
     * @param array<string, mixed> $body
     * @return array<string, mixed>
     */
    private function validate(array $body, bool $keyRequired): array
    {
        $space = $body['space'] ?? null;
        if (!is_string($space) || !Norm::isValidSpace($space)) {
            throw new ApiError(400, 'validation', 'space must match ^[a-z][a-z0-9-]{0,15}$ (e.g. it, el, concepts)');
        }
        $kind = $body['kind'] ?? null;
        if (!in_array($kind, Norm::KINDS, true)) {
            throw new ApiError(400, 'validation', 'kind must be one of ' . implode(', ', Norm::KINDS));
        }
        $label = $body['label_md'] ?? null;
        if (!is_string($label) || trim($label) === '' || mb_strlen($label) > 512) {
            throw new ApiError(400, 'validation', 'label_md must be a non-empty string of at most 512 characters');
        }
        $gloss = $body['gloss_md'] ?? '';
        $text = $body['body_md'] ?? '';
        if (!is_string($gloss) || !is_string($text)) {
            throw new ApiError(400, 'validation', 'gloss_md and body_md must be strings');
        }
        $attrs = $body['attrs'] ?? [];
        if (!is_array($attrs) || ($attrs !== [] && array_is_list($attrs))) {
            throw new ApiError(400, 'validation', 'attrs must be an object');
        }
        foreach (self::STRONG_IDS as $idName) {
            if (array_key_exists($idName, $attrs)) {
                if (!is_string($attrs[$idName]) || trim($attrs[$idName]) === '') {
                    throw new ApiError(400, 'validation', "attrs.$idName must be a non-empty string");
                }
                // DOIs are case-insensitive; store them canonically
                $attrs[$idName] = $idName === 'doi' ? strtolower(trim($attrs[$idName])) : trim($attrs[$idName]);
            }
        }
        $priority = $body['priority'] ?? 50;
        if (!is_int($priority) || $priority < 0 || $priority > 100) {
            throw new ApiError(400, 'validation', 'priority must be an integer 0..100');
        }
        $level = $body['level'] ?? null;
        if ($level !== null && (!is_int($level) || $level < 1 || $level > 6)) {
            throw new ApiError(400, 'validation', 'level must be null or an integer 1..6');
        }
        $key = $body['key'] ?? null;
        if ($key === null && !$keyRequired) {
            if (!in_array($kind, Norm::DERIVABLE, true)) {
                throw new ApiError(400, 'validation', "key is required for kind '$kind'");
            }
            $key = Norm::slug($label);
            $sense = $body['sense'] ?? null;
            if (is_string($sense) && Norm::slug($sense) !== '') {
                $key .= '.' . Norm::slug($sense);
            }
            if ($key === '' || str_starts_with($key, '.')) {
                throw new ApiError(400, 'validation', 'Cannot derive a key from this label; send key');
            }
        }
        if (!is_string($key)) {
            throw new ApiError(400, 'validation', 'key must be a string');
        }
        $error = Norm::keyError($key);
        if ($error !== null) {
            throw new ApiError(400, 'validation', $error);
        }
        if ($kind === 'form' && !str_contains($key, '.')) {
            throw new ApiError(400, 'validation', 'form keys are <lexeme-key>.<cell>, e.g. essere.pres.1sg');
        }
        return [
            'space' => $space, 'key' => $key, 'kind' => $kind,
            'label_md' => $label, 'label_norm' => Norm::norm($label),
            'gloss_md' => $gloss, 'body_md' => $text, 'attrs' => $attrs,
            'priority' => $priority, 'level' => $level,
        ];
    }

    /**
     * Exact identity: same key, an alias, or a shared strong id.
     *
     * @param array<string, mixed> $item
     * @return array{0: array<string, mixed>, 1: string}|null
     */
    private function exactIdentity(int $userId, array $item): ?array
    {
        $row = $this->fetchOne('i.user_id = ? AND i.space = ? AND i.`key` = ?', [$userId, $item['space'], $item['key']]);
        if ($row !== null) {
            return [$this->resolve($userId, (int) $row['id']), 'key'];
        }
        $aliases = array_values(array_unique(array_filter([$item['key'], Norm::slug($item['label_md'])])));
        $placeholders = implode(',', array_fill(0, count($aliases), '?'));
        $stmt = $this->pdo->prepare(
            "SELECT item_id FROM item_aliases WHERE user_id = ? AND space = ? AND alias IN ($placeholders) LIMIT 1"
        );
        $stmt->execute([$userId, $item['space'], ...$aliases]);
        $id = $stmt->fetchColumn();
        if ($id !== false) {
            return [$this->resolve($userId, (int) $id), 'alias'];
        }
        foreach (self::STRONG_IDS as $idName) {
            if (isset($item['attrs'][$idName])) {
                $row = $this->fetchOne("i.user_id = ? AND i.$idName = ?", [$userId, $item['attrs'][$idName]]);
                if ($row !== null) {
                    return [$this->resolve($userId, (int) $row['id']), $idName];
                }
            }
        }
        return null;
    }

    /**
     * Lexical candidates for a new item (high recall, no claim of
     * sameness; the LLM judges them).
     *
     * @param array<string, mixed> $item
     * @return list<array<string, mixed>>
     */
    private function candidates(int $userId, array $item): array
    {
        $norm = $item['label_norm'];
        $base = Norm::keyBase($item['key']);
        $lexical = in_array($item['kind'], Norm::LEXICAL, true);
        $sql = "SELECT id, space, `key`, key_base, kind, label_md, label_norm, gloss_md FROM items
                WHERE user_id = ? AND archived_at IS NULL AND (
                  (space = ? AND (label_norm = ? OR key_base = ?
                                  OR CONCAT(' ', label_norm, ' ') LIKE ?
                                  OR ? LIKE CONCAT('% ', label_norm, ' %')
                                  OR LEFT(label_norm, 3) = ?))";
        $params = [$userId, $item['space'], $norm, $base, '% ' . $norm . ' %', ' ' . $norm . ' ', mb_substr($norm, 0, 3)];
        if (!$lexical) {
            $sql .= ' OR label_norm = ?';
            $params[] = $norm;
            if (mb_strlen($norm) >= 4) {
                $sql .= ' OR (space = ? AND LOWER(gloss_md) REGEXP ?)';
                $params[] = $item['space'];
                $params[] = '\\b' . preg_quote($norm) . '\\b';
            }
        }
        $sql .= ') LIMIT 300';
        $stmt = $this->pdo->prepare($sql);
        $stmt->execute($params);

        $order = ['label' => 0, 'key_base' => 1, 'label_other_space' => 2, 'contains' => 3, 'similar' => 4, 'gloss' => 5];
        $found = [];
        $newTokens = $norm === '' ? 0 : count(explode(' ', $norm));
        foreach ($stmt->fetchAll() as $c) {
            $reason = null;
            $sameSpace = $c['space'] === $item['space'];
            $cLexical = in_array($c['kind'], Norm::LEXICAL, true);
            if ($sameSpace && $c['label_norm'] === $norm) {
                $reason = 'label';
            } elseif ($sameSpace && $c['key_base'] === $base
                && $item['kind'] !== 'form' && $c['kind'] !== 'form') {
                $reason = 'key_base';
            } elseif (!$sameSpace && $c['label_norm'] === $norm && !$cLexical) {
                $reason = 'label_other_space';
            } elseif ($sameSpace && $norm !== '' && $c['label_norm'] !== '') {
                $short = mb_strlen($norm) <= mb_strlen($c['label_norm']) ? $norm : $c['label_norm'];
                $long = $short === $norm ? $c['label_norm'] : $norm;
                $contains = str_contains(' ' . $long . ' ', ' ' . $short . ' ');
                $extra = count(explode(' ', $long)) - count(explode(' ', $short));
                if ($contains && ($lexical || $cLexical
                        ? mb_strlen($short) >= 3 && $extra <= 1
                        : mb_strlen($short) >= 4)) {
                    $reason = 'contains';
                } elseif (!$lexical && !$cLexical && mb_strlen($norm) >= 8
                    && Text::levenshtein($norm, $c['label_norm']) <= 2) {
                    $reason = 'similar';
                } elseif (!$lexical && mb_strlen($norm) >= 4
                    && preg_match('/\b' . preg_quote($norm, '/') . '\b/u', Norm::norm($c['gloss_md'])) === 1) {
                    $reason = 'gloss';
                }
            }
            if ($reason !== null) {
                $c['id'] = (int) $c['id'];
                $c['reason'] = $reason;
                $found[] = $c;
            }
        }
        usort($found, fn ($a, $b) => $order[$a['reason']] <=> $order[$b['reason']] ?: $a['id'] <=> $b['id']);
        unset($newTokens);
        return array_slice($found, 0, self::MAX_CANDIDATES);
    }

    /**
     * Teacher-origin items with the same normalized label, reported
     * (not blocked) by bulk imports.
     *
     * @return list<string>
     */
    private function teacherTwins(int $userId, array $item, int $exceptId): array
    {
        $stmt = $this->pdo->prepare(
            "SELECT CONCAT(space, '/', `key`) FROM items
             WHERE user_id = ? AND space = ? AND label_norm = ? AND id <> ? AND archived_at IS NULL
               AND JSON_VALUE(attrs, '$.origin') = 'teacher'"
        );
        $stmt->execute([$userId, $item['space'], $item['label_norm'], $exceptId]);
        return $stmt->fetchAll(\PDO::FETCH_COLUMN);
    }

    /** @param array<string, mixed> $item */
    private function insert(int $userId, array $item): int
    {
        try {
            $this->pdo->prepare(
                'INSERT INTO items (user_id, space, `key`, kind, label_md, label_norm, gloss_md, body_md, attrs, priority, level)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'
            )->execute([
                $userId, $item['space'], $item['key'], $item['kind'], $item['label_md'], $item['label_norm'],
                $item['gloss_md'], $item['body_md'], self::jsonObject($item['attrs']), $item['priority'], $item['level'],
            ]);
        } catch (\PDOException $e) {
            if (($e->errorInfo[1] ?? null) === 1062) {
                throw new ApiError(409, 'conflict', "Item {$item['space']}/{$item['key']} collides with an existing key or strong id");
            }
            throw $e;
        }
        return (int) $this->pdo->lastInsertId();
    }

    /**
     * Update content fields; returns whether anything changed.
     *
     * @param array<string, mixed> $row
     * @param array<string, mixed> $item
     */
    private function updateFields(array $row, array $item): bool
    {
        $attrs = self::jsonObject($item['attrs']);
        $changed = $row['kind'] !== $item['kind'] || $row['label_md'] !== $item['label_md']
            || $row['gloss_md'] !== $item['gloss_md'] || $row['body_md'] !== $item['body_md']
            || json_decode($row['attrs'], true) != $item['attrs']
            || (int) $row['priority'] !== $item['priority']
            || ($row['level'] === null ? null : (int) $row['level']) !== $item['level'];
        if ($changed) {
            try {
                $this->pdo->prepare(
                    'UPDATE items SET kind = ?, label_md = ?, label_norm = ?, gloss_md = ?, body_md = ?,
                            attrs = ?, priority = ?, level = ? WHERE id = ?'
                )->execute([
                    $item['kind'], $item['label_md'], $item['label_norm'], $item['gloss_md'], $item['body_md'],
                    $attrs, $item['priority'], $item['level'], $row['id'],
                ]);
            } catch (\PDOException $e) {
                if (($e->errorInfo[1] ?? null) === 1062) {
                    throw new ApiError(409, 'conflict', "A strong identifier of {$row['space']}/{$row['key']} belongs to another item");
                }
                throw $e;
            }
        }
        return $changed;
    }

    /**
     * Subjects, links and the automatic form_of link from a create or
     * bulk body. In bulk mode unresolved link targets are returned
     * instead of failing the batch.
     *
     * @param array<string, mixed> $item
     * @param array<string, mixed> $body
     * @return list<array<string, string>>
     */
    private function applyRelations(int $userId, int $id, array $item, array $body, bool $strict = true): array
    {
        $unresolved = [];
        $dirIds = $body['dirs'] ?? [];
        if (!is_array($dirIds) || array_filter($dirIds, fn ($d) => !is_int($d)) !== []) {
            throw new ApiError(400, 'validation', 'dirs must be a list of directory ids');
        }
        foreach ($dirIds as $dirId) {
            $this->dirs->get($userId, $dirId);
            $this->pdo->prepare('INSERT IGNORE INTO dir_items (dir_id, item_id) VALUES (?, ?)')->execute([$dirId, $id]);
        }
        if ($item['kind'] === 'form') {
            $lexeme = $item['space'] . '/' . Norm::keyBase($item['key']);
            try {
                $this->insertLink($id, (int) $this->resolve($userId, $lexeme)['id'], 'form_of', null);
            } catch (ApiError $e) {
                if ($strict) {
                    throw new ApiError(400, 'validation', "form needs its lexeme $lexeme to exist");
                }
                $unresolved[] = ['from' => "{$item['space']}/{$item['key']}", 'rel' => 'form_of', 'to' => $lexeme];
            }
        }
        $links = $body['links'] ?? [];
        if (!is_array($links)) {
            throw new ApiError(400, 'validation', 'links must be a list of {rel, to}');
        }
        foreach ($links as $link) {
            $rel = $link['rel'] ?? null;
            $to = $link['to'] ?? null;
            if (!in_array($rel, self::RELS, true) || !is_string($to)) {
                throw new ApiError(400, 'validation', 'each link needs rel (' . implode('|', self::RELS) . ') and to');
            }
            // a bare key links within the item's own space
            $toRef = str_contains($to, '/') ? $to : $item['space'] . '/' . $to;
            try {
                $toId = (int) $this->resolve($userId, $toRef)['id'];
            } catch (ApiError $e) {
                if ($strict) {
                    throw $e;
                }
                $unresolved[] = ['from' => "{$item['space']}/{$item['key']}", 'rel' => $rel, 'to' => $toRef];
                continue;
            }
            if ($toId !== $id) {
                $this->insertLink($id, $toId, $rel, isset($link['note']) && is_string($link['note']) ? mb_substr($link['note'], 0, 255) : null);
            }
        }
        return $unresolved;
    }

    private function insertLink(int $from, int $to, string $rel, ?string $note): void
    {
        $this->pdo->prepare(
            'INSERT INTO item_links (from_id, to_id, rel, note) VALUES (?, ?, ?, ?)
             ON DUPLICATE KEY UPDATE note = COALESCE(VALUES(note), note)'
        )->execute([$from, $to, $rel, $note]);
    }

    /**
     * @param array{space?: string, dir?: int, recursive?: bool, kind?: string, q?: string,
     *              status?: string, archived?: bool} $filters
     * @return array{0: list<string>, 1: list<mixed>}
     */
    private function filterSql(int $userId, array $filters): array
    {
        $where = ['i.user_id = ?'];
        $params = [$userId];
        if (!($filters['archived'] ?? false)) {
            $where[] = 'i.archived_at IS NULL';
        }
        if (isset($filters['space'])) {
            $where[] = 'i.space = ?';
            $params[] = $filters['space'];
        }
        if (isset($filters['kind'])) {
            $where[] = 'i.kind = ?';
            $params[] = $filters['kind'];
        }
        if (isset($filters['status'])) {
            $where[] = "COALESCE(s.status, 'active') = ?";
            $params[] = $filters['status'];
        }
        if (isset($filters['dir'])) {
            $this->dirs->get($userId, $filters['dir']);
            $dirIds = ($filters['recursive'] ?? false) ? $this->dirs->subtreeIds($filters['dir']) : [$filters['dir']];
            $where[] = 'i.id IN (SELECT item_id FROM dir_items WHERE dir_id IN (' . implode(',', array_fill(0, count($dirIds), '?')) . '))';
            array_push($params, ...$dirIds);
        }
        if (isset($filters['q']) && $filters['q'] !== '') {
            $q = '%' . strtr(Norm::norm($filters['q']), ['%' => '\\%', '_' => '\\_']) . '%';
            $raw = '%' . strtr(mb_strtolower($filters['q']), ['%' => '\\%', '_' => '\\_']) . '%';
            $where[] = '(i.label_norm LIKE ? OR LOWER(i.gloss_md) LIKE ? OR LOWER(i.body_md) LIKE ? OR i.`key` LIKE ?
                        OR i.id IN (SELECT item_id FROM item_aliases WHERE user_id = ? AND (alias LIKE ? OR LOWER(label_md) LIKE ?)))';
            array_push($params, $q, $raw, $raw, '%' . Norm::slug($filters['q']) . '%', $userId, '%' . Norm::slug($filters['q']) . '%', $raw);
        }
        return [$where, $params];
    }

    /** @return array<string, mixed>|null */
    private function fetchOne(string $where, array $params): ?array
    {
        $stmt = $this->pdo->prepare(self::SELECT . " WHERE $where LIMIT 1");
        $stmt->execute($params);
        $row = $stmt->fetch();
        return $row === false ? null : $row;
    }

    /** @return list<string> */
    private function listOfStrings(array $body, string $field): array
    {
        $value = $body[$field] ?? [];
        if (!is_array($value) || array_filter($value, fn ($v) => !is_string($v)) !== []) {
            throw new ApiError(400, 'validation', "$field must be a list of item refs");
        }
        return array_values($value);
    }

    public static function jsonObject(array $value): string
    {
        return json_encode($value === [] ? new \stdClass() : $value, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
    }
}

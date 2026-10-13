<?php

declare(strict_types=1);

namespace Pauk\Repo;

use Pauk\ApiError;
use Pauk\Knowledge\Norm;
use Pauk\Knowledge\Time;

/**
 * Reversible item merges and merge suggestions (docs/tutor.md 4.10).
 * A merge moves evidence and links from b to a, keeps b archived
 * with merged_into = a, and records what it moved, so unmerge can
 * restore the previous state exactly. The log is never rewritten:
 * interaction_items keep their origin_item_id.
 */
final class Merges
{
    public const BY = ['teacher', 'observer', 'sweep', 'human'];

    public function __construct(
        private readonly \PDO $pdo,
        private readonly Items $items,
        private readonly Interactions $interactions,
    ) {
    }

    /** @param array<string, mixed> $body */
    public function merge(int $userId, string|int $intoRef, array $body): array
    {
        [$a, $b, $reason, $by, $sessionId] = $this->validate($userId, $intoRef, $body);
        $this->pdo->beginTransaction();
        try {
            $this->pdo->prepare(
                "INSERT INTO item_merges (user_id, into_id, from_id, status, reason, suggested_by, session_id)
                 VALUES (?, ?, ?, 'done', ?, ?, ?)"
            )->execute([$userId, $a, $b, $reason, $by, $sessionId]);
            $mergeId = (int) $this->pdo->lastInsertId();
            $this->execute($userId, $mergeId, $a, $b);
            $this->pdo->commit();
        } catch (\Throwable $e) {
            $this->pdo->rollBack();
            throw $e;
        }
        return $this->get($userId, $mergeId);
    }

    /** @param array<string, mixed> $body */
    public function suggest(int $userId, array $body): array
    {
        $into = $body['into'] ?? null;
        if (!is_string($into) && !is_int($into)) {
            throw new ApiError(400, 'validation', 'into must be an item ref');
        }
        [$a, $b, $reason, $by, $sessionId] = $this->validate($userId, $into, $body);
        $stmt = $this->pdo->prepare(
            "SELECT id FROM item_merges WHERE user_id = ? AND status = 'suggested'
               AND ((into_id = ? AND from_id = ?) OR (into_id = ? AND from_id = ?))"
        );
        $stmt->execute([$userId, $a, $b, $b, $a]);
        $existing = $stmt->fetchColumn();
        if ($existing !== false) {
            return $this->get($userId, (int) $existing);
        }
        $this->pdo->prepare(
            "INSERT INTO item_merges (user_id, into_id, from_id, status, reason, suggested_by, session_id)
             VALUES (?, ?, ?, 'suggested', ?, ?, ?)"
        )->execute([$userId, $a, $b, $reason, $by, $sessionId]);
        return $this->get($userId, (int) $this->pdo->lastInsertId());
    }

    public function accept(int $userId, int $mergeId): array
    {
        $merge = $this->row($userId, $mergeId);
        if ($merge['status'] !== 'suggested') {
            throw new ApiError(409, 'conflict', "Merge $mergeId is {$merge['status']}, not suggested");
        }
        $into = $this->items->resolve($userId, (int) $merge['into_id']);
        $from = $this->items->resolve($userId, (int) $merge['from_id'], false);
        if ($from['archived_at'] !== null || (int) $into['id'] === (int) $from['id']) {
            throw new ApiError(409, 'conflict', 'The suggested items can no longer be merged');
        }
        $this->pdo->beginTransaction();
        try {
            $this->execute($userId, $mergeId, (int) $into['id'], (int) $from['id']);
            $this->pdo->commit();
        } catch (\Throwable $e) {
            $this->pdo->rollBack();
            throw $e;
        }
        return $this->get($userId, $mergeId);
    }

    public function dismiss(int $userId, int $mergeId): array
    {
        $merge = $this->row($userId, $mergeId);
        if ($merge['status'] !== 'suggested') {
            throw new ApiError(409, 'conflict', "Merge $mergeId is {$merge['status']}, not suggested");
        }
        $this->pdo->prepare("UPDATE item_merges SET status = 'dismissed', decided_at = NOW() WHERE id = ?")->execute([$mergeId]);
        // a dismissed pair is distinct: record it like distinct_from
        $this->items->link($userId, (int) $merge['from_id'], 'related', (int) $merge['into_id'], 'merge dismissed: ' . $merge['reason']);
        return $this->get($userId, $mergeId);
    }

    /** Undo the latest merge of $fromRef into another item. */
    public function unmerge(int $userId, string|int $fromRef): array
    {
        $b = $this->items->resolve($userId, $fromRef, false);
        $stmt = $this->pdo->prepare(
            "SELECT * FROM item_merges WHERE user_id = ? AND from_id = ? AND status = 'done' ORDER BY id DESC LIMIT 1"
        );
        $stmt->execute([$userId, $b['id']]);
        $merge = $stmt->fetch();
        if ($merge === false || (int) ($b['merged_into'] ?? 0) !== (int) $merge['into_id']) {
            throw new ApiError(409, 'conflict', "Item $fromRef is not merged");
        }
        $a = (int) $merge['into_id'];
        $bId = (int) $b['id'];
        $moved = json_decode($merge['moved'], true);

        $this->pdo->beginTransaction();
        try {
            // evidence recorded against b, or against items merged into b
            $origins = $this->mergedInto($userId, $bId);
            $placeholders = implode(',', array_fill(0, count($origins), '?'));
            $this->pdo->prepare(
                "UPDATE interaction_items SET item_id = ? WHERE item_id = ? AND origin_item_id IN ($placeholders)"
            )->execute([$bId, $a, ...$origins]);

            foreach ($moved['cards_added'] as $cardId) {
                $this->pdo->prepare('DELETE FROM card_items WHERE card_id = ? AND item_id = ?')->execute([$cardId, $a]);
            }
            foreach ($moved['cards'] as $cardId) {
                $this->pdo->prepare('INSERT IGNORE INTO card_items (card_id, item_id) VALUES (?, ?)')->execute([$cardId, $bId]);
            }
            foreach ($moved['dirs_added'] as $dirId) {
                $this->pdo->prepare('DELETE FROM dir_items WHERE dir_id = ? AND item_id = ?')->execute([$dirId, $a]);
            }
            foreach ($moved['dirs'] as $dirId) {
                $this->pdo->prepare('INSERT IGNORE INTO dir_items (dir_id, item_id) VALUES (?, ?)')->execute([$dirId, $bId]);
            }
            foreach ($moved['links_added'] as [$from, $to, $rel]) {
                $this->pdo->prepare('DELETE FROM item_links WHERE from_id = ? AND to_id = ? AND rel = ?')->execute([$from, $to, $rel]);
            }
            foreach ($moved['links'] as [$from, $to, $rel, $note]) {
                $this->pdo->prepare('INSERT IGNORE INTO item_links (from_id, to_id, rel, note) VALUES (?, ?, ?, ?)')
                    ->execute([$from, $to, $rel, $note]);
            }
            foreach ($moved['aliases_added'] as $alias) {
                $this->pdo->prepare('DELETE FROM item_aliases WHERE user_id = ? AND space = ? AND alias = ? AND item_id = ?')
                    ->execute([$userId, $alias[0], $alias[1], $a]);
            }
            foreach ($moved['aliases'] as $alias) {
                $this->pdo->prepare('UPDATE item_aliases SET item_id = ? WHERE user_id = ? AND space = ? AND alias = ?')
                    ->execute([$bId, $userId, $alias[0], $alias[1]]);
            }
            $this->restoreFlags($userId, $a, $moved['flags_a']);
            $this->restoreFlags($userId, $bId, $moved['flags_b']);
            $this->pdo->prepare('UPDATE items SET archived_at = NULL, merged_into = NULL WHERE id = ?')->execute([$bId]);
            $this->pdo->prepare("UPDATE item_merges SET status = 'undone', decided_at = NOW() WHERE id = ?")->execute([$merge['id']]);
            $this->interactions->replay($userId, $a);
            $this->interactions->replay($userId, $bId);
            $this->pdo->commit();
        } catch (\Throwable $e) {
            $this->pdo->rollBack();
            throw $e;
        }
        return $this->get($userId, (int) $merge['id']);
    }

    /** @return list<array<string, mixed>> */
    public function list(int $userId, ?string $status): array
    {
        $sql = 'SELECT id FROM item_merges WHERE user_id = ?' . ($status === null ? '' : ' AND status = ?') . ' ORDER BY id DESC LIMIT 200';
        $stmt = $this->pdo->prepare($sql);
        $stmt->execute($status === null ? [$userId] : [$userId, $status]);
        return array_map(fn ($id) => $this->get($userId, (int) $id), $stmt->fetchAll(\PDO::FETCH_COLUMN));
    }

    /** @return array<string, mixed> */
    public function get(int $userId, int $mergeId): array
    {
        $m = $this->row($userId, $mergeId);
        $into = $this->items->resolve($userId, (int) $m['into_id'], false);
        $from = $this->items->resolve($userId, (int) $m['from_id'], false);
        return [
            'id' => (int) $m['id'],
            'into' => $into['space'] . '/' . $into['key'],
            'into_label_md' => $into['label_md'],
            'from' => $from['space'] . '/' . $from['key'],
            'from_label_md' => $from['label_md'],
            'status' => $m['status'],
            'reason' => $m['reason'],
            'suggested_by' => $m['suggested_by'],
            'session_id' => $m['session_id'],
            'created_at' => Time::iso($m['created_at']),
            'decided_at' => Time::iso($m['decided_at']),
        ];
    }

    /**
     * @param array<string, mixed> $body
     * @return array{0: int, 1: int, 2: string, 3: string, 4: ?string}
     */
    private function validate(int $userId, string|int $intoRef, array $body): array
    {
        $from = $body['from'] ?? null;
        $reason = $body['reason'] ?? null;
        $by = $body['by'] ?? 'human';
        $sessionId = $body['session_id'] ?? null;
        if (!is_string($from) && !is_int($from)) {
            throw new ApiError(400, 'validation', 'from must be an item ref');
        }
        if (!is_string($reason) || trim($reason) === '') {
            throw new ApiError(400, 'validation', 'reason is required');
        }
        if (!in_array($by, self::BY, true)) {
            throw new ApiError(400, 'validation', 'by must be one of ' . implode(', ', self::BY));
        }
        if ($sessionId !== null && (!is_string($sessionId) || strlen($sessionId) > 64)) {
            throw new ApiError(400, 'validation', 'session_id must be a short string');
        }
        $a = $this->items->resolve($userId, $intoRef);
        $b = $this->items->resolve($userId, $from);
        if ((int) $a['id'] === (int) $b['id']) {
            throw new ApiError(400, 'validation', 'Cannot merge an item into itself');
        }
        if ($a['archived_at'] !== null || $b['archived_at'] !== null) {
            throw new ApiError(409, 'conflict', 'Archived items cannot be merged');
        }
        return [(int) $a['id'], (int) $b['id'], $reason, $by, $sessionId];
    }

    /** Caller holds the transaction. */
    private function execute(int $userId, int $mergeId, int $a, int $b): void
    {
        $moved = [
            'cards' => [], 'cards_added' => [], 'dirs' => [], 'dirs_added' => [],
            'links' => [], 'links_added' => [], 'aliases' => [], 'aliases_added' => [],
            'flags_a' => $this->flags($userId, $a), 'flags_b' => $this->flags($userId, $b),
        ];
        // evidence: one event that touched both items counts once (a's row)
        $stmt = $this->pdo->prepare(
            'SELECT interaction_id FROM interaction_items WHERE item_id = ?
               AND interaction_id NOT IN (SELECT interaction_id FROM interaction_items WHERE item_id = ?)'
        );
        $stmt->execute([$b, $a]);
        foreach ($stmt->fetchAll(\PDO::FETCH_COLUMN) as $interactionId) {
            $this->pdo->prepare('UPDATE interaction_items SET item_id = ? WHERE interaction_id = ? AND item_id = ?')
                ->execute([$a, $interactionId, $b]);
        }

        foreach (['card_items' => ['card_id', 'cards'], 'dir_items' => ['dir_id', 'dirs']] as $table => [$col, $name]) {
            $stmt = $this->pdo->prepare("SELECT $col FROM $table WHERE item_id = ?");
            $stmt->execute([$b]);
            foreach (array_map('intval', $stmt->fetchAll(\PDO::FETCH_COLUMN)) as $id) {
                $moved[$name][] = $id;
                $ins = $this->pdo->prepare("INSERT IGNORE INTO $table ($col, item_id) VALUES (?, ?)");
                $ins->execute([$id, $a]);
                if ($ins->rowCount() > 0) {
                    $moved[$name . '_added'][] = $id;
                }
            }
            $this->pdo->prepare("DELETE FROM $table WHERE item_id = ?")->execute([$b]);
        }

        $stmt = $this->pdo->prepare('SELECT from_id, to_id, rel, note FROM item_links WHERE from_id = ? OR to_id = ?');
        $stmt->execute([$b, $b]);
        foreach ($stmt->fetchAll() as $l) {
            $link = [(int) $l['from_id'], (int) $l['to_id'], $l['rel'], $l['note']];
            $moved['links'][] = $link;
            $from = $link[0] === $b ? $a : $link[0];
            $to = $link[1] === $b ? $a : $link[1];
            if ($from !== $to) {
                $ins = $this->pdo->prepare('INSERT IGNORE INTO item_links (from_id, to_id, rel, note) VALUES (?, ?, ?, ?)');
                $ins->execute([$from, $to, $l['rel'], $l['note']]);
                if ($ins->rowCount() > 0) {
                    $moved['links_added'][] = [$from, $to, $l['rel']];
                }
            }
        }
        $this->pdo->prepare('DELETE FROM item_links WHERE from_id = ? OR to_id = ?')->execute([$b, $b]);

        $stmt = $this->pdo->prepare('SELECT space, alias FROM item_aliases WHERE item_id = ?');
        $stmt->execute([$b]);
        $moved['aliases'] = array_map(fn ($r) => [$r['space'], $r['alias']], $stmt->fetchAll());
        $this->pdo->prepare('UPDATE item_aliases SET item_id = ? WHERE item_id = ?')->execute([$a, $b]);
        $bRow = $this->items->resolve($userId, $b, false);
        $slug = Norm::slug($bRow['label_md']);
        if ($slug !== '' && $this->items->addAlias($userId, $bRow['space'], $slug, $bRow['label_md'], $a, 'merge', null)) {
            $moved['aliases_added'][] = [$bRow['space'], $slug];
        }

        $fa = $moved['flags_a'];
        $fb = $moved['flags_b'];
        $status = in_array('focus', [$fa['status'], $fb['status']], true) ? 'focus'
            : ($fa['status'] === 'suspended' && $fb['status'] === 'suspended' ? 'suspended' : 'active');
        $note = trim(implode("\n", array_unique(array_filter([$fa['note'], $fb['note']]))));
        $this->restoreFlags($userId, $a, ['status' => $status, 'note' => $note]);

        $this->pdo->prepare('UPDATE items SET archived_at = NOW(), merged_into = ? WHERE id = ?')->execute([$a, $b]);
        $this->pdo->prepare("UPDATE item_merges SET into_id = ?, status = 'done', moved = ?, decided_at = NOW() WHERE id = ?")
            ->execute([$a, json_encode($moved, JSON_THROW_ON_ERROR), $mergeId]);
        $this->interactions->replay($userId, $a);
        $this->interactions->replay($userId, $b);
    }

    /** @return array{status: string, note: string} */
    private function flags(int $userId, int $itemId): array
    {
        $stmt = $this->pdo->prepare('SELECT status, note FROM item_states WHERE user_id = ? AND item_id = ?');
        $stmt->execute([$userId, $itemId]);
        $row = $stmt->fetch();
        return $row === false ? ['status' => 'active', 'note' => ''] : ['status' => $row['status'], 'note' => $row['note']];
    }

    /** @param array{status: string, note: string} $flags */
    private function restoreFlags(int $userId, int $itemId, array $flags): void
    {
        $this->pdo->prepare(
            "INSERT INTO item_states (user_id, item_id, model, status, note) VALUES (?, ?, 'pauk-mm@1', ?, ?)
             ON DUPLICATE KEY UPDATE status = VALUES(status), note = VALUES(note)"
        )->execute([$userId, $itemId, $flags['status'], $flags['note']]);
    }

    /**
     * $itemId plus every item merged into it (transitively, done merges).
     *
     * @return list<int>
     */
    private function mergedInto(int $userId, int $itemId): array
    {
        $ids = [$itemId];
        for ($i = 0; $i < count($ids) && $i < 1000; $i++) {
            $stmt = $this->pdo->prepare("SELECT from_id FROM item_merges WHERE user_id = ? AND into_id = ? AND status = 'done'");
            $stmt->execute([$userId, $ids[$i]]);
            foreach ($stmt->fetchAll(\PDO::FETCH_COLUMN) as $from) {
                if (!in_array((int) $from, $ids, true)) {
                    $ids[] = (int) $from;
                }
            }
        }
        return $ids;
    }

    /** @return array<string, mixed> */
    private function row(int $userId, int $mergeId): array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM item_merges WHERE id = ? AND user_id = ?');
        $stmt->execute([$mergeId, $userId]);
        $row = $stmt->fetch();
        if ($row === false) {
            throw new ApiError(404, 'not_found', "Merge $mergeId not found");
        }
        return $row;
    }
}

<?php

declare(strict_types=1);

namespace Pauk\Repo;

use Pauk\ApiError;

final class Dirs
{
    public function __construct(private readonly \PDO $pdo)
    {
    }

    /** @return array<string, mixed> */
    public function get(int $userId, int $dirId): array
    {
        $stmt = $this->pdo->prepare('SELECT id, name FROM dirs WHERE id = ? AND user_id = ?');
        $stmt->execute([$dirId, $userId]);
        $dir = $stmt->fetch();
        if ($dir === false) {
            throw new ApiError(404, 'not_found', "Directory $dirId not found");
        }
        return $this->hydrate($userId, $dir);
    }

    /** @return list<array<string, mixed>> */
    public function listChildren(int $userId, ?int $parentId): array
    {
        if ($parentId === null) {
            $stmt = $this->pdo->prepare(
                'SELECT d.id, d.name FROM dirs d
                 LEFT JOIN dir_dirs dd ON dd.child_id = d.id
                 WHERE d.user_id = ? AND dd.parent_id IS NULL
                 ORDER BY d.name'
            );
            $stmt->execute([$userId]);
        } else {
            $this->get($userId, $parentId);
            $stmt = $this->pdo->prepare(
                'SELECT d.id, d.name FROM dirs d
                 JOIN dir_dirs dd ON dd.child_id = d.id
                 WHERE dd.parent_id = ? AND d.user_id = ?
                 ORDER BY d.name'
            );
            $stmt->execute([$parentId, $userId]);
        }
        return array_map(fn ($row) => $this->hydrate($userId, $row), $stmt->fetchAll());
    }

    /** Resolve a slash-separated name path from the top level. */
    public function resolvePath(int $userId, string $path): array
    {
        $segments = array_values(array_filter(explode('/', trim($path, '/')), fn ($s) => $s !== ''));
        if ($segments === []) {
            throw new ApiError(400, 'validation', 'Empty path');
        }
        $parentId = null;
        $dirId = null;
        foreach ($segments as $segment) {
            $children = $parentId === null
                ? $this->topLevelIdsByName($userId)
                : $this->childIdsByName($userId, $parentId);
            if (!isset($children[$segment])) {
                throw new ApiError(404, 'not_found', "Path not found at segment '$segment'");
            }
            $dirId = $children[$segment];
            $parentId = $dirId;
        }
        return $this->get($userId, (int) $dirId);
    }

    public function create(int $userId, string $name, ?int $parentId): array
    {
        $this->assertValidName($name);
        $siblings = $parentId === null
            ? $this->topLevelIdsByName($userId)
            : $this->childIdsByName($userId, $parentId);
        if ($parentId !== null) {
            $this->get($userId, $parentId);
        }
        if (isset($siblings[$name])) {
            throw new ApiError(409, 'conflict', "A sibling named '$name' already exists");
        }
        $stmt = $this->pdo->prepare('INSERT INTO dirs (user_id, name) VALUES (?, ?)');
        $stmt->execute([$userId, $name]);
        $dirId = (int) $this->pdo->lastInsertId();
        if ($parentId !== null) {
            $stmt = $this->pdo->prepare('INSERT INTO dir_dirs (parent_id, child_id) VALUES (?, ?)');
            $stmt->execute([$parentId, $dirId]);
        }
        return $this->get($userId, $dirId);
    }

    public function rename(int $userId, int $dirId, string $name): array
    {
        $this->assertValidName($name);
        $this->get($userId, $dirId);
        foreach ($this->parentIds($dirId) as $parentId) {
            $siblings = $this->childIdsByName($userId, $parentId);
            if (isset($siblings[$name]) && $siblings[$name] !== $dirId) {
                throw new ApiError(409, 'conflict', "A sibling named '$name' already exists");
            }
        }
        if ($this->parentIds($dirId) === []) {
            $top = $this->topLevelIdsByName($userId);
            if (isset($top[$name]) && $top[$name] !== $dirId) {
                throw new ApiError(409, 'conflict', "A top-level directory named '$name' already exists");
            }
        }
        $stmt = $this->pdo->prepare('UPDATE dirs SET name = ? WHERE id = ?');
        $stmt->execute([$name, $dirId]);
        return $this->get($userId, $dirId);
    }

    public function delete(int $userId, int $dirId, bool $force): void
    {
        $this->get($userId, $dirId);
        $childIds = $this->childIds($dirId);
        $orphans = array_filter($childIds, fn ($c) => count($this->parentIds($c)) === 1);
        if ($orphans !== [] && !$force) {
            throw new ApiError(
                409,
                'conflict',
                'Deleting would orphan child directories (ids: '
                . implode(', ', $orphans) . '); repeat with force=1'
            );
        }
        $this->pdo->beginTransaction();
        try {
            $this->deleteRecursive($dirId);
            $this->pdo->commit();
        } catch (\Throwable $e) {
            $this->pdo->rollBack();
            throw $e;
        }
    }

    public function linkCard(int $userId, int $dirId, int $cardId): void
    {
        $this->get($userId, $dirId);
        $stmt = $this->pdo->prepare('SELECT id FROM cards WHERE id = ? AND user_id = ?');
        $stmt->execute([$cardId, $userId]);
        if ($stmt->fetch() === false) {
            throw new ApiError(404, 'not_found', "Card $cardId not found");
        }
        $stmt = $this->pdo->prepare('INSERT IGNORE INTO dir_cards (dir_id, card_id) VALUES (?, ?)');
        $stmt->execute([$dirId, $cardId]);
    }

    public function unlinkCard(int $userId, int $dirId, int $cardId): void
    {
        $this->get($userId, $dirId);
        $stmt = $this->pdo->prepare('DELETE FROM dir_cards WHERE dir_id = ? AND card_id = ?');
        $stmt->execute([$dirId, $cardId]);
    }

    public function linkDir(int $userId, int $parentId, int $childId): void
    {
        $parent = $this->get($userId, $parentId);
        $child = $this->get($userId, $childId);
        if ($parentId === $childId || in_array($parentId, $this->subtreeIds($childId), true)) {
            throw new ApiError(409, 'conflict', 'Link would create a cycle');
        }
        $siblings = $this->childIdsByName($userId, $parentId);
        if (isset($siblings[$child['name']]) && $siblings[$child['name']] !== $childId) {
            throw new ApiError(409, 'conflict', "A sibling named '{$child['name']}' already exists");
        }
        $stmt = $this->pdo->prepare('INSERT IGNORE INTO dir_dirs (parent_id, child_id) VALUES (?, ?)');
        $stmt->execute([$parentId, $childId]);
        unset($parent);
    }

    public function unlinkDir(int $userId, int $parentId, int $childId): void
    {
        $this->get($userId, $parentId);
        $stmt = $this->pdo->prepare('DELETE FROM dir_dirs WHERE parent_id = ? AND child_id = ?');
        $stmt->execute([$parentId, $childId]);
    }

    /**
     * The directory itself plus all transitive subdirectories.
     * UNION (not UNION ALL) deduplicates diamonds and guards
     * against loops.
     *
     * @return list<int>
     */
    public function subtreeIds(int $dirId): array
    {
        $stmt = $this->pdo->prepare(
            // The anchor must be CAST: the CTE column type is
            // inferred from it, and a bare bound parameter is typed
            // as a short string, truncating longer child ids.
            'WITH RECURSIVE subdirs (id) AS (
                SELECT CAST(? AS UNSIGNED)
                UNION
                SELECT dd.child_id FROM dir_dirs dd JOIN subdirs s ON dd.parent_id = s.id
            )
            SELECT id FROM subdirs'
        );
        $stmt->execute([$dirId]);
        return array_map('intval', $stmt->fetchAll(\PDO::FETCH_COLUMN));
    }

    /** @return list<int> */
    public function parentIds(int $dirId): array
    {
        $stmt = $this->pdo->prepare('SELECT parent_id FROM dir_dirs WHERE child_id = ?');
        $stmt->execute([$dirId]);
        return array_map('intval', $stmt->fetchAll(\PDO::FETCH_COLUMN));
    }

    /** @return list<int> */
    private function childIds(int $dirId): array
    {
        $stmt = $this->pdo->prepare('SELECT child_id FROM dir_dirs WHERE parent_id = ?');
        $stmt->execute([$dirId]);
        return array_map('intval', $stmt->fetchAll(\PDO::FETCH_COLUMN));
    }

    private function deleteRecursive(int $dirId): void
    {
        foreach ($this->childIds($dirId) as $childId) {
            $stmt = $this->pdo->prepare('DELETE FROM dir_dirs WHERE parent_id = ? AND child_id = ?');
            $stmt->execute([$dirId, $childId]);
            if ($this->parentIds($childId) === []) {
                $this->deleteRecursive($childId);
            }
        }
        $stmt = $this->pdo->prepare('DELETE FROM dirs WHERE id = ?');
        $stmt->execute([$dirId]);
    }

    /** @return array<string, int> name => id */
    private function topLevelIdsByName(int $userId): array
    {
        $stmt = $this->pdo->prepare(
            'SELECT d.name, d.id FROM dirs d
             LEFT JOIN dir_dirs dd ON dd.child_id = d.id
             WHERE d.user_id = ? AND dd.parent_id IS NULL'
        );
        $stmt->execute([$userId]);
        return array_map('intval', $stmt->fetchAll(\PDO::FETCH_KEY_PAIR));
    }

    /** @return array<string, int> name => id */
    private function childIdsByName(int $userId, int $parentId): array
    {
        $stmt = $this->pdo->prepare(
            'SELECT d.name, d.id FROM dirs d
             JOIN dir_dirs dd ON dd.child_id = d.id
             WHERE dd.parent_id = ? AND d.user_id = ?'
        );
        $stmt->execute([$parentId, $userId]);
        return array_map('intval', $stmt->fetchAll(\PDO::FETCH_KEY_PAIR));
    }

    /** @param array<string, mixed> $dir */
    private function hydrate(int $userId, array $dir): array
    {
        $dirId = (int) $dir['id'];
        $stmt = $this->pdo->prepare(
            'SELECT d.id, d.name FROM dirs d
             JOIN dir_dirs dd ON dd.parent_id = d.id
             WHERE dd.child_id = ? ORDER BY d.name'
        );
        $stmt->execute([$dirId]);
        $parents = array_map(
            fn ($r) => ['id' => (int) $r['id'], 'name' => $r['name']],
            $stmt->fetchAll()
        );
        $stmt = $this->pdo->prepare(
            'SELECT d.id, d.name FROM dirs d
             JOIN dir_dirs dd ON dd.child_id = d.id
             WHERE dd.parent_id = ? ORDER BY d.name'
        );
        $stmt->execute([$dirId]);
        $subdirs = array_map(
            fn ($r) => ['id' => (int) $r['id'], 'name' => $r['name']],
            $stmt->fetchAll()
        );
        $stmt = $this->pdo->prepare('SELECT COUNT(*) FROM dir_cards WHERE dir_id = ?');
        $stmt->execute([$dirId]);
        $direct = (int) $stmt->fetchColumn();

        $subtree = $this->subtreeIds($dirId);
        $placeholders = implode(',', array_fill(0, count($subtree), '?'));
        $stmt = $this->pdo->prepare(
            "SELECT COUNT(DISTINCT card_id) FROM dir_cards WHERE dir_id IN ($placeholders)"
        );
        $stmt->execute($subtree);
        $total = (int) $stmt->fetchColumn();

        return [
            'id' => $dirId,
            'name' => $dir['name'],
            'parents' => $parents,
            'subdirs' => $subdirs,
            'cards' => $direct,
            'cards_total' => $total,
        ];
    }

    private function assertValidName(string $name): void
    {
        if (!\Pauk\Text::isValidName($name)) {
            throw new ApiError(400, 'validation', 'Directory name must match ^[a-z0-9-]{1,64}$');
        }
    }
}

<?php

declare(strict_types=1);

namespace Pauk\Repo;

use Pauk\Knowledge\Time;
use Pauk\Version;

/**
 * The knowledge export (docs/tutor.md section 6): JSON lines with a
 * versioned header, everything except the derived states, so it can
 * be re-imported into any schema and the states rebuilt.
 */
final class Export
{
    public const FORMAT_VERSION = 1;

    public function __construct(
        private readonly \PDO $pdo,
        private readonly Items $items,
        private readonly Interactions $interactions,
        private readonly Settings $settings,
    ) {
    }

    /** @return \Generator<int, array<string, mixed>> */
    public function records(int $userId): \Generator
    {
        yield [
            'format' => 'pauk-export',
            'version' => self::FORMAT_VERSION,
            'api_version' => Version::VERSION,
            'exported_at' => Time::iso(Time::toDb(Time::now())),
        ];

        $stmt = $this->pdo->prepare('SELECT id, name FROM dirs WHERE user_id = ? ORDER BY id');
        $stmt->execute([$userId]);
        foreach ($stmt->fetchAll() as $dir) {
            $parents = $this->pdo->prepare('SELECT parent_id FROM dir_dirs WHERE child_id = ? ORDER BY parent_id');
            $parents->execute([$dir['id']]);
            yield ['type' => 'dir', 'id' => (int) $dir['id'], 'name' => $dir['name'],
                   'parents' => array_map('intval', $parents->fetchAll(\PDO::FETCH_COLUMN))];
        }

        $stmt = $this->pdo->prepare('SELECT id FROM items WHERE user_id = ? ORDER BY id');
        $stmt->execute([$userId]);
        foreach ($stmt->fetchAll(\PDO::FETCH_COLUMN) as $id) {
            $item = $this->items->detail($userId, $this->items->resolve($userId, (int) $id, false));
            $flags = $item['state'] === null ? null : ['status' => $item['state']['status'], 'note' => $item['state']['note']];
            unset($item['state'], $item['interactions'], $item['id']);
            $item['links'] = array_values(array_filter($item['links'], fn ($l) => $l['direction'] === 'out'));
            $item['links'] = array_map(fn ($l) => ['rel' => $l['rel'], 'to' => $l['ref'], 'note' => $l['note']], $item['links']);
            $item['dirs'] = array_map(fn ($d) => $d['id'], $item['dirs']);
            yield ['type' => 'item'] + $item + ['flags' => $flags];
        }

        $stmt = $this->pdo->prepare('SELECT * FROM interactions WHERE user_id = ? ORDER BY occurred_at, id');
        $stmt->execute([$userId]);
        while (($row = $stmt->fetch()) !== false) {
            yield ['type' => 'interaction'] + $this->interactions->view($row);
        }

        yield ['type' => 'settings', 'values' => $this->settings->all($userId)];
    }
}

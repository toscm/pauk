<?php

declare(strict_types=1);

namespace Pauk\Tests\integration;

final class ItemsDryRunTest extends ApiTestCase
{
    private function rowCount(string $table): int
    {
        return (int) self::$pdo->query("SELECT COUNT(*) FROM $table")->fetchColumn();
    }

    /** @return array{0: int, 1: mixed} */
    private function dryRun(array $body): array
    {
        return $this->request('POST', '/items', $body + ['space' => 'it', 'kind' => 'word', 'dry_run' => true]);
    }

    public function testWouldCreateWritesNothing(): void
    {
        $dir = $this->makeDir('italian');
        [$status, $body] = $this->dryRun(['label_md' => 'Farfalla', 'gloss_md' => 'butterfly', 'dirs' => [$dir]]);
        $this->assertSame(200, $status, json_encode($body));
        $this->assertFalse($body['created']);
        $this->assertTrue($body['would_create']);
        $this->assertSame('it/farfalla', $body['item']['ref']);
        $this->assertSame('it', $body['item']['space']);
        $this->assertSame('farfalla', $body['item']['key']);
        $this->assertSame('word', $body['item']['kind']);
        $this->assertSame('Farfalla', $body['item']['label_md']);
        $this->assertSame('butterfly', $body['item']['gloss_md']);
        $this->assertArrayNotHasKey('id', $body['item']);
        $this->assertSame(0, $this->rowCount('items'));
        $this->assertSame(0, $this->rowCount('dir_items'));

        [$status] = $this->request('GET', '/items/it/farfalla');
        $this->assertSame(404, $status);
    }

    public function testValidationAndRelationsStillApply(): void
    {
        [$status] = $this->dryRun(['label_md' => '']);
        $this->assertSame(400, $status);
        [$status] = $this->dryRun(['label_md' => 'farfalla', 'dry_run' => 'yes']);
        $this->assertSame(400, $status);
        // a form needs its lexeme, also in a dry run
        [$status] = $this->dryRun(['kind' => 'form', 'key' => 'essere.pres.1sg', 'label_md' => 'sono']);
        $this->assertSame(400, $status);
        $this->assertSame(0, $this->rowCount('items'));
    }

    public function testExactHitIsReported(): void
    {
        [$status, $created] = $this->request('POST', '/items', ['space' => 'it', 'kind' => 'word', 'label_md' => 'farfalla']);
        $this->assertSame(201, $status);
        [$status, $body] = $this->dryRun(['label_md' => 'farfalla']);
        $this->assertSame(200, $status);
        $this->assertFalse($body['created']);
        $this->assertSame('key', $body['via']);
        $this->assertArrayNotHasKey('would_create', $body);
        $this->assertSame($created['item']['id'], $body['item']['id']);
    }

    public function testCandidatesAndDecisions(): void
    {
        [, $peach] = $this->request('POST', '/items', ['space' => 'it', 'kind' => 'word', 'label_md' => 'pesca', 'gloss_md' => 'peach']);

        [$status, $body] = $this->dryRun(['label_md' => 'pesca', 'sense' => 'fishing']);
        $this->assertSame(409, $status);
        $this->assertSame('possible_duplicates', $body['error']['code']);
        $this->assertSame('it/pesca', $body['candidates'][0]['ref']);

        // distinct_from still needs a reason
        [$status] = $this->dryRun(['label_md' => 'pesca', 'sense' => 'fishing', 'distinct_from' => ['it/pesca']]);
        $this->assertSame(400, $status);

        [$status, $body] = $this->dryRun(['label_md' => 'pesca', 'sense' => 'fishing',
            'distinct_from' => ['it/pesca'], 'reason' => 'fishing, not peach']);
        $this->assertSame(200, $status, json_encode($body));
        $this->assertTrue($body['would_create']);
        $this->assertSame('it/pesca.fishing', $body['item']['ref']);
        $this->assertSame('it/pesca', $body['item']['links'][0]['ref']);
        $this->assertSame(1, $this->rowCount('items'));
        $this->assertSame(0, $this->rowCount('item_links'));
        unset($peach);
    }

    public function testSameAsWritesNoAliases(): void
    {
        [, $item] = $this->request('POST', '/items', ['space' => 'it', 'kind' => 'word', 'label_md' => 'farfalla']);
        $aliases = $this->rowCount('item_aliases');

        [$status, $body] = $this->dryRun(['label_md' => 'la farfalla', 'same_as' => 'it/farfalla', 'reason' => 'article only']);
        $this->assertSame(200, $status, json_encode($body));
        $this->assertFalse($body['created']);
        $this->assertSame('same_as', $body['via']);
        $this->assertSame($item['item']['id'], $body['item']['id']);
        $this->assertSame([], $body['item']['aliases']);
        $this->assertSame($aliases, $this->rowCount('item_aliases'));

        [$status] = $this->request('GET', '/items/it/la-farfalla');
        $this->assertSame(404, $status);
    }
}

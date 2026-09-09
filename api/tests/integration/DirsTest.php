<?php

declare(strict_types=1);

namespace Pauk\Tests\integration;

final class DirsTest extends ApiTestCase
{
    public function testCreateNestedAndResolve(): void
    {
        $italian = $this->makeDir('italian');
        $verbs = $this->makeDir('verbs', $italian);
        [$status, $dir] = $this->request('GET', '/dirs/resolve?path=italian/verbs');
        $this->assertSame(200, $status);
        $this->assertSame($verbs, $dir['id']);
        $this->assertSame([['id' => $italian, 'name' => 'italian']], $dir['parents']);

        [$status] = $this->request('GET', '/dirs/resolve?path=italian/nope');
        $this->assertSame(404, $status);
    }

    public function testSiblingNameClash(): void
    {
        $parent = $this->makeDir('parent');
        $this->makeDir('child', $parent);
        [$status, $data] = $this->request('POST', '/dirs', [
            'name' => 'child',
            'parent_id' => $parent,
        ]);
        $this->assertSame(409, $status);
        $this->assertSame('conflict', $data['error']['code']);
        // same name under a different parent is fine
        $other = $this->makeDir('other');
        [$status] = $this->request('POST', '/dirs', ['name' => 'child', 'parent_id' => $other]);
        $this->assertSame(201, $status);
    }

    public function testInvalidNameRejected(): void
    {
        [$status] = $this->request('POST', '/dirs', ['name' => 'No Spaces!']);
        $this->assertSame(400, $status);
    }

    public function testTopLevelListing(): void
    {
        $a = $this->makeDir('aaa');
        $this->makeDir('sub', $a);
        $this->makeDir('bbb');
        [, $data] = $this->request('GET', '/dirs');
        $this->assertSame(['aaa', 'bbb'], array_column($data['items'], 'name'));
        [, $data] = $this->request('GET', "/dirs?parent=$a");
        $this->assertSame(['sub'], array_column($data['items'], 'name'));
    }

    public function testDagMultipleParentsAndCounts(): void
    {
        // italian -> verbs -> core; italian -> a1; a1 -> verbs (diamond)
        $italian = $this->makeDir('italian');
        $verbs = $this->makeDir('verbs', $italian);
        $core = $this->makeDir('core', $verbs);
        $a1 = $this->makeDir('a1', $italian);
        [$status] = $this->request('PUT', "/dirs/$a1/dirs/$verbs");
        $this->assertSame(204, $status);

        $inCore = $this->makeTextCard('core card', ['x'], [$core]);
        $inVerbs = $this->makeTextCard('verbs card', ['x'], [$verbs]);
        // card linked twice inside the subtree must count once
        [$status] = $this->request('PUT', "/dirs/$core/cards/$inVerbs");
        $this->assertSame(204, $status);

        [, $dir] = $this->request('GET', "/dirs/$a1");
        $this->assertSame(0, $dir['cards']);
        $this->assertSame(2, $dir['cards_total']);
        [, $dir] = $this->request('GET', "/dirs/$verbs");
        $this->assertSame(1, $dir['cards']);
        $this->assertSame(2, $dir['cards_total']);
        $this->assertCount(2, $dir['parents']);

        // recursive card listing dedupes as well
        [, $data] = $this->request('GET', "/cards?dir=$a1&recursive=1");
        $this->assertCount(2, $data['items']);
        [, $data] = $this->request('GET', "/cards?dir=$a1");
        $this->assertCount(0, $data['items']);
        unset($inCore);
    }

    public function testCycleRejected(): void
    {
        $a = $this->makeDir('a');
        $b = $this->makeDir('b', $a);
        $c = $this->makeDir('c', $b);
        [$status, $data] = $this->request('PUT', "/dirs/$c/dirs/$a");
        $this->assertSame(409, $status);
        $this->assertSame('conflict', $data['error']['code']);
        [$status] = $this->request('PUT', "/dirs/$a/dirs/$a");
        $this->assertSame(409, $status);
    }

    public function testDeleteOrphanProtectionAndForce(): void
    {
        $parent = $this->makeDir('parent');
        $child = $this->makeDir('child', $parent);
        $cardId = $this->makeTextCard('Q', ['x'], [$child]);

        [$status] = $this->request('DELETE', "/dirs/$parent");
        $this->assertSame(409, $status);

        [$status] = $this->request('DELETE', "/dirs/$parent?force=1");
        $this->assertSame(204, $status);
        [$status] = $this->request('GET', "/dirs/$child");
        $this->assertSame(404, $status);
        // the card survives, now unfiled
        [$status, $card] = $this->request('GET', "/cards/$cardId");
        $this->assertSame(200, $status);
        $this->assertSame([], $card['dirs']);
        [, $data] = $this->request('GET', '/cards?unfiled=1');
        $this->assertCount(1, $data['items']);
    }

    public function testDeleteKeepsChildrenLinkedElsewhere(): void
    {
        $a = $this->makeDir('a');
        $b = $this->makeDir('b');
        $shared = $this->makeDir('shared', $a);
        [$status] = $this->request('PUT', "/dirs/$b/dirs/$shared");
        $this->assertSame(204, $status);
        [$status] = $this->request('DELETE', "/dirs/$a");
        $this->assertSame(204, $status);
        [$status, $dir] = $this->request('GET', "/dirs/$shared");
        $this->assertSame(200, $status);
        $this->assertSame([['id' => $b, 'name' => 'b']], $dir['parents']);
    }

    public function testRenameClash(): void
    {
        $parent = $this->makeDir('parent');
        $this->makeDir('x', $parent);
        $y = $this->makeDir('y', $parent);
        [$status] = $this->request('PATCH', "/dirs/$y", ['name' => 'x']);
        $this->assertSame(409, $status);
        [$status, $dir] = $this->request('PATCH', "/dirs/$y", ['name' => 'z']);
        $this->assertSame(200, $status);
        $this->assertSame('z', $dir['name']);
    }

    public function testUnlinkCard(): void
    {
        $dir = $this->makeDir('d');
        $card = $this->makeTextCard('Q', ['x'], [$dir]);
        [$status] = $this->request('DELETE', "/dirs/$dir/cards/$card");
        $this->assertSame(204, $status);
        [, $data] = $this->request('GET', "/cards?dir=$dir");
        $this->assertCount(0, $data['items']);
    }
}

<?php

declare(strict_types=1);

namespace Pauk\Tests\integration;

final class ItemsTest extends ApiTestCase
{
    /** @return array<string, mixed> the created item */
    private function makeItem(array $body): array
    {
        [$status, $data] = $this->request('POST', '/items', $body + ['space' => 'it', 'kind' => 'word']);
        $this->assertSame(201, $status, json_encode($data));
        return $data['item'];
    }

    public function testCreateDerivesKeyAndGetsByRef(): void
    {
        $item = $this->makeItem(['label_md' => 'Farfalla', 'gloss_md' => 'butterfly', 'priority' => 70]);
        $this->assertSame('it/farfalla', $item['ref']);
        $this->assertNull($item['state']);
        $this->assertEquals(new \stdClass(), (object) $item['attrs']);

        [$status, $byRef] = $this->request('GET', '/items/it/farfalla');
        $this->assertSame(200, $status);
        $this->assertSame('butterfly', $byRef['gloss_md']);
        [$status, $byId] = $this->request('GET', "/items/{$item['id']}");
        $this->assertSame(200, $status);
        $this->assertSame('it/farfalla', $byId['ref']);
    }

    public function testKeyRules(): void
    {
        [$status, $body] = $this->request('POST', '/items', ['space' => 'concepts', 'kind' => 'term', 'key' => 'term.retention-time', 'label_md' => 'retention time']);
        $this->assertSame(400, $status);
        $this->assertStringContainsString('kind prefix', $body['error']['message']);

        [$status] = $this->request('POST', '/items', ['space' => 'concepts', 'kind' => 'paper', 'label_md' => 'Park et al. 2006']);
        $this->assertSame(400, $status, 'papers need an explicit key');

        [$status, $body] = $this->request('POST', '/items', ['space' => 'el', 'kind' => 'word', 'label_md' => 'α']);
        $this->assertSame(201, $status);
        $this->assertSame('el/alpha', $body['item']['ref']);
    }

    public function testExactIdentityReturnsExistingItem(): void
    {
        $first = $this->makeItem(['label_md' => 'farfalla']);
        [$status, $again] = $this->request('POST', '/items', ['space' => 'it', 'kind' => 'word', 'label_md' => '*farfalla*']);
        $this->assertSame(200, $status);
        $this->assertFalse($again['created']);
        $this->assertSame('key', $again['via']);
        $this->assertSame($first['id'], $again['item']['id']);
    }

    public function testDoiIsStrongIdentity(): void
    {
        $paper = $this->makeItem(['space' => 'concepts', 'kind' => 'paper', 'key' => 'park-2006-flow-cytometry-gating',
            'label_md' => 'Park et al. 2006', 'attrs' => ['doi' => '10.1000/XYZ']]);
        [$status, $body] = $this->request('POST', '/items', ['space' => 'concepts', 'kind' => 'paper', 'key' => 'gating-paper',
            'label_md' => 'The gating paper', 'attrs' => ['doi' => '10.1000/xyz']]);
        $this->assertSame(200, $status);
        $this->assertSame('doi', $body['via']);
        $this->assertSame($paper['id'], $body['item']['id']);
    }

    public function testPatchToATakenDoiIsAConflict(): void
    {
        $this->makeItem(['space' => 'concepts', 'kind' => 'paper', 'key' => 'a-2001-x', 'label_md' => 'A', 'attrs' => ['doi' => '10.1/a']]);
        $this->makeItem(['space' => 'concepts', 'kind' => 'paper', 'key' => 'b-2002-y', 'label_md' => 'B', 'attrs' => ['doi' => '10.1/b']]);
        [$status, $body] = $this->request('PATCH', '/items/concepts/b-2002-y', ['attrs' => ['doi' => '10.1/A']]);
        $this->assertSame(409, $status, json_encode($body));
    }

    public function testCandidatesNeedAnExplicitDecision(): void
    {
        $peach = $this->makeItem(['label_md' => 'pesca', 'gloss_md' => 'peach']);

        // same label, different sense: candidates come back, nothing is created
        [$status, $body] = $this->request('POST', '/items', ['space' => 'it', 'kind' => 'word', 'label_md' => 'pesca', 'sense' => 'fishing']);
        $this->assertSame(409, $status);
        $this->assertSame('possible_duplicates', $body['error']['code']);
        $this->assertSame('it/pesca', $body['candidates'][0]['ref']);
        $this->assertSame('peach', $body['candidates'][0]['gloss_md']);

        // distinct_from without a reason is refused
        [$status] = $this->request('POST', '/items', ['space' => 'it', 'kind' => 'word', 'label_md' => 'pesca', 'sense' => 'fishing',
            'distinct_from' => ['it/pesca']]);
        $this->assertSame(400, $status);

        [$status, $body] = $this->request('POST', '/items', ['space' => 'it', 'kind' => 'word', 'label_md' => 'pesca', 'sense' => 'fishing',
            'gloss_md' => 'fishing', 'distinct_from' => ['it/pesca'], 'reason' => 'fishing, not peach']);
        $this->assertSame(201, $status);
        $this->assertSame('it/pesca.fishing', $body['item']['ref']);
        $related = array_values(array_filter($body['item']['links'], fn ($l) => $l['rel'] === 'related'));
        $this->assertSame('it/pesca', $related[0]['ref']);
        $this->assertSame('fishing, not peach', $related[0]['note']);
        unset($peach);
    }

    public function testArticleVariantIsACandidateAndSameAsMakesAnAlias(): void
    {
        $item = $this->makeItem(['label_md' => 'farfalla']);
        [$status, $body] = $this->request('POST', '/items', ['space' => 'it', 'kind' => 'word', 'label_md' => 'la farfalla']);
        $this->assertSame(409, $status);
        $this->assertSame('contains', $body['candidates'][0]['reason']);

        [$status, $body] = $this->request('POST', '/items', ['space' => 'it', 'kind' => 'word', 'label_md' => 'la farfalla',
            'same_as' => 'it/farfalla', 'reason' => 'article only']);
        $this->assertSame(200, $status);
        $this->assertSame('same_as', $body['via']);
        $this->assertSame($item['id'], $body['item']['id']);
        $this->assertSame('la-farfalla', $body['item']['aliases'][0]['alias']);

        // the alias now resolves, and creating it again is an exact hit
        [$status, $viaAlias] = $this->request('GET', '/items/it/la-farfalla');
        $this->assertSame(200, $status);
        $this->assertSame($item['id'], $viaAlias['id']);
        [$status, $again] = $this->request('POST', '/items', ['space' => 'it', 'kind' => 'word', 'label_md' => 'la farfalla']);
        $this->assertSame(200, $status);
        $this->assertSame('alias', $again['via']);
    }

    public function testNoFuzzyCandidatesForUnrelatedWords(): void
    {
        $this->makeItem(['label_md' => 'pesce']);
        $this->makeItem(['label_md' => 'fare']);
        // edit distance 1, but different words: words never get fuzzy candidates
        [$status] = $this->request('POST', '/items', ['space' => 'it', 'kind' => 'word', 'label_md' => 'pesca']);
        $this->assertSame(201, $status);
        [$status] = $this->request('POST', '/items', ['space' => 'it', 'kind' => 'word', 'label_md' => 'dare']);
        $this->assertSame(201, $status);
    }

    public function testTermsGetFuzzyAndCrossSpaceCandidates(): void
    {
        $this->makeItem(['space' => 'concepts', 'kind' => 'term', 'label_md' => 'regulatory T cell']);
        [$status, $body] = $this->request('POST', '/items', ['space' => 'concepts', 'kind' => 'term', 'label_md' => 'regulatory T cells']);
        $this->assertSame(409, $status);
        $this->assertSame('similar', $body['candidates'][0]['reason']);

        $this->makeItem(['space' => 'concepts', 'kind' => 'term', 'label_md' => 'Retention time']);
        [$status, $body] = $this->request('POST', '/items', ['space' => 'en', 'kind' => 'term', 'label_md' => 'retention time']);
        $this->assertSame(409, $status);
        $this->assertSame('label_other_space', $body['candidates'][0]['reason']);
    }

    public function testFormNeedsLexemeAndLinksToIt(): void
    {
        [$status] = $this->request('POST', '/items', ['space' => 'it', 'kind' => 'form', 'key' => 'essere.pres.1sg', 'label_md' => 'sono']);
        $this->assertSame(400, $status);
        $this->makeItem(['label_md' => 'essere', 'gloss_md' => 'to be']);
        $form = $this->makeItem(['kind' => 'form', 'key' => 'essere.pres.1sg', 'label_md' => 'sono']);
        $this->assertSame('form_of', $form['links'][0]['rel']);
        $this->assertSame('it/essere', $form['links'][0]['ref']);
    }

    public function testRenameKeepsOldKeyAsAlias(): void
    {
        $item = $this->makeItem(['label_md' => 'ancora', 'gloss_md' => 'anchor']);
        [$status, $renamed] = $this->request('PATCH', '/items/it/ancora', ['key' => 'ancora.anchor']);
        $this->assertSame(200, $status);
        $this->assertSame('it/ancora.anchor', $renamed['ref']);
        [$status, $old] = $this->request('GET', '/items/it/ancora');
        $this->assertSame(200, $status);
        $this->assertSame($item['id'], $old['id']);
    }

    public function testSubjectsAreDirectoriesWithManyMemberships(): void
    {
        $stats = $this->makeDir('statistics');
        $bio = $this->makeDir('bioinformatics');
        $this->makeItem(['space' => 'concepts', 'kind' => 'term', 'label_md' => 'linear regression', 'dirs' => [$stats]]);
        [$status] = $this->request('PUT', "/dirs/$bio/items/concepts/linear-regression");
        $this->assertSame(204, $status);
        [, $item] = $this->request('GET', '/items/concepts/linear-regression');
        $this->assertSame(['bioinformatics', 'statistics'], array_column($item['dirs'], 'name'));
        [, $list] = $this->request('GET', "/items?dir=$bio");
        $this->assertSame(['concepts/linear-regression'], array_column($list['items'], 'ref'));
    }

    public function testSearchCoversGlossAndAliases(): void
    {
        $this->makeItem(['space' => 'concepts', 'kind' => 'term', 'label_md' => 'regulatory T cell', 'gloss_md' => 'Treg, suppresses immune responses']);
        [, $list] = $this->request('GET', '/items?q=treg');
        $this->assertCount(1, $list['items']);
        [, $list] = $this->request('GET', '/items?q=suppresses');
        $this->assertCount(1, $list['items']);
    }

    public function testArchiveHidesFromLists(): void
    {
        $this->makeItem(['label_md' => 'farfalla']);
        [$status] = $this->request('POST', '/items/it/farfalla/archive');
        $this->assertSame(200, $status);
        [, $list] = $this->request('GET', '/items');
        $this->assertSame([], $list['items']);
        [, $list] = $this->request('GET', '/items?archived=1');
        $this->assertCount(1, $list['items']);
    }

    public function testBulkUpsertsAndProtectsTeacherItems(): void
    {
        $this->makeItem(['label_md' => 'pesca', 'gloss_md' => 'fishing', 'attrs' => ['origin' => 'teacher']]);
        [$status, $result] = $this->request('PUT', '/items/bulk', ['items' => [
            ['space' => 'it', 'kind' => 'word', 'key' => 'parlare', 'label_md' => 'parlare', 'gloss_md' => 'to speak',
             'links' => [['rel' => 'requires', 'to' => 'present-are']]],
            ['space' => 'it', 'kind' => 'rule', 'key' => 'present-are', 'label_md' => 'present tense of -are verbs'],
            ['space' => 'it', 'kind' => 'word', 'key' => 'pesca', 'label_md' => 'pesca', 'gloss_md' => 'peach'],
        ]]);
        $this->assertSame(200, $status, json_encode($result));
        $this->assertSame(2, $result['created']);
        $this->assertSame('it/pesca', $result['conflicts'][0]['ref']);
        $this->assertSame([], $result['unresolved_links'], 'forward links within a batch resolve');
        [, $pesca] = $this->request('GET', '/items/it/pesca');
        $this->assertSame('fishing', $pesca['gloss_md']);

        [, $again] = $this->request('PUT', '/items/bulk', ['items' => [
            ['space' => 'it', 'kind' => 'word', 'key' => 'parlare', 'label_md' => 'parlare', 'gloss_md' => 'to speak, to talk'],
        ]]);
        $this->assertSame(1, $again['updated']);
    }

    public function testFlags(): void
    {
        $this->makeItem(['label_md' => 'farfalla']);
        [$status, $item] = $this->request('PUT', '/items/it/farfalla/state', ['status' => 'focus', 'note' => 'confuses with farfallina']);
        $this->assertSame(200, $status);
        $this->assertSame('focus', $item['state']['status']);
        $this->assertSame(0, $item['state']['mastery']);
        $this->assertNull($item['state']['recall']);
    }
}

<?php

declare(strict_types=1);

namespace Pauk\Tests\integration;

use Pauk\Repo\Interactions;

/** Profile summary, selection, merges, settings and export. */
final class ProfileTest extends ApiTestCase
{
    private function item(string $ref, string $kind = 'word', array $extra = []): void
    {
        [$space, $key] = explode('/', $ref);
        [$status, $body] = $this->request('POST', '/items', $extra + ['space' => $space, 'kind' => $kind, 'key' => $key, 'label_md' => str_replace('-', ' ', $key)]);
        $this->assertContains($status, [200, 201], json_encode($body));
    }

    private function answer(string $ref, string $outcome, string $at, string $mode = 'recall'): void
    {
        [$status, $body] = $this->request('POST', '/interactions', ['uuid' => Interactions::uuid(), 'mode' => $mode,
            'occurred_at' => $at, 'items' => [['ref' => $ref, 'outcome' => $outcome]]]);
        $this->assertSame(201, $status, json_encode($body));
    }

    public function testSummaryCountsLevelsAndCoverage(): void
    {
        $this->item('it/ape', 'word', ['priority' => 100]);
        $this->item('it/farfalla', 'word', ['priority' => 100]);
        $this->answer('it/ape', 'good', gmdate('Y-m-d\TH:i:s\Z'));
        [$status, $summary] = $this->request('GET', '/profile?space=it');
        $this->assertSame(200, $status);
        $this->assertSame(2, $summary['items']);
        $this->assertSame(1, $summary['by_mastery']['0']);
        $this->assertSame(1, $summary['by_mastery']['3']);
        $this->assertEqualsWithDelta(0.5, $summary['coverage'], 0.01);
    }

    public function testNextOrdersReviewAndRespectsPrerequisitesAndFlags(): void
    {
        $this->item('it/present-are', 'rule', ['priority' => 90]);
        $this->item('it/parlare', 'word', ['priority' => 95, 'links' => [['rel' => 'requires', 'to' => 'present-are']]]);
        $this->item('it/ape', 'word', ['priority' => 40]);
        $this->item('it/farfalla', 'word', ['priority' => 60]);
        $this->item('it/vespa', 'word', ['priority' => 99]);
        $this->request('PUT', '/items/it/vespa/state', ['status' => 'suspended']);
        // ape learnt long ago: due
        $this->answer('it/ape', 'good', '2025-01-01T00:00:00Z');

        [$status, $next] = $this->request('GET', '/profile/next?space=it&n=10');
        $this->assertSame(200, $status);
        $this->assertSame(['it/ape'], array_column($next['review'], 'ref'));
        $this->assertStringStartsWith('due: R=', $next['review'][0]['reason']);
        // parlare is blocked by its prerequisite; vespa is suspended
        $this->assertSame(['it/present-are', 'it/farfalla'], array_column($next['new'], 'ref'));

        // once the rule is known (level >= 3), parlare is offered first
        $this->answer('it/present-are', 'easy', gmdate('Y-m-d\TH:i:s\Z'));
        [, $next] = $this->request('GET', '/profile/next?space=it&n=10&new=1');
        $this->assertSame(['it/parlare'], array_column($next['new'], 'ref'));
    }

    public function testMergeMovesEvidenceAndUnmergeRestoresIt(): void
    {
        $this->item('concepts/bayes-theorem', 'term');
        $this->item('concepts/bayes-rule', 'term', ['distinct_from' => ['concepts/bayes-theorem'], 'reason' => 'test setup']);
        $stats = $this->makeDir('statistics');
        $this->request('PUT', "/dirs/$stats/items/concepts/bayes-rule");
        $this->answer('concepts/bayes-theorem', 'good', '2026-01-01T00:00:00Z');
        $this->answer('concepts/bayes-rule', 'good', '2026-01-05T00:00:00Z');

        [$status, $merge] = $this->request('POST', '/items/concepts/bayes-theorem/merge',
            ['from' => 'concepts/bayes-rule', 'reason' => 'two names of one theorem', 'by' => 'teacher']);
        $this->assertSame(200, $status, json_encode($merge));
        $this->assertSame('done', $merge['status']);

        [, $a] = $this->request('GET', '/items/concepts/bayes-theorem');
        $this->assertSame(2, $a['state']['reps']);
        $this->assertSame(['statistics'], array_column($a['dirs'], 'name'));
        // the old ref resolves to the surviving item
        [, $viaOld] = $this->request('GET', '/items/concepts/bayes-rule');
        $this->assertSame($a['id'], $viaOld['id']);

        [$status, $undone] = $this->request('POST', '/items/concepts/bayes-rule/unmerge');
        $this->assertSame(200, $status, json_encode($undone));
        $this->assertSame('undone', $undone['status']);
        [, $a] = $this->request('GET', '/items/concepts/bayes-theorem');
        [, $b] = $this->request('GET', '/items/concepts/bayes-rule');
        $this->assertSame(1, $a['state']['reps']);
        $this->assertSame(1, $b['state']['reps']);
        $this->assertSame([], $a['dirs']);
        $this->assertSame(['statistics'], array_column($b['dirs'], 'name'));
        $this->assertFalse($b['archived']);
    }

    public function testMergeSuggestions(): void
    {
        $this->item('concepts/t-cell', 'term');
        $this->item('concepts/t-lymphocyte', 'term');
        [$status, $suggestion] = $this->request('POST', '/merges', ['into' => 'concepts/t-cell', 'from' => 'concepts/t-lymphocyte',
            'reason' => 'synonyms', 'by' => 'sweep']);
        $this->assertSame(201, $status);
        $this->assertSame('suggested', $suggestion['status']);
        [, $pending] = $this->request('GET', '/merges?status=suggested');
        $this->assertCount(1, $pending['items']);

        [$status, $accepted] = $this->request('POST', "/merges/{$suggestion['id']}/accept");
        $this->assertSame(200, $status);
        $this->assertSame('done', $accepted['status']);
        [, $b] = $this->request('GET', '/items/concepts/t-lymphocyte');
        $this->assertSame('concepts/t-cell', $b['ref']);
    }

    public function testDismissedSuggestionRecordsDistinctPair(): void
    {
        $this->item('concepts/t-cell', 'term');
        $this->item('concepts/b-cell', 'term');
        [, $suggestion] = $this->request('POST', '/merges', ['into' => 'concepts/t-cell', 'from' => 'concepts/b-cell', 'reason' => 'similar', 'by' => 'sweep']);
        [$status] = $this->request('POST', "/merges/{$suggestion['id']}/dismiss");
        $this->assertSame(200, $status);
        [, $b] = $this->request('GET', '/items/concepts/b-cell');
        $this->assertSame('related', $b['links'][0]['rel']);
    }

    public function testSettingsDefaultsAndValidation(): void
    {
        [$status, $settings] = $this->request('GET', '/settings');
        $this->assertSame(200, $status);
        $this->assertSame('de', $settings['tutor.language']);
        $this->assertSame('propose', $settings['tutor.item_creation']);

        [$status, $settings] = $this->request('PATCH', '/settings', ['tutor.language' => 'en', 'tutor.immersion' => ['it' => 'partial']]);
        $this->assertSame(200, $status);
        $this->assertSame('en', $settings['tutor.language']);
        $this->assertSame(['it' => 'partial'], $settings['tutor.immersion']);

        [$status] = $this->request('PATCH', '/settings', ['tutor.item_creation' => 'always']);
        $this->assertSame(400, $status);
        [$status] = $this->request('PATCH', '/settings', ['no.such.setting' => 1]);
        $this->assertSame(400, $status);
    }

    public function testExportIsVersionedJsonLines(): void
    {
        $this->item('it/ape', 'word', ['gloss_md' => 'bee']);
        $this->answer('it/ape', 'good', '2026-01-01T00:00:00Z');
        $request = (new \Slim\Psr7\Factory\ServerRequestFactory())
            ->createServerRequest('GET', 'http://localhost/api/v1/export')
            ->withHeader('Authorization', 'Bearer ' . self::$token);
        $response = self::$app->handle($request);
        $this->assertSame(200, $response->getStatusCode());
        $this->assertStringStartsWith('application/x-ndjson', $response->getHeaderLine('Content-Type'));
        $lines = array_map(fn ($l) => json_decode($l, true), array_filter(explode("\n", (string) $response->getBody())));
        $lines = array_values($lines);
        $this->assertSame(['format' => 'pauk-export', 'version' => 1], array_intersect_key($lines[0], ['format' => 1, 'version' => 1]));
        $types = array_column(array_slice($lines, 1), 'type');
        $this->assertSame(['item', 'interaction', 'settings'], $types);
        $this->assertSame('it/ape', $lines[1]['ref']);
        $this->assertSame('it/ape', $lines[2]['items'][0]['ref']);
        $this->assertArrayNotHasKey('state', $lines[1]);
    }
}

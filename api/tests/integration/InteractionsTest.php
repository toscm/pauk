<?php

declare(strict_types=1);

namespace Pauk\Tests\integration;

use Pauk\Repo\Interactions;

final class InteractionsTest extends ApiTestCase
{
    protected function setUp(): void
    {
        parent::setUp();
        foreach (['farfalla' => 'butterfly', 'ape' => 'bee', 'parlare' => 'to speak'] as $word => $gloss) {
            [$status] = $this->request('POST', '/items', ['space' => 'it', 'kind' => 'word', 'label_md' => $word, 'gloss_md' => $gloss]);
            $this->assertSame(201, $status);
        }
    }

    private function record(array $body): array
    {
        [$status, $data] = $this->request('POST', '/interactions', $body + ['uuid' => Interactions::uuid(), 'source' => 'tutor']);
        $this->assertSame(201, $status, json_encode($data));
        return $data;
    }

    public function testExplicitOutcomesUpdateStates(): void
    {
        $result = $this->record(['mode' => 'recall', 'items' => [
            ['ref' => 'it/farfalla', 'outcome' => 'good'],
            ['ref' => 'it/ape', 'outcome' => 'fail', 'note' => 'said vespa'],
        ]]);
        $byRef = array_column($result['items'], null, 'ref');
        $this->assertSame(0, $byRef['it/farfalla']['mastery_before']);
        $this->assertSame(3, $byRef['it/farfalla']['state']['mastery']);
        $this->assertEqualsWithDelta(1.0, $byRef['it/farfalla']['state']['recall'], 0.001);
        $this->assertSame(1, $byRef['it/ape']['state']['mastery']);
        $this->assertSame(1, $byRef['it/ape']['state']['lapses']);

        [, $item] = $this->request('GET', '/items/it/ape');
        $this->assertSame('said vespa', $item['interactions'][0]['note']);
    }

    public function testKeyedExerciseIsGradedByTheApi(): void
    {
        $result = $this->record([
            'mode' => 'recall',
            'exercise' => ['kind' => 'text', 'prompt_md' => 'Italian for *butterfly*?', 'accepted' => ['farfalla']],
            'response' => ['text' => 'farfala'],
            'items' => [['ref' => 'it/farfalla']],
        ]);
        $this->assertSame('typo', $result['match']);
        $this->assertTrue($result['correct']);
        $this->assertSame('hard', $result['items'][0]['outcome']);
        $this->assertSame(['accepted' => ['farfalla']], $result['expected']);

        [, $history] = $this->request('GET', '/interactions?item=it/farfalla');
        $this->assertSame('text@1', $history['items'][0]['grader']);
        $this->assertSame('farfala', $history['items'][0]['response']['text']);
    }

    public function testOutcomeRequiredWithoutKey(): void
    {
        [$status] = $this->request('POST', '/interactions', ['mode' => 'explain', 'items' => [['ref' => 'it/ape']]]);
        $this->assertSame(400, $status);
        [$status] = $this->request('POST', '/interactions', ['mode' => 'introduce', 'items' => [['ref' => 'it/ape', 'outcome' => 'good']]]);
        $this->assertSame(400, $status);
    }

    public function testUuidMakesRecordingIdempotent(): void
    {
        $uuid = Interactions::uuid();
        $body = ['uuid' => $uuid, 'mode' => 'recall', 'items' => [['ref' => 'it/ape', 'outcome' => 'good']]];
        [$status] = $this->request('POST', '/interactions', $body);
        $this->assertSame(201, $status);
        [$status, $again] = $this->request('POST', '/interactions', $body);
        $this->assertSame(200, $status);
        $this->assertFalse($again['created']);
        [, $item] = $this->request('GET', '/items/it/ape');
        $this->assertSame(1, $item['state']['reps']);
    }

    public function testHintCapsAtHard(): void
    {
        $result = $this->record(['mode' => 'recall', 'hinted' => true, 'items' => [['ref' => 'it/ape', 'outcome' => 'easy']]]);
        // first contact with a capped 'hard': S = 1.0 instead of 8.0
        $this->assertEqualsWithDelta(1.0, $result['items'][0]['state']['stability'], 0.001);
    }

    public function testAmendmentReplaysWithoutEditingTheLog(): void
    {
        $result = $this->record(['mode' => 'recall', 'items' => [['ref' => 'it/parlare', 'outcome' => 'fail']]]);
        $this->assertSame(1, $result['items'][0]['state']['mastery']);
        [$status, $amended] = $this->request('POST', "/interactions/{$result['uuid']}/amendments", [
            'items' => [['ref' => 'it/parlare', 'outcome' => 'good']], 'reason' => 'synonym accepted', 'by' => 'teacher',
        ]);
        $this->assertSame(200, $status, json_encode($amended));
        $this->assertSame('good', $amended['items'][0]['outcome']);
        $this->assertSame(3, $amended['items'][0]['state']['mastery']);
        $this->assertSame(0, $amended['items'][0]['state']['lapses']);

        [, $history] = $this->request('GET', '/interactions?item=it/parlare');
        $this->assertSame('fail', $history['items'][0]['items'][0]['outcome'], 'the original outcome stays in the log');
        $this->assertSame('synonym accepted', $history['items'][0]['amendments'][0]['reason']);
    }

    public function testOutOfOrderEventsAreReplayedInTimeOrder(): void
    {
        $this->record(['mode' => 'recall', 'occurred_at' => '2026-01-10T10:00:00Z', 'items' => [['ref' => 'it/ape', 'outcome' => 'good']]]);
        $this->record(['mode' => 'recall', 'occurred_at' => '2026-01-01T10:00:00Z', 'items' => [['ref' => 'it/ape', 'outcome' => 'good']]]);
        [, $item] = $this->request('GET', '/items/it/ape');
        $this->assertSame('2026-01-01T10:00:00.000Z', $item['state']['first_seen_at']);
        $this->assertSame('2026-01-10T10:00:00.000Z', $item['state']['last_seen_at']);
        $this->assertSame(2, $item['state']['reps']);
    }

    public function testRebuildReproducesIncrementalStates(): void
    {
        // the replay test (docs/tutor.md 4.6): states are a faithful cache of the log
        $times = ['2026-01-01T08:00:00Z', '2026-01-03T08:00:00Z', '2026-01-09T08:00:00Z', '2026-02-20T08:00:00Z'];
        $outcomes = ['good', 'hard', 'fail', 'easy'];
        $this->record(['mode' => 'introduce', 'occurred_at' => '2025-12-31T08:00:00Z', 'items' => [['ref' => 'it/farfalla']]]);
        foreach ($times as $i => $t) {
            $this->record(['mode' => $i % 2 ? 'recognize' : 'recall', 'occurred_at' => $t, 'hinted' => $i === 3,
                'items' => [['ref' => 'it/farfalla', 'outcome' => $outcomes[$i]], ['ref' => 'it/ape', 'outcome' => $outcomes[3 - $i]]]]);
        }
        $before = self::$pdo->query('SELECT * FROM item_states ORDER BY item_id')->fetchAll();
        [$status, $rebuilt] = $this->request('POST', '/admin/rebuild-states');
        $this->assertSame(200, $status);
        $this->assertSame(2, $rebuilt['items']);
        $after = self::$pdo->query('SELECT * FROM item_states ORDER BY item_id')->fetchAll();
        $this->assertCount(2, $after);
        foreach ($before as $i => $row) {
            foreach (['stability', 'difficulty'] as $col) {
                $this->assertEqualsWithDelta((float) $row[$col], (float) $after[$i][$col], 1e-9);
            }
            foreach (['first_seen_at', 'last_seen_at', 'reps', 'lapses', 'best_mode', 'model'] as $col) {
                $this->assertSame($row[$col], $after[$i][$col], $col);
            }
        }
    }

    public function testLinkedCardAnswersFeedTheProfileAndLinkingBackfills(): void
    {
        $cardId = $this->makeTextCard('Italian for **butterfly**?', ['farfalla']);
        // an answer before linking: only a review
        $this->request('POST', "/cards/$cardId/answer", ['answer' => 'farfalla']);
        [$status] = $this->request('PUT', "/cards/$cardId/items/it/farfalla");
        $this->assertSame(204, $status);
        [, $item] = $this->request('GET', '/items/it/farfalla');
        $this->assertSame([$cardId], $item['cards']);
        $this->assertSame(1, $item['state']['reps'], 'past review backfilled');
        $this->assertSame('card', $item['interactions'][0]['source']);

        // answers after linking are recorded live, typo = hard
        $this->request('POST', "/cards/$cardId/answer", ['answer' => 'farfala']);
        [, $item] = $this->request('GET', '/items/it/farfalla');
        $this->assertSame(2, $item['state']['reps']);
        $this->assertSame('hard', $item['interactions'][0]['outcome']);

        // linking a second item reuses the existing interactions
        $this->request('PUT', "/cards/$cardId/items/it/ape");
        $count = (int) self::$pdo->query('SELECT COUNT(*) FROM interactions')->fetchColumn();
        $this->assertSame(2, $count);
        [, $ape] = $this->request('GET', '/items/it/ape');
        $this->assertSame(2, $ape['state']['reps']);
    }

    public function testSessionHistory(): void
    {
        $this->record(['mode' => 'introduce', 'session_id' => 's1', 'items' => [['ref' => 'it/ape']]]);
        $this->record(['mode' => 'introduce', 'session_id' => 's2', 'items' => [['ref' => 'it/parlare']]]);
        [, $history] = $this->request('GET', '/interactions?session_id=s1');
        $this->assertCount(1, $history['items']);
        $this->assertSame('it/ape', $history['items'][0]['items'][0]['ref']);
    }
}

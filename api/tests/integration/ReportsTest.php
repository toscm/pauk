<?php

declare(strict_types=1);

namespace Pauk\Tests\integration;

final class ReportsTest extends ApiTestCase
{
    /** @return array<string, mixed> the created report */
    private function makeReport(array $body): array
    {
        [$status, $data] = $this->request('POST', '/reports', $body + [
            'reporter' => 'learner', 'category' => 'bug', 'text_md' => 'Something broke',
        ]);
        $this->assertSame(201, $status, json_encode($data));
        return $data;
    }

    public function testCreateAndGet(): void
    {
        $report = $this->makeReport([
            'session_uid' => 's-42', 'seq' => 17, 'category' => 'content', 'reporter' => 'teacher',
            'text_md' => 'Gloss of *pesca* is wrong', 'context' => ['events' => [['seq' => 17]], 'api' => '0.11.0'],
        ]);
        $this->assertSame('s-42', $report['session_uid']);
        $this->assertSame(17, $report['seq']);
        $this->assertSame('teacher', $report['reporter']);
        $this->assertSame('content', $report['category']);
        $this->assertSame(['events' => [['seq' => 17]], 'api' => '0.11.0'], $report['context']);
        $this->assertSame('new', $report['status']);
        $this->assertNull($report['issue_ref']);

        [$status, $got] = $this->request('GET', "/reports/{$report['id']}");
        $this->assertSame(200, $status);
        $this->assertSame($report, $got);

        // defaults: no session, empty context object
        $bare = $this->makeReport([]);
        $this->assertNull($bare['session_uid']);
        $this->assertNull($bare['seq']);
        $this->assertSame([], $bare['context']);
        $raw = (string) self::$pdo->query("SELECT context FROM reports WHERE id = {$bare['id']}")->fetchColumn();
        $this->assertSame('{}', $raw);

        [$status] = $this->request('GET', '/reports/999999');
        $this->assertSame(404, $status);
    }

    public function testValidation(): void
    {
        $valid = ['reporter' => 'learner', 'category' => 'bug', 'text_md' => 'x'];
        foreach ([
            ['reporter' => 'robot'],
            ['category' => 'feature'],
            ['text_md' => '   '],
            ['text_md' => 5],
            ['context' => ['a', 'b']],
            ['context' => 'text'],
            ['session_uid' => 'Not Valid'],
            ['seq' => 'seven'],
            ['seq' => -1],
        ] as $change) {
            [$status, $body] = $this->request('POST', '/reports', $change + $valid);
            $this->assertSame(400, $status, json_encode($change));
            $this->assertSame('validation', $body['error']['code']);
        }

        [$status, $body] = $this->request('POST', '/reports', ['text_md' => str_repeat('ä', 20001)] + $valid);
        $this->assertSame(413, $status);
        $this->assertStringContainsString('text_md', $body['error']['message']);
        // the limit itself is accepted, also for multi-byte text
        [$status] = $this->request('POST', '/reports', ['text_md' => str_repeat('ä', 20000)] + $valid);
        $this->assertSame(201, $status);

        [$status, $body] = $this->request('POST', '/reports', ['context' => ['blob' => str_repeat('x', 210 * 1024)]] + $valid);
        $this->assertSame(413, $status);
        $this->assertSame('too_large', $body['error']['code']);
        $this->assertStringContainsString('context', $body['error']['message']);
    }

    public function testFiltersAndPagination(): void
    {
        $first = $this->makeReport(['session_uid' => 's-1', 'category' => 'bug']);
        $second = $this->makeReport(['session_uid' => 's-1', 'category' => 'ux']);
        $third = $this->makeReport(['session_uid' => 's-2', 'category' => 'bug']);

        [$status, $all] = $this->request('GET', '/reports');
        $this->assertSame(200, $status);
        $this->assertSame([$third['id'], $second['id'], $first['id']], array_column($all['items'], 'id'));
        $this->assertNull($all['next_cursor']);

        [, $bugs] = $this->request('GET', '/reports?category=bug');
        $this->assertSame([$third['id'], $first['id']], array_column($bugs['items'], 'id'));
        [, $session] = $this->request('GET', '/reports?session_uid=s-1');
        $this->assertSame([$second['id'], $first['id']], array_column($session['items'], 'id'));
        [, $both] = $this->request('GET', '/reports?session_uid=s-1&category=bug');
        $this->assertSame([$first['id']], array_column($both['items'], 'id'));

        $this->request('PATCH', "/reports/{$second['id']}", ['status' => 'closed']);
        [, $new] = $this->request('GET', '/reports?status=new');
        $this->assertSame([$third['id'], $first['id']], array_column($new['items'], 'id'));

        [, $page] = $this->request('GET', '/reports?limit=2');
        $this->assertSame([$third['id'], $second['id']], array_column($page['items'], 'id'));
        [, $rest] = $this->request('GET', '/reports?limit=2&cursor=' . urlencode($page['next_cursor']));
        $this->assertSame([$first['id']], array_column($rest['items'], 'id'));
        $this->assertNull($rest['next_cursor']);
    }

    public function testPatchStatusAndIssueRef(): void
    {
        $report = $this->makeReport([]);
        [$status, $triaged] = $this->request('PATCH', "/reports/{$report['id']}", [
            'status' => 'triaged', 'issue_ref' => 'issues/0042-pesca-gloss.md',
        ]);
        $this->assertSame(200, $status, json_encode($triaged));
        $this->assertSame('triaged', $triaged['status']);
        $this->assertSame('issues/0042-pesca-gloss.md', $triaged['issue_ref']);
        $this->assertSame('Something broke', $triaged['text_md']);

        [$status, $closed] = $this->request('PATCH', "/reports/{$report['id']}", ['status' => 'closed']);
        $this->assertSame(200, $status);
        $this->assertSame('issues/0042-pesca-gloss.md', $closed['issue_ref'], 'absent fields are kept');

        [$status] = $this->request('PATCH', "/reports/{$report['id']}", ['status' => 'done']);
        $this->assertSame(400, $status);
        [$status] = $this->request('PATCH', "/reports/{$report['id']}", ['issue_ref' => str_repeat('x', 256)]);
        $this->assertSame(400, $status);
        [$status] = $this->request('PATCH', '/reports/999999', ['status' => 'closed']);
        $this->assertSame(404, $status);
    }

    public function testMalformedCursorAndUidAreRejected(): void
    {
        [$status] = $this->request('GET', '/reports?cursor[]=1');
        $this->assertSame(400, $status);
        [$status] = $this->request('GET', '/items?cursor[]=1');
        $this->assertSame(400, $status);
        [$status] = $this->request('POST', '/tutor-sessions', ['uid' => "s-1
"]);
        $this->assertSame(400, $status);
    }
}

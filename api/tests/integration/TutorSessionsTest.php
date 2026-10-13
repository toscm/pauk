<?php

declare(strict_types=1);

namespace Pauk\Tests\integration;

final class TutorSessionsTest extends ApiTestCase
{
    public function testCreateIsIdempotentOnUid(): void
    {
        [$status, $session] = $this->request('POST', '/tutor-sessions', [
            'uid' => 's-42', 'goal' => ['dir' => 'italian', 'minutes' => 15], 'teacher' => 'claude',
            'started_at' => '2026-10-13T10:00:00.250+02:00',
        ]);
        $this->assertSame(201, $status, json_encode($session));
        $this->assertSame('s-42', $session['uid']);
        $this->assertSame(['dir' => 'italian', 'minutes' => 15], $session['goal']);
        $this->assertSame('claude', $session['teacher']);
        $this->assertSame('2026-10-13T08:00:00.250Z', $session['started_at']);
        $this->assertNull($session['ended_at']);
        $this->assertNull($session['summary_md']);

        // a retry returns the stored session unchanged
        [$status, $again] = $this->request('POST', '/tutor-sessions', ['uid' => 's-42', 'teacher' => 'other']);
        $this->assertSame(200, $status);
        $this->assertSame($session, $again);
        $this->assertSame(1, (int) self::$pdo->query('SELECT COUNT(*) FROM tutor_sessions')->fetchColumn());
    }

    public function testDefaultsAndValidation(): void
    {
        [$status, $session] = $this->request('POST', '/tutor-sessions', ['uid' => 'minimal']);
        $this->assertSame(201, $status);
        $this->assertNull($session['goal']);
        $this->assertNull($session['teacher']);
        $this->assertNotNull($session['started_at']);

        foreach ([
            ['uid' => 'Upper'],
            ['uid' => str_repeat('a', 65)],
            [],
            ['uid' => 'x', 'goal' => ['a', 'b']],
            ['uid' => 'x', 'goal' => 'learn'],
            ['uid' => 'x', 'teacher' => 5],
            ['uid' => 'x', 'started_at' => 'no date!'],
        ] as $body) {
            [$status] = $this->request('POST', '/tutor-sessions', $body);
            $this->assertSame(400, $status, json_encode($body));
        }
    }

    public function testPatchEndsSession(): void
    {
        $this->request('POST', '/tutor-sessions', ['uid' => 's-1', 'goal' => ['dir' => 'greek']]);
        [$status, $session] = $this->request('PATCH', '/tutor-sessions/s-1', [
            'ended_at' => '2026-10-13T10:30:00Z', 'summary_md' => 'Practised the alphabet.', 'teacher' => 'claude opus',
        ]);
        $this->assertSame(200, $status, json_encode($session));
        $this->assertSame('2026-10-13T10:30:00.000Z', $session['ended_at']);
        $this->assertSame('Practised the alphabet.', $session['summary_md']);
        $this->assertSame('claude opus', $session['teacher']);
        $this->assertSame(['dir' => 'greek'], $session['goal'], 'absent fields are kept');

        [$status, $got] = $this->request('GET', '/tutor-sessions/s-1');
        $this->assertSame(200, $status);
        $this->assertSame('Practised the alphabet.', $got['summary_md']);

        [$status, $cleared] = $this->request('PATCH', '/tutor-sessions/s-1', ['goal' => null]);
        $this->assertSame(200, $status);
        $this->assertNull($cleared['goal']);

        [$status] = $this->request('PATCH', '/tutor-sessions/s-1', ['ended_at' => 'no date!']);
        $this->assertSame(400, $status);
        [$status] = $this->request('PATCH', '/tutor-sessions/missing', ['summary_md' => 'x']);
        $this->assertSame(404, $status);
        [$status] = $this->request('GET', '/tutor-sessions/missing');
        $this->assertSame(404, $status);
    }

    public function testListIsNewestFirstAndPaginated(): void
    {
        foreach (['a', 'b', 'c'] as $uid) {
            $this->request('POST', '/tutor-sessions', ['uid' => $uid]);
        }
        [$status, $page] = $this->request('GET', '/tutor-sessions?limit=2');
        $this->assertSame(200, $status);
        $this->assertSame(['c', 'b'], array_column($page['items'], 'uid'));
        $this->assertNotNull($page['next_cursor']);

        [, $rest] = $this->request('GET', '/tutor-sessions?limit=2&cursor=' . urlencode($page['next_cursor']));
        $this->assertSame(['a'], array_column($rest['items'], 'uid'));
        $this->assertNull($rest['next_cursor']);

        [$status] = $this->request('GET', '/tutor-sessions?cursor=nope');
        $this->assertSame(400, $status);
    }

    public function testSessionsArePerUser(): void
    {
        $this->request('POST', '/tutor-sessions', ['uid' => 'mine']);
        self::$pdo->exec("INSERT INTO users (name) VALUES ('other')");
        $otherId = (int) self::$pdo->lastInsertId();
        $token = bin2hex(random_bytes(16));
        self::$pdo->prepare('INSERT INTO api_tokens (user_id, token_hash) VALUES (?, ?)')
            ->execute([$otherId, hash('sha256', $token)]);

        [$status] = $this->request('GET', '/tutor-sessions/mine', null, $token);
        $this->assertSame(404, $status);
        // the same uid is free for another user
        [$status] = $this->request('POST', '/tutor-sessions', ['uid' => 'mine'], $token);
        $this->assertSame(201, $status);
    }
}

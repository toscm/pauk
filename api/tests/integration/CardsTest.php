<?php

declare(strict_types=1);

namespace Pauk\Tests\integration;

final class CardsTest extends ApiTestCase
{
    public function testCreateAndGetTextCard(): void
    {
        $id = $this->makeTextCard('Translate: **to be**', ['essere']);
        [$status, $card] = $this->request('GET', "/cards/$id");
        $this->assertSame(200, $status);
        $this->assertSame('text', $card['type']);
        $this->assertSame('Translate: **to be**', $card['question_md']);
        $this->assertSame(['essere'], $card['accepted_answers']);
        $this->assertSame([], $card['dirs']);
        $this->assertMatchesRegularExpression(
            '/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/',
            $card['created_at']
        );
    }

    public function testCreateMcCardValidation(): void
    {
        [$status, $data] = $this->request('POST', '/cards', [
            'type' => 'mc',
            'question_md' => 'Pick one',
            'options' => [
                ['text_md' => 'a', 'correct' => false],
                ['text_md' => 'b', 'correct' => false],
            ],
        ]);
        $this->assertSame(400, $status);
        $this->assertSame('validation', $data['error']['code']);

        [$status] = $this->request('POST', '/cards', [
            'type' => 'bogus',
            'question_md' => 'x',
        ]);
        $this->assertSame(400, $status);

        [$status] = $this->request('POST', '/cards', [
            'type' => 'text',
            'question_md' => 'x',
            'accepted_answers' => [],
        ]);
        $this->assertSame(400, $status);
    }

    public function testQuizModeHidesSolutions(): void
    {
        $id = $this->makeTextCard('Q', ['a']);
        [, $card] = $this->request('GET', "/cards/$id?quiz=1");
        $this->assertArrayNotHasKey('accepted_answers', $card);

        [, $data] = $this->request('POST', '/cards', [
            'type' => 'mc',
            'question_md' => 'Pick',
            'options' => [
                ['text_md' => 'right', 'correct' => true],
                ['text_md' => 'wrong', 'correct' => false],
            ],
        ]);
        [, $card] = $this->request('GET', "/cards/{$data['id']}?quiz=1");
        foreach ($card['options'] as $option) {
            $this->assertArrayNotHasKey('correct', $option);
        }
    }

    public function testPatchReplacesAnswersAndDirs(): void
    {
        $dirA = $this->makeDir('a');
        $dirB = $this->makeDir('b');
        $id = $this->makeTextCard('Q', ['one'], [$dirA]);
        [$status, $card] = $this->request('PATCH', "/cards/$id", [
            'accepted_answers' => ['two', 'three'],
            'dirs' => [$dirB],
        ]);
        $this->assertSame(200, $status);
        $this->assertSame(['two', 'three'], $card['accepted_answers']);
        $this->assertSame([['id' => $dirB, 'name' => 'b']], $card['dirs']);
    }

    public function testTypeChangeRejected(): void
    {
        $id = $this->makeTextCard('Q', ['a']);
        [$status] = $this->request('PATCH', "/cards/$id", ['type' => 'mc']);
        $this->assertSame(400, $status);
    }

    public function testDeleteThen404(): void
    {
        $id = $this->makeTextCard('Q', ['a']);
        [$status] = $this->request('DELETE', "/cards/$id");
        $this->assertSame(204, $status);
        [$status] = $this->request('GET', "/cards/$id");
        $this->assertSame(404, $status);
    }

    public function testListPaginationAndFilters(): void
    {
        for ($i = 1; $i <= 5; $i++) {
            $this->makeTextCard("card $i", ['x']);
        }
        [, $page1] = $this->request('GET', '/cards?limit=2');
        $this->assertCount(2, $page1['items']);
        $this->assertNotNull($page1['next_cursor']);
        [, $page2] = $this->request('GET', '/cards?limit=2&cursor=' . urlencode($page1['next_cursor']));
        $this->assertCount(2, $page2['items']);
        [, $page3] = $this->request('GET', '/cards?limit=2&cursor=' . urlencode($page2['next_cursor']));
        $this->assertCount(1, $page3['items']);
        $this->assertNull($page3['next_cursor']);
        $ids = array_merge(
            array_column($page1['items'], 'id'),
            array_column($page2['items'], 'id'),
            array_column($page3['items'], 'id'),
        );
        $this->assertSame(array_values(array_unique($ids)), $ids);

        [, $data] = $this->request('GET', '/cards?q=card 3');
        $this->assertCount(1, $data['items']);
        [, $data] = $this->request('GET', '/cards?type=mc');
        $this->assertCount(0, $data['items']);
    }

    public function testUsersAreIsolated(): void
    {
        $id = $this->makeTextCard('mine', ['x']);
        self::$pdo->exec("INSERT INTO users (name) VALUES ('other')");
        $otherId = (int) self::$pdo->lastInsertId();
        $otherToken = bin2hex(random_bytes(16));
        $stmt = self::$pdo->prepare('INSERT INTO api_tokens (user_id, token_hash) VALUES (?, ?)');
        $stmt->execute([$otherId, hash('sha256', $otherToken)]);
        [$status] = $this->request('GET', "/cards/$id", null, $otherToken);
        $this->assertSame(404, $status);
        [, $data] = $this->request('GET', '/cards', null, $otherToken);
        $this->assertCount(0, $data['items']);
    }
}

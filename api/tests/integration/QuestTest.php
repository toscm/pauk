<?php

declare(strict_types=1);

namespace Pauk\Tests\integration;

final class QuestTest extends ApiTestCase
{
    private function makeQuest(int $maxMessages = 10): array
    {
        [$status, $card] = $this->request('POST', '/cards', [
            'type' => 'quest',
            'scenario_md' => 'Order 2 croissants and 1 coffee in Italian.',
            'role_prompt' => 'You are an Italian baker who speaks only Italian.',
            'success_criteria' => 'Customer ordered 2 croissants and 1 coffee.',
            'max_messages' => $maxMessages,
            'lang' => 'it',
        ]);
        $this->assertSame(201, $status);
        return $card;
    }

    public function testCreateAndGet(): void
    {
        $card = $this->makeQuest();
        $this->assertSame('quest', $card['type']);
        $this->assertSame('Order 2 croissants and 1 coffee in Italian.', $card['scenario_md']);
        $this->assertStringContainsString('baker', $card['role_prompt']);
        $this->assertSame(10, $card['max_messages']);
        $this->assertSame('it', $card['lang']);
        // the scenario doubles as question_md for search/listing
        $this->assertSame($card['scenario_md'], $card['question_md']);
    }

    public function testValidationRequiresFields(): void
    {
        [$status] = $this->request('POST', '/cards', [
            'type' => 'quest',
            'scenario_md' => 'x',
            // missing role_prompt / success_criteria
        ]);
        $this->assertSame(400, $status);
    }

    public function testQuestRunRecordsHighscore(): void
    {
        $card = $this->makeQuest();
        // first success in 8 messages
        [$status, $r1] = $this->request('POST', "/cards/{$card['id']}/quest-run", [
            'success' => true, 'messages_used' => 8,
        ]);
        $this->assertSame(200, $status);
        $this->assertTrue($r1['success']);
        $this->assertSame(8, $r1['best_messages']);
        $this->assertSame(1, $r1['rank']);

        // a failed attempt does not become the best
        [, $r2] = $this->request('POST', "/cards/{$card['id']}/quest-run", [
            'success' => false, 'messages_used' => 3,
        ]);
        $this->assertNull($r2['rank']);
        $this->assertSame(8, $r2['best_messages']);

        // a better success (6 messages) takes the top spot
        [, $r3] = $this->request('POST', "/cards/{$card['id']}/quest-run", [
            'success' => true, 'messages_used' => 6,
        ]);
        $this->assertSame(6, $r3['best_messages']);
        $this->assertSame(1, $r3['rank']);
        $this->assertSame([6, 8], array_column($r3['top'], 'messages_used'));
    }

    public function testQuestRunLogsToReviews(): void
    {
        $card = $this->makeQuest();
        $this->request('POST', "/cards/{$card['id']}/quest-run", [
            'success' => true, 'messages_used' => 5,
        ]);
        $stmt = self::$pdo->prepare('SELECT was_correct FROM reviews WHERE card_id = ?');
        $stmt->execute([$card['id']]);
        $this->assertSame([1], array_map('intval', $stmt->fetchAll(\PDO::FETCH_COLUMN)));
    }

    public function testQuestRunOnNonQuestIs404(): void
    {
        $textId = $this->makeTextCard('Q', ['a']);
        [$status] = $this->request('POST', "/cards/$textId/quest-run", [
            'success' => true, 'messages_used' => 1,
        ]);
        $this->assertSame(404, $status);
    }

    public function testUpdateMergesSpec(): void
    {
        $card = $this->makeQuest();
        [$status, $updated] = $this->request('PATCH', "/cards/{$card['id']}", [
            'max_messages' => 5,
        ]);
        $this->assertSame(200, $status);
        $this->assertSame(5, $updated['max_messages']);
        // other fields preserved
        $this->assertSame('it', $updated['lang']);
        $this->assertStringContainsString('baker', $updated['role_prompt']);
    }
}

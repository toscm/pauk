<?php

declare(strict_types=1);

namespace Pauk\Tests\integration;

final class MatchTest extends ApiTestCase
{
    private function makeMatchCard(): array
    {
        [$status, $card] = $this->request('POST', '/cards', [
            'type' => 'match',
            'question_md' => 'Match the pronoun to the form of parlare',
            'pairs' => [
                ['left_md' => 'io', 'right_md' => 'parlo'],
                ['left_md' => 'tu', 'right_md' => 'parli'],
                ['left_md' => 'lui/lei', 'right_md' => 'parla'],
            ],
        ]);
        $this->assertSame(201, $status);
        return $card;
    }

    public function testCreateAndGet(): void
    {
        $card = $this->makeMatchCard();
        $this->assertSame('match', $card['type']);
        $this->assertCount(3, $card['pairs']);
        $this->assertSame('io', $card['pairs'][0]['left_md']);
        $this->assertSame('parlo', $card['pairs'][0]['right_md']);
        $this->assertArrayHasKey('id', $card['pairs'][0]);
    }

    public function testQuizModeHidesPairingButKeepsIds(): void
    {
        $card = $this->makeMatchCard();
        [, $quiz] = $this->request('GET', "/cards/{$card['id']}?quiz=1");
        $this->assertArrayNotHasKey('pairs', $quiz);
        $this->assertCount(3, $quiz['lefts']);
        $this->assertCount(3, $quiz['choices']);
        // the ids on both sides are the same set (the correct match)
        $leftIds = array_column($quiz['lefts'], 'id');
        $choiceIds = array_column($quiz['choices'], 'id');
        sort($leftIds);
        sort($choiceIds);
        $this->assertSame($leftIds, $choiceIds);
        // lefts carry no right_md
        $this->assertArrayNotHasKey('right_md', $quiz['lefts'][0]);
    }

    public function testGradingAllCorrect(): void
    {
        $card = $this->makeMatchCard();
        $matches = [];
        foreach ($card['pairs'] as $pair) {
            $matches[(string) $pair['id']] = $pair['id'];   // correct = same id
        }
        [$status, $result] = $this->request('POST', "/cards/{$card['id']}/answer", [
            'matches' => $matches,
        ]);
        $this->assertSame(200, $status);
        $this->assertTrue($result['correct']);
        $this->assertSame('exact', $result['match']);
        $this->assertCount(3, $result['detail']);
        $this->assertTrue($result['detail'][0]['ok']);
    }

    public function testGradingOneWrong(): void
    {
        $card = $this->makeMatchCard();
        $ids = array_column($card['pairs'], 'id');
        $matches = [
            (string) $ids[0] => $ids[1],   // wrong
            (string) $ids[1] => $ids[1],   // right
            (string) $ids[2] => $ids[2],   // right
        ];
        [, $result] = $this->request('POST', "/cards/{$card['id']}/answer", [
            'matches' => $matches,
        ]);
        $this->assertFalse($result['correct']);
        $this->assertSame('wrong', $result['match']);
        $this->assertFalse($result['detail'][0]['ok']);
        $this->assertTrue($result['detail'][1]['ok']);
        // expected reveals the full pairing
        $this->assertSame('parlo', $result['expected']['pairs'][0]['right_md']);
    }

    public function testValidationRejectsTooFewPairs(): void
    {
        [$status] = $this->request('POST', '/cards', [
            'type' => 'match',
            'question_md' => 'q',
            'pairs' => [['left_md' => 'a', 'right_md' => 'b']],
        ]);
        $this->assertSame(400, $status);
    }

    public function testUpdateReplacesPairs(): void
    {
        $card = $this->makeMatchCard();
        [$status, $updated] = $this->request('PATCH', "/cards/{$card['id']}", [
            'pairs' => [
                ['left_md' => 'noi', 'right_md' => 'parliamo'],
                ['left_md' => 'voi', 'right_md' => 'parlate'],
            ],
        ]);
        $this->assertSame(200, $status);
        $this->assertCount(2, $updated['pairs']);
        $this->assertSame('noi', $updated['pairs'][0]['left_md']);
    }
}

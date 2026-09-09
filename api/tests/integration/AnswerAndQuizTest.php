<?php

declare(strict_types=1);

namespace Pauk\Tests\integration;

final class AnswerAndQuizTest extends ApiTestCase
{
    private function makeMcCard(): array
    {
        [, $card] = $this->request('POST', '/cards', [
            'type' => 'mc',
            'question_md' => 'Pick right ones',
            'options' => [
                ['text_md' => 'r1', 'correct' => true],
                ['text_md' => 'w1', 'correct' => false],
                ['text_md' => 'r2', 'correct' => true],
            ],
        ]);
        $correctIds = array_column(
            array_filter($card['options'], fn ($o) => $o['correct']),
            'id'
        );
        return [$card['id'], array_values($correctIds)];
    }

    public function testMcAnswerSetEquality(): void
    {
        [$id, $correctIds] = $this->makeMcCard();
        // order must not matter
        [$status, $result] = $this->request('POST', "/cards/$id/answer", [
            'selected' => array_reverse($correctIds),
        ]);
        $this->assertSame(200, $status);
        $this->assertTrue($result['correct']);
        $this->assertSame('exact', $result['match']);

        // subset is wrong
        [, $result] = $this->request('POST', "/cards/$id/answer", [
            'selected' => [$correctIds[0]],
        ]);
        $this->assertFalse($result['correct']);
        $this->assertSame('wrong', $result['match']);
        $this->assertSame($correctIds, $result['expected']['correct_option_ids']);
    }

    public function testTextAnswerGrades(): void
    {
        $id = $this->makeTextCard('to be', ['essere']);
        [, $r] = $this->request('POST', "/cards/$id/answer", ['answer' => ' Essere ']);
        $this->assertSame('exact', $r['match']);
        [, $r] = $this->request('POST', "/cards/$id/answer", ['answer' => 'esere']);
        $this->assertSame('typo', $r['match']);
        $this->assertTrue($r['correct']);
        [, $r] = $this->request('POST', "/cards/$id/answer", ['answer' => 'avere']);
        $this->assertSame('wrong', $r['match']);
        $this->assertSame(['essere'], $r['expected']['accepted_answers']);
    }

    public function testAnswersAreLoggedAsReviews(): void
    {
        $id = $this->makeTextCard('Q', ['a']);
        $this->request('POST', "/cards/$id/answer", ['answer' => 'a']);
        $this->request('POST', "/cards/$id/answer", ['answer' => 'b']);
        $stmt = self::$pdo->prepare(
            'SELECT was_correct FROM reviews WHERE card_id = ? ORDER BY id'
        );
        $stmt->execute([$id]);
        $this->assertSame([1, 0], array_map('intval', $stmt->fetchAll(\PDO::FETCH_COLUMN)));
    }

    public function testQuizSelectionEndpoint(): void
    {
        $dir = $this->makeDir('d');
        $ids = [];
        for ($i = 0; $i < 5; $i++) {
            $ids[] = $this->makeTextCard("q$i", ['a'], [$dir]);
        }
        [$status, $data] = $this->request('GET', "/quiz/cards?dir=$dir&n=3&seed=7");
        $this->assertSame(200, $status);
        $this->assertCount(3, $data['items']);
        foreach ($data['items'] as $item) {
            $this->assertArrayNotHasKey('accepted_answers', $item);
            $this->assertContains($item['id'], $ids);
        }
        // deterministic with the same seed
        [, $again] = $this->request('GET', "/quiz/cards?dir=$dir&n=3&seed=7");
        $this->assertSame(
            array_column($data['items'], 'id'),
            array_column($again['items'], 'id')
        );
        // n larger than candidates returns all, once each
        [, $all] = $this->request('GET', "/quiz/cards?dir=$dir&n=50");
        $allIds = array_column($all['items'], 'id');
        sort($allIds);
        sort($ids);
        $this->assertSame($ids, $allIds);
    }

    public function testQuizPrefersUnseenAndWrongCards(): void
    {
        $dir = $this->makeDir('d');
        $mastered = $this->makeTextCard('mastered', ['a'], [$dir]);
        $unseen = $this->makeTextCard('unseen', ['a'], [$dir]);
        for ($i = 0; $i < 20; $i++) {
            $this->request('POST', "/cards/$mastered/answer", ['answer' => 'a']);
        }
        $firstUnseen = 0;
        for ($seed = 0; $seed < 50; $seed++) {
            [, $data] = $this->request('GET', "/quiz/cards?dir=$dir&n=1&seed=$seed");
            if ($data['items'][0]['id'] === $unseen) {
                $firstUnseen++;
            }
        }
        // weight ratio is ~1.0 vs ~0.05, so unseen should dominate
        $this->assertGreaterThan(35, $firstUnseen);
    }
}

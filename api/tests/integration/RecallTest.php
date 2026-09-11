<?php

declare(strict_types=1);

namespace Pauk\Tests\integration;

final class RecallTest extends ApiTestCase
{
    private function makeRecall(string $question = 'Explain why the EM algorithm converges.', string $answer = 'Each E/M step cannot decrease the likelihood.'): array
    {
        [$status, $card] = $this->request('POST', '/cards', [
            'type' => 'recall',
            'question_md' => $question,
            'answer_md' => $answer,
        ]);
        $this->assertSame(201, $status);
        return $card;
    }

    public function testCreateAndGetIncludesAnswer(): void
    {
        $card = $this->makeRecall();
        $this->assertSame('recall', $card['type']);
        $this->assertSame('Each E/M step cannot decrease the likelihood.', $card['answer_md']);

        [$status, $fetched] = $this->request('GET', "/cards/{$card['id']}");
        $this->assertSame(200, $status);
        $this->assertSame($card['answer_md'], $fetched['answer_md']);
    }

    public function testAnswerMdRequired(): void
    {
        [$status, $body] = $this->request('POST', '/cards', [
            'type' => 'recall',
            'question_md' => 'Q with no answer',
        ]);
        $this->assertSame(400, $status);
        $this->assertSame('validation', $body['error']['code']);
    }

    public function testQuizModeKeepsAnswer(): void
    {
        $card = $this->makeRecall();
        // unlike mc/text, recall keeps answer_md in quiz form: there is
        // no server-side grading to protect (docs/api.md)
        [$status, $quizCard] = $this->request('GET', "/cards/{$card['id']}?quiz=1");
        $this->assertSame(200, $status);
        $this->assertSame($card['answer_md'], $quizCard['answer_md']);

        // and through the quiz selection endpoint too
        $dirId = $this->makeDir('recalldeck');
        $this->request('PUT', "/dirs/$dirId/cards/{$card['id']}");
        [$status, $picked] = $this->request('GET', "/quiz/cards?dir=$dirId&n=5");
        $this->assertSame(200, $status);
        $this->assertSame('recall', $picked['items'][0]['type']);
        $this->assertSame($card['answer_md'], $picked['items'][0]['answer_md']);
    }

    public function testPatchUpdatesAnswer(): void
    {
        $card = $this->makeRecall();
        [$status, $updated] = $this->request('PATCH', "/cards/{$card['id']}", [
            'answer_md' => 'A revised reference answer.',
        ]);
        $this->assertSame(200, $status);
        $this->assertSame('A revised reference answer.', $updated['answer_md']);
    }

    public function testSelfGradeLogsReviewAndUpdatesPerformance(): void
    {
        $dirId = $this->makeDir('perfdeck');
        $card = $this->makeRecall();
        $this->request('PUT', "/dirs/$dirId/cards/{$card['id']}");

        [$status, $r1] = $this->request('POST', "/cards/{$card['id']}/self-grade", [
            'correct' => true,
        ]);
        $this->assertSame(200, $status);
        $this->assertTrue($r1['correct']);

        [, $r2] = $this->request('POST', "/cards/{$card['id']}/self-grade", [
            'correct' => false,
        ]);
        $this->assertFalse($r2['correct']);

        // both verdicts are logged to reviews
        $stmt = self::$pdo->prepare('SELECT was_correct FROM reviews WHERE card_id = ? ORDER BY id');
        $stmt->execute([$card['id']]);
        $this->assertSame([1, 0], array_map('intval', $stmt->fetchAll(\PDO::FETCH_COLUMN)));

        // performance metric reflects the reviews: (correct - wrong)/total
        // = (1 - 1)/2 = 0.0
        $dirs = $this->request('GET', '/quiz/dirs')[1]['items'];
        $deck = null;
        foreach ($dirs as $d) {
            if ($d['id'] === $dirId) {
                $deck = $d;
                break;
            }
        }
        $this->assertNotNull($deck);
        $this->assertEqualsWithDelta(0.0, $deck['performance'], 1e-9);
    }

    public function testSelfGradeRequiresBoolean(): void
    {
        $card = $this->makeRecall();
        [$status, $body] = $this->request('POST', "/cards/{$card['id']}/self-grade", [
            'correct' => 'yes',
        ]);
        $this->assertSame(400, $status);
        $this->assertSame('validation', $body['error']['code']);
    }

    public function testSelfGradeOnNonRecallIs404(): void
    {
        $textId = $this->makeTextCard('Q', ['a']);
        [$status] = $this->request('POST', "/cards/$textId/self-grade", [
            'correct' => true,
        ]);
        $this->assertSame(404, $status);
    }

    public function testAnswerOnRecallIs400(): void
    {
        $card = $this->makeRecall();
        [$status, $body] = $this->request('POST', "/cards/{$card['id']}/answer", [
            'answer' => 'anything',
        ]);
        $this->assertSame(400, $status);
        $this->assertSame('validation', $body['error']['code']);
    }
}

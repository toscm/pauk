<?php

declare(strict_types=1);

namespace Pauk\Tests\integration;

final class QuizRunsAndStatsTest extends ApiTestCase
{
    public function testRunLifecycleAndRanking(): void
    {
        $dir = $this->makeDir('d');
        // three finished runs with different scores
        foreach ([[5, 10], [9, 10], [7, 10], [3, 10]] as [$correct, $total]) {
            [$status, $run] = $this->request('POST', '/quiz/runs', [
                'dir_id' => $dir, 'total' => $total,
            ]);
            $this->assertSame(201, $status);
            [$status, $result] = $this->request('PATCH', "/quiz/runs/{$run['id']}", [
                'correct' => $correct, 'total' => $total,
            ]);
            $this->assertSame(200, $status);
        }
        // last run (3/10) must not be in the top 3
        $this->assertNull($result['rank']);
        $this->assertSame(
            [9, 7, 5],
            array_column($result['top'], 'correct')
        );

        // a new best run ranks first
        [, $run] = $this->request('POST', '/quiz/runs', ['dir_id' => $dir, 'total' => 10]);
        [, $result] = $this->request('PATCH', "/quiz/runs/{$run['id']}", [
            'correct' => 10, 'total' => 10,
        ]);
        $this->assertSame(1, $result['rank']);
    }

    public function testRunValidation(): void
    {
        [$status] = $this->request('POST', '/quiz/runs', ['dir_id' => 999, 'total' => 5]);
        $this->assertSame(404, $status);
        [, $run] = $this->request('POST', '/quiz/runs', ['dir_id' => null, 'total' => 5]);
        [$status] = $this->request('PATCH', "/quiz/runs/{$run['id']}", [
            'correct' => 6, 'total' => 5,
        ]);
        $this->assertSame(400, $status);
        [$status] = $this->request('PATCH', "/quiz/runs/{$run['id']}", [
            'correct' => 4, 'total' => 5,
        ]);
        $this->assertSame(200, $status);
        // finishing twice conflicts
        [$status] = $this->request('PATCH', "/quiz/runs/{$run['id']}", [
            'correct' => 4, 'total' => 5,
        ]);
        $this->assertSame(409, $status);
    }

    public function testZeroTotalRunsAreNotRanked(): void
    {
        $dir = $this->makeDir('d');
        [, $run] = $this->request('POST', '/quiz/runs', ['dir_id' => $dir, 'total' => 5]);
        [, $result] = $this->request('PATCH', "/quiz/runs/{$run['id']}", [
            'correct' => 0, 'total' => 0,
        ]);
        $this->assertNull($result['rank']);
        $this->assertSame([], $result['top']);
    }

    public function testPickerDirsSortedByPopularity(): void
    {
        $italian = $this->makeDir('italian');
        $verbs = $this->makeDir('verbs', $italian);
        $this->makeDir('unused');
        $this->makeTextCard('Q', ['x'], [$verbs]);
        foreach (range(1, 3) as $ignored) {
            [, $run] = $this->request('POST', '/quiz/runs', ['dir_id' => $verbs, 'total' => 1]);
            $this->request('PATCH', "/quiz/runs/{$run['id']}", ['correct' => 1, 'total' => 1]);
        }
        [$status, $data] = $this->request('GET', '/quiz/dirs');
        $this->assertSame(200, $status);
        $first = $data['items'][0];
        $this->assertSame('italian/verbs', $first['path']);
        $this->assertSame(3, $first['runs']);
        $this->assertSame(1, $first['cards_total']);
        $this->assertSame(['correct' => 1, 'total' => 1], $first['best']);
        // unstarted dirs follow, alphabetically by path
        $this->assertSame(['italian', 'unused'], array_column(array_slice($data['items'], 1), 'path'));
        $this->assertNull($data['items'][1]['best']);
    }

    public function testPickerPathIsCanonicalUnderMultipleParents(): void
    {
        $aaa = $this->makeDir('aaa');
        $zzz = $this->makeDir('zzz');
        $shared = $this->makeDir('shared', $zzz);
        [$status] = $this->request('PUT', "/dirs/$aaa/dirs/$shared");
        $this->assertSame(204, $status);
        [, $data] = $this->request('GET', '/quiz/dirs');
        $paths = array_column($data['items'], 'path', 'id');
        $this->assertSame('aaa/shared', $paths[$shared]);
    }

    public function testStats(): void
    {
        $dir = $this->makeDir('d');
        $hard = $this->makeTextCard('hard one', ['x'], [$dir]);
        $easy = $this->makeTextCard('easy one', ['x'], [$dir]);
        $this->makeTextCard('never asked', ['x'], [$dir]);
        // hard: 1/3 correct; easy: 2/2 correct
        foreach (['x', 'nope', 'nah'] as $answer) {
            $this->request('POST', "/cards/$hard/answer", ['answer' => $answer]);
        }
        foreach (['x', 'x'] as $answer) {
            $this->request('POST', "/cards/$easy/answer", ['answer' => $answer]);
        }
        [$status, $data] = $this->request('GET', "/stats?dir=$dir");
        $this->assertSame(200, $status);
        $this->assertSame(3, $data['summary']['cards']);
        $this->assertSame(2, $data['summary']['asked_cards']);
        $this->assertSame(5, $data['summary']['reviews']);
        $this->assertSame(3, $data['summary']['correct']);
        $this->assertSame(0.6, $data['summary']['accuracy']);
        // worst first
        $this->assertSame([$hard, $easy], array_column($data['items'], 'id'));
        $this->assertSame(0.333, $data['items'][0]['accuracy']);
    }

    public function testStatsEmpty(): void
    {
        [$status, $data] = $this->request('GET', '/stats');
        $this->assertSame(200, $status);
        $this->assertSame(0, $data['summary']['cards']);
        $this->assertNull($data['summary']['accuracy']);
        $this->assertSame([], $data['items']);
    }
}

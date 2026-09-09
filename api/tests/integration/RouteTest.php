<?php

declare(strict_types=1);

namespace Pauk\Tests\integration;

final class RouteTest extends ApiTestCase
{
    private function makeRoute(): array
    {
        [$status, $card] = $this->request('POST', '/cards', [
            'type' => 'route',
            'question_md' => 'Drive from München to Berlin using as few km as possible.',
            'graph_name' => 'germany-autobahn',
            'start_node' => 'muenchen',
            'goal_node' => 'berlin',
        ]);
        $this->assertSame(201, $status);
        return $card;
    }

    public function testCreateAndGet(): void
    {
        $card = $this->makeRoute();
        $this->assertSame('route', $card['type']);
        $this->assertSame('germany-autobahn', $card['graph_name']);
        $this->assertSame('muenchen', $card['start_node']);
        $this->assertSame('berlin', $card['goal_node']);
    }

    public function testFilterByRouteType(): void
    {
        $this->makeRoute();
        $this->makeTextCard('a text card', ['x']);
        [$status, $data] = $this->request('GET', '/cards?type=route');
        $this->assertSame(200, $status);
        $this->assertCount(1, $data['items']);
        $this->assertSame('route', $data['items'][0]['type']);
    }

    public function testValidationRejectsBadNode(): void
    {
        [$status] = $this->request('POST', '/cards', [
            'type' => 'route',
            'question_md' => 'x',
            'graph_name' => 'g',
            'start_node' => 'Bad Node!',
            'goal_node' => 'berlin',
        ]);
        $this->assertSame(400, $status);
    }

    public function testRouteRunHighscoreByFewestKm(): void
    {
        $card = $this->makeRoute();
        [$status, $r1] = $this->request('POST', "/cards/{$card['id']}/route-run", [
            'success' => true, 'km' => 700,
        ]);
        $this->assertSame(200, $status);
        $this->assertSame(700, $r1['best_km']);
        $this->assertSame(1, $r1['rank']);

        // a longer route does not beat the best (still 700), but with
        // room in the top three it ranks second
        [, $r2] = $this->request('POST', "/cards/{$card['id']}/route-run", [
            'success' => true, 'km' => 900,
        ]);
        $this->assertSame(700, $r2['best_km']);
        $this->assertSame(2, $r2['rank']);

        // a shorter successful route takes the top
        [, $r3] = $this->request('POST', "/cards/{$card['id']}/route-run", [
            'success' => true, 'km' => 595,
        ]);
        $this->assertSame(595, $r3['best_km']);
        $this->assertSame(1, $r3['rank']);
        $this->assertSame([595, 700, 900], array_column($r3['top'], 'km'));
    }

    public function testFailedRouteNotRanked(): void
    {
        $card = $this->makeRoute();
        [, $r] = $this->request('POST', "/cards/{$card['id']}/route-run", [
            'success' => false, 'km' => 100,
        ]);
        $this->assertNull($r['rank']);
        $this->assertNull($r['best_km']);
    }
}

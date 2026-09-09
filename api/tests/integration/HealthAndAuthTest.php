<?php

declare(strict_types=1);

namespace Pauk\Tests\integration;

final class HealthAndAuthTest extends ApiTestCase
{
    public function testHealthNeedsNoAuth(): void
    {
        [$status, $data] = $this->request('GET', '/health', null, null);
        $this->assertSame(200, $status);
        $this->assertSame('ok', $data['status']);
        $this->assertSame('ok', $data['db']);
        $this->assertArrayHasKey('version', $data);
    }

    public function testMissingTokenIs401(): void
    {
        [$status, $data] = $this->request('GET', '/cards', null, null);
        $this->assertSame(401, $status);
        $this->assertSame('unauthorized', $data['error']['code']);
    }

    public function testInvalidTokenIs401(): void
    {
        [$status] = $this->request('GET', '/cards', null, 'not-a-real-token');
        $this->assertSame(401, $status);
    }

    public function testUnknownRouteIs404Json(): void
    {
        [$status, $data] = $this->request('GET', '/nonsense');
        $this->assertSame(404, $status);
        $this->assertSame('not_found', $data['error']['code']);
    }
}

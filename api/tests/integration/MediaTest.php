<?php

declare(strict_types=1);

namespace Pauk\Tests\integration;

use Slim\Psr7\Factory\StreamFactory;
use Slim\Psr7\UploadedFile;

final class MediaTest extends ApiTestCase
{
    // 1x1 transparent PNG
    private const PNG = "\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        . "\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0aIDATx\x9cc\x00\x01"
        . "\x00\x00\x05\x00\x01\x0d\x0a\x2d\xb4\x00\x00\x00\x00IEND\xaeB`\x82";

    private function uploadPng(string $name = 'pixel.png'): array
    {
        $stream = (new StreamFactory())->createStream(self::PNG);
        $file = new UploadedFile($stream, $name, 'image/png', strlen(self::PNG));
        return $this->request('POST', '/media', null, '', ['file' => $file]);
    }

    public function testUploadDedupAndList(): void
    {
        [$status, $object] = $this->uploadPng();
        $this->assertSame(201, $status);
        $this->assertSame(hash('sha256', self::PNG), $object['sha256']);
        $this->assertSame('image/png', $object['mime']);
        $this->assertStringEndsWith('/media/' . $object['sha256'] . '.png', $object['url']);
        $this->assertFileExists(
            getenv('PAUK_MEDIA_DIR') . '/' . $object['sha256'] . '.png'
        );

        // identical content: 200 + same object, no duplicate row
        [$status, $again] = $this->uploadPng('other-name.png');
        $this->assertSame(200, $status);
        $this->assertSame($object['id'], $again['id']);

        [, $list] = $this->request('GET', '/media');
        $this->assertCount(1, $list['items']);
    }

    public function testRejectUnsupportedType(): void
    {
        $data = "#!/bin/sh\necho hi\n";
        $stream = (new StreamFactory())->createStream($data);
        $file = new UploadedFile($stream, 'script.sh', 'text/x-sh', strlen($data));
        [$status, $body] = $this->request('POST', '/media', null, '', ['file' => $file]);
        $this->assertSame(400, $status);
        $this->assertSame('validation', $body['error']['code']);
    }

    public function testDeleteProtectionAndDelete(): void
    {
        [, $object] = $this->uploadPng();
        $this->makeTextCard("look: ![p]({$object['url']})", ['x']);
        [$status, $body] = $this->request('DELETE', "/media/{$object['id']}");
        $this->assertSame(409, $status);
        $this->assertSame('conflict', $body['error']['code']);

        // remove the referencing card, then deletion succeeds
        [, $cards] = $this->request('GET', '/cards');
        $this->request('DELETE', '/cards/' . $cards['items'][0]['id']);
        [$status] = $this->request('DELETE', "/media/{$object['id']}");
        $this->assertSame(204, $status);
        $this->assertFileDoesNotExist(
            getenv('PAUK_MEDIA_DIR') . '/' . $object['sha256'] . '.png'
        );
        [$status] = $this->request('DELETE', "/media/{$object['id']}");
        $this->assertSame(404, $status);
    }
}

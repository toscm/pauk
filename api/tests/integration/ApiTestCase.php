<?php

declare(strict_types=1);

namespace Pauk\Tests\integration;

use Pauk\App;
use Pauk\Db;
use PHPUnit\Framework\TestCase;
use Slim\Psr7\Factory\ServerRequestFactory;
use Slim\Psr7\Factory\StreamFactory;

/**
 * Base class for integration tests: fresh database once per
 * phpunit run (created on the scratch MariaDB the environment
 * points at), truncated tables + seeded user/token per test.
 * Requests run through the real Slim app in-process.
 */
abstract class ApiTestCase extends TestCase
{
    protected static \PDO $pdo;
    protected static \Slim\App $app;
    protected static string $token;
    protected static int $userId;
    private static bool $ready = false;

    public static function setUpBeforeClass(): void
    {
        if (self::$ready) {
            return;
        }
        $host = getenv('PAUK_DB_HOST') ?: '127.0.0.1';
        $port = getenv('PAUK_DB_PORT') ?: '33068';
        $user = getenv('PAUK_DB_USER') ?: 'root';
        $pass = getenv('PAUK_DB_PASS') ?: '';
        $name = getenv('PAUK_DB_NAME') ?: 'pauk_test';
        $admin = new \PDO("mysql:host=$host;port=$port;charset=utf8mb4", $user, $pass, [
            \PDO::ATTR_ERRMODE => \PDO::ERRMODE_EXCEPTION,
        ]);
        $admin->exec("DROP DATABASE IF EXISTS `$name`");
        $admin->exec("CREATE DATABASE `$name` CHARACTER SET utf8mb4");
        putenv("PAUK_DB_HOST=$host");
        putenv("PAUK_DB_PORT=$port");
        putenv("PAUK_DB_USER=$user");
        putenv("PAUK_DB_PASS=$pass");
        putenv("PAUK_DB_NAME=$name");
        $mediaDir = sys_get_temp_dir() . '/pauk-test-media-' . getmypid();
        @mkdir($mediaDir, 0755, true);
        putenv("PAUK_MEDIA_DIR=$mediaDir");
        putenv('PAUK_BASE_URL=http://localhost');
        self::$pdo = Db::connect();
        Db::migrate(self::$pdo, dirname(__DIR__, 2) . '/migrations');
        self::$app = App::build(fn () => self::$pdo);
        self::$ready = true;
    }

    protected function setUp(): void
    {
        self::$pdo->exec('SET FOREIGN_KEY_CHECKS = 0');
        foreach (['route_runs', 'quest_runs', 'quiz_runs', 'reviews', 'dir_cards', 'dir_dirs', 'dirs',
                  'text_answers', 'mc_options', 'match_pairs', 'quest_specs', 'route_specs', 'cards', 'media',
                  'api_tokens', 'users'] as $table) {
            self::$pdo->exec("TRUNCATE TABLE $table");
        }
        self::$pdo->exec('SET FOREIGN_KEY_CHECKS = 1');
        self::$pdo->exec("INSERT INTO users (name) VALUES ('tester')");
        self::$userId = (int) self::$pdo->lastInsertId();
        self::$token = bin2hex(random_bytes(16));
        $stmt = self::$pdo->prepare(
            'INSERT INTO api_tokens (user_id, token_hash) VALUES (?, ?)'
        );
        $stmt->execute([self::$userId, hash('sha256', self::$token)]);
    }

    /**
     * @param array<string, mixed>|null $body
     * @param array<string, \Psr\Http\Message\UploadedFileInterface>|null $files
     * @return array{0: int, 1: mixed} [status, decoded json|null]
     */
    protected function request(string $method, string $path, ?array $body = null, ?string $token = '', ?array $files = null): array
    {
        $request = (new ServerRequestFactory())
            ->createServerRequest($method, 'http://localhost/api/v1' . $path);
        if ($token !== null) {
            $request = $request->withHeader(
                'Authorization',
                'Bearer ' . ($token === '' ? self::$token : $token)
            );
        }
        if ($files !== null) {
            $request = $request->withUploadedFiles($files);
        }
        if ($body !== null) {
            $stream = (new StreamFactory())->createStream(
                json_encode($body, JSON_THROW_ON_ERROR)
            );
            $request = $request
                ->withBody($stream)
                ->withHeader('Content-Type', 'application/json');
        }
        $response = self::$app->handle($request);
        $raw = (string) $response->getBody();
        return [$response->getStatusCode(), $raw === '' ? null : json_decode($raw, true)];
    }

    /** Create a text card, return its id. */
    protected function makeTextCard(string $question, array $accepted, array $dirIds = []): int
    {
        [$status, $data] = $this->request('POST', '/cards', [
            'type' => 'text',
            'question_md' => $question,
            'accepted_answers' => $accepted,
            'dirs' => $dirIds,
        ]);
        $this->assertSame(201, $status);
        return $data['id'];
    }

    /** Create a dir, return its id. */
    protected function makeDir(string $name, ?int $parentId = null): int
    {
        [$status, $data] = $this->request('POST', '/dirs', [
            'name' => $name,
            'parent_id' => $parentId,
        ]);
        $this->assertSame(201, $status);
        return $data['id'];
    }
}

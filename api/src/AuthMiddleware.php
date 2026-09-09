<?php

declare(strict_types=1);

namespace Pauk;

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Psr\Http\Server\MiddlewareInterface;
use Psr\Http\Server\RequestHandlerInterface;
use Slim\Psr7\Response as SlimResponse;

final class AuthMiddleware implements MiddlewareInterface
{
    /** @param callable(): \PDO $getPdo */
    public function __construct(private $getPdo)
    {
    }

    public function process(Request $request, RequestHandlerInterface $handler): Response
    {
        $header = $request->getHeaderLine('Authorization');
        if (!str_starts_with($header, 'Bearer ')) {
            return Http::error(new SlimResponse(), 401, 'unauthorized', 'Missing bearer token');
        }
        $token = substr($header, 7);
        $pdo = ($this->getPdo)();
        $stmt = $pdo->prepare('SELECT id, user_id FROM api_tokens WHERE token_hash = ?');
        $stmt->execute([hash('sha256', $token)]);
        $row = $stmt->fetch();
        if ($row === false) {
            return Http::error(new SlimResponse(), 401, 'unauthorized', 'Invalid token');
        }
        $stmt = $pdo->prepare('UPDATE api_tokens SET last_used_at = NOW() WHERE id = ?');
        $stmt->execute([$row['id']]);
        return $handler->handle($request->withAttribute('user_id', (int) $row['user_id']));
    }
}

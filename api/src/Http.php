<?php

declare(strict_types=1);

namespace Pauk;

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;

/** Small JSON request/response helpers shared by all handlers. */
final class Http
{
    public static function json(Response $response, mixed $data, int $status = 200): Response
    {
        $response->getBody()->write(
            json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR)
        );
        return $response
            ->withHeader('Content-Type', 'application/json; charset=utf-8')
            ->withStatus($status);
    }

    public static function error(Response $response, int $status, string $code, string $message): Response
    {
        return self::json($response, ['error' => ['code' => $code, 'message' => $message]], $status);
    }

    /** @return array<string, mixed> */
    public static function body(Request $request): array
    {
        $raw = (string) $request->getBody();
        if ($raw === '') {
            return [];
        }
        $data = json_decode($raw, true);
        if (!is_array($data)) {
            throw new ApiError(400, 'validation', 'Request body must be a JSON object');
        }
        return $data;
    }

    public static function intQuery(Request $request, string $name, int $default, int $min, int $max): int
    {
        $params = $request->getQueryParams();
        if (!isset($params[$name])) {
            return $default;
        }
        $value = filter_var($params[$name], FILTER_VALIDATE_INT);
        if ($value === false) {
            throw new ApiError(400, 'validation', "Query parameter '$name' must be an integer");
        }
        return max($min, min($max, $value));
    }
}

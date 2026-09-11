<?php

declare(strict_types=1);

namespace Pauk;

use Pauk\Repo\Cards;
use Pauk\Repo\Dirs;
use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\Factory\AppFactory;
use Slim\Routing\RouteCollectorProxy;

final class App
{
    /**
     * Build the Slim application. $pdoFactory is lazy so that
     * /health can report a broken DB instead of throwing a 500
     * before routing.
     *
     * @param callable(): \PDO $pdoFactory
     */
    public static function build(callable $pdoFactory): \Slim\App
    {
        $app = AppFactory::create();
        $app->setBasePath('/api/v1');
        $app->addRoutingMiddleware();

        $pdo = null;
        $getPdo = function () use (&$pdo, $pdoFactory): \PDO {
            return $pdo ??= $pdoFactory();
        };

        $app->get('/health', function (Request $request, Response $response) use ($getPdo) {
            $db = 'ok';
            try {
                $getPdo()->query('SELECT 1');
            } catch (\Throwable) {
                $db = 'error';
            }
            return Http::json(
                $response,
                ['status' => $db === 'ok' ? 'ok' : 'error', 'db' => $db, 'version' => Version::VERSION],
                $db === 'ok' ? 200 : 503
            );
        });

        $app->group('', function (RouteCollectorProxy $group) use ($getPdo) {
            $repos = function (Request $request) use ($getPdo): array {
                $pdo = $getPdo();
                $userId = (int) $request->getAttribute('user_id');
                $dirs = new Dirs($pdo);
                return [$pdo, $userId, $dirs, new Cards($pdo, $dirs)];
            };

            // --- cards ---------------------------------------------------
            $group->get('/cards', function (Request $request, Response $response) use ($repos) {
                [, $userId, , $cards] = $repos($request);
                $params = $request->getQueryParams();
                $result = $cards->list(
                    $userId,
                    self::cardFilters($request),
                    ($params['quiz'] ?? '') === '1',
                    Http::intQuery($request, 'limit', 50, 1, 200),
                    $params['cursor'] ?? null
                );
                return Http::json($response, $result);
            });

            $group->post('/cards', function (Request $request, Response $response) use ($repos) {
                [, $userId, , $cards] = $repos($request);
                return Http::json($response, $cards->create($userId, Http::body($request)), 201);
            });

            $group->get('/cards/{id:[0-9]+}', function (Request $request, Response $response, array $args) use ($repos) {
                [, $userId, , $cards] = $repos($request);
                $quiz = ($request->getQueryParams()['quiz'] ?? '') === '1';
                return Http::json($response, $cards->get($userId, (int) $args['id'], $quiz));
            });

            $group->patch('/cards/{id:[0-9]+}', function (Request $request, Response $response, array $args) use ($repos) {
                [, $userId, , $cards] = $repos($request);
                return Http::json($response, $cards->update($userId, (int) $args['id'], Http::body($request)));
            });

            $group->delete('/cards/{id:[0-9]+}', function (Request $request, Response $response, array $args) use ($repos) {
                [, $userId, , $cards] = $repos($request);
                $cards->delete($userId, (int) $args['id']);
                return $response->withStatus(204);
            });

            $group->post('/cards/{id:[0-9]+}/answer', function (Request $request, Response $response, array $args) use ($repos) {
                [, $userId, , $cards] = $repos($request);
                return Http::json($response, $cards->answer($userId, (int) $args['id'], Http::body($request)));
            });

            $group->post('/cards/{id:[0-9]+}/self-grade', function (Request $request, Response $response, array $args) use ($repos) {
                [, $userId, , $cards] = $repos($request);
                return Http::json($response, $cards->selfGrade($userId, (int) $args['id'], Http::body($request)));
            });

            $group->post('/cards/{id:[0-9]+}/quest-run', function (Request $request, Response $response, array $args) use ($repos) {
                [$pdo, $userId] = $repos($request);
                $body = Http::body($request);
                $success = $body['success'] ?? null;
                $messagesUsed = $body['messages_used'] ?? null;
                if (!is_bool($success) || !is_int($messagesUsed)) {
                    throw new ApiError(400, 'validation', 'success bool, messages_used int required');
                }
                $quests = new \Pauk\Repo\QuestRuns($pdo);
                return Http::json($response, $quests->record($userId, (int) $args['id'], $success, $messagesUsed));
            });

            $group->post('/cards/{id:[0-9]+}/route-run', function (Request $request, Response $response, array $args) use ($repos) {
                [$pdo, $userId] = $repos($request);
                $body = Http::body($request);
                $success = $body['success'] ?? null;
                $km = $body['km'] ?? null;
                if (!is_bool($success) || !is_int($km)) {
                    throw new ApiError(400, 'validation', 'success bool, km int required');
                }
                $routes = new \Pauk\Repo\RouteRuns($pdo);
                return Http::json($response, $routes->record($userId, (int) $args['id'], $success, $km));
            });

            // --- quiz selection ------------------------------------------
            $group->get('/quiz/cards', function (Request $request, Response $response) use ($repos) {
                [$pdo, $userId, , $cards] = $repos($request);
                $params = $request->getQueryParams();
                $candidates = $cards->candidateIds($userId, self::cardFilters($request));
                $seed = isset($params['seed'])
                    ? (int) filter_var($params['seed'], FILTER_VALIDATE_INT)
                    : null;
                $quiz = new Quiz($pdo);
                $ids = $quiz->select($userId, $candidates, Http::intQuery($request, 'n', 20, 1, 200), $seed);
                $items = array_map(fn ($id) => $cards->get($userId, $id, true), $ids);
                return Http::json($response, ['items' => $items]);
            });

            // --- quiz picker, runs, stats --------------------------------
            $group->get('/quiz/dirs', function (Request $request, Response $response) use ($repos) {
                [$pdo, $userId] = $repos($request);
                $runs = new \Pauk\Repo\QuizRuns($pdo);
                return Http::json($response, ['items' => $runs->pickerDirs($userId)]);
            });

            $group->post('/quiz/runs', function (Request $request, Response $response) use ($repos) {
                [$pdo, $userId] = $repos($request);
                $body = Http::body($request);
                $dirId = $body['dir_id'] ?? null;
                $total = $body['total'] ?? null;
                $ranked = $body['ranked'] ?? true;
                if (($dirId !== null && !is_int($dirId)) || !is_int($total) || $total < 0
                    || !is_bool($ranked)) {
                    throw new ApiError(400, 'validation', 'dir_id int|null, total non-negative int, ranked bool');
                }
                $runs = new \Pauk\Repo\QuizRuns($pdo);
                $id = $runs->start($userId, $dirId, $total, $ranked);
                $best = $ranked ? $runs->bestForN($userId, $dirId, $total) : null;
                return Http::json($response, [
                    'id' => $id,
                    'best' => $best === null ? null : [
                        'correct' => $best['correct'],
                        'total' => $best['total'],
                        'accuracy' => round($best['correct'] / $best['total'], 3),
                    ],
                ], 201);
            });

            $group->patch('/quiz/runs/{id:[0-9]+}', function (Request $request, Response $response, array $args) use ($repos) {
                [$pdo, $userId] = $repos($request);
                $body = Http::body($request);
                $correct = $body['correct'] ?? null;
                $total = $body['total'] ?? null;
                $ranked = $body['ranked'] ?? null;   // false = abandoned run
                if (!is_int($correct) || !is_int($total) || ($ranked !== null && !is_bool($ranked))) {
                    throw new ApiError(400, 'validation', 'correct/total integers, ranked bool');
                }
                $runs = new \Pauk\Repo\QuizRuns($pdo);
                return Http::json($response, $runs->finish($userId, (int) $args['id'], $correct, $total, $ranked));
            });

            $group->get('/stats', function (Request $request, Response $response) use ($repos) {
                [$pdo, $userId, , $cards] = $repos($request);
                $candidates = $cards->candidateIds($userId, self::cardFilters($request));
                $stats = new \Pauk\Repo\Stats($pdo);
                return Http::json($response, $stats->forCards($userId, $candidates));
            });

            // --- media ---------------------------------------------------
            $group->post('/media', function (Request $request, Response $response) use ($repos) {
                [$pdo, $userId] = $repos($request);
                $files = $request->getUploadedFiles();
                if (!isset($files['file'])) {
                    throw new ApiError(400, 'validation', "multipart field 'file' required");
                }
                $media = new \Pauk\Repo\Media($pdo);
                [$object, $created] = $media->upload($userId, $files['file']);
                return Http::json($response, $object, $created ? 201 : 200);
            });

            $group->get('/media', function (Request $request, Response $response) use ($repos) {
                [$pdo, $userId] = $repos($request);
                $media = new \Pauk\Repo\Media($pdo);
                return Http::json($response, $media->list(
                    $userId,
                    Http::intQuery($request, 'limit', 50, 1, 200),
                    $request->getQueryParams()['cursor'] ?? null,
                ));
            });

            $group->delete('/media/{id:[0-9]+}', function (Request $request, Response $response, array $args) use ($repos) {
                [$pdo, $userId] = $repos($request);
                $media = new \Pauk\Repo\Media($pdo);
                $media->delete($userId, (int) $args['id']);
                return $response->withStatus(204);
            });

            // --- dirs ----------------------------------------------------
            $group->get('/dirs', function (Request $request, Response $response) use ($repos) {
                [, $userId, $dirs] = $repos($request);
                $params = $request->getQueryParams();
                $parent = isset($params['parent'])
                    ? Http::intQuery($request, 'parent', 0, 1, PHP_INT_MAX)
                    : null;
                return Http::json($response, ['items' => $dirs->listChildren($userId, $parent)]);
            });

            $group->get('/dirs/resolve', function (Request $request, Response $response) use ($repos) {
                [, $userId, $dirs] = $repos($request);
                $path = $request->getQueryParams()['path'] ?? '';
                return Http::json($response, $dirs->resolvePath($userId, $path));
            });

            $group->get('/dirs/{id:[0-9]+}', function (Request $request, Response $response, array $args) use ($repos) {
                [, $userId, $dirs] = $repos($request);
                return Http::json($response, $dirs->get($userId, (int) $args['id']));
            });

            $group->post('/dirs', function (Request $request, Response $response) use ($repos) {
                [, $userId, $dirs] = $repos($request);
                $body = Http::body($request);
                $name = $body['name'] ?? '';
                $parentId = $body['parent_id'] ?? null;
                if ($parentId !== null && !is_int($parentId)) {
                    throw new ApiError(400, 'validation', 'parent_id must be an integer');
                }
                if (!is_string($name)) {
                    throw new ApiError(400, 'validation', 'name must be a string');
                }
                return Http::json($response, $dirs->create($userId, $name, $parentId), 201);
            });

            $group->patch('/dirs/{id:[0-9]+}', function (Request $request, Response $response, array $args) use ($repos) {
                [, $userId, $dirs] = $repos($request);
                $name = Http::body($request)['name'] ?? '';
                if (!is_string($name)) {
                    throw new ApiError(400, 'validation', 'name must be a string');
                }
                return Http::json($response, $dirs->rename($userId, (int) $args['id'], $name));
            });

            $group->delete('/dirs/{id:[0-9]+}', function (Request $request, Response $response, array $args) use ($repos) {
                [, $userId, $dirs] = $repos($request);
                $force = ($request->getQueryParams()['force'] ?? '') === '1';
                $dirs->delete($userId, (int) $args['id'], $force);
                return $response->withStatus(204);
            });

            $group->put('/dirs/{id:[0-9]+}/cards/{cardId:[0-9]+}', function (Request $request, Response $response, array $args) use ($repos) {
                [, $userId, $dirs] = $repos($request);
                $dirs->linkCard($userId, (int) $args['id'], (int) $args['cardId']);
                return $response->withStatus(204);
            });

            $group->delete('/dirs/{id:[0-9]+}/cards/{cardId:[0-9]+}', function (Request $request, Response $response, array $args) use ($repos) {
                [, $userId, $dirs] = $repos($request);
                $dirs->unlinkCard($userId, (int) $args['id'], (int) $args['cardId']);
                return $response->withStatus(204);
            });

            $group->put('/dirs/{id:[0-9]+}/dirs/{childId:[0-9]+}', function (Request $request, Response $response, array $args) use ($repos) {
                [, $userId, $dirs] = $repos($request);
                $dirs->linkDir($userId, (int) $args['id'], (int) $args['childId']);
                return $response->withStatus(204);
            });

            $group->delete('/dirs/{id:[0-9]+}/dirs/{childId:[0-9]+}', function (Request $request, Response $response, array $args) use ($repos) {
                [, $userId, $dirs] = $repos($request);
                $dirs->unlinkDir($userId, (int) $args['id'], (int) $args['childId']);
                return $response->withStatus(204);
            });
        })->add(new AuthMiddleware($getPdo));

        // Error handling: ApiError → its status/code; anything else → 500.
        $errorMiddleware = $app->addErrorMiddleware(false, true, true);
        $errorMiddleware->setDefaultErrorHandler(
            function (Request $request, \Throwable $e) use ($app) {
                $response = $app->getResponseFactory()->createResponse();
                if ($e instanceof ApiError) {
                    return Http::error($response, $e->status, $e->errorCode, $e->getMessage());
                }
                if ($e instanceof \Slim\Exception\HttpNotFoundException) {
                    return Http::error($response, 404, 'not_found', 'Route not found');
                }
                if ($e instanceof \Slim\Exception\HttpMethodNotAllowedException) {
                    return Http::error($response, 405, 'method_not_allowed', 'Method not allowed');
                }
                error_log('pauk: ' . $e::class . ': ' . $e->getMessage());
                return Http::error($response, 500, 'internal', 'Internal server error');
            }
        );

        return $app;
    }

    /** @return array{dir?: int, recursive?: bool, unfiled?: bool, type?: string, q?: string} */
    private static function cardFilters(Request $request): array
    {
        $params = $request->getQueryParams();
        $filters = [];
        if (isset($params['dir'])) {
            $filters['dir'] = Http::intQuery($request, 'dir', 0, 1, PHP_INT_MAX);
            $filters['recursive'] = ($params['recursive'] ?? '') === '1';
        }
        if (($params['unfiled'] ?? '') === '1') {
            $filters['unfiled'] = true;
        }
        if (isset($params['type'])) {
            $filters['type'] = (string) $params['type'];
        }
        if (isset($params['q'])) {
            $filters['q'] = (string) $params['q'];
        }
        return $filters;
    }
}

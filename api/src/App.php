<?php

declare(strict_types=1);

namespace Pauk;

use Pauk\Repo\Cards;
use Pauk\Repo\Dirs;
use Pauk\Repo\Export;
use Pauk\Repo\Interactions;
use Pauk\Repo\Items;
use Pauk\Repo\Merges;
use Pauk\Repo\Profile;
use Pauk\Repo\Settings;
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
                $interactions = new Interactions($pdo, new Items($pdo, $dirs));
                return [$pdo, $userId, $dirs, new Cards($pdo, $dirs, $interactions)];
            };
            // knowledge profile (docs/tutor.md)
            $kb = function (Request $request) use ($getPdo): object {
                $pdo = $getPdo();
                $items = new Items($pdo, new Dirs($pdo));
                $interactions = new Interactions($pdo, $items);
                $settings = new Settings($pdo);
                return (object) [
                    'userId' => (int) $request->getAttribute('user_id'),
                    'items' => $items,
                    'interactions' => $interactions,
                    'merges' => new Merges($pdo, $items, $interactions),
                    'profile' => new Profile($pdo, $items),
                    'settings' => $settings,
                    'export' => new Export($pdo, $items, $interactions, $settings),
                ];
            };
            self::knowledgeRoutes($group, $kb);

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
                    return Http::error($response, $e->status, $e->errorCode, $e->getMessage(), $e->details);
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

    /**
     * Routes of the knowledge profile. Items are addressed as
     * /items/{space}/{key} or /items/{id}; every item route is
     * registered in both forms.
     */
    private static function knowledgeRoutes(RouteCollectorProxy $group, callable $kb): void
    {
        $refPatterns = ['{id:[0-9]+}', '{space:[a-z][a-z0-9-]*}/{key:[a-z0-9][a-z0-9.-]*}'];
        $itemRoute = function (string $method, string $prefix, string $suffix, callable $handler) use ($group, $refPatterns): void {
            foreach ($refPatterns as $pattern) {
                $group->map([$method], $prefix . $pattern . $suffix, function (Request $request, Response $response, array $args) use ($handler) {
                    $ref = isset($args['id']) ? (int) $args['id'] : $args['space'] . '/' . $args['key'];
                    return $handler($request, $response, $ref, $args);
                });
            }
        };

        // --- items -------------------------------------------------------
        $group->get('/items', function (Request $request, Response $response) use ($kb) {
            $k = $kb($request);
            return Http::json($response, $k->items->list(
                $k->userId,
                self::itemFilters($request),
                Http::intQuery($request, 'limit', 50, 1, 200),
                $request->getQueryParams()['cursor'] ?? null
            ));
        });

        $group->post('/items', function (Request $request, Response $response) use ($kb) {
            $k = $kb($request);
            [$status, $payload] = $k->items->create($k->userId, Http::body($request));
            return Http::json($response, $payload, $status);
        });

        $group->put('/items/bulk', function (Request $request, Response $response) use ($kb) {
            $k = $kb($request);
            return Http::json($response, $k->items->bulk($k->userId, Http::body($request)['items'] ?? null));
        });

        $itemRoute('GET', '/items/', '', function (Request $request, Response $response, $ref) use ($kb) {
            $k = $kb($request);
            return Http::json($response, $k->items->get($k->userId, $ref));
        });

        $itemRoute('PATCH', '/items/', '', function (Request $request, Response $response, $ref) use ($kb) {
            $k = $kb($request);
            return Http::json($response, $k->items->update($k->userId, $ref, Http::body($request)));
        });

        foreach (['archive' => true, 'unarchive' => false] as $action => $archived) {
            $itemRoute('POST', '/items/', "/$action", function (Request $request, Response $response, $ref) use ($kb, $archived) {
                $k = $kb($request);
                return Http::json($response, $k->items->setArchived($k->userId, $ref, $archived));
            });
        }

        $itemRoute('PUT', '/items/', '/state', function (Request $request, Response $response, $ref) use ($kb) {
            $k = $kb($request);
            return Http::json($response, $k->items->setFlags($k->userId, $ref, Http::body($request)));
        });

        $itemRoute('PUT', '/items/', '/links', function (Request $request, Response $response, $ref) use ($kb) {
            $k = $kb($request);
            $body = Http::body($request);
            $k->items->link($k->userId, $ref, $body['rel'] ?? null, $body['to'] ?? null, $body['note'] ?? null);
            return $response->withStatus(204);
        });

        $itemRoute('DELETE', '/items/', '/links', function (Request $request, Response $response, $ref) use ($kb) {
            $k = $kb($request);
            $params = $request->getQueryParams();
            $k->items->unlink($k->userId, $ref, (string) ($params['rel'] ?? ''), (string) ($params['to'] ?? ''));
            return $response->withStatus(204);
        });

        $itemRoute('POST', '/items/', '/merge', function (Request $request, Response $response, $ref) use ($kb) {
            $k = $kb($request);
            return Http::json($response, $k->merges->merge($k->userId, $ref, Http::body($request)));
        });

        $itemRoute('POST', '/items/', '/unmerge', function (Request $request, Response $response, $ref) use ($kb) {
            $k = $kb($request);
            return Http::json($response, $k->merges->unmerge($k->userId, $ref));
        });

        // --- merge suggestions -------------------------------------------
        $group->get('/merges', function (Request $request, Response $response) use ($kb) {
            $k = $kb($request);
            $status = $request->getQueryParams()['status'] ?? null;
            return Http::json($response, ['items' => $k->merges->list($k->userId, is_string($status) ? $status : null)]);
        });

        $group->post('/merges', function (Request $request, Response $response) use ($kb) {
            $k = $kb($request);
            return Http::json($response, $k->merges->suggest($k->userId, Http::body($request)), 201);
        });

        $group->post('/merges/{id:[0-9]+}/{action:accept|dismiss}', function (Request $request, Response $response, array $args) use ($kb) {
            $k = $kb($request);
            $merge = $args['action'] === 'accept'
                ? $k->merges->accept($k->userId, (int) $args['id'])
                : $k->merges->dismiss($k->userId, (int) $args['id']);
            return Http::json($response, $merge);
        });

        // --- subject and card membership ---------------------------------
        foreach (['PUT', 'DELETE'] as $method) {
            $itemRoute($method, '/dirs/{dirId:[0-9]+}/items/', '', function (Request $request, Response $response, $ref, array $args) use ($kb, $method) {
                $k = $kb($request);
                if ($method === 'PUT') {
                    $k->items->linkDir($k->userId, (int) $args['dirId'], $ref);
                } else {
                    $k->items->unlinkDir($k->userId, (int) $args['dirId'], $ref);
                }
                return $response->withStatus(204);
            });
            $itemRoute($method, '/cards/{cardId:[0-9]+}/items/', '', function (Request $request, Response $response, $ref, array $args) use ($kb, $method) {
                $k = $kb($request);
                if ($method === 'PUT') {
                    $k->interactions->linkCard($k->userId, (int) $args['cardId'], $ref);
                } else {
                    $k->interactions->unlinkCard($k->userId, (int) $args['cardId'], $ref);
                }
                return $response->withStatus(204);
            });
        }

        // --- interactions ------------------------------------------------
        $group->post('/interactions', function (Request $request, Response $response) use ($kb) {
            $k = $kb($request);
            [$status, $payload] = $k->interactions->record($k->userId, Http::body($request));
            return Http::json($response, $payload, $status);
        });

        $group->get('/interactions', function (Request $request, Response $response) use ($kb) {
            $k = $kb($request);
            $params = $request->getQueryParams();
            $filters = array_filter([
                'item' => $params['item'] ?? null,
                'session_id' => $params['session_id'] ?? null,
                'since' => $params['since'] ?? null,
            ], fn ($v) => is_string($v) && $v !== '');
            return Http::json($response, $k->interactions->history(
                $k->userId, $filters, Http::intQuery($request, 'limit', 50, 1, 200), $params['cursor'] ?? null
            ));
        });

        $group->post('/interactions/{uuid:[0-9a-f-]{36}}/amendments', function (Request $request, Response $response, array $args) use ($kb) {
            $k = $kb($request);
            return Http::json($response, $k->interactions->amend($k->userId, $args['uuid'], Http::body($request)));
        });

        // --- profile, settings, export, maintenance ----------------------
        $group->get('/profile', function (Request $request, Response $response) use ($kb) {
            $k = $kb($request);
            return Http::json($response, $k->profile->summary($k->userId, self::itemFilters($request, true)));
        });

        $group->get('/profile/next', function (Request $request, Response $response) use ($kb) {
            $k = $kb($request);
            $n = Http::intQuery($request, 'n', 10, 1, 100);
            return Http::json($response, $k->profile->next(
                $k->userId, self::itemFilters($request, true), $n, Http::intQuery($request, 'new', $n, 0, 100)
            ));
        });

        $group->get('/settings', function (Request $request, Response $response) use ($kb) {
            $k = $kb($request);
            return Http::json($response, $k->settings->all($k->userId));
        });

        $group->patch('/settings', function (Request $request, Response $response) use ($kb) {
            $k = $kb($request);
            return Http::json($response, $k->settings->update($k->userId, Http::body($request)));
        });

        $group->get('/export', function (Request $request, Response $response) use ($kb) {
            $k = $kb($request);
            foreach ($k->export->records($k->userId) as $record) {
                $response->getBody()->write(
                    json_encode($record, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR) . "\n"
                );
            }
            return $response->withHeader('Content-Type', 'application/x-ndjson; charset=utf-8');
        });

        $group->post('/admin/rebuild-states', function (Request $request, Response $response) use ($kb) {
            $k = $kb($request);
            return Http::json($response, ['items' => $k->interactions->rebuild($k->userId)]);
        });
    }

    /** @return array<string, mixed> */
    private static function itemFilters(Request $request, bool $recursiveDefault = false): array
    {
        $params = $request->getQueryParams();
        $filters = [];
        if (isset($params['dir'])) {
            $filters['dir'] = Http::intQuery($request, 'dir', 0, 1, PHP_INT_MAX);
            $filters['recursive'] = ($params['recursive'] ?? ($recursiveDefault ? '1' : '')) === '1';
        }
        foreach (['space', 'kind', 'q', 'status'] as $name) {
            if (isset($params[$name]) && is_string($params[$name]) && $params[$name] !== '') {
                $filters[$name] = $params[$name];
            }
        }
        if (($params['archived'] ?? '') === '1') {
            $filters['archived'] = true;
        }
        return $filters;
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

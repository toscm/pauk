<?php

declare(strict_types=1);

// Front controller. Locally the app lives one level up; on the
// server the docroot stub sets PAUK_APP_DIR to ~/pauk-app.
$appDir = getenv('PAUK_APP_DIR') ?: dirname(__DIR__);
require $appDir . '/vendor/autoload.php';

// CGI PHP + internal redirects (FallbackResource) bury the
// Authorization header under REDIRECT_ prefixes; promote it.
if (!isset($_SERVER['HTTP_AUTHORIZATION'])) {
    foreach ($_SERVER as $key => $value) {
        if (preg_match('/^(REDIRECT_)+HTTP_AUTHORIZATION$/', (string) $key)) {
            $_SERVER['HTTP_AUTHORIZATION'] = $value;
            break;
        }
    }
}

Pauk\App::build(fn () => Pauk\Db::connect())->run();

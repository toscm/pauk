<?php

declare(strict_types=1);

// Front controller. Locally the app lives one level up; on the
// server .htaccess sets PAUK_APP_DIR to ~/pauk-app.
$appDir = getenv('PAUK_APP_DIR') ?: dirname(__DIR__);
require $appDir . '/vendor/autoload.php';

Pauk\App::build(fn () => Pauk\Db::connect())->run();

<?php

declare(strict_types=1);

// Under the PHP built-in dev server, serve uploaded media files
// directly (Apache does this in production). The built-in server's
// docroot is the CWD, not public/, so emit the file ourselves
// rather than `return false`.
if (PHP_SAPI === 'cli-server') {
    $path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?? '';
    if (preg_match('#^/media/([a-f0-9]{64}\.[a-z0-9]+)$#', $path, $m)) {
        $mediaDir = getenv('PAUK_MEDIA_DIR') ?: __DIR__ . '/media';
        $file = $mediaDir . '/' . $m[1];
        if (is_file($file)) {
            $finfo = new finfo(FILEINFO_MIME_TYPE);
            header('Content-Type: ' . ($finfo->file($file) ?: 'application/octet-stream'));
            header('Content-Length: ' . filesize($file));
            readfile($file);
            return true;
        }
        http_response_code(404);
        return true;
    }
}

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

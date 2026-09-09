<?php

declare(strict_types=1);

namespace Pauk\Repo;

use Pauk\ApiError;
use Pauk\Env;
use Psr\Http\Message\UploadedFileInterface;

final class Media
{
    public const MAX_BYTES = 50 * 1024 * 1024;

    /** mime => canonical file extension */
    public const ALLOWED = [
        'image/png' => 'png',
        'image/jpeg' => 'jpg',
        'image/gif' => 'gif',
        'image/webp' => 'webp',
        'image/svg+xml' => 'svg',
        'video/mp4' => 'mp4',
        'video/webm' => 'webm',
        'application/pdf' => 'pdf',
    ];

    public function __construct(private readonly \PDO $pdo)
    {
    }

    public static function dir(): string
    {
        return Env::get('PAUK_MEDIA_DIR');
    }

    public static function baseUrl(): string
    {
        return rtrim(Env::get('PAUK_BASE_URL'), '/');
    }

    /** @return array{0: array<string, mixed>, 1: bool} [object, created] */
    public function upload(int $userId, UploadedFileInterface $file): array
    {
        if ($file->getError() !== UPLOAD_ERR_OK) {
            throw new ApiError(400, 'validation', 'upload failed');
        }
        $size = $file->getSize() ?? 0;
        if ($size <= 0 || $size > self::MAX_BYTES) {
            throw new ApiError(413, 'too_large', 'file empty or larger than 50 MB');
        }
        $data = (string) $file->getStream();
        $finfo = new \finfo(FILEINFO_MIME_TYPE);
        $mime = (string) $finfo->buffer($data);
        // SVG is XML; finfo may report text/xml or text/plain
        $name = $file->getClientFilename() ?? 'file';
        if (in_array($mime, ['text/xml', 'application/xml', 'text/plain', 'text/html'], true)
            && str_ends_with(strtolower($name), '.svg')
            && str_contains(substr($data, 0, 4096), '<svg')) {
            $mime = 'image/svg+xml';
        }
        if (!isset(self::ALLOWED[$mime])) {
            throw new ApiError(400, 'validation', "unsupported media type '$mime'");
        }
        $sha = hash('sha256', $data);
        $stmt = $this->pdo->prepare('SELECT * FROM media WHERE sha256 = ?');
        $stmt->execute([$sha]);
        $existing = $stmt->fetch();
        if ($existing !== false) {
            return [$this->hydrate($existing), false];
        }
        $ext = self::ALLOWED[$mime];
        $dir = self::dir();
        if (!is_dir($dir) && !mkdir($dir, 0755, true) && !is_dir($dir)) {
            throw new ApiError(500, 'internal', 'media directory not writable');
        }
        if (file_put_contents("$dir/$sha.$ext", $data) === false) {
            throw new ApiError(500, 'internal', 'could not store file');
        }
        $stmt = $this->pdo->prepare(
            'INSERT INTO media (user_id, sha256, original_name, mime, size)
             VALUES (?, ?, ?, ?, ?)'
        );
        $stmt->execute([$userId, $sha, $name, $mime, strlen($data)]);
        $stmt = $this->pdo->prepare('SELECT * FROM media WHERE id = ?');
        $stmt->execute([$this->pdo->lastInsertId()]);
        return [$this->hydrate($stmt->fetch()), true];
    }

    /** @return array{items: list<array<string, mixed>>, next_cursor: ?string} */
    public function list(int $userId, int $limit, ?string $cursor): array
    {
        $afterId = 0;
        if ($cursor !== null) {
            $decoded = base64_decode($cursor, true);
            if ($decoded === false || filter_var($decoded, FILTER_VALIDATE_INT) === false) {
                throw new ApiError(400, 'validation', 'Invalid cursor');
            }
            $afterId = (int) $decoded;
        }
        $stmt = $this->pdo->prepare(
            'SELECT * FROM media WHERE user_id = ? AND id > ? ORDER BY id LIMIT ' . ($limit + 1)
        );
        $stmt->execute([$userId, $afterId]);
        $rows = $stmt->fetchAll();
        $nextCursor = null;
        if (count($rows) > $limit) {
            $rows = array_slice($rows, 0, $limit);
            $nextCursor = base64_encode((string) end($rows)['id']);
        }
        return [
            'items' => array_map(fn ($r) => $this->hydrate($r), $rows),
            'next_cursor' => $nextCursor,
        ];
    }

    public function delete(int $userId, int $mediaId): void
    {
        $stmt = $this->pdo->prepare('SELECT * FROM media WHERE id = ? AND user_id = ?');
        $stmt->execute([$mediaId, $userId]);
        $row = $stmt->fetch();
        if ($row === false) {
            throw new ApiError(404, 'not_found', "Media $mediaId not found");
        }
        $stmt = $this->pdo->prepare(
            'SELECT COUNT(*) FROM cards WHERE question_md LIKE ?'
        );
        $stmt->execute(['%' . $row['sha256'] . '%']);
        if ((int) $stmt->fetchColumn() > 0) {
            throw new ApiError(409, 'conflict', 'media is referenced by a card');
        }
        $ext = self::ALLOWED[$row['mime']] ?? 'bin';
        @unlink(self::dir() . '/' . $row['sha256'] . '.' . $ext);
        $stmt = $this->pdo->prepare('DELETE FROM media WHERE id = ?');
        $stmt->execute([$mediaId]);
    }

    /** @param array<string, mixed> $row */
    private function hydrate(array $row): array
    {
        $ext = self::ALLOWED[$row['mime']] ?? 'bin';
        return [
            'id' => (int) $row['id'],
            'url' => self::baseUrl() . '/media/' . $row['sha256'] . '.' . $ext,
            'sha256' => $row['sha256'],
            'original_name' => $row['original_name'],
            'mime' => $row['mime'],
            'size' => (int) $row['size'],
        ];
    }
}

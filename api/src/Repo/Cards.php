<?php

declare(strict_types=1);

namespace Pauk\Repo;

use Pauk\ApiError;
use Pauk\Text;

final class Cards
{
    public function __construct(
        private readonly \PDO $pdo,
        private readonly Dirs $dirs,
    ) {
    }

    /** @return array<string, mixed> */
    public function get(int $userId, int $cardId, bool $quiz = false): array
    {
        $stmt = $this->pdo->prepare(
            'SELECT id, type, question_md, created_at, updated_at
             FROM cards WHERE id = ? AND user_id = ?'
        );
        $stmt->execute([$cardId, $userId]);
        $card = $stmt->fetch();
        if ($card === false) {
            throw new ApiError(404, 'not_found', "Card $cardId not found");
        }
        return $this->hydrate($card, $quiz);
    }

    /**
     * @param array{dir?: int, recursive?: bool, unfiled?: bool,
     *              type?: string, q?: string} $filters
     * @return array{items: list<array<string, mixed>>, next_cursor: ?string}
     */
    public function list(int $userId, array $filters, bool $quiz, int $limit, ?string $cursor): array
    {
        [$where, $params] = $this->filterSql($userId, $filters);
        $afterId = 0;
        if ($cursor !== null) {
            $decoded = base64_decode($cursor, true);
            if ($decoded === false || filter_var($decoded, FILTER_VALIDATE_INT) === false) {
                throw new ApiError(400, 'validation', 'Invalid cursor');
            }
            $afterId = (int) $decoded;
        }
        $where[] = 'c.id > ?';
        $params[] = $afterId;
        $sql = 'SELECT DISTINCT c.id, c.type, c.question_md, c.created_at, c.updated_at
                FROM cards c ' . $this->filterJoins($filters) . '
                WHERE ' . implode(' AND ', $where) . '
                ORDER BY c.id LIMIT ' . ($limit + 1);
        $stmt = $this->pdo->prepare($sql);
        $stmt->execute($params);
        $rows = $stmt->fetchAll();
        $nextCursor = null;
        if (count($rows) > $limit) {
            $rows = array_slice($rows, 0, $limit);
            $nextCursor = base64_encode((string) end($rows)['id']);
        }
        return [
            'items' => array_map(fn ($row) => $this->hydrate($row, $quiz), $rows),
            'next_cursor' => $nextCursor,
        ];
    }

    /**
     * Ids of all candidate cards for the given filters (used by
     * quiz selection, which samples rather than paginates).
     *
     * @return list<int>
     */
    public function candidateIds(int $userId, array $filters): array
    {
        [$where, $params] = $this->filterSql($userId, $filters);
        $sql = 'SELECT DISTINCT c.id FROM cards c ' . $this->filterJoins($filters)
             . ' WHERE ' . implode(' AND ', $where);
        $stmt = $this->pdo->prepare($sql);
        $stmt->execute($params);
        return array_map('intval', $stmt->fetchAll(\PDO::FETCH_COLUMN));
    }

    /** @param array<string, mixed> $body */
    public function create(int $userId, array $body): array
    {
        $type = $body['type'] ?? null;
        if (!in_array($type, ['mc', 'text'], true)) {
            throw new ApiError(400, 'validation', "type must be 'mc' or 'text'");
        }
        $question = $body['question_md'] ?? null;
        if (!is_string($question) || trim($question) === '') {
            throw new ApiError(400, 'validation', 'question_md must be a non-empty string');
        }
        $options = null;
        $answers = null;
        if ($type === 'mc') {
            $options = $this->validateOptions($body['options'] ?? null);
        } else {
            $answers = $this->validateAnswers($body['accepted_answers'] ?? null);
        }
        $dirIds = $this->validateDirIds($userId, $body['dirs'] ?? []);

        $this->pdo->beginTransaction();
        try {
            $stmt = $this->pdo->prepare(
                'INSERT INTO cards (user_id, type, question_md) VALUES (?, ?, ?)'
            );
            $stmt->execute([$userId, $type, $question]);
            $cardId = (int) $this->pdo->lastInsertId();
            if ($options !== null) {
                $this->replaceOptions($cardId, $options);
            }
            if ($answers !== null) {
                $this->replaceAnswers($cardId, $answers);
            }
            foreach ($dirIds as $dirId) {
                $stmt = $this->pdo->prepare(
                    'INSERT IGNORE INTO dir_cards (dir_id, card_id) VALUES (?, ?)'
                );
                $stmt->execute([$dirId, $cardId]);
            }
            $this->pdo->commit();
        } catch (\Throwable $e) {
            $this->pdo->rollBack();
            throw $e;
        }
        return $this->get($userId, $cardId);
    }

    /** @param array<string, mixed> $body */
    public function update(int $userId, int $cardId, array $body): array
    {
        $card = $this->get($userId, $cardId);
        if (array_key_exists('type', $body) && $body['type'] !== $card['type']) {
            throw new ApiError(400, 'validation', 'Card type cannot be changed');
        }
        $this->pdo->beginTransaction();
        try {
            if (array_key_exists('question_md', $body)) {
                $question = $body['question_md'];
                if (!is_string($question) || trim($question) === '') {
                    throw new ApiError(400, 'validation', 'question_md must be a non-empty string');
                }
                $stmt = $this->pdo->prepare('UPDATE cards SET question_md = ? WHERE id = ?');
                $stmt->execute([$question, $cardId]);
            }
            if (array_key_exists('options', $body)) {
                if ($card['type'] !== 'mc') {
                    throw new ApiError(400, 'validation', 'options only apply to mc cards');
                }
                $this->replaceOptions($cardId, $this->validateOptions($body['options']), true);
            }
            if (array_key_exists('accepted_answers', $body)) {
                if ($card['type'] !== 'text') {
                    throw new ApiError(400, 'validation', 'accepted_answers only apply to text cards');
                }
                $this->replaceAnswers($cardId, $this->validateAnswers($body['accepted_answers']), true);
            }
            if (array_key_exists('dirs', $body)) {
                $dirIds = $this->validateDirIds($userId, $body['dirs']);
                $stmt = $this->pdo->prepare('DELETE FROM dir_cards WHERE card_id = ?');
                $stmt->execute([$cardId]);
                foreach ($dirIds as $dirId) {
                    $stmt = $this->pdo->prepare(
                        'INSERT IGNORE INTO dir_cards (dir_id, card_id) VALUES (?, ?)'
                    );
                    $stmt->execute([$dirId, $cardId]);
                }
            }
            $this->pdo->commit();
        } catch (\Throwable $e) {
            $this->pdo->rollBack();
            throw $e;
        }
        return $this->get($userId, $cardId);
    }

    public function delete(int $userId, int $cardId): void
    {
        $this->get($userId, $cardId);
        $stmt = $this->pdo->prepare('DELETE FROM cards WHERE id = ?');
        $stmt->execute([$cardId]);
    }

    /**
     * Grade an answer, log it to reviews, and return the result
     * (docs/api.md, "Answering").
     *
     * @param array<string, mixed> $body
     */
    public function answer(int $userId, int $cardId, array $body): array
    {
        $card = $this->get($userId, $cardId);
        if ($card['type'] === 'mc') {
            $selected = $body['selected'] ?? null;
            if (!is_array($selected) || array_filter($selected, fn ($v) => !is_int($v)) !== []) {
                throw new ApiError(400, 'validation', 'selected must be a list of option ids');
            }
            $correctIds = array_values(array_map(
                fn ($o) => $o['id'],
                array_filter($card['options'], fn ($o) => $o['correct'])
            ));
            sort($selected);
            $match = $selected === $correctIds ? 'exact' : 'wrong';
            $expected = ['correct_option_ids' => $correctIds];
        } else {
            $answer = $body['answer'] ?? null;
            if (!is_string($answer)) {
                throw new ApiError(400, 'validation', 'answer must be a string');
            }
            $match = Text::grade($answer, $card['accepted_answers']);
            $expected = ['accepted_answers' => $card['accepted_answers']];
        }
        $correct = $match !== 'wrong';
        $stmt = $this->pdo->prepare(
            'INSERT INTO reviews (card_id, user_id, was_correct) VALUES (?, ?, ?)'
        );
        $stmt->execute([$cardId, $userId, $correct ? 1 : 0]);
        return ['correct' => $correct, 'match' => $match, 'expected' => $expected];
    }

    /** @return array{0: list<string>, 1: list<mixed>} */
    private function filterSql(int $userId, array $filters): array
    {
        $where = ['c.user_id = ?'];
        $params = [$userId];
        if (isset($filters['dir'])) {
            $dirIds = ($filters['recursive'] ?? false)
                ? $this->dirs->subtreeIds($filters['dir'])
                : [$filters['dir']];
            $placeholders = implode(',', array_fill(0, count($dirIds), '?'));
            $where[] = "dc.dir_id IN ($placeholders)";
            array_push($params, ...$dirIds);
        }
        if ($filters['unfiled'] ?? false) {
            $where[] = 'dc.card_id IS NULL';
        }
        if (isset($filters['type'])) {
            if (!in_array($filters['type'], ['mc', 'text'], true)) {
                throw new ApiError(400, 'validation', "type must be 'mc' or 'text'");
            }
            $where[] = 'c.type = ?';
            $params[] = $filters['type'];
        }
        if (isset($filters['q']) && $filters['q'] !== '') {
            $where[] = 'c.question_md LIKE ?';
            $params[] = '%' . addcslashes($filters['q'], '%_\\') . '%';
        }
        return [$where, $params];
    }

    private function filterJoins(array $filters): string
    {
        if (isset($filters['dir'])) {
            return 'JOIN dir_cards dc ON dc.card_id = c.id';
        }
        if ($filters['unfiled'] ?? false) {
            return 'LEFT JOIN dir_cards dc ON dc.card_id = c.id';
        }
        return '';
    }

    /** @return list<array{text_md: string, correct: bool}> */
    private function validateOptions(mixed $options): array
    {
        if (!is_array($options) || count($options) < 2) {
            throw new ApiError(400, 'validation', 'options must be a list of at least 2 entries');
        }
        $clean = [];
        $correctCount = 0;
        foreach ($options as $option) {
            $text = $option['text_md'] ?? null;
            $correct = $option['correct'] ?? null;
            if (!is_string($text) || trim($text) === '' || !is_bool($correct)) {
                throw new ApiError(
                    400,
                    'validation',
                    'each option needs a non-empty text_md and a boolean correct'
                );
            }
            $correctCount += $correct ? 1 : 0;
            $clean[] = ['text_md' => $text, 'correct' => $correct];
        }
        if ($correctCount === 0) {
            throw new ApiError(400, 'validation', 'at least one option must be correct');
        }
        return $clean;
    }

    /** @return list<string> */
    private function validateAnswers(mixed $answers): array
    {
        if (!is_array($answers) || $answers === []) {
            throw new ApiError(400, 'validation', 'accepted_answers must be a non-empty list');
        }
        $clean = [];
        foreach ($answers as $answer) {
            if (!is_string($answer) || trim($answer) === '') {
                throw new ApiError(400, 'validation', 'accepted answers must be non-empty strings');
            }
            $clean[] = trim($answer);
        }
        return $clean;
    }

    /** @return list<int> */
    private function validateDirIds(int $userId, mixed $dirIds): array
    {
        if (!is_array($dirIds)) {
            throw new ApiError(400, 'validation', 'dirs must be a list of directory ids');
        }
        $clean = [];
        foreach ($dirIds as $dirId) {
            if (!is_int($dirId)) {
                throw new ApiError(400, 'validation', 'dirs must be a list of directory ids');
            }
            $this->dirs->get($userId, $dirId);
            $clean[] = $dirId;
        }
        return $clean;
    }

    /** @param list<array{text_md: string, correct: bool}> $options */
    private function replaceOptions(int $cardId, array $options, bool $clear = false): void
    {
        if ($clear) {
            $stmt = $this->pdo->prepare('DELETE FROM mc_options WHERE card_id = ?');
            $stmt->execute([$cardId]);
        }
        $stmt = $this->pdo->prepare(
            'INSERT INTO mc_options (card_id, position, text_md, is_correct) VALUES (?, ?, ?, ?)'
        );
        foreach ($options as $i => $option) {
            $stmt->execute([$cardId, $i, $option['text_md'], $option['correct'] ? 1 : 0]);
        }
    }

    /** @param list<string> $answers */
    private function replaceAnswers(int $cardId, array $answers, bool $clear = false): void
    {
        if ($clear) {
            $stmt = $this->pdo->prepare('DELETE FROM text_answers WHERE card_id = ?');
            $stmt->execute([$cardId]);
        }
        $stmt = $this->pdo->prepare(
            'INSERT INTO text_answers (card_id, accepted_answer) VALUES (?, ?)'
        );
        foreach ($answers as $answer) {
            $stmt->execute([$cardId, $answer]);
        }
    }

    /** @param array<string, mixed> $row */
    private function hydrate(array $row, bool $quiz): array
    {
        $cardId = (int) $row['id'];
        $card = [
            'id' => $cardId,
            'type' => $row['type'],
            'question_md' => $row['question_md'],
        ];
        if ($row['type'] === 'mc') {
            $stmt = $this->pdo->prepare(
                'SELECT id, text_md, is_correct FROM mc_options
                 WHERE card_id = ? ORDER BY position'
            );
            $stmt->execute([$cardId]);
            $card['options'] = array_map(
                fn ($o) => $quiz
                    ? ['id' => (int) $o['id'], 'text_md' => $o['text_md']]
                    : [
                        'id' => (int) $o['id'],
                        'text_md' => $o['text_md'],
                        'correct' => (bool) $o['is_correct'],
                    ],
                $stmt->fetchAll()
            );
        } elseif (!$quiz) {
            $stmt = $this->pdo->prepare(
                'SELECT accepted_answer FROM text_answers WHERE card_id = ? ORDER BY id'
            );
            $stmt->execute([$cardId]);
            $card['accepted_answers'] = $stmt->fetchAll(\PDO::FETCH_COLUMN);
        }
        $stmt = $this->pdo->prepare(
            'SELECT d.id, d.name FROM dirs d
             JOIN dir_cards dc ON dc.dir_id = d.id
             WHERE dc.card_id = ? ORDER BY d.name'
        );
        $stmt->execute([$cardId]);
        $card['dirs'] = array_map(
            fn ($d) => ['id' => (int) $d['id'], 'name' => $d['name']],
            $stmt->fetchAll()
        );
        $card['created_at'] = self::iso($row['created_at']);
        $card['updated_at'] = self::iso($row['updated_at']);
        return $card;
    }

    private static function iso(string $dbTime): string
    {
        return str_replace(' ', 'T', $dbTime) . 'Z';
    }
}

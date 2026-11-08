<?php
/**
 * To'lov xabarlarini qabul qiluvchi manzil (hosting uchun):
 *
 *   https://cripto.smm-api.uz/pay?miqdor=541545.00&method=CardXabarBot&secret_key=KALIT
 *
 * Bu fayl faqat so'rovni tekshiradi va MySQL dagi `pay_inbox` navbatiga yozadi.
 * Bot (main.py) navbatni har 2 soniyada o'qiydi, summani faol chek bilan moslaydi,
 * balansni to'ldiradi va foydalanuvchiga xabar yuboradi. Bot vaqtincha to'xtagan bo'lsa ham
 * to'lov yo'qolmaydi — bot yonganda qayta ishlanadi.
 *
 * DB ma'lumotlari loyiha papkasidagi .env faylidan o'qiladi (DB_HOST, DB_USER, DB_PASSWORD, DB_NAME).
 * secret_key — bot admin panelidagi kalit (settings jadvalida saqlanadi).
 */
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');

function respond(int $code, array $data): void
{
    http_response_code($code);
    echo json_encode($data, JSON_UNESCAPED_UNICODE);
    exit;
}

/** python-dotenv bilan mos .env o'quvchi (KEY=value, "..." va '...' qiymatlar, # izohlar). */
function parse_env_file(string $path): array
{
    $vars = [];
    $lines = @file($path, FILE_IGNORE_NEW_LINES);
    if ($lines === false) {
        return $vars;
    }
    foreach ($lines as $line) {
        $line = trim($line);
        if ($line === '' || $line[0] === '#') {
            continue;
        }
        if (strncmp($line, 'export ', 7) === 0) {
            $line = ltrim(substr($line, 7));
        }
        $eq = strpos($line, '=');
        if ($eq === false) {
            continue;
        }
        $key = trim(substr($line, 0, $eq));
        $val = ltrim(substr($line, $eq + 1));
        if ($val !== '' && ($val[0] === '"' || $val[0] === "'")) {
            $quote = $val[0];
            $end = strrpos($val, $quote);
            if ($end !== false && $end > 0) {
                $val = substr($val, 1, $end - 1);
                if ($quote === '"') {
                    $val = strtr($val, ['\\\\' => '\\', '\\"' => '"', "\\'" => "'", '\\n' => "\n", '\\r' => "\r", '\\t' => "\t"]);
                }
            }
        } else {
            $hash = strpos($val, ' #');
            if ($hash !== false) {
                $val = substr($val, 0, $hash);
            }
            $val = rtrim($val);
        }
        $vars[$key] = $val;
    }
    return $vars;
}

function env_value(array $env, string $key, string $default = ''): string
{
    $v = getenv($key);
    if ($v !== false && $v !== '') {
        return $v;
    }
    return isset($env[$key]) && $env[$key] !== '' ? $env[$key] : $default;
}

function db_connect(array $env): PDO
{
    $host = env_value($env, 'DB_HOST', 'localhost');
    $port = env_value($env, 'DB_PORT', '3306');
    $user = env_value($env, 'DB_USER', 'root');
    $pass = env_value($env, 'DB_PASSWORD');
    $name = env_value($env, 'DB_NAME');
    $socket = env_value($env, 'DB_SOCKET');

    if ($name === '') {
        // DATABASE_URL=mysql+aiomysql://user:parol@host:3306/baza?charset=utf8mb4
        $url = env_value($env, 'DATABASE_URL');
        $parts = $url !== '' ? parse_url($url) : false;
        if ($parts === false || !isset($parts['scheme']) || stripos($parts['scheme'], 'mysql') !== 0) {
            throw new RuntimeException('MySQL sozlamalari topilmadi');
        }
        $host = $parts['host'] ?? 'localhost';
        $port = (string)($parts['port'] ?? 3306);
        $user = urldecode($parts['user'] ?? 'root');
        $pass = urldecode($parts['pass'] ?? '');
        $name = ltrim($parts['path'] ?? '', '/');
        if (!empty($parts['query'])) {
            parse_str($parts['query'], $q);
            if (!empty($q['unix_socket'])) {
                $socket = (string)$q['unix_socket'];
            }
        }
    }

    $dsn = $socket !== ''
        ? "mysql:unix_socket={$socket};dbname={$name};charset=utf8mb4"
        : "mysql:host={$host};port={$port};dbname={$name};charset=utf8mb4";
    return new PDO($dsn, $user, $pass, [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_TIMEOUT => 5,
        PDO::ATTR_EMULATE_PREPARES => false,
    ]);
}

if (!in_array($_SERVER['REQUEST_METHOD'] ?? 'GET', ['GET', 'POST'], true)) {
    respond(405, ['ok' => false, 'error' => 'method not allowed']);
}

// GET + POST (form yoki JSON) parametrlari
$params = $_GET;
if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST') {
    $params = array_merge($_POST, $params);
    $ctype = strtolower($_SERVER['CONTENT_TYPE'] ?? '');
    if (strpos($ctype, 'application/json') !== false) {
        $json = json_decode((string)file_get_contents('php://input', false, null, 0, 65536), true);
        if (is_array($json)) {
            foreach ($json as $k => $v) {
                if (!isset($params[$k]) && is_scalar($v)) {
                    $params[$k] = (string)$v;
                }
            }
        }
    }
}

$secret = is_string($params['secret_key'] ?? null) ? $params['secret_key'] : '';
$amount = is_string($params['miqdor'] ?? null) ? $params['miqdor'] : (is_string($params['amount'] ?? null) ? $params['amount'] : '');
$method = is_string($params['method'] ?? null) ? substr($params['method'], 0, 64) : null;

try {
    $envPath = dirname(__DIR__) . '/.env';
    if (!is_readable($envPath) && getenv('DB_NAME') === false && getenv('DATABASE_URL') === false) {
        // Ko'pincha sabab: .env boshqa foydalanuvchiga tegishli (bot root, PHP www-data) yoki fayl yo'q
        error_log('pay.php: .env o\'qilmadi: ' . $envPath);
        respond(500, ['ok' => false, 'error' => 'config: .env not readable by PHP']);
    }
    $env = parse_env_file($envPath);
    try {
        $pdo = db_connect($env);
    } catch (PDOException $e) {
        error_log('pay.php: MySQL ulanmadi: ' . $e->getMessage());
        respond(503, ['ok' => false, 'error' => 'database unavailable']);
    } catch (RuntimeException $e) {
        respond(500, ['ok' => false, 'error' => 'config: DB_* settings missing in .env']);
    }

    $stmt = $pdo->prepare('SELECT `value` FROM `settings` WHERE `key` = ?');
    $stmt->execute(['pay_secret_key']);
    $expected = (string)($stmt->fetchColumn() ?: '');
    if ($expected === '') {
        respond(503, ['ok' => false, 'error' => 'bot hali ishga tushirilmagan']);
    }
    if ($secret === '' || !hash_equals($expected, $secret)) {
        respond(403, ['ok' => false, 'error' => 'invalid secret_key']);
    }

    $amount = trim($amount);
    if ($amount === '' || strlen($amount) > 64 || !preg_match('/^[0-9][0-9 .,\']*$/', $amount)) {
        respond(400, ['ok' => false, 'error' => 'invalid amount']);
    }

    $ins = $pdo->prepare(
        'INSERT INTO `pay_inbox` (`raw_amount`, `method`, `remote_ip`, `status`, `created_at`) VALUES (?, ?, ?, ?, UTC_TIMESTAMP())'
    );
    $ins->execute([$amount, $method, substr((string)($_SERVER['REMOTE_ADDR'] ?? ''), 0, 64), 'new']);
    respond(200, ['ok' => true, 'queued' => true, 'id' => (int)$pdo->lastInsertId()]);
} catch (PDOException $e) {
    error_log('pay.php: ' . $e->getMessage());
    if ($e->getCode() === '42S02') {   // jadval yo'q — bot hali birinchi marta ishga tushirilmagan
        respond(503, ['ok' => false, 'error' => 'bot hali ishga tushirilmagan']);
    }
    respond(500, ['ok' => false, 'error' => 'internal error']);
} catch (Throwable $e) {
    error_log('pay.php: ' . $e->getMessage());
    respond(500, ['ok' => false, 'error' => 'internal error']);
}

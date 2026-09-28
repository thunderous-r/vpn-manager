# VPN Manager

> VPN Manager — учебно-практический self-hosted проект для изучения и автоматизации управления сетевой инфраструктурой на базе FastAPI и sing-box.  
> Проект используется для экспериментов с конфигурацией VPN-протоколов, маршрутизацией, DNS, автоматическим развёртыванием конфигураций, управлением пользователями и подписками, а также для практики разработки и администрирования Linux-сервисов.
> Проект предназначен для личного использования и небольшого закрытого круга пользователей. Он не является коммерческой VPN-платформой, публичным сетевым сервисом или готовым продуктом для массового развёртывания.
> Репозиторий в первую очередь служит учебным примером архитектуры небольшого сервиса: FastAPI-приложение управляет пользователями и подписками, генерирует конфигурации sing-box для нескольких узлов и автоматизирует их проверку и развёртывание.

VPN Manager — FastAPI-панель для управления пользователями, подписками и конфигурациями `sing-box`.

Поддерживаются:

- VLESS Reality;
- Hysteria2;
- несколько VPN-узлов;
- роли `exit` и `ru-entry`;
- локальный и SSH-deploy;
- единая subscription-ссылка пользователя;
- автоматическая публикация профилей со всех `publish`-нод;
- Happ routing profile и автообновление подписки;
- DNS hijack + DoH на exit-нодах;
- автоматический render/deploy при изменении пользователей;
- проверка конфигурации и rollback при ошибке;
- централизованная статистика активности пользователей по нодам, протоколам и source IP/network;
- leak alerts по числу одновременно активных сетей.

## Архитектура

Конфигурация строится вокруг списка `nodes` в `base.json`.

Поддерживаемые роли:

- `exit` — обычная выходная VPN-нода;
- `ru-entry` — входная нода: российский трафик может идти напрямую, остальной — через VLESS-туннель на основной exit.

Текущая топология:

```text
                    VPN user
                       │
              VLESS Reality / HY2
                       │
           ┌───────────┴───────────┐
           ▼                       ▼
       DE1 exit                DE2 exit
       direct                  direct
       DNS hijack              DNS hijack
           ▲
           │ VLESS tunnel
           │
        RU entry
      RU → direct
      rest → DE1
```

Рендер и deploy не привязаны к фиксированному количеству exit-нод.

## Что генерируется для нод

### `role: "exit"`

Для exit-ноды создаются:

- VLESS Reality inbound;
- Hysteria2 inbound;
- `direct` outbound;
- `sniff`;
- DNS hijack;
- блокировка BitTorrent;
- `final: direct`.

DNS клиентов перехватывается `sing-box` и резолвится через DoH:

```text
client DNS
    ↓
VPN tunnel
    ↓
hijack-dns
    ↓
https://1.1.1.1/dns-query
```

Используется `ipv4_only` DNS strategy.

Если у exit-ноды задано:

```json
"accept_legacy_tunnel": true
```

добавляется inbound `ru-tunnel` для текущего RU → DE туннеля.

### `role: "ru-entry"`

Для RU Entry создаются:

- VLESS Reality inbound;
- Hysteria2 inbound;
- `direct` outbound;
- VLESS outbound `de-out`;
- rule sets для direct-трафика;
- `final: de-out`.

DNS hijack на RU Entry намеренно не выполняется: DNS проходит через туннель и обрабатывается на exit-ноде.

## Основные файлы

```text
server.py          FastAPI API, users, admin, subscriptions
render.py          генерация sing-box-конфигов всех enabled-нод
deploy.py          local/SSH deploy
links.py           VLESS/HY2 URI и subscription URL
subscriptions.py   subscription headers и Happ routing
stats.py           SQLite storage, агрегаты и leak detection
stats_collector.py journal collector для local/SSH нод
config.py          development/production пути
templates/index.html
requirements.txt
```

Runtime-файлы:

```text
users.json
base.json
client-routing.json
```

Они не хранятся в Git.

## `base.json`

`base.json` содержит инфраструктурную конфигурацию:

```text
panel
nodes
  <node-name>
    enabled
    publish
    role
    deploy
    meta
    reality
    hy2
tunnel
routing
```

Пример общих параметров ноды:

```json
{
  "enabled": true,
  "publish": true,
  "role": "exit",
  "deploy": {
    "mode": "ssh",
    "env_prefix": "DE2"
  },
  "meta": {
    "location": "DE2"
  },
  "reality": {
    "domain": "<node-domain>",
    "listen_port": 443,
    "server_name": "<handshake-host>",
    "private_key": "<private-key>",
    "public_key": "<public-key>",
    "short_id": "<short-id>"
  },
  "hy2": {
    "domain": "<node-domain>",
    "listen_port": 8443,
    "certificate_path": "<certificate-path>",
    "key_path": "<key-path>"
  }
}
```

### Deploy mode

Локальная нода:

```json
"deploy": {
  "mode": "local"
}
```

Удалённая нода:

```json
"deploy": {
  "mode": "ssh",
  "env_prefix": "DE2"
}
```

Опционально можно переопределить:

```json
"remote_temp_file": "/tmp/vpn-manager-config.new.json",
"remote_helper": "/usr/local/sbin/deploy-sing-box-config"
```

В текущей реализации допускается не более одной `local`-ноды.

## Добавление новой ноды

Для новой exit-ноды обычно достаточно:

1. добавить её в `base.json`;
2. указать `role: "exit"`;
3. заполнить Reality/HY2;
4. выбрать `deploy.mode`;
5. для SSH-ноды добавить переменные окружения;
6. установить `publish: true`, если нода должна появиться в подписках.

После этого Python-код менять не требуется.

Render автоматически создаст:

```text
/tmp/<node-name>-config.new.json
```

а subscription автоматически получит VLESS + HY2 для новой `publish`-ноды.

## Подписки

Пользователь получает один URL:

```text
https://<panel-host>:<port>/sub/<token>
```

В подписку попадают только ноды, у которых одновременно:

```json
"enabled": true,
"publish": true
```

Для каждой такой ноды добавляются:

```text
VLESS Reality
Hysteria2
```

### Happ routing

Для Happ сервер дополнительно отдаёт routing profile через HTTP header `routing`:

```text
happ://routing/add/<base64-json>
```

Также включается автообновление подписки:

```text
subscription-auto-update-open-enable: 1
```

Интервал задаётся в `client-routing.json`:

```json
"update_interval_hours": 24
```

`client-routing.json` читается при каждом запросе `/sub/...`, поэтому его изменения не требуют рестарта `vpn-manager`.

## Development

По умолчанию:

```text
ENV=development
```

Используются:

```text
./users.json
./base.json
./client-routing.json
./rendered/<node-name>-config.json
```

Проверка Python:

```bash
python -m py_compile render.py deploy.py server.py links.py subscriptions.py config.py
```

Рендер:

```bash
python render.py
```

Пример:

```text
Generated de: .../rendered/de-config.json
Generated de2: .../rendered/de2-config.json
Generated ru: .../rendered/ru-config.json
```

В development `render.py` только создаёт файлы и не применяет их к production.

## Production

Основные runtime-файлы:

```text
/opt/vpn-manager/users.json
/opt/vpn-manager/base.json
/opt/vpn-manager/client-routing.json
/var/lib/vpn-manager/stats.db
/etc/vpn-manager.env
```

Сгенерированные конфиги:

```text
/tmp/<node-name>-config.new.json
```

В `vpn-manager.service`:

```ini
[Service]
Environment="ENV=production"
EnvironmentFile=/etc/vpn-manager.env
```

## SSH deploy

Для удалённой ноды используются:

```ini
<PREFIX>_SSH_HOST=<host>
<PREFIX>_SSH_USER=<user>
<PREFIX>_SSH_KEY=<private-key-path>
```

Например при:

```json
"env_prefix": "DE2"
```

нужны:

```ini
DE2_SSH_HOST=<host>
DE2_SSH_USER=<user>
DE2_SSH_KEY=<key-path>
```

Если `env_prefix` не задан, он формируется из имени ноды: upper-case, `-` заменяется на `_`.

Рекомендуемые права:

```bash
sudo chown root:root /etc/vpn-manager.env
sudo chmod 600 /etc/vpn-manager.env
```

## Sudoers

FastAPI-сервис работает от непривилегированного пользователя и вызывает `deploy.py` через `sudo`.

Пример:

```sudoers
<service-user> ALL=(root) NOPASSWD: /opt/vpn-manager/venv/bin/python /opt/vpn-manager/deploy.py
```

На удалённых нодах SSH-пользователю разрешается запуск helper:

```sudoers
<ssh-user> ALL=(root) NOPASSWD: /usr/local/sbin/deploy-sing-box-config
```

Remote helper должен проверять новый конфиг, применять его, перезапускать `sing-box` и выполнять локальный rollback при ошибке.

## Изменение пользователей

При создании, удалении, enable/disable пользователя:

```text
API request
    ↓
users.json
    ↓
render.py
    ↓
/tmp/<node>-config.new.json
    ↓
deploy.py
    ↓
remote nodes
    ↓
local node
```

Перед изменением сохраняется предыдущая версия users-state.

Если render/deploy падает:

1. восстанавливается старый `users.json`;
2. выполняется повторный render/deploy старой конфигурации;
3. если rollback тоже падает, API возвращает отдельную ошибку rollback.

## Порядок deploy

`deploy.py` делит enabled-ноды по `deploy.mode`:

```text
ssh   → remote nodes
local → local node
```

Сначала последовательно применяются удалённые ноды, затем локальная control-plane нода.

Если remote deploy падает, локальная нода не изменяется.

При нескольких remote-нодах весь deploy не является одной атомарной транзакцией: ноды, успешно обновлённые до сбоя следующей ноды, уже могут содержать новый конфиг. API rollback затем повторно применяет предыдущую пользовательскую конфигурацию.

## Ручной render на production

```bash
cd /opt/vpn-manager

sudo ENV=production \
  /opt/vpn-manager/venv/bin/python render.py
```

Проверка результатов:

```bash
ls -lh /tmp/*-config.new.json
```

Проверка всех конфигов:

```bash
for f in /tmp/*-config.new.json; do
  echo "== $f =="
  sudo sing-box check -c "$f" || break
done
```

## Ручной deploy

```bash
sudo /opt/vpn-manager/venv/bin/python \
  /opt/vpn-manager/deploy.py
```

Успешное завершение:

```text
ALL NODES DEPLOYED
```

`deploy.py` сам выставляет production environment по умолчанию.

## Обновление production

```bash
cd /opt/vpn-manager
git pull

sudo systemctl restart vpn-manager
sudo systemctl status vpn-manager --no-pager
```

`base.json`, `users.json` и `client-routing.json` не приезжают из Git. Если менялась их структура, production-копии обновляются отдельно.

## Логи и диагностика

Панель:

```bash
sudo journalctl -u vpn-manager -n 100 --no-pager
```

Локальный `sing-box`:

```bash
sudo journalctl -u sing-box -n 100 --no-pager
```

Удалённый `sing-box`:

```bash
ssh <user>@<host>
sudo journalctl -u sing-box -n 100 --no-pager
```

Проверка DNS hijack на exit:

```bash
sudo tcpdump -nn -i eth0 'host 1.1.1.1 and (udp port 53 or tcp port 443)'
```

При нормальной работе upstream DNS идёт к `1.1.1.1` по HTTPS/TCP 443, а клиентский UDP/53 не выпускается наружу как обычный DNS-запрос.

## Статистика активности

Статистика собирается отдельным процессом `stats_collector.py`. Он читает journal `sing-box` локальной ноды напрямую, а удалённых нод — через существующие SSH-подключения из `base.json` + `/etc/vpn-manager.env`.

Для VLESS и Hysteria2 в server-side users автоматически добавляется поле `name`. Благодаря этому collector связывает source IP с конкретным пользователем. Инфраструктурный RU → DE tunnel получает служебное имя `__ru_tunnel` и в пользовательскую статистику не попадает.

Хранение:

```text
/var/lib/vpn-manager/stats.db
```

SQLite содержит:

- `activity_ips` — агрегированная активность `user + node + network + protocol`;
- `usage_hourly` — количество inbound connections по часам;
- `abuse_state` — текущий уровень leak detection;
- `security_events` — переходы в warning/critical.

IPv4 считается отдельным адресом, IPv6 нормализуется до `/64`. Leak detection использует окно 5 минут:

```text
0..7 active networks  -> normal
8..9 active networks  -> warning
10+ active networks   -> critical
```

Автоматической блокировки нет: панель только подсвечивает подозрительную активность, после чего пользователя можно отключить вручную.

### Доступ collector к journal

Локальный collector запускается от root, поэтому локальный journal доступен без дополнительных прав. На каждой SSH-ноде пользователь из `<PREFIX>_SSH_USER` должен иметь право читать system journal:

```bash
sudo usermod -aG systemd-journal <ssh-user>
```

Новая SSH-сессия collector автоматически подхватит новую группу. Проверка с control-plane:

```bash
ssh <ssh-user>@<host> \
  /usr/bin/journalctl -u sing-box -n 3 -o cat --no-pager
```

Если конкретная нода использует другое имя systemd unit, в `base.json` можно задать:

```json
"stats": {
  "enabled": true,
  "service": "sing-box-custom"
}
```

По умолчанию статистика включена для всех enabled-нод и используется service `sing-box`. Для исключения ноды:

```json
"stats": {
  "enabled": false
}
```

### Systemd collector

Создать каталог БД так, чтобы root collector и пользователь FastAPI имели доступ к SQLite/WAL-файлам:

```bash
SERVICE_USER=$(systemctl show -p User --value vpn-manager)
SERVICE_GROUP=$(id -gn "$SERVICE_USER")

sudo install -d \
  -o root \
  -g "$SERVICE_GROUP" \
  -m 2770 \
  /var/lib/vpn-manager
```

Unit `/etc/systemd/system/vpn-manager-stats.service`:

```ini
[Unit]
Description=VPN Manager statistics collector
After=network-online.target sing-box.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/vpn-manager
Environment="ENV=production"
EnvironmentFile=/etc/vpn-manager.env
ExecStart=/opt/vpn-manager/venv/bin/python /opt/vpn-manager/stats_collector.py
Restart=always
RestartSec=5
UMask=0007

[Install]
WantedBy=multi-user.target
```

Запуск:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vpn-manager-stats
sudo systemctl status vpn-manager-stats --no-pager
```

Логи collector:

```bash
sudo journalctl -u vpn-manager-stats -f
```

После добавления новой ноды в `base.json` collector нужно перезапустить, чтобы он открыл новый journal stream:

```bash
sudo systemctl restart vpn-manager-stats
```

## Web API

```text
GET    /admin
GET    /api/users
GET    /api/stats/overview
GET    /api/stats/users/{name}
POST   /api/user/create
DELETE /api/user/{name}
POST   /api/users/{name}/enable
POST   /api/users/{name}/disable
GET    /sub/{token}
```

## Что не хранится в Git

`.gitignore` исключает:

```text
users.json
base.json
client-routing.json
rendered/
.env
TODO.md
```

Также в Git не должны попадать:

```text
/etc/vpn-manager.env
SSH private keys
Reality private keys
subscription tokens
HY2 passwords
production secrets
```

## Временные файлы

Production render создаёт:

```text
/tmp/<node-name>-config.new.json
```

Не стоит вручную создавать эти файлы через `sudo` и оставлять владельцем `root`, если `vpn-manager` должен перезаписывать их от непривилегированного пользователя.

Очистка:

```bash
sudo rm -f /tmp/*-config.new.json
```

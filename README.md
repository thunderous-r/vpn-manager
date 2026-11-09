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
- роли `exit` и `relay` (и совместимость с прежней `ru-entry`);
- локальный и SSH-deploy конфигураций sing-box для exit-нод;
- единая subscription-ссылка пользователя;
- автоматическая публикация профилей со всех `publish`-нод;
- Happ и INCY routing profiles;
- автообновление подписки Happ;
- DNS hijack + DoH на exit-нодах;
- автоматический render/deploy при изменении пользователей;
- проверка конфигурации и rollback при ошибке;
- централизованная статистика активности пользователей по нодам, протоколам и source IP/network;
- leak alerts по числу одновременно активных сетей.


## Архитектура

Панель управления (control-plane) работает на **DE1**. Топология и параметры узлов описаны в локальном `base.json`.

- **DE1** — основной `exit`, локальный sing-box и выход в интернет.
- **DE2** — дополнительный `exit`, sing-box обновляется по SSH.
- **RU Relay** — входной L4 TCP/UDP relay: Nginx Stream передаёт зашифрованный трафик на DE1, не завершая VLESS Reality или Hysteria2.

```text
                         VPN client
                             │
             ┌───────────────┼─────────────────┐
             │               │                 │
             ▼               ▼                 ▼
         DE1:443/TCP      DE2 exit        RU Relay:8444/TCP
         DE1:8443/UDP                    RU Relay:18443/UDP
             │                                  │
             │                                  ▼
             │                              nginx stream
             │                                  │
             ◄──────────────────────────────────┘
             ▼
       DE1 sing-box
        exit / DNS
             │
             ▼
          Internet
```

Прямые подключения к DE1/DE2 остаются самостоятельными. RU Relay не имеет собственного sing-box: авторизация пользователей, TLS/Reality/HY2 и выходной IP определяются DE1. На RU нет локальных правил `direct`, GeoIP/Geosite или DNS hijack VPN-клиентов.

**Граница ответственности:** VPN Manager публикует конфигурации relay-профилей и обновляет sing-box на exit-нодах, **но не управляет Nginx Stream на RU**. Его конфигурация и systemd-unit настраиваются отдельно.

Важно: L4 relay сохраняет зашифрованный клиентский протокол, но DE1 видит сетевой адрес RU как источник проксированного соединения. Реальный source IP VPN-клиента на DE1 таким способом не передаётся; это следует учитывать при анализе статистики по IP и leak alerts.

Роль `ru-entry` и связанная split-routing логика сохранены в коде для обратной совместимости, но в текущей рабочей схеме не используются. Render/deploy не привязаны к фиксированному числу exit-нод.

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


### `role: "relay"`

Relay-нода не генерирует sing-box-конфиг и пропускается `deploy.py`. В `base.json` она задаёт:

- `role: "relay"` и `relay_to` — имя включённой ноды с ролью `exit`;
- собственные `reality.domain` / `reality.listen_port` и `hy2.domain` / `hy2.listen_port` — адрес и порты входа для клиентов;
- `meta.location` — отображаемое имя профилей;
- `publish` — включение в подписки.

Ключи Reality (`public_key`, `short_id`, `server_name`), HY2 SNI и учётные данные пользователей при построении ссылки берутся с `relay_to`. Адрес и порт в ссылке остаются от relay-ноды. Поэтому на входном relay не нужны собственные TLS/Reality-ключи для обработки клиентских VPN-подключений.

Пример **Nginx Stream** на RU (часть самостоятельного Nginx-конфига, не генерируется Python):

```nginx
stream {
    server {
        listen 0.0.0.0:8444;
        proxy_pass DE1_IPV4:443;
        proxy_connect_timeout 5s;
        proxy_timeout 1h;
    }

    server {
        listen 0.0.0.0:18443 udp reuseport;
        proxy_pass DE1_IPV4:8443;
        proxy_timeout 10m;
    }
}
```

Заменить `DE1_IPV4` на актуальный IPv4 DE1. В рабочей установке используется отдельный `vpn-manager-stream-relay.service` с конфигом `/etc/nginx/vpn-manager-stream.conf`. Этот экземпляр Nginx проверяется и перезапускается независимо от VPN Manager:

```bash
sudo nginx -t -c /etc/nginx/vpn-manager-stream.conf
sudo systemctl status vpn-manager-stream-relay --no-pager
```

Изменение адреса или порта backend требует отдельного обновления Nginx; изменение клиентского адреса/порта — обновления `base.json` и подписок.

### `role: "ru-entry"` (legacy)

Старый режим с локальными VLESS Reality/HY2 inbounds, `direct`, VLESS outbound `de-out`, GeoIP/Geosite rule sets и `final: de-out` всё ещё поддерживается генератором, но не используется на RU после перехода на L4 relay.

Если на exit-ноде задано `"accept_legacy_tunnel": true`, она также получает inbound `ru-tunnel` для старой схемы. Для чистого L4 relay он не требуется.

## Основные файлы

```text
server.py          FastAPI API, users, admin, subscriptions
render.py          генерация sing-box-конфигов exit/legacy-нод; пропуск relay
deploy.py          local/SSH deploy sing-box, пропуск relay
links.py           VLESS/HY2 URI, backend-параметры relay, subscription URL
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
    relay_to  # для relay
    deploy    # для exit/legacy
    stats
    meta
    reality
    hy2
tunnel  # legacy
routing # legacy
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

### Exit-нода

Для новой exit-ноды:

1. Добавить её в `base.json` с `role: "exit"` и Reality/HY2-параметрами.
2. Указать `deploy.mode` (`local` или `ssh`) и переменные окружения SSH, если необходимо.
3. Установить `publish: true`, чтобы нода вошла в подписки.

Для включённой exit-ноды render создаёт `/tmp/<node-name>-config.new.json`. Далее `deploy.py` проверяет и применяет sing-box-конфиг.

### L4 relay-нода

В текущем развёртывании опубликованная входная нода называется `ru-relay`. Минимальная структура её записи:

```json
{
  "enabled": true,
  "publish": true,
  "role": "relay",
  "relay_to": "de",
  "meta": {"location": "RU→DE Relay"},
  "reality": {
    "domain": "ru.dntun.com",
    "listen_port": 8444
  },
  "hy2": {
    "domain": "ru.dntun.com",
    "listen_port": 18443
  },
  "stats": {"enabled": false}
}
```

Это **пример содержимого `nodes.ru-relay`**, а не всего файла `base.json`. Имя `de` должно соответствовать существующему ключу exit-ноды в `nodes`. У relay отсутствует обязательный `deploy`: Python не устанавливает Nginx-конфигурацию.

Старую запись `nodes.ru` можно сохранить для отката с `publish: false` и `role: "relay"`, если у неё тоже есть корректный `relay_to`. Если она остаётся `enabled: true`, для неё также следует задать `stats.enabled: false`. Для восстановления устаревших VLESS/HY2-ссылок одного изменения `publish` недостаточно: тогда понадобится вернуть и старую схему sing-box.

Перед публикацией проверить доступность обоих портов relay и корректность ключей/SNI backend. У клиента в подписке изменяются адрес/порт входа, но не backend-учётные данные.

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

Для `relay` ссылки указывают на входной домен/порт RU, а Reality public key, short ID, SNI и HY2 SNI берутся с указанного exit backend. В подписку **не попадают** ноды с `publish: false`, даже когда они `enabled: true`. Изменения `base.json` учитываются при следующем запросе подписки.

### Client routing

Для поддерживаемых клиентов сервер дополнительно отдаёт routing profile через HTTP header `routing`:

Happ:

```text
happ://routing/add/<base64-json>
```

Также включается автообновление подписки:

```text
subscription-auto-update-open-enable: 1
```

INCY:

```text
incy://routing/add/<base64-json>
```

Happ и INCY используют общий routing profile из `client-routing.json`.

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
```

В development `render.py` только создаёт файлы и не применяет их к production. Для relay-ноды выходной sing-box JSON не создаётся.

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

Для удалённой **exit-ноды**, управляющейся через SSH deploy, используются:

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

При создании, удалении и enable/disable пользователя выполняются:

```text
API request
    ↓
users.json
    ↓
render.py
    ├── exit/legacy → sing-box config
    └── relay → skip
    ↓
deploy.py
    ├── SSH exit-ноды
    ├── local exit-нода (control-plane, последней)
    └── relay → skip
```

Учётные данные пользователей на exit-нодах общие; на RU Relay пользовательская аутентификация выполняется DE1.

Перед изменением сохраняется предыдущая версия `users.json`. Если render/deploy падает, приложение восстанавливает `users.json` и повторяет применение предыдущей конфигурации; сбой rollback возвращается как отдельная ошибка.

## Порядок deploy

`deploy.py` сначала **исключает `role: "relay"`**, затем делит оставшиеся enabled-ноды по `deploy.mode`:

```text
ssh   → remote exit nodes
local → control-plane exit node
relay → skipped
```

Удалённые ноды обновляются последовательно до локальной. При сбое remote deploy локальная нода ещё не меняется. Обновление нескольких удалённых нод не атомарно; rollback API повторно применяет предыдущее состояние пользователей, если это возможно.

`deploy.py` не заменяет Nginx Stream-конфиг, не перезагружает `vpn-manager-stream-relay.service` и не должен запускать sing-box на RU.

## Ручной render на production

```bash
cd /opt/vpn-manager

# Используйте сервисного пользователя, чтобы не менять владельца /tmp/*-config.new.json
SERVICE_USER=$(systemctl show -p User --value vpn-manager)
sudo -u "$SERVICE_USER" env ENV=production \
  /opt/vpn-manager/venv/bin/python render.py
```

Проверка результатов:

```bash
ls -lh /tmp/*-config.new.json
```

Старые конфиги relay/legacy могут оставаться в `/tmp` после смены роли ноды; наличие файла само по себе не означает, что он будет развёрнут.

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

Локальный `sing-box` на DE1:

```bash
sudo journalctl -u sing-box -n 100 --no-pager
```

Удалённый `sing-box` на DE2 (и других exit-нодах):

```bash
ssh <user>@<host>
sudo journalctl -u sing-box -n 100 --no-pager
```

Relay на RU (без sing-box):

```bash
sudo systemctl status vpn-manager-stream-relay --no-pager
sudo journalctl -u vpn-manager-stream-relay -n 100 --no-pager
sudo ss -lntup | grep -E ':(8444|18443)\\b'
```

Проверка DNS hijack на exit:

```bash
sudo tcpdump -nn -i eth0 'host 1.1.1.1 and (udp port 53 or tcp port 443)'
```

При нормальной работе upstream DNS идёт к `1.1.1.1` по HTTPS/TCP 443, а клиентский UDP/53 не выпускается наружу как обычный DNS-запрос.

## Статистика активности

Статистика собирается отдельным процессом `stats_collector.py`. Он читает journal `sing-box` локальной ноды напрямую, а удалённых нод — через существующие SSH-подключения из `base.json` + `/etc/vpn-manager.env`.

Для VLESS и Hysteria2 в server-side users автоматически добавляется поле `name`. Благодаря этому collector связывает source IP с конкретным пользователем. Служебный пользователь `__ru_tunnel` относится к legacy VLESS-туннелю и не используется в текущем Nginx Stream relay.

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

По умолчанию статистика включена для **всех** enabled-нод и использует service `sing-box` — сам collector пока не определяет роль `relay` автоматически. Для каждой relay-ноды статистику следует выключать явно:

```json
"stats": {
  "enabled": false
}
```

Иначе collector попробует читать journal `sing-box` на RU, где он больше не работает. На DE1 при relay-подключениях исходным сетевым адресом будет IP RU, а не реального клиента: при подсчёте активных IP/сетей и leak alerts этот тип трафика нельзя интерпретировать как обычное прямое подключение к DE1.

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
*.before-*
*.orig
*.rej
```

Также проверяйте перед `git add` непокрытые шаблонами резервные копии (например `base.json.bak*`) и временные каталоги: `git status --short` и `git check-ignore <path>`.

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

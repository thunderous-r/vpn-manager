# VPN Manager

> Проект предназначен для личного использования и небольшого числа пользователей, не является коммерческой VPN-платформой.

VPN Manager — простая панель управления пользователями, подписками и конфигурацией sing-box на базе FastAPI.

Поддерживаются:

- VLESS Reality;
- Hysteria2;
- несколько VPN-узлов;
- единая ссылка подписки;
- включение и отключение пользователей;
- автоматический рендер и применение конфигурации;
- проверка конфигурации и откат при ошибке.

## Архитектура

В текущей конфигурации используются два узла:

- **DE** — основной VPN-узел;
- **RU** — экспериментальная точка входа.

При подключении к RU-узлу часть трафика направляется напрямую, а остальной трафик передаётся через туннель на DE-узел.

Один пользователь получает четыре профиля подключения:

~~~text
DE VLESS Reality
DE Hysteria2
RU Experimental VLESS Reality
RU Experimental Hysteria2
~~~

## Структура окружений

### Development

Локальная среда используется для разработки и проверки интерфейса, API, подписок и рендера конфигурации.

~~~text
users.json
base.json
rendered/de-config.json
rendered/ru-config.json
~~~

В development-режиме:

- не используется `sudo`;
- не вызывается `systemctl`;
- конфигурация sing-box не применяется;
- production-серверы не затрагиваются.

### Production

Основные файлы:

~~~text
/opt/vpn-manager/users.json
/opt/vpn-manager/base.json

/tmp/de-config.new.json
/tmp/ru-config.new.json

/etc/vpn-manager.env
~~~

`users.json` содержит пользователей и их ключи.

`base.json` содержит параметры узлов, протоколов, туннеля и маршрутизации.

## Production-настройки

Параметры подключения к удалённому узлу хранятся вне Git:

~~~ini
RU_SSH_HOST=<ru-node-address>
RU_SSH_USER=<ssh-user>
RU_SSH_KEY=/root/.ssh/vpn-manager-ru
~~~

Файл настроек:

~~~text
/etc/vpn-manager.env
~~~

Рекомендуемые права:

~~~bash
sudo chown root:root /etc/vpn-manager.env
sudo chmod 600 /etc/vpn-manager.env
~~~

В systemd-unit панели должен быть подключён файл окружения:

~~~ini
[Service]
Environment="ENV=production"
EnvironmentFile=/etc/vpn-manager.env
~~~

## Sudoers

Панель запускается от непривилегированного системного пользователя, но для применения конфигурации вызывает `deploy.py` через `sudo`.

Пример правила на основном сервере:

~~~sudoers
<service-user> ALL=(root) NOPASSWD: /opt/vpn-manager/venv/bin/python3 /opt/vpn-manager/deploy.py
~~~

`<service-user>` — системный пользователь, от которого запускается `vpn-manager.service`.

На удалённом узле разрешён запуск отдельного deployment-helper:

~~~sudoers
<ssh-user> ALL=(root) NOPASSWD: /usr/local/sbin/deploy-sing-box-config
~~~

## Работа с пользователями

При создании, удалении, включении или отключении пользователя выполняется следующий процесс:

~~~text
users.json
    ↓
render.py
    ↓
DE config + RU config
    ↓
deploy.py
    ↓
RU deploy
    ↓
DE deploy
~~~

Сначала обновляется RU-узел.

Если RU-узел не принял конфигурацию, конфигурация DE-узла не изменяется.

Перед применением конфигурации выполняется проверка через:

~~~bash
sing-box check
~~~

При ошибке запуска выполняется откат к предыдущей конфигурации.

## Ручной рендер

На production-сервере:

~~~bash
cd /opt/vpn-manager

sudo ENV=production \
  /opt/vpn-manager/venv/bin/python render.py
~~~

Результат:

~~~text
/tmp/de-config.new.json
/tmp/ru-config.new.json
~~~

Проверка DE-конфига:

~~~bash
sudo sing-box check -c /tmp/de-config.new.json
~~~

## Ручной deploy

~~~bash
sudo /opt/vpn-manager/venv/bin/python \
  /opt/vpn-manager/deploy.py
~~~

`deploy.py` всегда использует production-пути и выполняет:

1. проверку наличия сгенерированных конфигов;
2. загрузку RU-конфига;
3. проверку и применение RU-конфига;
4. применение DE-конфига;
5. откат при ошибке.

## Обновление production

~~~bash
cd /opt/vpn-manager
git pull

sudo systemctl restart vpn-manager
sudo systemctl status vpn-manager --no-pager
~~~

Если менялась структура `base.json`, production-файл необходимо обновить вручную до запуска панели.

## Проверка журналов

Журнал панели:

~~~bash
sudo journalctl -u vpn-manager -n 50 --no-pager
~~~

Журнал локального sing-box:

~~~bash
sudo journalctl -u sing-box -n 50 --no-pager
~~~

Журнал sing-box на удалённом узле:

~~~bash
ssh <ssh-user>@<ru-node-address>
sudo journalctl -u sing-box -n 50 --no-pager
~~~

## Что не хранится в Git

В репозиторий не должны попадать:

~~~text
users.json
base.json
rendered/
production IP-адреса
SSH private keys
/etc/vpn-manager.env
~~~

## Временные файлы

Панель рендерит конфиги от непривилегированного системного пользователя.

Не следует вручную создавать файлы в `/tmp` через `sudo` и оставлять их владельцем `root`, иначе панель не сможет их перезаписать.

При необходимости временные файлы можно удалить:

~~~bash
sudo rm -f \
  /tmp/de-config.new.json \
  /tmp/ru-config.new.json
~~~

После этого панель создаст их заново с корректным владельцем.
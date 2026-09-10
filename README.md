# File Share

Минимальный self-hosted файлообменник: загрузил файл — получил короткую ссылку на скачивание.
Один файл на Python (только стандартная библиотека), без БД и внешних зависимостей.

## Возможности

- Загрузка файла (drag & drop или выбор) до **500 МБ**
- Уникальная ссылка вида `https://<host>/d/<token>`
- Список загруженных файлов: размер, дата, копирование ссылки, удаление
- Автоочистка: файлы хранятся **7 дней**
- Тёмный адаптивный интерфейс

## Запуск

### Локально

```bash
cp .env.example .env
python3 app.py
```

Откройте http://127.0.0.1:8081/.

### Docker

```bash
docker compose up -d --build
```

### Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `HOST` | `0.0.0.0` | адрес прослушивания |
| `PORT` | `8081` | порт |
| `UPLOAD_DIR` | `/data` | каталог для файлов и `.meta.json` |
| `AUTH_USER` | `admin` | логин для загрузки/списка/удаления |
| `AUTH_PASSWORD` | _(пусто)_ | пароль; **пусто = авторизация выключена** |

## Авторизация

Если задан `AUTH_PASSWORD`, HTTP Basic-авторизация защищает загрузку, список и удаление
(`/`, `/upload`, `/api/files`, `/api/delete/*`). Скачивание по ссылке `/d/<token>` остаётся
**публичным**, чтобы получатель мог открыть ссылку без пароля.

Проверка:

```bash
curl -i http://127.0.0.1:8081/            # 401
curl -u admin:secret http://127.0.0.1:8081/   # 200
```

За обратным прокси `HOST` зависит от того, где стоит прокси:

- прокси на **том же** хосте — `HOST=127.0.0.1` (сервис не торчит в сеть);
- прокси на **другом** хосте (как в проде: Caddy на CT 108, приложение на zoopark) —
  `HOST=0.0.0.0` или LAN-IP хоста, иначе прокси получит `connection refused`.

## HTTP API

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/` | страница загрузки и список файлов |
| `POST` | `/upload` | загрузка файла (multipart/form-data, поле `file`) |
| `GET` | `/api/files` | список файлов (JSON) |
| `GET` | `/d/<token>` | скачивание файла |
| `DELETE` | `/api/delete/<token>` | удаление файла |

## Деплой (zoopark)

Сервис хостится на zoopark (192.168.0.217) под systemd, публикуется через Caddy на
`files.ivanwebdeveloper.ru` (CT 108):

```bash
sudo mkdir -p /opt/file-share && sudo chown bvv:bvv /opt/file-share
rsync -a --exclude .git --exclude data ./ bvv@192.168.0.217:/opt/file-share/
# /opt/file-share/.env: HOST=0.0.0.0, PORT=8081, UPLOAD_DIR=/opt/file-share/data, AUTH_USER=..., AUTH_PASSWORD=...
ssh bvv@192.168.0.217 'sudo systemctl enable --now file-share'
```

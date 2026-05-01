# Selam gang

Flask ve dependencyleri yüklemek için

```bash
pip install -e .
```

Dili (lang klasöründeki) yüklemek için

```bash
pip install -e ./lang
```

## Docker (PostgreSQL)

Projede app ve test için iki ayrı PostgreSQL container var.

Önce `.env.example` dosyasını kopyala:

```bash
cp .env.example .env
```

### Database Connection

App database:

- Username: `d20`
- Password: `d20`
- Host: `localhost`
- Port: `5432`
- Database: `d20`
- URL: `postgresql://d20:d20@localhost:5432/d20`

Test database:

- Username: `d20`
- Password: `d20`
- Host: `localhost`
- Port: `5433`
- Database: `d20_test`
- URL: `postgresql://d20:d20@localhost:5433/d20_test`

```bash
docker compose up -d
```

`.env` (veya `.env.example`):

```env
POSTGRES_USER=d20
POSTGRES_PASSWORD=d20
POSTGRES_DB=d20
POSTGRES_TEST_DB=d20_test

DATABASE_URL=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:5432/${POSTGRES_DB}
TEST_DATABASE_URL=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:5433/${POSTGRES_TEST_DB}
```

## Init

Uygulamayı çalıştırmadan önce dbyi init ve seed yapıyoruz

```bash
flask --app d20 init-db && flask --app d20 seed
```

Ya da ayrı ayrı:

```bash
flask --app d20 init-db
flask --app d20 seed
```

`init-db` komutu `schema.sql`ı çalıştırıyor `seed` de örnek veri ekliyor, her yeni feature içın `seed` fonksiyonuyla bir örnek veri eklemek lazım. Örnek oyun isimleri de burda yaratılıyor.

## Run

```bash
flask --app d20 run --debug
```

> Debug modda çalıştırınca exceptionlar daha net gözüküyor, yoksa şart değil.

## Test

Pytest ile testleri çalıştırmak için:

```bash
pytest
```

Not: Testlerin çoğu PostgreSQL gerektirir ve sadece `--pg` ile çalışır.

Önce test DB container'ını ayağa kaldır:

```bash
docker compose up -d db_test
```

Sonra PostgreSQL testlerini çalıştır:

```bash
pytest --pg
```

Farklı bir test veritabanı URL'i kullanacaksan:

```bash
TEST_DATABASE_URL=postgresql://d20:d20@localhost:5433/d20_test pytest --pg
```

## Kullandığımız stack
Web frameworkü olarak Flask kullandık
Stylign (CSS) için Bootstrap diye bir library var
Bazı gereken dynamic/interaktif yerler için htmx 

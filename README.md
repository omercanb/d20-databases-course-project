# CS 353 Project Group 13
## People
Ahmet Utku Özdoğru
Berkay Demirçin
Ceyhun Deniz Keleş
Ege Şeşen
Ömer Can Baykara
# Setup

To install Flask and its dependencies:
```bash
pip install -e .
```

To install the language package (located in the `lang` directory):
```bash
pip install -e ./lang
```

## Docker (PostgreSQL)

The project uses two separate PostgreSQL containers — one for the application and one for testing.

Begin by copying the example environment file:
```bash
cp .env.example .env
```

### Database Connection

Application database:
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

Start the containers:
```bash
docker compose up -d
```

`.env` (or `.env.example`):
```env
POSTGRES_USER=d20
POSTGRES_PASSWORD=d20
POSTGRES_DB=d20
POSTGRES_TEST_DB=d20_test
DATABASE_URL=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:5432/${POSTGRES_DB}
TEST_DATABASE_URL=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:5433/${POSTGRES_TEST_DB}
# MinIO (game image upload)
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=game-images
MINIO_SECURE=false
```

## MinIO

Game cover images are stored in MinIO.

- API endpoint: `http://localhost:9000`
- Console: `http://localhost:9001`
- Bucket: `game-images`

Running `docker compose up -d` will also start the MinIO service.

## Initialization

Before running the application, the database must be initialized and seeded:
```bash
flask --app d20 init-db && flask --app d20 seed
```

Or run each step separately:
```bash
flask --app d20 init-db
flask --app d20 seed
```

`init-db` executes `schema.sql` to set up the database schema. `seed` populates it with sample data. Each new feature should include at least one corresponding entry in the `seed` function. Sample game names are also generated at this stage.

## Running

```bash
flask --app d20 run --debug
```

> Debug mode provides more detailed exception output and is recommended during development, though not required.

## Testing

To run the test suite with pytest:
```bash
pytest
```

> **Note:** Most tests require PostgreSQL and will only run with the `--pg` flag.

First, start the test database container:
```bash
docker compose up -d db_test
```

Then run the PostgreSQL tests:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest --pg
```

To use a custom test database URL:
```bash
TEST_DATABASE_URL=postgresql://d20:d20@localhost:5433/d20_test PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest --pg
```

## Stack

- **Flask** — web framework
- **Bootstrap** — CSS styling
- **htmx** — dynamic and interactive UI components

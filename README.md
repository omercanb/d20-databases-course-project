# Selam gang

Flask ve dependencyleri yüklemek için

```bash
pip install -e .
```

Dili (lang klasöründeki) yüklemek için

```bash
pip install -e ./lang
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

## Kullandığımız stack
Web frameworkü olarak Flask kullandık
Stylign (CSS) için Bootstrap diye bir library var
Bazı gereken dynamic/interaktif yerler için htmx 
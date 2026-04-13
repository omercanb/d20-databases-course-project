Selam gang,

Çalıştırmak için 
    flask -A d20 run --debug \
    (debug modda çalıştırınca exceptionlar daha net gözüküyor, yoksa şart değil)

Çalıştırmadan önce
     flask --app d20 init-db \
     flask --app d20 seed \
     ya da direkt birlikte \
        flask --app d20 init-db && flask --app d20 seed

    Bunlar şunu yapıyor, init-db schema.sql'ı runlıyor. seed de db'yi dolduruyor. Seed diye bir functionımız tanımlı, oraya yeni eklenen her feature için bir örnek veri koymak lazım. Oyunlar falan da burada yaratılıyor. Bu 'flask --app d20' da flaskin cli commandleri çalıştırma yöntemi ama biraz uzun yazması. Ondan burdan kopyalamak makul.




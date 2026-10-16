# WP-2A düzeltme doğrulaması

16 Ekim 2026. Python 3.11.15; OR-Tools 9.11.4210; Pydantic 2.14.1.

`requirements-lock.txt` boş bir geçici sanal ortama kuruldu. Bu ortamda:

- `python -m pytest -q tests`: 69 geçti.
- `ruff check core benchmarks tests`: geçti.
- `git diff --check`: geçti.
- Mk01 tekrar çalıştırması: referans 87, CP-SAT OPTIMAL 40, iki çizelgede 0 ihlal.
- Kaynak external checkout kodunda değişiklik yok.

Yeni regresyonlar: gerçek makine ve gerçekleşen süre, devam eden işin kalan
süresi ve kaynak işgali, büyük hazır olma zamanı, uygulanabilir/uygulanamaz sert
termin, duruşa çakışma ve duruş sınırına dokunma, alternatif makine, sabit işle
çelişen duruş, global kimlik/öncül/ilk hazır operasyon, orijinal senaryoya göre
bağımsız doğrulama, geçersiz veri reddi, girdi snapshot izolasyonu ve retrospektif
simülasyon etiketi. Yeni testler `tests/test_workshop_constraints.py` içindedir.

Bu turda on Brandimarte probleminin tamamı tekrar çalıştırılmadı; önceki toplu
rapor `benchmark-results.md` içinde korunur. Kaynak benchmark modeli değişmedi.
SQLite plan kaydı, yeni sipariş karşılaştırma servisi ve kullanıcı arayüzü
henüz bu testlerin kapsamına girmez. Commit veya push yapılmadı.

# Brandimarte yerel test raporu

16 Ekim 2026; kaynak commit d088a26582f5cb79c6b4f2ad94f68ac7c50878cb.

CP-SAT: OR-Tools 9.11.4210, seed=0, tek worker, örnek başına 10 saniye.
20 çizelgenin tümü bağımsız denetimden geçti: 0 ihlal. CP-SAT sonuçlarının
5 tanesi OPTIMAL, 5 tanesi FEASIBLE. 18 pytest testi ve Ruff kontrolü geçti.

| Problem | İş | Makine | Operasyon | Referans makespan | CP-SAT makespan | Alt sınır | Durum | CP-SAT saniye |
|---|---:|---:|---:|---:|---:|---:|---|---:|
| Mk01 | 10 | 6 | 55 | 87 | 40 | 40.0 | OPTIMAL | 0.0607 |
| Mk02 | 10 | 6 | 58 | 77 | 27 | 25.0 | FEASIBLE | 10.0006 |
| Mk03 | 15 | 8 | 150 | 597 | 204 | 204.0 | OPTIMAL | 2.142 |
| Mk04 | 15 | 8 | 90 | 226 | 60 | 60.0 | OPTIMAL | 0.3537 |
| Mk05 | 15 | 4 | 106 | 469 | 177 | 127.0 | FEASIBLE | 10.0003 |
| Mk06 | 10 | 10 | 150 | 220 | 63 | 33.0 | FEASIBLE | 10.0005 |
| Mk07 | 20 | 5 | 100 | 340 | 158 | 133.0 | FEASIBLE | 10.0005 |
| Mk08 | 20 | 10 | 225 | 2081 | 523 | 523.0 | OPTIMAL | 7.1704 |
| Mk09 | 20 | 10 | 240 | 1541 | 307 | 307.0 | OPTIMAL | 7.6291 |
| Mk10 | 20 | 15 | 240 | 1080 | 277 | 181.0 | FEASIBLE | 10.0006 |

## Mk01 gerçek çıktı izi

Dosyada ilk operasyon M1:5 veya M3:4 seçeneklerine sahiptir.
Aşağıdaki satırlar gerçek çalıştırmanın JSON çıktısından alınmıştır.
JSON kimlikleri 0 tabanlıdır; burada okuma kolaylığı için 1 tabanlı gösterilir.

| İş | Operasyon | Seçilen makine | Başlangıç | Bitiş |
|---|---|---|---:|---:|
| J1 | O1 | M1 | 9 | 14 |
| J1 | O2 | M5 | 14 | 17 |
| J1 | O3 | M3 | 21 | 25 |
| J1 | O4 | M1 | 25 | 26 |
| J1 | O5 | M3 | 29 | 30 |
| J1 | O6 | M6 | 32 | 38 |

Süreler benchmark birimidir. Statik, sürekli çalışma varsayımı geçerlidir.
Referans yöntem job-order/EFT, kaynak FIFO/SPT uygulaması değildir.
Bu sonuçlar yalnız FJSP hattını doğrular; yeni sipariş, termin, duruş ve Gemma henüz yok.

Platform: macOS-27.0.1-arm64-arm-64bit
Python: 3.11.15 (main, Mar  3 2026, 00:52:57) [Clang 21.0.0 (clang-2100.0.123.102)]

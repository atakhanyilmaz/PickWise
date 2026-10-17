# Yeni sipariş demosu — doğrulama

16 Ekim 2026. Tamamı sentetik demo; süreler dakika, t=0 referansı aynı.

Çalıştırma: `.venv/bin/python -m benchmarks.workshop_order_demo`.
Başlangıç planında tamamlanmış operasyon [0,3), devam eden operasyon [3,10)
korunur. Şimdi=5; devam eden işin kalan süresi 5. Bekleyen mevcut iş [10,15).

| Senaryo | Durum | Makespan | Yeni iş bitişi | Eski plandan geç biten mevcut iş | Terminini aşan iş | Toplam termin gecikmesi |
|---|---|---:|---:|---:|---:|---:|
| Tek makine | OPTIMAL | 25 | 20 | 1 | 1 | 5 |
| Alternatif makine | OPTIMAL | 17 | 17 | 0 | 0 | 0 |
| Tek makine + mevcut bitişleri koru | INFEASIBLE | — | — | — | — | — |

İlk senaryoda eski işin bitişi 15 → 25; müşteri termini 20 olduğundan plan
bitiş kayması 10, termin gecikmesi 5 dakikadır. Bunlar farklı metriklerdir.
Alternatif senaryoda yeni iş Torna 2'de [5,17); mevcut bekleyen iş [10,15) kalır.
Koruma senaryosunda yeni işi 20'ye yetiştirmek ve eski işi 15'te bitirmek aynı
makine üzerinde mümkün değildir. Başlangıç planı her durumda değişmez.

Doğrulama: 97 pytest testi geçti; Ruff ve git diff --check geçti. Yeni testler
snapshot yeniden doğrulama, başlangıç ve istek değişmezliği, fiilen başlamış
operasyonların korunması, alternatif makine, termin metrikleri, mevcut bitiş
koruması, uygulanamaz/UNKNOWN sonuçta karşılaştırma üretmeme, kaynak kimlikleri,
bozuk sipariş girdileri, JSON round-trip ve HTML/CSV dışa aktarımı kapsar.

Yumuşak terminler raporlanır; optimizasyon hedefi makespan'dir. SQLite onaylı
plan kaydı, gerçek takvim, Gemma ve Streamlit bu teslimde uygulanmamıştır.
Rapor dışa aktarımı üretim planına onay verildiği anlamına gelmez.

# 001 — Sabit kaynak checkout ve küçük FJSP adaptörü

Tarih: 2026-10-16

Kapsam: Atakan WP-1A, Brandimarte Mk01–Mk10 doğrulaması.

Kaynak depo uygulamamızın atası değil, bağımlılığıdır. Bu nedenle PickWise
origin adresine dokunmadan external/job_shop_benchmark altında ayrı checkout
kullanıyoruz. Checkout gitignore içindedir; scripts/fetch_upstream.sh sabit
commit'i yeniden getirir. Submodule seçilmedi; kurulum adımı README'de açıkça bulunur.

Kaynak commit: d088a26582f5cb79c6b4f2ad94f68ac7c50878cb.
Kaynak parser, JobShop nesneleri ve fjsp_cp_sat_model değiştirilmeden kullanılır.
Kendi katmanımız girdi doğrulama, çözücü ayarları, sonuç çıkarma, deterministik
referans yöntem, bağımsız çizelge doğrulama ve raporlamadan sorumludur.

Kaynak run_cp_sat.py, CP_SAT büyük harfli importlar kullanırken checkout klasörü
cp_sat adındadır. helper_functions.py ayrıca torch yükler; bu FJSP testi için
zorunlu değildir. FJSPmodel.update_env FEASIBLE sonucu da 'Optimal Schedule Length'
olarak yazdırır ve çözüm yokken results atanmadan dönebilir. Bu giriş/yazıcı
katmanları kullanılmaz. Modelin kendisinde değişiklik yapılmamıştır.

Referans: iş kimliği sırası, her işin operasyon sırası; uygun makinelerden
max(işin hazır zamanı, makinenin boşalma zamanı) + süre en küçük olanı seçilir.
Eşitlikte küçük makine kimliği seçilir. Makine kuyruğunun sonuna eklenir;
boşluk doldurma yapılmaz. Bu yöntem FIFO/SPT adıyla sunulmaz.

Amaç makespan; zaman benchmark birimi, tüm işler t=0'da hazır, sürekli çalışma,
bölünmeyen operasyonlar. Termin, duruş, vardiya ve başlamış iş koruması bu
benchmark adaptöründe desteklenmez. Üretim senaryosu API'si değildir.

Sabit seed=0 ve tek worker kullanılır. Duvar saati sınırı nedeniyle farklı
makinelerde birebir aynı CP-SAT sonucu garanti edilmez; referans yöntem deterministiktir.

# 012 — Eğitim modellerini kaydetmek ve tam veri refit'ini ayrı tutmak

17 Ekim 2026. Kullanıcı belirtilen ham Production Analysis CSV ile eğitim
ve model dosyalarının kaydını istedi. Önceki train-only kapsam ayrı
saklanır; toplam hedefte 225 iş ve geçiş hedefinde 418 adayın tamamıyla
ayrı full refit yapılır. Eski validation/test/quarantine dahil olduğundan
full refit için bağımsız başarı skoru yoktur; gelecekteki ölçüm verisi gerekir.

Klasik modeller ve ön işleme pipeline'ları joblib/CatBoost native formatında,
TabPFN görev bağlamı native fit state ve kategori kodlayıcısıyla kaydedilir.
TabPFN temel ağırlığı değişmedi, ortak checkpoint manifest hash'iyle korunur.
Her kayıtta dosyadan yükleme ve aynı probe tahminine eşitlik kontrolü yapılır.
Ana planlama/Gemma/SQLite kodu veya otomatik süre kaynağı değiştirilmez.

Artefaktlar yerelde, Git dışında; kaynak hedef satırları, metadata, kapsam ve
hash bilgileri model klasörlerinde. Kullanım:
`../../results/saved_models/README.md`.

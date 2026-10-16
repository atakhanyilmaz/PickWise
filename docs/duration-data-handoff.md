# Yunus → Atakan: Süre deneyi veri teslimi

Beklenen örnek sözleşme: `data/examples/duration_experiment_synthetic.json`.
Bu dosya sentetiktir; Production Analysis değildir. Ham CSV değişmeden tutulmalı;
temizleme kodu, duplicate tanımı, span/birim incelemesi ve çıkarma gerekçeleri ayrıca
verilmelidir. İşlem adı tekrarı tek başına duplicate değildir.

Her kayıtta: record_id, job_id, part_desc, operation_type, machine_id, batch_size,
started_at, finished_at, duration_minutes. Zaman damgaları açık zaman dilimli olsun.
finished_at hedefin elde edildiği zaman olarak kabul edilir; kayıt gecikmeli
bildiriliyorsa gerçek kullanılabilirlik zamanı ayrıca modellenmeden gelecekteki
süre tahmini iddiası yapılmamalıdır.

Paket: source, source_version, target_definition, target_reviewed, train, test.
`target_definition`: recorded_elapsed_minutes veya verified_processing_minutes.
İlk seçenek başlangıç-bitiş aralığıdır; net makine süresi olduğu iddia edilmez.
Span farklıysa hemen silmeyin: önce span'ın net iş/bekleme/birim anlamını doğrulayın.
`target_reviewed=True` insan incelemesini ifade eder; ham girdide otomatik eklenmemeli.

Aynı iş emri train/test arasında bölünmesin; eğitim kayıtları test tahmin anından
önce tamamen biliniyor olsun. Sınır aşan işleri inceleyip ayrı tutun. Testi model
ve özellik seçimi için tekrar tekrar kullanmayın; model seçiminde ayrıca ayrılmış
bir doğrulama bölümü gereklidir. Mevcut API yalnız son train/test değerlendirme
kapısını denetler, otomatik splitter veya model seçimi yapmaz.

İzin verilen özellikler: part_desc, operation_type, machine_id, batch_size.
Gerçekleşen süre, bitiş zamanı, sonradan tamamlanan miktar veya tüm dönemden
hesaplanmış geçmiş ortalamaları özellik olarak göndermeyin. TabPFN adaptörü
kategorileri yalnız eğitimde öğrenilmiş ön işleme ile ele almalıdır.

Kontrol/medyan çalıştırma:

```sh
.venv/bin/python -m ml_experiments.duration_evaluation --dataset YOUR_REVIEWED_DATA.json
```

Gerçek müşteri dosyalarını veya raporlarını Git'e eklemeyin. CLI yalnız medyanı
çalıştırır; TabPFN performansı üretmez. Harici fit/predict arayüzü test edilebilir,
ama kendi model kurulumu/lisansı ve gerçek veri deneyi ayrıca tamamlanmalıdır.

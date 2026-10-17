# ADR 0005 — Production Analysis karışık geçen süre karşılaştırması

Kabul edildi — 18 Ekim 2026; çevrimdışı deney.

`production_analysis_target_ready.csv` içindeki geçerli 3.840 kayıt korunur.
Proje sahibinin verdiği tanıma göre `S` setup/hazırlık, `D` işleme/geçen çalışma,
`B` arıza aralığıdır. Bu anlamlar yayıncı kaynağından bağımsız doğrulanmamıştır.
`Report Type` hedef üretildikten sonra kaldırılır; bu nedenle hedef, üç türü
karıştıran gözlenen rapor süresidir ve net makine süresi diye sunulamaz.

Model girdileri `Part Desc.`, `Activity` ve miktarın `log1p` dönüşümüdür.
İş emri ayrık kronolojik train/validation/test bölümü korunur. `median`, `ridge`,
`elastic_net`, `huber`, `knn`, `random_forest`, `extra_trees`, `gradient_boosting`,
`hist_gradient_boosting`, `mlp`, `lightgbm`, `xgboost` ve `catboost` modelleri
doğrulama grup-makro MAE ile karşılaştırılır; seçim kuralı kazananı kilitlerken
tüm modellerin doğrulama ve test metrikleri (`metrics.json`), satır bazlı tahminleri
(`all_model_predictions.csv`) ve 6 panelli karşılaştırma grafiği (`model_comparison.png`)
raporlanır. Sonuçlar FJSP makinelerine bağlanmaz, çünkü iki veri alanı arasında
doğrulanmış operasyon/makine eşlemesi yoktur.

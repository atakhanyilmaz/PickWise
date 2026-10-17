# Eğitim dosyaları

Veriler: `data/dataforNewVersion/biPre/`. Bu klasörde tam üç CSV vardır.

| Dosya | Girdiler | Tahmin edilecek süre |
| --- | --- | --- |
| production_analysis_engineered.csv | Part Desc., Activity, log1p_work_order_qty | target_elapsed_time (dakika) |
| cnc_changeover_selected.csv | 24 seçilmiş özellik | remaining_changeover_time_min (dakika) |
| cnc_changeover_extracted.csv | PC001–PC089 | remaining_changeover_time_min (dakika) |

Production ve CNC ayrı görevlerdir. İki CNC CSV'si aynı görev için alternatif
temsillerdir; bunları art arda ekleyip örnek sayısını artırmayın. PCA dosyası tam
60 saniye geçmişi olmayan ilk 59 oturum satırını içermez.

`split=train` öğrenme, `split=validation` model/özellik karşılaştırması,
`split=test` son değerlendirme içindir. Yeniden rastgele satır bölmesi yapmayın.

`source_row`, `group_id`, `split`, varsa `time` model girdisi değildir. Hedef süre
de girdilerden ayrılır. Kalan sütunlar özelliklerdir; Production/seçilmiş CNC'deki
metin kategorileri eğitimde öğrenilen kodlamayla işlenmelidir.

Kararlar ve metrikler bu klasördeki veri setine ait `report.json` içindedir.
`feature_selection.csv` hangi özelliğin neden çıkarıldığını, `pca_loadings.csv`
bileşenlerin içeriğini açıklar. `transformers.joblib` aynı öğrenilmiş dönüşümleri
yeni veriye uygulamak içindir. Özgün altı matrisin içerikleri değişmeden taşındı;
raporlardaki yollar yeni konumları gösterir. Kullanılmayan üç ara matris
`data/dataforNewVersion/biPre_intermediate/` altında korunur.

# Süre tahmini: özellik seçimi ve çıkarımı

Komut iki gerçek veri seti için yeni matrisler üretir. Ham ve mevcut hedef
CSV'lerini değiştirmez. Karar: [ADR 0004](decisions/0004-duration-feature-selection.md).

## Çalıştırma

Proje kökünde, Python 3.11 / PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-features.txt
$env:LOKY_MAX_CPU_COUNT='1'
.\.venv\Scripts\python.exe -m ml_experiments.duration_features
.\.venv\Scripts\python.exe -m pytest -q tests/test_duration_features.py tests/test_prepare_data.py tests/test_cnc_audit.py tests/test_duration_evaluation.py
.\.venv\Scripts\ruff.exe check ml_experiments/duration_features.py tests/test_duration_features.py
```

`--dataset production` veya `--dataset cnc` ile ayrı çalıştırılabilir.
`--output reports/duration_features_yeni --data-output data/dataforNewVersion/biPre_yeni`
önceki deneyi korur. Aynı klasörlerle
yeniden çalıştırma, o deneye ait aynı adlı çıktıları yeniler. Birleşik güncel
özet için varsayılan `--dataset all` kullanılır. Windows'taki isteğe bağlı
`LOKY_MAX_CPU_COUNT=1` fiziksel çekirdek sorgusu uyarısını önler.

## Seçim

1. Tahmin anı filtresi: Production yalnız `Part Desc.`, `Work Order  Qty`,
   `Activity`. `Qty Rejected` dahil gerçekleşen miktarlar hedef tahmininde
   kullanılmaz. CNC'de mevcut canlı sensörler ve bilinen ürün geçişi adaydır.
2. Sayısal aralıkla normalize edilmiş varyans `<=0,0001`; kategorilerde
   baskınlık `>=%99,5`: sabit/yakın sabit eleme.
3. Sayısal `|Pearson| >=0,95`: çiftten kaynak sırasındaki temsilci korunur;
   geçen hazırlık süresine öncelik verilir. Kategorilerde eşdeğer birebir kod
   eşlemeleri de kaldırılır. Eşdeğerlik yalnız eğitim için geçerlidir.
4. Sürekli sayısal ölçümlerde VIF `>20`: en yüksekten başlayarak eleme.
   Kategori kodları, one-hot sütunları ve ikili bayraklara VIF uygulanmaz.
5. Mutual information + SelectKBest: CNC en fazla 24, Production en fazla 3
   kaynak özelliği. `k` bu deneyde sabittir; en iyi sayı olduğu iddia edilmez.
6. Standardize seçilmiş sayısallar/one-hot kategoriler üzerinde Lasso tanısı.
   L1 sıfırları ayrı raporlanır; doğrusal olmayan ilişkiyi tek başına elemez.

MI, VIF ve Lasso için en fazla 6.000 satırlık grup dengeli eğitim örneği
kullanılır. Uzun oturumların etkisi sınırlanır; bu işlem satırları bağımsız
deneylere dönüştürmez. Test/doğrulama, bu seçimlerin öğrenilmesine katılmaz.

## Çıkarım

Production'da miktar `log1p` ile dönüştürülür; kategoriler eğitimde öğrenilen
sözlükle one-hot kodlanır. CNC'de seçilmiş özelliklerin mevcut değerlerine
30/60 saniyelik geçmiş ortalaması, standart sapması, minimum/maksimumu,
pencere başına göre farkı veya kategori değişim sayısı eklenir. Geçen süre
tam olarak mevcut değeriyle tutulur; gereksiz kayan kopyaları üretilmez.
Pencereler ileriye bakmaz, oturum sınırını geçmez; tam geçmişi olmayan ilk
59 satır, pencere deneyinin dışında kalır. Boşluk varsa işlem hata verir.

Sayısal eksik değer medyanları, kategori sözlüğü, ölçekler ve PCA yalnız
eğitimde öğrenilir. Bilinmeyen kategori one-hot'ta sıfır vektördür; kategoriler
raporda listelenir. One-hot dahil ölçeklenmiş eğitim matrisinin en az %95
varyansını koruyan PCA ayrı çıktı üretir. Bu oran tahmin doğruluğu değildir.

## Çıktıların kullanımı

Eğitimde kullanılacak üç CSV, `data/dataforNewVersion/biPre/` içindedir:

- `production_analysis_engineered.csv`: parça, operasyon ve logaritmik sipariş miktarı.
- `cnc_changeover_selected.csv`: seçilmiş 24 özgün girdi.
- `cnc_changeover_extracted.csv`: geçmiş sensör özetlerinden çıkarılmış 89 PCA bileşeni.

Son iki dosya aynı CNC hedefi için alternatif girdilerdir; birleştirilmez.
Bu dosyalarda mevcut `split` ayrımı korunur. Ham/hedef girdiler aynı yerde kalır.
Diğer üç keşif/ara matris `data/dataforNewVersion/biPre_intermediate/<veri_seti>/`
altındadır; büyük ara CNC matrisi gzip'tir (`pd.read_csv` doğrudan açar).

`reports/duration_features/<veri_seti>/` içinde yalnız açıklama ve deney bilgileri kalır:

- `feature_selection.csv`: her kaynak özelliği için seçim/çıkarma gerekçesi ve MI.
- `report.json`: eşikler, sıralamalar, L1 katsayıları, çıkarılan sütunlar,
  örnek sayıları, doğrulama ve son test metrikleri.
- `pca_loadings.csv`: bileşenlerin kodlanmış özelliklere yükleri.
- `transformers.joblib`: eğitimde öğrenilmiş seçim, kodlama, ölçek, PCA ve sabit
  karşılaştırma modelleri. Yerel olarak üretilen bu dosya yeni veride
  `transform_bundle` ile tekrar kullanılabilir.
- `holdout_predictions.csv`: doğrulamada seçilen yaklaşımın son test tahminleri.

CSV'lerde `source_row`, `group_id`, `split` ve CNC'de `time` sadece metadata'dır;
hedef `target_elapsed_time` veya `remaining_changeover_time_min` ayrı tutulur.
Bu sütunları modele özellik olarak vermeyin. `source_row` sıfır tabanlı ham
CSV kayıt sırasıdır. Gerçek özellik listesi JSON'da ve PCA için `PC*`
sütunlarındadır. Kök `summary.json` ham/hedef dosyaların ve kullanılan betiğin
SHA-256 değerlerini, paket sürümlerini ve deney özetini taşır. Klasör düzeni sonradan
taşındığında özgün eğitim betiğinin hash'i korunur; taşıma betiğinin hash'i
`artifact_layout.relocation_script_sha256` alanına ayrıca yazılır.

Önceden üretilmiş çıktıları yeniden öğrenme yapmadan taşımak için
`python -m ml_experiments.duration_features --relocate-existing` kullanılır.
İçerik hash'leri doğrulanır, JSON dosya yolları güncellenir ve yalnız doğrulanmış
yeni kopyası bulunan eski veri matrisi kaldırılır.

## Doğrulama ve sınırlar

Production: kalite filtresinden geçen 3.840 satırın 2.501'i zaman sınırını aşan
iş emirleri nedeniyle karantinadadır. Eğitim/doğrulama/test 838/150/351 satır
ve 71/15/44 ayrı iş emridir. Üç uygun girdi korunur. Miktarın log1p dönüşümü
sonrasında one-hot matris 53 sütun, PCA 45 bileşendir. Kaynakta üç sütun olması,
kategoriler kodlandıktan sonra üç sayısal boyut olacağı anlamına gelmez.

CNC: 36.356 gözlem ve 30 tam oturum; eğitim/doğrulama/test 18/6/6 oturum.
Tam 60 saniyelik pencere için 1.770 başlangıç satırı dışarıda kalır. Seçim
166 aday girdi 24'e indi (%85,54 azalma). Bunlardan çıkarılan 214 özelliğin
one-hot sonrası 269 sütunu, PCA'da 89 bileşene indi; eğitim varyansının
%95,074'ü korundu. Seçilmiş CSV 10,51 MB, PCA CSV 39,03 MB; hedef kaynak
CSV 52,20 MB'dir (ondalık MB). Büyük türetilmiş ara tablo gzip ile 17,89 MB
tutulur; sıkıştırılmamış eski ara kopya teslim çıktısı değildir. Seçim listesi
`reports/duration_features/cnc_changeover/report.json` dosyasındadır.

17 Ekim 2026 gerçek veri deneyinde doğrulama grup-makro MAE (dakika):

| Temsil | Production (15 iş emri) | CNC (6 oturum) |
| --- | ---: | ---: |
| Seçilmiş kaynak özellikleri | 127,858 | 8,620 |
| Türetilmiş özellikler | 126,466 | 7,933 |
| PCA | 152,014 | 6,634 |
| Eğitim medyanı referansı | 140,267 | 3,039 |

Doğrulama kararı Production'da türetilmiş özellikler, CNC'de medyandır. Bu
kararlardan sonraki tek son-test değerlendirmesinde grup-makro MAE sırasıyla
112,474 dakika (44 iş emri / 351 satır) ve 2,436 dakika (6 oturum / 5.778
pencere satırı) oldu. CNC'de PCA varyans koruması, medyanı geçmeye yetmedi;
bu sonuç yalnız buradaki sabit Ridge karşılaştırması içindir.

İlgili 34 test ve hedefli Ruff kontrolü geçti. Sayısal yeniden yükleme kontrolü
iki gerçek veri setinde kaydedilen dönüşümlerin PCA CSV'lerini yeniden
ürettiğini; matrislerin sonlu, grupların ayrık ve ham/hedef hash'lerinin
değişmemiş olduğunu ayrıca denetler. Bu, tam depo test koşusu değildir.

Sabit `Ridge(alpha=10)` yalnız özellik temsillerini karşılaştıran deneysel
bir kontroldür. Eğitim grupları eşit ağırlıklıdır; negatif tahminler sıfıra
kırpılır. Seçilmiş, türetilmiş ve PCA temsilleri aynı pencere satırlarında
karşılaştırılır. Karar doğrulama grup-makro MAE'sine göre, medyan referansı da
dahil edilerek verilir; son test yalnız bu karar kilitlendikten sonra ölçülür.
Production medyanı eğitim operasyonundan, CNC medyanı eğitim oturumlarının
ürün geçişi bazlı toplam sürelerinden hesaplanır; yeni geçişte eğitim geneli
medyanına dönülür ve mevcut geçen süre çıkarılıp sıfıra kırpılır.

Production'da rapor türleri/agregasyon ve gerçek makine süresi anlamı çözülmüş
değildir. CNC tek makinedeki devam eden hazırlığa aittir; yalnız 30 oturum vardır.
Test MAE'si bu belirsizlikleri ortadan kaldırmaz. Bu hazırlık TabPFN eğitimi,
üretimde model onayı veya başka makinelere genelleme kanıtı değildir.

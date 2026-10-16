# Veri Hazırlama İlk Beş Adım Uygulama Planı

Tarih: 16 Ekim 2026  
Durum: İlk beş adım için tekrarlanabilir temel uygulandı; açık veri anlamları çözülmeden modelleme başlamaz.

## 1. Sonuç ve kapsam

İlk üç adım dokümanlarda kısmen tanımlanmış ve iki ham CSV depoya eklenmiştir. `ml_experiments.prepare_data` ve `configs/data_contracts.toml` artık sözleşmeleri, salt-okunur profillemeyi, kalite raporunu, grup/zaman temelli bölmeyi ve yalnızca eğitim verisiyle üretilen EDA'yı tekrarlanabilir biçimde çalıştırır. Ham dosyalar değişmeden kalır; raporlar ve yerel veri CSV'leri Git dışında tutulur.

Bu plan, aşağıdaki beş çıktıyı tamamlar:

1. Her model için ayrı amaç ve tahmin anı sözleşmesi.
2. Ham veriyi değiştirmeyen, checksum içeren veri envanteri ve profil raporu.
3. Hataları silmek yerine önce işaretleyen veri kalite raporu.
4. Zamanı ve iş/oturum gruplarını koruyan eğitim, doğrulama ve test manifestleri.
5. Yalnızca eğitim bölümünde üretilen ayrıntılı analiz ve grafikler.

Dönüşüm pipeline'ı, model eğitimi ve test setiyle son değerlendirme bu teslimin dışında, sırasıyla 6-9. adımlarda yapılacaktır.

## 2. Veri seti ve model görevleri

| Veri kaynağı | Birincil kullanım | İlk hedef | Tahmin anında kullanılabilecek bilgi | Kullanılmayacak veya ayrı tutulacak bilgi |
| --- | --- | --- | --- | --- |
| Production Analysis | TabPFN regresyonu | Anlamı doğrulanmış operasyon kaydının dakika cinsinden `recorded_duration_min` değeri | Parça açıklaması, sipariş miktarı, operasyon türü ve planlama anında gerçekten biliniyorsa atanmış kaynak | Bitiş zamanı, `Span`, tamamlanan/reddedilen/MRB miktarı, `Rework`, testten hesaplanan özetler |
| Production Analysis | EmbeddingGemma 2 ile geçmiş iş arama | Denetimli hedef yok; arama birimi iş emri veya doğrulanmış operasyon özeti | Tahmin anında mevcut metinsel iş ve rota bilgisi | Doğrulama/test dönemindeki gelecekteki işlerin arama indeksine eklenmesi |
| CNC Changeovers v1.0.1 | Değişim/üretim oturumlarının betimleyici analizi | Bu ürün planında denetimli hedef yok; `Label_03` oturum/faz sınırı bulmak için, `Label_10` daha ayrıntılı betimleme için kullanılır | Sensör kayıtları, oturum ve fazlar | 30 oturumu bağımsız satır gibi değerlendirmek; etiketleri özellik olarak kullanmak; sınıflandırmayı mevcut ürün göreviymiş gibi sunmak |
| Brandimarte | CP-SAT ve sezgisel yöntem doğrulaması | Tahmin hedefi yok; makespan ve çizelge geçerliliği | Benchmark dosyasındaki işler, operasyonlar, uygun makineler ve süreler | TabPFN eğitim verisi olarak kullanma |
| Gemma | Türkçe talep yapılandırma ve sonuç açıklama | Bu iki CSV üzerinde model eğitimi yok | Kullanıcı talebi ve hesaplanmış araç çıktıları | Süre, uygun makine veya performans değerlerini modelin üretmesi |

Production Analysis hedefi şimdilik özellikle `recorded_duration_min` olarak adlandırılmalıdır. Başlangıç-bitiş farkının saf makine çalışma süresi olduğu doğrulanmadan `processing_time_min` adı kullanılmayacaktır. `Report Type` değerleri olan `S`, `D` ve `B` ile satırların operasyona nasıl birleştirileceği, hedef tablo oluşturulmadan önce veri kaynağı dokümanıyla doğrulanacaktır.

CNC verisi ürün planında bağımsız hazırlık/değişim analizi içindir; mevcut ürün hedefi bir sınıflandırma modeli değildir. Resmî veri tanımı 30 oturum ve beş tam değişim matrisini doğrular. `Label_03` ve `Label_10` bu hazırlık aşamasında yalnızca fazları betimlemek için kullanılır; 52.026 saniyelik satır bağımsız oturum sayılmaz.

## 3. Doğrulanmış ham veri özeti

Bu bölüm 16 Ekim 2026'da yerel dosyalardan yeniden ölçülmüştür. Ayrıntılı tip/örnek/kategori envanteri `reports/data_preparation/raw_inventory.json`, kural bazlı bulgular `quality_report.json` içindedir. SHA-256, üretilen envanterde yer alır.

### 3.1 Production Analysis

- 4.543 satır, 14 sütun ve 225 iş emri vardır. SHA-256: `ef2477450926aa650e83a038cc81578a048a31ee22dfb858b5eab2a7883a21e6`.
- Zaman aralığı 2 Ocak 2012 ile 30 Mart 2012 arasındadır; kaynak saat dilimi dosyada belirtilmemiştir.
- 43 parça açıklaması, 55 aktivite, 31 kaynak, 49 çalışan ve 3 rapor türü vardır.
- `Rework` 4.511 satırda boştur; boş değerin kesin olarak `hayır` anlamına geldiği varsayılmamalıdır.
- 22 yinelenen tam satır fazlası ve seçilen olay anahtarında 50 yinelenen kayıt fazlası vardır (rapor bunlara dahil tüm etkilenmiş satırları sırasıyla 41 ve 97 olarak gösterir).
- 9 kayıt sıfır dakika sürmektedir.
- Bir `Span` değeri beklenen `HH:MM` biçiminde değildir.
- 699 satırda `Span` ile zaman damgalarından hesaplanan süre 1 dakikadan fazla uyuşmamaktadır (önceki 704 sayısı farklı toleransla hesaplanmıştır).
- Bu uyuşmazlıkların 672'si `D`, 23'ü `S`, 4'ü `B` türündedir; 652 kayıtta `Span`, başlangıç-bitiş farkından kısadır. Bu tek başına hangisinin doğru süre olduğunu kanıtlamaz.
- Negatif zaman farkı veya negatif miktar bulunmamıştır.
- Bir iş emri içinde parça açıklaması ve sipariş miktarı tutarlıdır.

Bu bulgular, CSV satırlarının doğrudan bağımsız operasyon örneği sayılamayacağını gösterir. Tekrarlar, rapor türleri, yeniden işleme ve parçalı kayıtlar hedef tablo öncesinde açıklanmalıdır.

### 3.2 CNC Changeovers

- Yerel dosya Zenodo v1.0.1 checksum'u ile eşleşmektedir: MD5 `5a758c263562595416007d554ea824da`; SHA-256 `d7227badb6ae1a27339622b337207cc342f75acc5baa18538352228fd52be580`.
- Resmî kayıt, veri setini 1 saniye frekanslı, 3 ürün ve 30 oturum/5 değişim matrisi olarak tanımlar. Bu doğrulama, etiket sınıflandırmasının mevcut ürün hedefi olduğu anlamına gelmez. [Zenodo v1.0.1 kaydı](https://zenodo.org/records/15735480), [veri tanımlayıcı makale](https://www.nature.com/articles/s41597-025-05294-0).
- 52.026 satır ve 182 sütun vardır: bir yerel indeks, bir zaman damgası, 170 özellik ve 10 etiket.
- Zaman aralığı 12-22 Mart 2024'tür; geçersiz zaman damgası yoktur.
- `Label_03` geçişleri 30 değişim ve 30 üretim fazı verir; bunlar 30 tam oturum oluşturur.
- `Label_01` içinde teorik 73 sınıfın 57'si, `Label_10` içinde teorik 43 sınıfın 30'u gözlenmektedir.
- `Label_03` dağılımı dengesizdir: 36.356 değişim ve 15.670 üretim saniyesi.
- Yerel indeks oturumlar arasında sıfırlanır; 22.526 indeks değeri tekrar eder ve benzersiz kayıt anahtarı olarak kullanılamaz.
- Eksikler altı sütunda yoğunlaşır. `Line_Content` 51.603, `Tool_ID` 11.255 ve üç `Magazine_9999` alanı 7.555'er satırda boştur. Kaynak açıklamasına göre bazı boşluklar çalışma bağlamı gereği beklenen olabilir; otomatik doldurma yapılmayacaktır.

## 4. İlk beş adımın uygulama durumu ve kalan sınırlar

| Adım | Uygulanan | Kalan sınır | Çıkış ölçütü |
| --- | --- | --- | --- |
| 1 Amaç | TOML sözleşmeleri her görev için tahmin/analiz birimi, hedef, grup/zaman anahtarı ve izinli/yasak alanları tanımlar. CNC için model hedefi yoktur; `Label_03` ve `Label_10` betimleyici işaretlerdir | Production Analysis hedefi ve rapor birimi `S/D/B` anlamı doğrulanana kadar geçicidir | Sözleşme var; model eğitimine izin veren onaylı operasyon hedefi henüz yok |
| 2 Ham veri inceleme | SHA-256, boyut, satır/sütun, çıkarılmış tip, eksik sayısı, örnekler, sayısal aralıklar ve zaman aralığı `profile` ile üretilir | Kaynak saat dilimi ve bazı alanların iş anlamı mevcut CSV'den çıkarılamaz | Profil JSON'u üretildi; ham kaynaklara yazılmaz |
| 3 Veri kalitesi | `issue_code`, önem, etkilenen satır sayısı ve örneklerle JSON raporu; satır bazlı `valid`/`review_required`/`quarantine` manifesti. Ham kayıt silinmez/değiştirilmez | CNC etiket hiyerarşisi/fiziksel sensör aralıkları ve `S/D/B` kaynak semantiği harici veri sözlüğüyle teyit bekler | Kurallar çalıştı; işaretler otomatik veri silme veya model hedefi kabulü değildir |
| 4 Veri bölme | İş emri zaman sınırı ve CNC çevrim/matris grupları için satır manifestleri, zaman/sınıf kapsamı üretilir; sınır aşan her iş emrinin nedeni ve tarih aralığı `production_boundary_cases.csv` içine yazılır | Production Analysis'ta 91/225 iş sınırları aştığı için karantinada; kalan iş oranı 60/20/20 değildir. Bu set regresyon değerlendirmesi için zayıftır. CNC bölümleri ilerideki deneyler için ayrılmıştır; mevcut model doğrulaması değildir | Grup çakışması sıfır; CNC 18/6/6 çevrim ve 3/1/1 matris olarak korunur |
| 5 Detaylı analiz | Süre dağılımı, IQR/MAD aykırı işaretleri, parça/rapor türü ve miktar ilişkisi, vaka özeti; CNC faz/oturum süreleri, etiket özetleri, sensör eksikleri/sabitliği/korelasyonları. Grafikler eğitim verisinden | Production gözlenen süre yalnızca betimleyicidir; doğrulanmış model hedefi değildir. CNC satırları zaman bağımlıdır; sınıflandırma üründe kararlaştırılmış değildir | EDA kodu yalnızca `train` gruplarını analiz eder; test/validasyon grafikleri veya özellik kararlarına karışmaz |

Uygulama komutu: `.venv\\Scripts\\python.exe -m ml_experiments.prepare_data all`. Tek adımlar `profile`, `quality`, `split` ve `eda` argümanlarıyla çalıştırılabilir. Raporlar `reports/data_preparation/` altına yazılır ve `.gitignore` ile dışarıda tutulur.

## 5. Uygulama tasarımı

Mevcut depoyu geniş çapta yeniden düzenlemeden aşağıdaki küçük yapı önerilir:

```text
ml_experiments/
  data_contracts.py
  inspect_raw.py
  quality_checks.py
  split_datasets.py
  eda.py
configs/
  data_contracts.toml
reports/
  data_preparation/
    raw_inventory.json
    quality_report.json
    split_summary.json
    eda_summary.md
tests/
  ml_experiments/
```

Ham CSV'ler değiştirilmez. Büyük türetilmiş tablolar ve grafikler varsayılan olarak Git'e eklenmez. Her JSON raporunda kaynak checksum'ları ve sözleşme sürümü bulunur; kod commit'i ve çıktı zamanı henüz kaydedilmemektedir.

### 5.1 Adım 1 görevleri

1. `data_contracts.toml` içinde her görev için ayrı sözleşme oluştur.
2. Production Analysis için model satırının bir CSV rapor satırı mı, kesintisiz faaliyet segmenti mi yoksa iş emri-operasyon toplamı mı olduğunu kaynak semantiğiyle doğrula.
3. `S`, `D`, `B` rapor türlerinin anlamı doğrulanmadan birleştirme kuralı yazma.
4. Tahmin anında bilinmeyen alanları `forbidden_features` listesine koy ve testle koru.
5. Embedding arama için indeks birimini iş emri özeti olarak başlat; operasyon düzeyi ancak rota ayrıştırması güvenilir olduğunda eklenir.
6. CNC için birincil sözleşmeyi `Label_03`, ikincil sözleşmeyi `Label_10` olarak kaydet. Diğer etiketleri özellik olarak kullanma.

### 5.2 Adım 2 görevleri

1. Dosya boyutu, SHA-256, satır/sütun sayısı, sütun tipi, örnek değer, min/max ve kategori sayısını çıkar.
2. Production Analysis için `Span` birimini dakika olarak ayrıştır, fakat timestamp farkının yerine geçirme.
3. CNC yerel indeksini veri alanı olarak koru ama benzersiz kimlik sayma; `session_id` ve `row_in_session` üretimini sonraki türetilmiş tabloda yap.
4. Veri sözlüğünde kaynak birimi, dönüştürülen birim ve anlamı doğrulanmamış alanları ayrı işaretle.
5. Ham verinin yanlışlıkla commit edilmesini önlemek için uygulama aşamasında `.gitignore` kuralı ve checksum manifesti ekle.

### 5.3 Adım 3 görevleri

Production Analysis kalite kuralları:

- Geçersiz/ters zaman aralığı.
- Sıfır süre ve yapılandırılabilir aşırı süre eşiği.
- `Span` biçim hatası ve timestamp farkıyla uyuşmazlık.
- Tam tekrar ile olay anahtarı tekrarını ayrı raporlama.
- İş emri içinde parça ve sipariş miktarı tutarsızlığı.
- Negatif miktar ve satır miktarlarının sipariş miktarını aşması.
- Bilinmeyen aktivite-kaynak eşleşmesi.
- Yeniden işleme ve parçalı raporların hedef tabloya girmeden önce karantinaya alınması.

CNC kalite kuralları:

- Zaman sırasının artması ve beklenen 1 saniyelik frekanstan kopmalar.
- Oturum sınırlarının ve 30 değişim-üretim çiftinin yeniden üretilebilmesi.
- Etiketlerin tamsayı, eksiksiz ve kaynakta izin verilen kümelerde olması.
- Etiketler arası bilinen hiyerarşik eşlemelerin tutarlılığı.
- Sabit, tamamen boş, aşırı eksik ve fiziksel aralığı şüpheli sensörlerin raporlanması.
- Yerel indeks tekrarlarının hata değil oturum sıfırlaması olarak işaretlenmesi.

Kalite hattı ham satırları yerinde düzeltmez. Her kayıt `valid`, `quarantine` veya `review_required` statüsü alır; dışlama gerekçesi manifestte tutulur.

### 5.4 Adım 4 görevleri

Production Analysis için önerilen ayrım:

1. Gruplama anahtarı `Case ID`, zaman anahtarı iş emrinin ilk ve son zamanıdır.
2. Hedef oran yaklaşık yüzde 60 eğitim, yüzde 20 doğrulama ve yüzde 20 testtir.
3. Bir iş emrinin bütün satırları tek bölümde kalır.
4. Zaman kesimini aşan uzun iş emirleri ayrı `boundary_quarantine` manifestine alınır; farklı bölümlere parçalanmaz.
5. Bu veride iş emirlerinin medyan yayılımı yaklaşık 13,9 gün, ortalaması 20,6 gündür. Bu yüzden katı zaman sınırı çok sayıda işi karantinaya alabilir. Gerçek sayılar raporlanır; örnek sayısını büyütmek için rastgele satır bölmeye dönülmez.
6. Eğitimden hesaplanan medyanlar, kategori sözlükleri ve diğer özetler doğrulama/teste yalnızca dönüştürme amacıyla uygulanır.

`boundary_quarantine`, ham satırların silindiği anlamına gelmez. `Case ID` bir iş emrinin tüm raporlarını kapsadığı için, ilk ve son rapor zamanı kesim tarihini iki tarafa bölüyorsa iş emrinin tamamı mevcut katı kronolojik bölmeden çıkarılır. Bu ölçümde 63 iş ilk kesimi, 56 iş ikinci kesimi aştı; 28'i iki kesimi de geçti. 91 iş emrinin 2.938 satırı kaynağında korunur ve ayrı manifestte açıklanır. Bu karar, tamamlanmış hedeflerin kesim anında bilinmesini gerektiren zamansal değerlendirmeyi korumak içindir.

Verinin daha fazlasını kullanmak için alternatif, iş emrinin tamamını ilk rapor zamanına göre bir bölüme atamaktır. Bu, aynı `Case ID`'yi bölmez ve karantina sayısını kaldırır; ancak eğitimdeki eski işlerin kesim tarihinden sonraki raporlarını kullanabilir. Böyle bir bölme ileriye dönük performansı olduğundan iyi gösterebilir. Bu nedenle ancak deney amacı açıkça grup ayrımıysa tercih edilmeli; üretimde geleceğe tahmin iddiası için katı kronolojik bölme tutulmalıdır.

CNC için önerilen ayrım:

1. `Label_03` geçişlerinden 30 oturum kimliği üret.
2. Altı geçiş türünü içeren her ardışık altılı oturum bir değişim matrisi olarak tutulur.
3. İlk 3 matris, yani 18 oturum eğitim; 4. matris, yani 6 oturum doğrulama; 5. matris, yani 6 oturum test olur.
4. Satır düzeyinde rastgele ayırma ve aynı oturumun farklı bölümlere dağılması yasaktır.
5. Mevcut dosyada bu taslak ayrım yaklaşık 33.441 eğitim, 9.118 doğrulama ve 9.467 test satırı üretir.
6. Sınıf kapsamı her bölümde raporlanır. Nadir fazların doğrulama/testte bulunmaması kalite hatası değil, genelleme sınırlaması olarak gösterilir.

### 5.5 Adım 5 görevleri

Production Analysis eğitim EDA'sı:

- Hedef süre dağılımı, log ölçeği ve robust yüzdelikler.
- Parça, aktivite, kaynak ve sipariş miktarına göre örnek sayısı ve süre özeti.
- İş emri başına rapor sayısı, rota uzunluğu, yeniden işleme ve bekleme aralıkları.
- Aykırı değerleri silmeden IQR ve robust z-score ile işaretleme.
- Hedefle ilişkili görünen ancak tahmin anında bilinmeyen alanlar için açık leakage tablosu.
- Görülmeyen kategori riski ve medyan fallback kapsamı.

CNC eğitim EDA'sı:

- Oturum ve değişim türüne göre değişim/üretim süresi.
- `Label_03` ve `Label_10` sınıf dengesi ve oturumlara dağılımı.
- Sensör eksikliği, sabitlik, varyans, korelasyon kümeleri ve fiziksel aralıklar.
- Zaman içindeki öğrenme etkisi; eğitim, doğrulama ve test matrisleri karşılaştırması yalnızca son raporlama amacıyla ayrı tutulur.
- Nadir sınıflar ve ardışık örnek bağımlılığı; etkin bağımsız örnek sayısının satır sayısından küçük olduğu açıkça belirtilir.

## 6. Doğrulama ve kabul ölçütleri

İki gerçek CSV üzerinde salt-okunur komut çalıştırıldı: `.venv\\Scripts\\python.exe -m ml_experiments.prepare_data all`. Bu çalıştırma üretim kodunu ve rapor üretimini doğrular; henüz otomatik fixture testleri eklenmemiş veya çalıştırılmamıştır.

- Ham dosya checksum'u çalıştırma öncesi ve sonrası aynıdır.
- Sözleşmede hedef veya yasak özellik çakışması varsa işlem durur.
- Geçersiz tarih, negatif süre, malformed `Span`, tekrar ve grup taşması fixture'ları beklenen issue kodunu üretir.
- Hiçbir `Case ID` veya CNC `session_id` birden fazla splitte bulunmaz.
- Production Analysis splitinde eğitim zamanı doğrulama/testten önce gelir; sınır aşan işler görünür karantinadadır.
- CNC splitinde 18/6/6 oturum ve 3/1/1 matris korunur.
- EDA hesaplamaları ve grafikler yalnızca `train` satırlarından üretilir; komut manifest ve satırları seçmek için CSV'leri okusa da validation/test hedefleriyle istatistik veya özellik kararı üretmez.
- Aynı girdi ve sözleşme sürümünde manifest checksum'ları değişmez.
- Raporlar kullanılan satır, karantina satırı, iş/oturum sayısı ve dışlama gerekçelerini birlikte verir.

## 7. Uygulama sırası

1. Veri-model sözleşmeleri ve veri sözlüğü.
2. Salt-okunur ham veri profilleyici ve checksum envanteri.
3. Kalite kuralları, issue kodları ve karantina raporu.
4. Production Analysis ve CNC için ayrı split üreticileri.
5. Yalnızca eğitim bölümü EDA raporları.
6. Hedefli testler ve gerçek veri kabul raporu.
7. Sonuçlara göre 6. adım dönüşüm kuralları için ayrı karar.

Bu sıra tamamlanmadan TabPFN kıyaslamasına veya CNC model eğitimine geçilmemelidir. Özellikle `Span` uyuşmazlığı ve Production Analysis satır granülerliği çözülmeden elde edilen regresyon metriği güvenilir kabul edilmez.

## 8. Açık kararlar ve engeller

İlk beş adımın veri keşfini durdurmayan, ancak model eğitimini engelleyen iki açık alan:

1. Production Analysis için `S`, `D`, `B` rapor türlerinin kaynak anlamı ve hedef agregasyon kuralı.
2. Gelecekte ayrıca CNC faz sınıflandırması istenirse hedef ve tahmin anı veri tanımına göre yeniden kararlaştırılmalıdır. Mevcut ürün planı bunu model görevi olarak tanımlamıyor.

Diğer adımlar bu iki kararı beklemeden ham profil, kalite kuralları ve oturum/iş emri manifestlerine kadar geliştirilebilir.


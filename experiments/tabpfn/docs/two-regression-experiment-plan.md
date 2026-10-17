# İki ayrı süre regresyonu: araştırma ve deney planı

> Sonraki kullanıcı açıklaması: "A'dan B'ye" ürün değişimi değil, makineler
> arası geçiş ve toplam iş süresi olarak tanımlandı. Bu belgedeki CNC toplam
> hazırlık tasarımı ayrı deney önerisidir; yeni isteğin yeterlilik incelemesi
> `docs/process-target-feasibility.md` içindedir. Henüz model eğitilmedi.

> Son durum: sonradan iki gerçek TabPFN v2 doğrulama deneyi yapıldı;
> tarihsel araştırma planının aşağıdaki "kurulmadı" ifadeleri önceki aşamaya
> aittir. Sonuç ve sınırlar `docs/learnability-results.md` içindedir.

Tarih: 17 Ekim 2026. Durum: deney tasarımı; bu çalışmada TabPFN kurulmadı,
ağırlık indirilmedi ve model çalıştırılmadı. Aşağıdaki yöntem seçimleri bizim
önerdiğimiz protokoldür; dokümanlardan alınmış başarı sonuçları değildir.

## Ne yapacağız?

İki ayrı veri kaynağı için iki ayrı regresyon problemi kuracağız. Regresyon,
sayısal süre tahmini görevinin kendisidir; modeli kurduktan sonra ayrıca
"regresyonunu yapmak" diye üçüncü bir aşama yoktur. TabPFNRegressor iki görevde
ayrı eğitim bağlamıyla kullanılabilir; iki CSV birleştirilmez.

| Deney | Tahmin anı / soru | Hedef | Bağımsız değerlendirme grubu |
| --- | --- | --- | --- |
| A — Production Analysis | Kayıttaki faaliyet başlamadan ne kadar geçen süre beklenir? | `target_elapsed_time`, dakika | `Case ID` / iş emri |
| B — CNC toplam hazırlık | A ürününden B'ye hazırlık başlamadan ne kadar sürer? | Oturum başına toplam hazırlık aralığı, dakika | Tam CNC oturumu |

**Mevcut CNC `remaining_changeover_time_min` tablosu B değildir.** Bu tablo
hazırlık devam ederken kalan süreyi tahmin eden, ayrı B-online deneyine aittir.
B'nin ilk sürümü oturum başına bir satır, toplam 30 satır olacak. B-online
istenirse ayrıca çalıştırılır; toplam süre ve kalan süre aynı hedef/sonuç
gibi raporlanmaz. Bu ayrım kullanıcının A→B geçiş süresi sorusunu karşılar.

TabPFN önceden eğitilmiş bir tablosal modeldir. Normal fit/predict akışı
göreve ait örnekleri bağlama verir; burada ağırlıkları sıfırdan eğitmek veya
fine-tuning yapmayı planlamıyoruz. Resmî yerel kullanım örneği
`TabPFNRegressor.fit(X_train, y_train)` ve `predict(X_test)` kullanır.
[Yerel kullanım ve API ayrımı](https://docs.priorlabs.ai/quickstart),
[in-context davranışı ve donanım](https://docs.priorlabs.ai/faq).

## A — Production Analysis hazırlığı

Mevcut teslim: 4.543 ham satırdan filtrelenmiş 3.840 hedef satırı. Hedef yalnız
gözlenen rapor aralığıdır; saf makine çalışma süresi olduğu veya tek satırın
tam operasyon olduğu iddia edilmez. S/D/B raporlarının anlamı ve agregasyon
belirsizken deney rapor-satırı düzeyinde deneysel kalır; ürün solver'ına girmez.

Başlamadan:

1. Kaynak dosya SHA-256 ve ham `source_row` kimliği korunur. Hazırlama
   fonksiyonunun filtrelenen satır indekslerinden hedefe kaynak satırı
   taşınır. Yalnız Case ID/aynı süre üzerinden eşleştirme yapılmaz.
2. Hedef CSV'si yeniden üretildiğinde mevcut teslimle eşitliği kontrol edilir;
   ham veriye yazılmaz. Satır kaybı/filtre gerekçeleri raporlanır.
3. Mevcut hedefteki 35 birebir tekrar fazlası ve ham olay anahtarı tekrarları
   incelenir. Aynı görünen hedef satırı otomatik gerçek duplicate sayılmaz:
   zaman sütunları çıkarılınca farklı olaylar aynı görünebilir. Kaynak satır
   üzerinden karar verilir; rework bilinmiyorsa hayır yapılmaz.
4. `production_analysis_split_manifest.csv` içindeki `source_row`, `group_id`
   ve `split` ile kimlik eşlemesi doğrulanır. Case ID tek bölüme ait olmalı;
   eğitim hedefinin elde edildiği bitiş doğrulama tahmininden önce bilinmeli.
   Sınır aşan karantina işleri rastgele train/teste dağıtılmaz. Filtrelerden
   sonra train/validation/test satır ve iş sayıları yeniden ölçülür.
5. Kaynak saat dilimi belirsizken model sözleşmesine uydurmak için İstanbul
   atanmaz. Mevcut AwareDatetime deney adaptörüne bağlanmadan bu karar çözülür
   veya ayrı, açıkça yerel zaman sıralaması kullanan deney sınırı tanımlanır.

İlk X: `Part Desc.`, `Activity`, `Work Order  Qty`.
`Resource` yalnız atama başlangıçta biliniyorsa ikinci bir karşılaştırmada.
Case ID, Report Type, Worker ID, Rework, tamamlanan/reddedilen/MRB miktarı,
başlangıç/bitiş, Span ve türetilmiş hedef süreleri X'e girmez. Yalnız eğitimde
öğrenilen kategori eşlemesi ve belgeli bilinmeyen kategori geri dönüşü
kullanılır. Parça açıklaması ilk deneyde kategori kabul edilir; doğrulanmamış
metin embedding'i veya yeni semantik alanlar eklenmez.

## B — CNC toplam hazırlık hazırlığı

1. Ham `Label_03` kesintisiz hazırlık fazlarından 30 oturum yeniden üretilir;
   Label_09 ürün geçişi eşlemesi kaynak açıklamasıyla doğrulanır. Etiketler
   yalnız denetim/segmentasyon içindir, fiziksel geçiş türünün başlangıçta
   bilindiği varsayımı açıkça kaydedilir.
2. Mevcut hedefle tutarlı ilk tanım `son hazırlık örneği - ilk hazırlık örneği`
   olacaktır. Son örnekten ilk üretim örneğine 1 saniye fark vardır; bitiş
   tanımı dondurulmadan model karşılaştırılmaz. Tanım değiştirilirse yeni
   veri sürümü ve yeniden hesaplanan bütün referanslar gerekir.
3. Her oturum için kaynak kimliği, from/to ürün, toplam dakika ve mevcut
   split tutulur. Eğitim 18, doğrulama 6, test 6 oturum; altı geçiş türünün
   her biri için eğitimde 3, doğrulama/testte 1'er tekrar vardır. Kapsam
   kaynak veriden tekrar kontrol edilir.
4. Başlangıç X yalnız bilinen from/to üründür. Hazırlık sonrasına ait sensör
   ortalaması, son takım listesi veya oturum toplamı özellik yapılamaz.
   Başlangıç anında mevcut sensör eklenirse zaman erişilebilirliği ayrıca
   test edilir; hazırlık boyunca alınan 30/60 saniyelik pencere kullanılmaz.

Bu ilk deneyde çok az özellik vardır; 170 sensör sütununu PCA ile küçültmek
B'nin zorunlu adımı değildir. 30 oturumun tek makine ve altı geçiş kapsamı,
başka makineye/ürüne genelleme iddiasını sınırlar. Görülmemiş geçiş performansı
ayrı deney gerektirir; mevcut split yalnız aynı geçişlerin sonraki tekrarlarını
ölçer. A ve B başka fabrikalara ait olduğu için süreler toplanıp Brandimarte
makinelerine aktarılmaz.

## Karşılaştırma ve karar protokolü

Her görevde aynı bölmelerle şu sıra izlenir:

1. Eğitimden global medyan (DummyRegressor median eşdeğeri).
2. A için faaliyet medyanı → görülmeyende global medyan;
   B için yönlü ürün geçişi medyanı → görülmeyende global medyan.
3. Basit öğrenen karşılaştırma: A'da kategoriler + miktarla küçük ağaç modeli;
   B'de from/to kategorileriyle basit düzenlenmiş doğrusal model.
4. Aynı izinli X ile yerel, sabit sürümlü TabPFNRegressor.
5. Yalnız doğrulama üzerinde karar; test son yöntem dondurulunca bir kez
   değerlendirme için kullanılır. Sonuç kötü çıkarsa gizlenmez veya testte
   tekrar özellik seçilmez. İlk raporda train bağlamı sabit tutulur; daha
   sonra train+validation refit ayrı ve açık protokol değişikliğidir.

DummyRegressor eğitim hedefinin ortalama/medyanı gibi basit kurallar kullanır;
tek başına bir özelliğin katkısını ölçmez. Özellikli/özelliksiz aynı öğrenen
model karşılaştırması gerekir.
[Resmî DummyRegressor tanımı](https://scikit-learn.org/stable/modules/generated/sklearn.dummy.DummyRegressor.html).

Ana ölçüt MAE (dakika), yardımcı ölçüt RMSE. A'da satır MAE ile birlikte her
işe eşit ağırlık veren Case ID başına MAE ortalaması; B'de oturum ve geçiş
başına hatalar raporlanır. Eğitim/doğrulama/test örnek ve grup sayısı, medyan
fallback oranı, seed=0, çalışma süresi ve kaynak checksum'ları eklenir.
Altı test oturumunda tek skor güçlü genelleme kanıtı sayılmaz; bireysel
hatalar ve kapsam açık gösterilir. Önceden garanti edilen başarı eşiği yoktur.
TabPFN referansı geçmezse medyan sonuçları korunur.

İki veri setinin MAE'leri farklı hedef/ölçeklerdedir; tek ortak başarı skoruna
birleştirilmez. CP-SAT makespan metriği de regresyon MAE'si değildir.

## B-online: kalan süre, ayrı isteğe bağlı deney

Mevcut 36.356 satır sadece 30 oturuma aittir. 30 veya 60 saniyelik pencere
aynı oturumda geçmişe bakar ve mevcut saniyede biter. İlk referans
`max(0, eğitimdeki geçiş medyan toplam süresi - geçen süre)` olur.
Sensörler için önceden tanımlı geçmiş pencere özetleri kullanılabilir;
gelecekten doldurma veya oturumun tamamından özet çıkarma yasaktır.
Her oturumdan eşit sayıda, sabit zaman aralıklı tahmin anları seçilir; seçimi
test hedefi belirlemez. Uzun oturumların binlerce satırla bağlamı domine etmesi
önlenir. Pencere uzunluğu/kategori/özellik kararı yalnız eğitim+doğrulamada.
Ana rapor oturum başına MAE ortalamasıdır. MPS/CPU bellek/süre denemesi küçük
eğitim alt kümesinde yapılır; sessizce guardrail kapatılmaz.

## Korelasyon, PCA ve sızıntı

Yunus'un ayrı daldaki ilk korelasyon betiği tüm veriyi kullanıyor; o grafikler
bu protokolde özellik seçiminin girdisi olmayacak. Bir sensörü diğerinden
türetme/kaldırma seçimi eğitim verisi ve erişilebilirlik bilgisiyle yapılır.
Yüksek korelasyon tek başına işe yararlılık, düşük korelasyon gereksizlik
kanıtı değildir. Eksik değer kodları gerçek ölçüm gibi işlenmez.

Kullanılacaksa eksik doldurma, kategori eşlemesi, ölçekleme, korelasyonla
seçim ve PCA yalnız train'de fit edilir; validation/test yalnız transform
edilir. PCA ilk sürüm varsayılanı değildir. PCA bileşen sayısı doğrulamada
seçilir; hedefe bakmadan varyansı koruması süre tahminini iyileştirme garantisi
vermez. sklearn PCA veriyi merkezler ama otomatik ölçeklemez.
[Sızıntı ve pipeline](https://scikit-learn.org/stable/common_pitfalls.html),
[PCA davranışı](https://scikit-learn.org/stable/modules/generated/sklearn.decomposition.PCA.html).

Otomatik kabul kapıları: grup çakışması sıfır; train hedeflerinin erişilebilirlik
sırası; feature whitelist; kaynak satır eşlemesi; yalnız train'den özet;
test görülmemiş kategori geri dönüşü; pencere sonrasındaki sensörleri
değiştirmenin önceki X'i değiştirmemesi. Bunlar tüm olası sızıntıların
yokluğunu kanıtlamaz, tanımlı tehlikeleri yakalar.

## TabPFN sürümü, cihaz ve lisans seçimi

17 Ekim 2026 resmî model listesinde yeni sürümler ile v2 birlikte bulunuyor.
Varsayılan sürüme güvenmek yerine küçük iki görev için **TabPFN v2 regressor**
ilk adayımızdır (10.000 satır/500 özellik önerilen ölçek); paket ve checkpoint
ayrı sabitlenecek. Güncel büyük sürümler varsayılan olarak seçilmeyecek.
Model ağırlıkları ve kod lisansları ayrıdır; v2 Prior Labs License altında,
yeni 2.5/2.6/3/3.5 ağırlıkları ticari olmayan koşullarla listelenmiştir.
[Model listesi ve koşullar](https://docs.priorlabs.ai/models).

v2 regressor lisansındaki ek atıf koşulları, dağıtım/ürün gösterimi öncesi
uygulanır; kaynak lisans ve ağırlık lisansı kaydedilir. Bu araştırma lisansın
her kullanım biçimine uygunluğuna hukuki onay değildir.
[v2 regressor lisansı](https://huggingface.co/Prior-Labs/TabPFN-v2-reg/blob/main/LICENSE.txt).

Kurulum aşamasında Python 3.11 + Apple Silicon için seçilecek paket sürümü
önce bağımlılık çözümlemesi ve küçük gerçek checkpoint smoke testiyle
doğrulanacak; sonra ayrı deney kilidi yazılacak. Henüz test edilmemiş paket
sürümü bu belgede çalışıyor diye sabitlenmiyor. v2 checkpoint açık model
seçimiyle yüklenir; cihaz, ağırlık kimliği/hash, paket/torch sürümü ve seed
rapora girer. CPU/MPS'nin bu makinede hız/bellek yeterliliği ölçülmeden
varsayılmaz. Resmî FAQ küçük verilerde CPU/MPS desteği belirtir.
[Cihaz ve tekrar üretilebilirlik](https://docs.priorlabs.ai/faq),
[açık sürüm seçimi](https://docs.priorlabs.ai/models/selecting-model-version).

Yerel `tabpfn` tercih edilir; `tabpfn-client` bulut çağrısı bu planın varsayılanı
değildir. İlk ağırlık indirmesi ile sonraki yerel çıkarım ayrılır; ağ kapalı
uçtan uca deneme yapılmadan tam çevrimdışı çalışıyor denmez.

## Teslim sırası

1. Yunus'un nihai temizleme/özellik kararlarını sürümleyip iki hedefi dondur.
2. A kaynak satır/duplicate/split kontrolünü, B oturum hedef tablosunu üret.
3. Train-only medyan referansları ve yukarıdaki otomatik kapıları çalıştır.
4. Ayrı ortamda TabPFN paket/checkpoint uyumluluğunu doğrula ve kilitle.
5. İki görevi bağımsız validation karşılaştırmasından geçir.
6. Yöntemleri dondur; son test, süre/bellek ve sınırlamaları raporla.

Veri hazırlanırken bu belge, test girdileri ve adaptör tasarımı ilerleyebilir;
nihai veriyi beklemeden gerçek başarı rakamı veya eğitilmiş model iddiası
üretilmez. Planlama demosunda kullanıcı onaylı süreler varsayılan kalır.

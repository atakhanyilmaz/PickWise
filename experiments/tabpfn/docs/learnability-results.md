# İki süre hedefi için gerçek öğrenilebilirlik deneyi

17 Ekim 2026. **Sonuç: bu ilk protokolde TabPFN v2, iki hedefte de eğitimden
hesaplanan global medyanı doğrulamada geçemedi.** Bu, görevler asla öğrenilemez
demek değildir; mevcut girdiler/hedefler/bölme/model ayarıyla üstünlük kanıtı yok.

Built with PriorLabs-TabPFN.
[Regressor ağırlık lisansının kopyası](licenses/TabPFN-v2-reg-LICENSE.txt),
[resmî lisans kaynağı](https://huggingface.co/Prior-Labs/TabPFN-v2-reg/blob/main/LICENSE.txt).

## Gerçekte çalıştırılan

İki ayrı `TabPFNRegressor.create_default_for_version(ModelVersion.V2, ...)`
örneği kullanıldı; aynı önceden eğitilmiş checkpoint'e ayrı eğitim bağlamları
verildi. Ağırlıklar sıfırdan eğitilmedi/fine-tune edilmedi. Paket tabpfn 9.2.0,
torch 2.14.1, pandas 2.2.3, numpy 2.1.3, sklearn 1.9.1; cihaz CPU, seed 0,
4 ensemble estimator. Tam ortam `experiments/tabpfn/requirements-lock.txt` içindedir.
İndirilen gerçek checkpoint ve kaynak CSV hash'leri JSON raporundadır.

Ana uygulamanın `.venv` ortamı değiştirilmedi; ayrı `.venv-tabpfn` kullanıldı.
CSV dosyaları bulut tahmin API'sine gönderilmedi; v2 ağırlıkları indirildi.
İlk font/cache/import maliyetleri raporlanan fit+predict süresine dahil değildir.
Ağ kapalı uçtan uca çalışma ayrıca test edilmedi.

## Hedefler ve bilinen girişler

1. **Toplam gözlenen iş aralığı:** son kayıt bitişi − ilk kayıt başlangıcı.
   72 eğitim işi, 17 doğrulama işi. X yalnız parça açıklaması (kategori) ve
   sipariş miktarı. Net makine süresi veya doğrulanmış sevk süresi değildir.
2. **Koşullu makine kaynakları arası bekleme:** zaman/tekrar kontrollerini
   geçen ardışık makine adı taşıyan iki kayıt için B başlangıcı − A bitişi.
   106 eğitim çifti / 52 iş, 13 doğrulama çifti / 8 iş. X parça, miktar,
   kaynak makine ve hedef makinedir. Hedef makinenin tahmin anında önceden
   atanmış olduğu varsayılır; bu atamanın gerçekten bilindiği kaynak veride
   doğrulanmadı. Bu nedenle retrospektif koşullu deneydir, operasyonel kanıt değil.

İlk denetimde makine sayımında yalnız Turning & Milling seçilmişti;
Grinding/Milling/Lapping vb. dışarıda kalmıştı. Sayım ve veri üreticisi bütün
Machine / Wire Cut - Machine adlarını kapsayacak şekilde düzeltildi. Model
deneyi düzeltilmiş alt kümede yapıldı; eski 1 eğitim çifti sayısı kullanılmadı.

## Doğrulama hataları

MAE düşükse daha iyi. Toplam hedefte her satır zaten bir iş; geçişte ana ölçüt
her işe eşit ağırlık veren **iş bazlı MAE ortalaması**dır. Aşağıdaki gün/saat
değerleri yuvarlatılmıştır; kaynak JSON dakika cinsindedir.

| Yöntem | Toplam iş aralığı MAE (gün) | Geçiş iş bazlı MAE (saat) |
| --- | ---: | ---: |
| Global medyan | 6,56 | 29,67 |
| Grup medyanı | 7,40 | 32,05 |
| ExtraTrees basit öğrenen model | 9,76 | 41,79 |
| Gerçek TabPFN v2 | 7,89 | 39,25 |

Grup medyanı toplamda parça, geçişte yönlü makine çifti üzerinden eğitimde
hesaplandı; görülmeyen grupta global medyana döndü. Toplamda 17 doğrulama
işinin 7'sinin parçası eğitimde yok; 7 kez fallback. Geçişte 13 çiftin 8'inde
parça eğitimde yok; yönlü makine medyanı 4 çiftte fallback kullandı.

Geçiş satırlarını eşit ağırlıkla hesaplayan yardımcı MAE medyanda 38,90 saat,
TabPFN'de 45,41 saat. Her iki ağırlıklandırmada da TabPFN daha kötü. Toplamda
TabPFN'nin MAE'si global medyandan yaklaşık %20,4, geçiş iş bazlı MAE'si
yaklaşık %32,3 daha yüksek. Yüzdeler yalnız bu doğrulama örnekleminin özeti.

İş bazlı eşlenik bootstrap ile global medyana göre TabPFN MAE iyileşmesi:
toplamda -1.924,42 dakika, keşifsel %95 aralık [-3.386,61; -417,38];
geçişte -574,45 dakika, aralık [-1.091,21; -7,14]. Pozitif değer iyileşme
anlamına gelirdi. Yalnız 17/8 iş ve zamansal bağımlılık nedeniyle bu aralıklar
saha güvenilirliği veya güçlü istatistiksel genelleme iddiası değildir.

## Sızıntıya karşı uygulanan sınırlar

- Case ID train/validation arasında ayrık; eğitim işlerinin tüm hedefleri
  ilk doğrulama işinden önce tamamlanmış. Sınır aşan karantina dışarıda.
- Test başarısı hesaplanmadı. Nihai testle özellik seçimi yapılmadı;
  önceki bütünlük analizlerinin test bölümünde betimleyici sayım yaptığı açık.
- Parça kategorileri, ordinal/one-hot kodlama ve medyanlar yalnız eğitimden
  öğrenildi. Validation bilinmeyen kategorileri geri dönüşle işlendi.
- Başlangıç/bitiş, gerçekleşmiş miktarlar, son iş istasyonu veya toplam
  gerçekleşmiş rota X'e girmedi. Geçiş hedefi/from-to bilgisi yukarıdaki
  koşullu atama varsayımına bağlı; ileriye dönük uygunluğu kanıtlanmış değil.
- Tahminler aynı protokolle sıfır altından kırpıldı; hedefler kırpılmadı,
  testte ayar seçilmedi. PCA veya korelasyonla özellik seçimi yapılmadı.
- Hata hesapları ve bootstrap iş bazında; tekrar satırları bağımsız iş sayılmadı.

Bu kontroller tüm olası sızıntıların yokluğunu kanıtlamaz. Özellikle kaynakta
gerçek iş kabul/sevk uçları, parti ilişkileri ve önceden planlanmış hedef
makine bilinmediğinden ürünün operasyonel tahmin kalitesi onaylanmış değildir.

## Karar ve sonraki adım

İki model ürün akışına bağlanmayacak. Kullanıcı onaylı süreler varsayılan.
Medyan da 6,56 günlük/29,67 saatlik hatası nedeniyle güvenilir teslim önerisi
sayılmaz. Bu sonuç model sayısını artırmak yerine önce hedef/girdi kalitesini
iyileştirme gereğini gösteriyor.

Öncelik: iş başlangıcında gerçekten bilinen planlı rota/kapasite/takvim gibi
alanları ve kaynak/hedef makine atamalarını doğrulamak; report-row/parti
semantiğini çözmek. Daha sonra yeni protokol ve yeni doğrulama dönemiyle
deney yapılabilir. Doğrulamada başarısız sonucu saklayıp final testte yeniden
ayar aramak yok. Bu tek deney "TabPFN kötü model" sonucu da değildir.

## Tekrar üretme

```sh
python3.11 -m venv .venv-tabpfn
.venv-tabpfn/bin/python -m pip install -r experiments/tabpfn/requirements-lock.txt
.venv-tabpfn/bin/python -m experiments.tabpfn.learnability --tabpfn --device cpu
```

`experiments/tabpfn/results/learnability/validation_report.json` ve iki validation prediction CSV
gerçek model sonuçlarıdır. Checkpoint/önbellek Git dışında. Tekrar çalıştırma
aynı validation raporunu yeniden üretir, test skoruna geçmez. Yalnız referans
ve basit model için `--tabpfn` çıkarılabilir; gerçek model yerine mock yoktur.

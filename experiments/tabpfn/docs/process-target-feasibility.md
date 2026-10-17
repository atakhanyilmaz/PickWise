# Makineden makineye geçiş ve toplam süreç: veri yeterliliği

17 Ekim 2026. Kullanıcı hedefi: (1) A makinesinden B makinesine geçiş süresi,
(2) işin tüm süreçte geçen süresi. Bu hedef ürün A→B changeover hedefi değildir;
önceki `two-regression-experiment-plan.md` CNC toplam hazırlık önerisi bu yeni
isteğin yerine geçmez.

Kaynak: mevcut Production Analysis ham CSV ve iş emri bölme manifesti.
Yeniden üretilebilir kontrol: `experiments/tabpfn/process_target_audit.py`.
Ayrıntılı sayımlar/checksum'lar `experiments/tabpfn/results/process_target_audit/summary.json`;
iş bazında sonuç `cases.csv`; aday aralıklar `adjacent_resource_pairs.csv`.
Kaynak değiştirilmedi; model eğitilmedi. Bütün bölümlerde yalnız betimleyici
veri bütünlüğü sayımları yapıldı, test skoruyla yöntem/özellik seçilmedi.

## Karar

**İki hedef için küçük bir deney kurulabilir; gerçek makineden makineye
transfer süresi için etiketlerin fiziksel anlamı hâlâ doğrulanmadı.**
İlk incelemede makine alt kümesi yanlışlıkla yalnız Turning & Milling adlarıyla
sınırlandı. Aşağıdaki güncellenmiş sayım Machine ile başlayan kaynakları ve
Wire Cut - Machine kaynağını da kapsar. Eski 23 aday/1 eğitim çifti sayısı
bütün makineleri temsil etmiyordu; bu hata düzeltildi.
"Veri var" ile "istenen tahmin hedefi için yeterli bağımsız örnek var" farklıdır.
Bu inceleme işin tamamlandığını veya sevk edildiğini kanıtlamaz.

## Toplam iş aralığı

- Ham 4.543 kayıt, 225 Case ID ve 31 farklı kaynak/istasyon.
- Hedef adayı: `max(Complete Timestamp) - min(Start Timestamp)`.
- Her iş emrinde parça açıklaması ve sipariş miktarı tek değer; bu, kayıtların
  aynı bölünmez parçaya ait olduğunu veya operasyonların seri olduğunu kanıtlamaz.
- İş bazlı hedef medyanı 20.018 dakika, yaklaşık 13,9 gün. Bu net makine
  süresi değildir; kayıtlar arasındaki bekleme/gece/hafta sonu da dahildir.
- Mevcut kronolojik bölmede eğitim 72 iş, validation 17 iş, test 45 iş;
  91 sınır aşan iş karantinadadır. Karantina rastgele bölmelere dağıtılmadı.
- Eğitim hedef medyanı 14.843,5 dakika (~10,3 gün), validation 8.275 dakika
  (~5,7 gün), test 5.766 dakika (~4,0 gün). Dağılım farkı ve uzun işlerin
  karantinada kalması raporlanmalı; performans tahmini veya neden kanıtı değildir.

Hedef, operasyon sürelerini toplamakla üretilmedi: örtüşen/bekleyen aralıklar
vardır. İş başlamadan bilinen parça/miktar gibi bilgiler X olabilir;
gerçekleşmiş son istasyon, son rapor zamanı, tamamlanan miktarlar veya bütün
gerçekleşmiş rota X'e konulamaz. İşin ilk kaydı sipariş kabulü, son kaydı sevk
olarak doğrulanmadığı için isim `observed_case_span_minutes` kalmalı.
72 eğitim işi başlangıç medyan referansı ve deneysel regresyon için bir
başlangıçtır; güvenilir saha başarısı garantisi değildir.

## A makinesinden B makinesine aday aralıklar

Yöntem: aynı Case ID içinde kayıtları başlangıç, bitiş, kaynak satır sırasıyla
sırala; ardışık iki farklı Resource için `B.start - A.end` hesapla.
Bu işlem gerçek öncül/rota ilişkisini doğrulamaz. Eşit başlangıçlar, tekrar
olaylar ve daha önce başlamış bir kaydın B anında hâlâ sürmesi işaretlenir;
negatif farklar eğitim etiketi diye kullanılmaz.

| Sayım | Sonuç |
| --- | --- |
| Farklı kaynaklar arasındaki ardışık kayıt çifti | 2.290 |
| Negatif fark | 570 |
| Sıfır fark | 69 |
| Pozitif fark | 1.651 |
| Zaman/tekrar/eşit başlangıç elemesini geçen aday çift | 1.556, 207 iş |
| Bu adayların eğitim / validation / test satırı | 402 / 69 / 123 |
| Bu adayların eğitim / validation / test işi | 68 / 14 / 34 |
| Kalan adayların karantina satırı | 962 |
| İki ucu da makine adı taşıyan aday çift | 418, 153 iş |
| Bu makine çiftlerinin eğitim / validation / test satırı | 106 / 13 / 30 |
| Bu makine çiftlerinin eğitim / validation / test işi | 52 / 8 / 16 |

Diğer adayların önemli kısmı makine–kalite kontrol–markalama gibi istasyon
geçişleridir. Kaynağın Machine / Wire Cut - Machine adı burada yalnız
sayısal alt küme seçimidir; bağımsız makine donanımı doğrulaması değildir.
Genel istasyon adaylarının medyan aralığı 533 dakika (~8,9 saat);
447 aday bir günden uzun. Bunlara saf taşıma süresi demek doğru olmaz.

Alternatif hassasiyet kontrolü: kalite/diğer istasyon kayıtlarını atlayıp yalnız
ardışık makine adı taşıyan kaynaklara bakınca 975 çift / 181 iş bulunur.
Bunların 751'i negatif olmayan aralık; train 182, validation 25, test 51,
karantina 493. Aradaki işlemleri atlamak doğrudan transfer
kanıtı sağlamaz. Bu alternatif veri silme veya nihai eğitim kararı değildir.

## Rota çıkarımını engelleyen işaretler

- 160/225 işte en az bir örtüşen rapor aralığı.
- 71 işte eşit başlangıç zamanları.
- 38 işte seçilen olay anahtarının tekrarları.
- Tam ham satır tekrar fazlası 22; olay anahtarı tekrar fazlası 50.
- Report Type S/D/B'nin kesin anlamı ve parça/parti bazlı raporlama belirsiz.

Bu olayların tümü hata değildir: kısmi raporlama, paralel işler, parti bölünmesi
veya rework olabilir. Otomatik silinmedi. Aynı işte kayıtları sıraya dizmek
tek başına A'nın çıkışının B'nin girdisi olduğunu göstermiyor.

## Sonraki adım

1. Toplam gözlenen iş aralığı için kaynak kimlikli 225 satırlık aday tablo,
   bölme ve eğitimden medyan referansı üretilebilir; model hedefi deneysel adla kalır.
2. Geçiş modeli isteniyorsa önce tanımı seç: tüm istasyonlar arası gözlenen
   bekleme mi, yalnız fiziksel makineler arası taşıma mı? İkincisi için mevcut
   etiketler taşıma süresini doğrulamıyor. Makine adı taşıyan kaynaklar arasında
   106 eğitim adayı var; koşullu bekleme deneyi yapılabilir. Genel istasyonlar
   için 402 eğitim adayı var. İkisinde de öncül/parti/rapor onayı hâlâ gerekiyor.
3. Gerçek transfer için ideal kayıtlar: aynı iş/parça/parti kimliği, doğrulanmış
   kaynak-hedef makine, çıkış/varış/işlem başlangıcı ve ölçülmüş taşıma/bekleme
   ayrımı. Tahmin anında bilinen atamalar ayrıca belirtilmeli.
4. CNC verisi tek makinedeki ürün hazırlığına ait ayrı deney olarak korunur;
   eksik çok makineli transfer verisinin yerine konulmaz.

Komut:

```sh
.venv/bin/python -m experiments.tabpfn.process_target_audit
.venv/bin/python -m pytest -q experiments/tabpfn/tests/test_process_target_audit.py
```

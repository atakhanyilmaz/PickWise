# 002 — Atölye kısıtlarını gerçekten uygulama

Tarih: 16 Ekim 2026. Kapsam: WP-2A incelemesindeki dört eksik.

Benchmark girdileri kaynak FJSP modeliyle çalışmaya devam eder. `build_env`
çıktısındaki atölye senaryosu varsa `solve` ayrı `workshop_model` kullanır.
Kaynak kod değiştirilmez. Bu ayrım, kaynak modelin toplam süreye göre kurduğu
ufkun büyük hazır olma zamanlarını/duruşları dışarıda bırakmasını da önler.

## Zaman ve operasyon durumu

Bütün zamanlar aynı t=0 referansından tamsayı dakikadır. `current_time` yeniden
planlama anıdır. Başlamamış operasyonlar bundan ve işin `release_time` değerinden
önce başlayamaz. Takvim dönüşümü bu katmanın dışındadır; sürekli çalışma kabul edilir.

Tamamlanmış operasyon için `fixed_machine_id`, `fixed_start`, `fixed_end`
zorunludur. Kayıtlı gerçek süre `fixed_end - fixed_start` kullanılır; eski plan
süresine eşit olması gerekmez. Bitiş `current_time` sonrasında olamaz.

Devam eden operasyon için gerçek makine, başlangıç ve kullanıcı tarafından
belirtilen pozitif `remaining_duration` zorunludur. Operasyon bölünmez; işgal
aralığı `[fixed_start, current_time + remaining_duration)` olarak korunur.
Kalan süre, eski tahminden sessizce çıkarılmaz. Fiilen devam eden işi duruş
nedeniyle bölmek/taşımak desteklenmez; çelişkili kısıtlar INFEASIBLE üretir.

Başlamış operasyonlar rota başından tutarlı bir önek oluşturmalıdır. Makine
ve süre seçimi sözlükteki ilk makineye dayanmaz. Kullanılmayan sabit alanlar ve
bilinmeyen alanlar reddedilir; modelde olmayan bir kısıt sessizce atlanmaz.

## Termin, duruş ve hedef

`deadline` sert termindir: son operasyon bitişi <= deadline. Hedef, bu sınırlar
altında makespan azaltmadır. Yumuşak termin, gecikme ağırlıkları veya müşteri
önceliği bu sözleşmede bulunmaz.

Makine duruşları `[başlangıç, bitiş)` sabit aralıklarıdır; operasyonlarla aynı
NoOverlap kısıtına girer. Duruş sınırına dokunmak serbesttir. Geçersiz ve birbiriyle
çakışan duruş girdileri reddedilir. Tamamlanmış işle çelişen duruş silinmez;
modellenen senaryo INFEASIBLE olur.

## Kimlikler, öncüller ve doğrulama

Kaynak operasyon kimliği `(job_id, operation_id)` çiftiyle tanımlıdır. Ortamdaki
operasyon kimlikleri global benzersizdir. Öncül tablosu operasyon → önceki
operasyon şeklindedir; aynı bilgi operasyon nesnesine de yazılır. Sonuç satırları
0 tabanlı iç kimliklere ek olarak `source_job_id`, `source_operation_id`,
`source_machine_id` alanları taşır.

`validate_workshop` çözücüden bağımsız şekilde orijinal senaryoya göre sabit
aralık, süre, makine, termin, hazır olma, şimdi ve duruş denetimi yapar. Uygulanabilir
atölye sonuçları dönüşten önce denetlenir. Çözüm bulunmayan durumda ihlal sayısı
None'dır; doğrulanmış çizelge gibi sunulmaz.

Varsayılan rota kapısı retrospektif rotayı engeller. `approved_only=False`
yalnız açık retrospektif simülasyon içindir; sonuç retrospektif olarak etiketlenir.
Sentetik demo rotaları gerçek kullanıcı onayı gibi etiketlenmez.

## Sınırlar

SQLite plan sürümü, yeni sipariş karşılaştırma servisi, UI, vardiya/mola ve
sevkiyat/ticari kapanış yönetimi bu değişikliğin kapsamı değildir. Boş işler ve
kaynak listeleri reddedilir. Pydantic 2.14.1 ve geçişli bağımlılıklar kilitlenmiştir.

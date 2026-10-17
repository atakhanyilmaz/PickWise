# ADR 0003 — CNC kalan changeover süresi hedefi

## Durum

Kabul edildi — 17 Ekim 2026.

## Karar

CNC akışındaki deneysel regresyon hedefi
`remaining_changeover_time_min` olacaktır. Her `Label_03 = 0` satırı için hedef,
aynı kesintisiz changeover oturumunun son zaman damgası ile mevcut zaman damgası
arasındaki dakika farkıdır. Hedef gerçek duvar saati süresidir ve gerçekleşmiş
kesintileri içerir.

Model girdisi son 30 veya 60 saniyelik sensör penceresidir. Eğitim, doğrulama ve
test ayrımı satır bazında değil tam oturum bazında 18/6/6 yapılır. Mutlak zaman,
oturum kimliği, tüm `Label_*` alanları ve geleceği kodlayan program sayaçları
özellik olarak kullanılmaz.

`Line_Content` komut metni ürün ve NC programını ezberletmemek için model
adayından çıkarılır. Yalnız devam eden changeover sırasında canlı kontrolcüden
okunabilen `nc_line_is_active` ikili özelliği tutulur. Bu özellik sipariş henüz
başlamadan yapılan planlama tahmininde kullanılamaz.

Kaynağın bilinçli olarak koruduğu CNC boşlukları mod veya medyanla doldurulmaz.
`Tool_ID` için `__NO_TOOL_IN_SPINDLE__` ve ayrı eksiklik göstergesi kullanılır.
Anlamı yeterince doğrulanmamış, kontrolcüye ve makine magazinine özgü dört alan
(`Tool_ID_Magazine_Place_49` ve üç `Magazine_9999_*`) değer uydurulmadan model
adayından çıkarılır.

## Sonuçlar

Bu hedef 52.026 satırı bağımsız örnek saymaz; satırlar 30 oturum içinde zaman
bağımlıdır. Model yalnızca aynı makinedeki devam eden changeover'ın kalan süresini
tahmin eder. Başka makinelerin paralel çizelgelenmesi ve sipariş teslim zamanı,
bu tahmin çözücüye girdikten sonra ayrıca hesaplanır.

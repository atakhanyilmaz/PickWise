# ADR 0002 — Production Analysis geçen süre hedefi

## Durum

Kabul edildi — 17 Ekim 2026.

## Karar

Bu ADR, ADR 0001'deki geçici `recorded_duration_min` hedef adını değiştirir.

Production Analysis regresyon adayında hedef, dakika cinsinden
`target_elapsed_time = Complete Timestamp - Start Timestamp` olarak üretilir.
Bu alan doğrulanmış saf makine çalışma süresi değil, kayıtta gözlenen geçen süredir.

Hedef tablosuna yalnızca şu satırlar alınır:

- başlangıç ve bitiş damgaları geçerlidir;
- geçen süre sıfırdan büyüktür;
- `Span` ayrıştırılabilir ve damga farkıyla en fazla 1 dakika ayrışır.

Hedef oluşturulduktan sonra `Rework`, kaynak zaman damgaları, `Span` ve bunlardan
türetilmiş inceleme alanları model adayından kaldırılır. Ham ve impute edilmiş
inceleme dosyaları değiştirilmez.

## Gerekçe ve sonuçlar

İki süre gösteriminin uyuştuğu alt küme, çizelgeleme süresi tahmini için daha
temkinli bir başlangıç etiketidir. Bir dakikalık tolerans dakika çözünürlüğündeki
yuvarlama farkını kabul eder. Bunun karşılığında veri azalır ve seçilim yanlılığı
oluşabilir. `Report Type` değerlerinin (`S`, `D`, `B`) anlamı ve satırların gerçek
operasyonlara nasıl birleştirileceği doğrulanana kadar bu hedef deneysel kalır.

# 010 — Başlamış operasyonları koruyan planlı duruş simülasyonu

17 Ekim 2026. Makine duruşu kısıtı çözücüde vardı, tipli olay ve önce/sonra
akışı eksikti. `core/downtime.py` yeni senaryo üretip aynı bağımsız
doğrulayıcıdan geçen sonucu ve mevcut iş etkilerini döndürür. Sipariş
karşılaştırmasının makine eşitliği kapısı korunur; ayrı duruş karşılaştırması
yalnız ek kullanılamayan aralıkları kabul eder, iş verisini değiştirmez.
Ortak etki hesabı `core/scenarios.py` içinde küçük yardımcıya ayrıldı.

Geçmişe yeni duruş ekleme ve devam eden operasyonu kesme desteklenmez;
açıkça reddedilir. Operasyonlar bölünemez. Mevcut kısıtlar korunur,
isteğe bağlı eski bitiş koruması ayrıca sert sınırdır. Simülasyon kaydetmez;
uygulanabilir sonuç kullanıcı seçimiyle SQLite'a yeni sürüm olabilir.

Mevcut kaynak/benchmark modeline müdahale edilmedi. Yeni framework yok.
Sentetik CLI/HTML örneği ve ilgili testler `docs/downtime-simulation.md`
içinde; gerçek zaman dönüşümü ve doğal dil araç entegrasyonu ayrı aşamadır.

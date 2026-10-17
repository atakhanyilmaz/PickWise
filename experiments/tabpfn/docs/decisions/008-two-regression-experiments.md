# 008 — İki veri kaynağını bağımsız regresyon deneyleri olarak değerlendirmek

17 Ekim 2026. İstek: veri hazır olunca iki süre modeli için araştırma planı.

Production Analysis hedefi rapor satırının gözlenen geçen süresidir; operasyon
anlamı doğrulanmadan makine işlem süresi diye kullanılmaz. Kullanıcının A→B
hazırlık sorusu için CNC toplam süre deneyi oturum başına bir kayıtla kurulur.
Mevcut sensör satırı kalan süre hedefi ayrı online deney olarak tutulur.
Kaynaklar başka fabrikalara ait olduğundan solver'a birlikte bağlanmaz.

Her görevde eğitimden medyan referansı, basit öğrenen model ve TabPFN
aynı grup/zaman bölmelerinde karşılaştırılır. İlk TabPFN adayı açık seçilmiş
v2 regressor'dür; paket/checkpoint kilidi uyumluluk testi sonrası yapılır.
PCA zorunlu değildir; ön işleme ve seçim yalnız eğitimde öğrenilir.
Deney planı uygulanmış model veya ölçülmüş başarı değildir.

Araştırma, kaynak bağlantıları ve uygulama kapıları:
`docs/two-regression-experiment-plan.md`.

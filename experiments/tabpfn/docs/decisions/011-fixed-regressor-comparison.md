# 011 — MAE odaklı üç regresyon adayının sabit bütçeyle karşılaştırılması

17 Ekim 2026. Kullanıcı QuantileRegressor, CatBoost ve küçük Gradient
Boosting sonuçlarını görmek istedi. Aynı train/validation örnekleriyle,
birer sabit ayarla gerçek fit/predict yapıldı. Ana uygulamaya müdahale yok;
ayrı ortam ve deney paketi korunur. Final test skoru hesaplanmadı.

Önceki validation görülmüş olduğundan bu tur keşifseldir. Toplamda medyan
en iyi; geçişte medyan regresyonunun 0,6875 dakika iş bazlı MAE farkı ve
sıfırı kapsayan bootstrap aralığı ek fayda kanıtı sayılmaz. Yeni modeller
ürüne bağlanmaz. Hedef/veri/özellik doğrulaması algoritma sayısından önce gelir.

Detay ve sayısal raporlar: `../regressor-comparison-results.md`.

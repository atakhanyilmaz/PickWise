# ADR 0004 — Süre hedefleri için özellik seçimi ve çıkarımı

Kabul edildi — 17 Ekim 2026; deneysel veri hazırlığı.

İki veri setinin hedefleri ADR 0002/0003'teki anlamıyla korunur. Production
Analysis gözlenen rapor aralığını, CNC devam eden hazırlığın kalan süresini
tahmin etmeye hazırlanır. Yeni sipariş başlamadan CNC sensör geçmişinin
kullanılabildiği varsayılmaz.

Önce tahmin anında bilinen girdiler seçilir. Production'da parça, planlanan
miktar ve operasyon adaydır; gerçekleşen miktarlar, rapor türü, iş/çalışan
kimliği ve önceden atandığı doğrulanmayan kaynak dışarıda kalır. CNC'de etiket,
hedef, mutlak zaman, oturum, pencere uygunluk işaretleri ve gelecek sayaçları
girdi değildir. Takım, magazin yuvası ve kontrolcü durum kodları nominaldir.

Sayısal varyans aralıkla normalize edilerek süzülür; baskın kategori, yüksek
mutlak Pearson ve nominal birebir eşleme tekrarları çıkarılır. Sürekli
ölçümlerde VIF uygulanır; ardından mutual information ve SelectKBest ile
CNC'de en fazla 24, Production'da en fazla 3 kaynak özelliği tutulur. L1/Lasso
ayrı bir tanıdır; sıfır doğrusal katsayı, doğrusal olmayan ilişkiyi tek başına
elemek için yeterli sayılmaz. Eşikler deney öncesi sabittir; optimum oldukları
iddia edilmez.

Seçim, kategori sözlüğü, eksik değer istatistikleri, ölçekleyici ve PCA yalnız
eğitimde öğrenilir. CNC seçimi/VIF/MI tanılarında uzun oturumların baskınlığını
azaltan, en fazla 6.000 satırlık oturum dengeli örnek kullanılır. Varyans ve
korelasyon tüm eğitim satırlarını kullanır. Satırlar bağımsız deney sayılmaz.

Seçimden sonra CNC'de oturum içi, sadece geçmiş/mevcut 30/60 saniyelik tam
pencerelerden ortalama, standart sapma, minimum, maksimum, fark ve kategori
değişim sayıları üretilir. İlk 59 saniyenin 60-saniye penceresi yoktur;
gelecekten doldurulmaz. Production'da miktarın log1p dönüşümü kullanılır.
One-hot ve standardizasyonun ardından eğitim varyansının en az %95'ini
koruyan PCA ayrı bir matris olarak üretilir.

İş emri bazlı kronolojik ayırma ve sınır karantinası; CNC'de tam oturum bazlı
18/6/6 ayırma korunur. Sabit Ridge tanısının seçilmiş/türetilmiş/PCA temsilleri
ve eğitimden hesaplanan medyan referansı doğrulama grup-makro MAE'siyle
karşılaştırılır. Temsil kilitlendikten sonra test yalnız bir kez ölçülür.
PCA otomatik olarak daha doğru veya zorunlu son model kabul edilmez.

Ham/hedef CSV'ler değişmez. Kullanıcının klasör düzeni isteğine göre üç eğitim
CSV'si `data/dataforNewVersion/biPre/`, diğer ara matrisler
`data/dataforNewVersion/biPre_intermediate/` altındadır. Seçim gerekçeleri, PCA
yükleri ve yeniden kullanılabilir dönüşümler `reports/duration_features/` altında tutulur.
Üretim veri anlamı, CNC fiziksel sınırı ve başka makinelere aktarım sorunları
çözülmüş sayılmaz. Bu deney TabPFN kıyaslaması veya operasyonel model onayı değildir.

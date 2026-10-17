# 17 Ekim 2026 — Proje görev çetelesi

Kontrol edilen main: dcae83b. Uzak main ile yerel HEAD aynı; kontrol öncesi çalışma
ağacı temizdi. Veri hazırlama dalı: origin/data_preprocesing, b5d99a1 (Yunus).
Bu rapor sırasında dal birleştirilmedi; commit/push yapılmadı.

Kaynak görev dağılımı: docs/18_ekim_hedefli_i_terasyon_ve_adil_i_paketi_sunumu.md.
18 Ekim ekip içi çalışma hedefidir; yarışmanın resmî teslim şartı/tarihi bu
kontrolde doğrulanmadı. Durumlar repo kanıtına dayanır; ekip üyelerinin bilgisayarında
henüz pushlanmamış işleri hakkında tamamlanma hükmü verilmez.

## Doğrulanmış çalışanlar

- Kaynak sabit commit, FJSP parser/model adaptörü, açık kaynak atıfları.
- Mk01–Mk10 karşılaştırması; önceki toplu çalıştırmada 20 geçerli çizelge, 0 ihlal.
- Bağımsız doğrulayıcı ve atölye Pydantic modelleri.
- Alternatif makine/süre, öncüller, gerçek makinede sabit geçmiş ve kalan süre.
- Hazır olma, current_time, sert termin ve makine duruşu kısıtları.
- Başlangıcı değiştirmeyen yeni sipariş simülasyonu; kaynak kimlikleri ve sürüm kontrolü.
- Önce/sonra metrikleri, yumuşak termin gecikmeleri, mevcut bitiş koruma kısıtları.
- Sentetik demo: başlangıç 15; tek makine sonrası 25 ve 5 dakika termin gecikmesi;
  alternatif makine sonrası 17 ve 0 gecikme; tek makine + bitiş koruması INFEASIBLE.
- Plotly HTML/JSON/CSV çıktıları, CLI ve model olmadan manuel giriş.
- Gerçek yerel Gemma ile tam sipariş örneği; onaydan sonra CP-SAT ve sayısal açıklama.
- Model metadatası, kullanıcı onayı kapısı, hesaplanan bulgu seçimine dayalı açıklama.
- Süre deneyi kontratı, zaman/iş emri/duplicate kontrolleri, eğitim medyanı ve MAE/RMSE.

Bu tur main üzerinde 140 pytest testi, Ruff ve git diff --check geçti. Gerçek
Gemma/model deneyi tekrar çalıştırılmadı; kayıtlı son istem v2 smoke sonucu 3/5.
Birim testleri gerçek model doğruluğu değildir.

## 15 iş paketi

| Paket | Sorumlu | Durum ve teslim kanıtı | Kalan |
|---|---|---|---|
| WP-1A | Atakan | Çekirdek tamam; core/cpsat_solver.py, benchmarks/brandimarte_runner.py | Referans job-order/EFT; başlangıç sunumundaki FIFO/SPT ile aynı olduğu söylenmemeli. |
| WP-2A | Atakan | Kısmen; modeller, rota kapısı, kaynak etiketi, alternatif makine hazır | Gerçek rota/veri adaptörü, sevkiyat-ticari kapanış için ayrı iş durumu ve testleri. |
| WP-3A | Atakan | Altyapı hazır; ml_experiments/duration_evaluation.py | Gerçek hedef tablosu, TabPFN sürüm/kullanım hakkı, model adaptörü, gerçek MAE karşılaştırması, kullanıcı süresine fallback ve planlama entegrasyonu. |
| WP-4A | Atakan | Sipariş senaryosu hazır; core/scenarios.py ve workshop_model.py | Duruş için ayrı değişiklik isteği/önce-sonra servisi; değişen sipariş API'si. Duruş kısıtı tek başına olay yönetimi değildir. |
| WP-5A | Atakan | Deneysel; core/llm ve CLI; tam gerçek model örneği geçti | Belirsizlik güvenilirliği, takip mesajları, gerçek tarih dönüşümü, doğal dille duruş/birleşik talep. |
| WP-1Y | Yunus | Kısmen; ortak Pydantic modellerini kullanabilir; veri sözleşmesi ayrı dalda | SQLite jobs/resources/operations/data_lineage/plan_versions ve veri adapter eşlemesi. |
| WP-2Y | Yunus | Ayrı dalda ilk profil/kalite raporları, kaynak hash'leri ve manifestler | Report Type anlamı, duplicate/rework/span incelemesi, onaylı operasyon agregasyonu, dondurulmuş temiz alt küme. |
| WP-3Y | Yunus | Ayrı dalda iş emri/zaman temelli train/validation/test manifesti | Bölmeyi bağımsız doğrulama, kalite filtreleri, sınır işleri ve özellik matrisi, bizim kontrata aktarım. |
| WP-4Y | Yunus | Bellek içi karşılaştırma ortak çekirdekte mevcut | SQLite onaylı sürüm kaydı, eski sürüm kontrolü, DB sürümleri üzerinden diff. |
| WP-5Y | Yunus | Repoda uygulama görünmüyor | Geçmiş özetler, yalnız izinli geçmişten indeks, embedding modeli/arama, veri kaynağı bağlantısı. |
| WP-1N | Nazlısu | Plotly çıktılarımız kullanılabilir; Streamlit uygulaması görünmüyor | Plan/benchmark yükleme, sonuç ve çözüm durumu ekranları, kaynak atfı. |
| WP-2N | Nazlısu | Backend rota onayı/veri kaynağı alanları hazır | Rota düzenleme/onay ekranı, süre kökeni rozetleri ve varsayımlar. |
| WP-3N | Nazlısu | Gerçek model deneyini bekliyor | Tahmin-gerçek/medyan grafikler, metrik ve örnek sayıları, süre kaynağı seçimi. |
| WP-4N | Nazlısu | Karşılaştırma servisi ve HTML örnek hazır | UI sipariş/duruş girdisi, önce/sonra Gantt, etkilenen iş tablosu, kaydetme bağlantısı. |
| WP-5N | Nazlısu | Repoda final UI/video görünmüyor | Gemma/arama kartları entegrasyonu, kaynak-katkı ayrımı, tekrar üretilebilir kısa video. |

## Yunus'un yeni dalı

Dal: data_preprocesing. Commit: b5d99a1. Kod ve raporlar okundu; hazırlama
betiği bu rapor sırasında çalıştırılmadı. Aşağıdaki sayılar kayıtlı raporundan,
bağımsız yeniden hesaplama sonucu değildir.

- Production Analysis: 4.543 rapor satırı, 225 iş emri.
- Başlangıç/bitiş–span farkı >1 dakika: 699 satır; span'ın HH:MM yorumunun ve
  iş süresi anlamının ayrıca doğrulanması gerekir.
- Birebir duplicate grubuna dahil 41 satır, ilkleri tutma hesabıyla 22 fazla satır.
- Olay anahtarı tekrarına dahil 97 satır, aynı hesapla 50 fazla satır. Bu sayılar
  birebir duplicate sayısıyla toplanamaz; kümeler örtüşebilir.
- 9 sıfır süre, 1 biçimsiz span; rapor bunları review olarak işaretler, silmez.
- Bölme: train 72 iş/1.029 satır; validation 17/179; test 45/397;
  zaman sınırını aşan karantina 91/2.938. Rapor grup çakışmasını 0 bildiriyor.
- Bu satırlar onaylanmış operasyon/hedef sayısı değildir. Bölme manifesti kalite
  filtresi yerine geçmez. Report Type S/D/B ve agregasyon hâlâ açık.
- CNC: 52.026 sensör satırı; raporda türetilmiş 30 döngü, 18/6/6 bölümü.
  Bu örnekleme yapısı bağımsız regresyon örneği sayısı gibi sunulmamalı.

Dal, docs/repo-walkthrough-tr.md dosyasını siliyor ve .gitignore ile
ml_experiments/__init__.py üzerinde değişiklik taşıyor. Birleştirme öncesinde
silme ve ortak dosyalar incelenmeli; bizim açıklamalar ve yerel model kayıtlarını
Git'ten dışlayan kurallar korunmalı. SQLite ve Streamlit bu dalda da görünmüyor.

## Öncelik ve ihtiyaç listesi

1. Veri hazırlama dalını kontrollü birleştirmek; kaynak lisans/dağıtım notlarını,
   ortak dosyaları ve tekrar çalıştırma bağımlılıklarını korumak. matplotlib bizim
   kilit ortamımızda yok; hazırlama betiğinin kurulumu henüz doğrulanmadı.
2. Yunus ile hedefi onaylamak: span mı, kaydedilmiş geçen süre mi, doğrulanmış net
   işlem süresi mi? Duplicate/rework ve Report Type kurallarını örneklerle belgelemek.
3. Kaynak zaman dilimini doğrulamak; ham timestamp'lere varsayımsal Europe/Istanbul
   etiketi basmamak. Kalan eğitim/test işlerini ve kalite filtrelerini dondurmak.
4. Atakan: gerçek veride medyanı çalıştırmak, seçilmiş TabPFN sürümü ve kullanım
   koşulları netleşince modeli aynı veri/split ile ölçmek. Test üzerinde seçim
   yapmamak; validasyon ve kategorik ön işleme yalnız izinli geçmişten kurulmalı.
5. Yunus: SQLite save/load/onaylı sürüm servisini ortak PlanSnapshot/SimulationResult
   sözleşmesine bağlamak. Simülasyon onaylı planı değiştirmemeli.
6. Nazlısu: ilk UI'yi mevcut örnek ve servislerle bağlamak. İlk akış manuel girişle
   de tamamlanmalı; Gemma/TabPFN başarısızlığı temel demoyu durdurmamalı.
7. Atakan: duruş olayı/karşılaştırma servisi ve Gemma belirsizlik/takip davranışını
   genişletmek. Doğal dille belirsiz tarihe otomatik saat uydurmamak.
8. Yunus/Nazlısu: embedding geçmiş araması ve ekranı; bu benzerlik makine
   uygunluğu veya süre doğruluğu kanıtı değildir.
9. Ortak: kaynaklar, varsayımlar, çözüm durumu ve gerçek/deneysel ayrımıyla demo
   provası/video. Ölçülmeyen işletme kazancı iddiası eklememek.

## En küçük uçtan uca ürün kabulü

- [x] Başlangıç planını çöz ve bağımsız doğrula.
- [x] Yeni sipariş taslağı ve açık kullanıcı onayı sınırı.
- [x] Simülasyon başlangıç planını değiştirmesin.
- [x] Başlamış/tamamlanmış operasyonları koru.
- [x] Önce/sonra, termin ve alternatif makine etkisini hesapla.
- [x] CLI ve HTML çıktısı; model yokken manuel yol.
- [ ] Streamlit üzerinden plan yükle/sipariş gir/onayla.
- [ ] Onaylı planı SQLite'da ayrı sürüm olarak kaydet/yükle.
- [ ] Gerçek veride onaylanmış süre hedefi ve medyan/TabPFN deneyi.
- [ ] Gemma netleştirmesini daha geniş örneklerde güvenilir doğrula.
- [ ] Duruş olayı ve değişen siparişin tam karşılaştırma akışı.
- [ ] Geçmiş embedding araması ve final demo/video.

Ücretli öncelik/ödeme, vardiya/mola, sıraya bağlı hazırlık, malzeme hazır olma ve
fason dönüşü temel demodan sonraki genişletmelerdir. Kodda başlangıç planı
bitişleri, müşteri terminleri ve ticari kapanış birbirine eşit kabul edilmez;
ticari kapanış modülü henüz yoktur.

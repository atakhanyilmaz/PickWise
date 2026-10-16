# 003 — Yeni sipariş simülasyonu ve plan karşılaştırması

Tarih: 16 Ekim 2026. Önceki adım: WP-2A kısıt düzeltmeleri.

## İşlem sınırı

`create_snapshot` uygulanabilir bir çizelgeyi giriş senaryosu ve sürüm kimliğiyle
bir araya getirir. `PlanSnapshot` içe aktarılan JSON'u da bağımsız doğrular;
`violations=[]` iddiasına güvenilmez. `simulate_order` bu snapshot ve tipli
`OrderRequest` alır, yeni senaryo üretir. Girdiler kopyalanır, başlangıç planı
ve istek değiştirilmez. Baseline sürüm kimliği yanlışsa işlem reddedilir.

Yeni sipariş kimliği benzersiz, rota kullanıcı onaylı, bütün operasyonlar
başlamamış ve uygun makineler senaryoda tanımlı olmalıdır. Sentetik demo ancak
`allow_demo=True` ile kabul edilir. Retrospektif rota yeni sipariş olarak kabul
edilmez. Serbest Türkçe metin bu araçta işlenmez; eksik/ekstra alanlar reddedilir.

Simülasyon anı baseline.current_time değeridir. Planlanmış bir işlemin fiilen
başladığı tahmin edilmez. Zamanı ilerletmek isteyen çağıran, gerçek durum ve
kalan sürelerle yeni bir başlangıç senaryosu hazırlamalıdır.

## Termin anlamı ve hedef

`deadline` sert sınır, `due_date` gecikmesi raporlanan yumuşak müşteri terminidir.
Gecikme T=max(0, C-d). due_date yoksa deadline rapor hedefi olur; ikisi de yoksa
iş gecikme sayısına ve toplamına katılmaz. Amaç sert sınırlar altında makespan
azaltmadır; yumuşak termin gecikmesini minimize ettiği iddia edilmez.

`preserve_existing_completions=True`, mevcut işlerin baseline bitişlerini
`completion_limits` ile ayrıca üst sınır yapar. Müşteri termini değiştirilmez.
Bu seçenek açık bir iş kuralıdır; varsayılan olarak mevcut bitişler korunma
zorunluluğunda değildir. Önceden mevcut limitler ve sert terminler gevşetilmez.

## Karşılaştırma

Karşılaştırma aynı makineler, zaman referansı ve mevcut iş girdilerinde yapılır.
Kaynak kimlikleri eşleştirilir. Makespan, çözüm süresi, ihlal sayısı, işlem ataması
veya zamanı değişen mevcut iş sayısı, eski plandan geç biten iş sayısı, müşteri
terminini aşan iş sayısı ve toplam termin gecikmesi ayrı raporlanır. Yeni işler
mevcut iş etkisi sayısına katılmaz; bitişleri ayrıca bulunur.

OPTIMAL/FEASIBLE dışındaki sonuçlar için karşılaştırma veya sahte makespan
üretilmez. UNKNOWN imkânsızlık olarak anlatılmaz. Kullanıcı mesajları bütün
çözücü durumlarını ayırır.

## Demo ve kalıcılık

`data/examples/order_demo.json` sentetik girdidir; bütün süreler, terminler ve
alternatif uygunluklar demo varsayımıdır. Çalıştırıcı başlangıç ve üç seçenek
JSON'u, özet CSV ve internet gerektirmeyen önce/sonra Plotly raporu üretir.
Bunlar deney çıktısıdır; onaylı planı veya SQLite kaydını değiştirmez. Onaylı
plan sürümü kaydetme, Streamlit ve Gemma sonraki entegrasyon adımlarıdır.

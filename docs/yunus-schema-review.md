# Yunus SQL şeması ve korelasyon incelemesi

17 Ekim 2026. İncelenen dal: `origin/data_preprocesing`, commit
`92f484c`. SQL şema commit'i `5e8bf66`. Uzak `main`, `ce0bb99` ile şemayı
içeren PR #3'ü birleştirmiş; korelasyon commit'i henüz bu main'de değil.
Yerel dala merge yapılmadı. Kaynaklar Git üzerinden salt okunur incelendi.

## SQL sonucu

`database/schema.sql` bellekte SQLite bağlantısında çalıştırıldı:
11 tablo, 37 trigger oluştu; foreign_keys açık.
Mevcut sentetik atölye girdisi gerçek CP-SAT ile çözülüp plan/makine/iş/
operasyon/uygun makine/sonuç/çizelge tablolarına eklendi, sürüm mühürlendi,
güncel sürüm işaretçisi ilerletildi ve transaction commit edildi.

- Foreign key ihlali çıkmadı.
- JSON snapshot Pydantic ile tekrar yüklendi; başlangıç nesnesine eşitti.
- Mühürlenmiş iş satırını değiştirme reddedildi.
- Güncel sürümü NULL'a geri çekme reddedildi.
- Aynı sürümü yeniden ekleme reddedildi.

Bu testler SQL şemasının temel akışını gösterir; çalışan repository, iki
bağlantılı eşzamanlılık testi veya bütün ilişkisel sütunların JSON ile eşitlik
kontrolü değildir. SQLite tablolarının üretilmesine başlanabilir; uygulamaya
bağlamadan önce `PlanRepository` yazılmalıdır.

## Kayıt katmanından önce tamamlanacaklar

1. Her bağlantıda `PRAGMA foreign_keys=ON`; kayıt/yüklemede tam
   `StoredPlanVersion` doğrulaması. SQL kendi başına bağımsız çizelge
   doğrulayıcısının yerine geçmez. Şemadaki `approved_at` yalnız boş olmayan
   metin kontrolü yapar; offsetli tarih kontrolü Pydantic katmanındadır.
2. `snapshot_json` version_id CHECK'i eksik JSON yolunda NULL döner;
   SQLite CHECK NULL'u reddetmez. Denemede `{}` JSON'u açık sürüm başlığına
   eklenebildi. Bu tam, mühürlü geçerli planın kabul edildiği anlamına gelmez.
   Alan yok/null/yanlış tip durumunu SQL düzeyinde reddetmek için ayrıca
   `CHECK (json_type(snapshot_json, '$.version_id') IS 'text')` eklenmeli.
   Mevcut eşitlik kontrolü korunmalı; tam Pydantic kontrolü yine zorunludur.
3. JSON ve ilişkisel kayıtlar tek doğrulanmış nesneden üretilmeli;
   ilişkisel tablolar farklı planı gösterirken JSON başka planı göstermemeli.
4. Beklenen güncel sürüm kontrolü, ilişkisel/JSON kayıt, mühürleme ve
   işaretçi değiştirme tek transaction olmalı. Hatalar rollback edilmeli;
   ilk sürümden sonra ikinci sürüm, stale writer ve yarım kayıt testleri gerekli.
5. Takip edilen `database/local/production_planning.sqlite3` 0 baytlık
   placeholder'dır; kurulmuş veritabanı değildir. Yerel DB'ler Git dışında
   tutulmalı; paylaşılacak kaynak SQL şeması olmalı.

## Korelasyon

`core/data_analysis/correlation.py` tüm CSV'yi okuyor ve tüm sayısal
sütunlarla Pearson/Spearman hesaplıyor. `split == 'train'` filtresi ve
özellik izin listesi yok. Ayrıca Windows'a özel sabit mutlak yol kullanıyor.

Bu çıktı bütün verinin betimleyici görünümü olabilir; bundan özellik/PCA
seçimi yapılırsa doğrulama/test bilgisi seçime sızar. Kod özellik seçimi için
kullanılmadan önce eğitim filtresi, açık tahmin hedefi ve izinli sütun listesi
eklenmeli. Oturum kimliği, hedef, split ve sonradan bilinen bilgiler özellik
sayılmamalı. Hedef ayrı korelasyon incelemesinde kullanılabilir, X'e konulamaz.

DummyRegressor bir sabit referans tahminidir; tek başına bir özelliğin
faydasını ölçmez. Özellik katkısı, aynı oturum/zaman bölmelerinde gerçek
bir modelin özellikli/özelliksiz doğrulama hatası karşılaştırılarak ölçülür.
PCA ilk deneyin zorunlu adımı değildir; kullanılırsa doldurma/ölçekleme/PCA
yalnız eğitimden öğrenilir. Hiçbir model bu incelemede eğitilmedi.

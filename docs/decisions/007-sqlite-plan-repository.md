# 007 — SQLite plan kayıt/yükleme uygulaması

17 Ekim 2026. ADR 006 arayüzü `core/sqlite_repository.py` ile uygulanır;
Yunus'un SQL şeması korunur, eksik JSON version_id için CHECK güçlendirilir.

Onaylı planın tam JSON'u ile ilişkisel sorgu tabloları aynı Pydantic nesnesinden
üretilir; yüklemede iki gösterimin eşitliği ve çizelge doğruluğu kontrol edilir.
Güncel sürüm okunması ve eski sürüm yüklenmesi tutarlı okuma transaction'ında;
kayıt/sürüm doğrulaması/mühürleme/işaretçi ilerletme `BEGIN IMMEDIATE` içinde
gerçekleşir. Başarısız işlemler rollback edilir. Ayrı bağlantılar aynı eski
sürümden kayıt denediğinde yalnız biri ilerler. Önceki sürümler değişmez.

Yeni bir ORM/bağımlılık eklenmez; Python sqlite3 kullanılır. Her işlem kendi
bağlantısını kapatır. Otomatik şema migration veya arka planda tekrar kayıt yok.
Plan onayı çağıran UI/servisin sorumluluğudur; simülasyon kayıt yapmaz.
CLI save açık komut ve `--confirm-save` ister; load mevcut baseline JSON
biçimine export sağlayabilir. Gerçek müşteri veya kullanıcı onayı iddiası yoktur.

Geçici dosyalarda roundtrip, alternatif sipariş sonrası açık yeni sürüm kaydı,
iki bağlantıyla yarış, rollback, bozulan JSON/ilişkisel kayıt, eski sürüm ve
geçersiz girdiler test edilmiştir. UI, gerçek veri süre deneyi ve takvim
dönüşümü bu değişikliğin kapsamı değildir.

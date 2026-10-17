# 008 — Git ile onaylı plan seed alışverişi

Tarih: 2026-10-17

Geliştirme aşamasında merkezi veritabanı yerine her geliştirici kendi SQLite
dosyasını kullanır. SQLite ikili dosyası Git tarafından güvenli birleştirilemez;
bu nedenle takip edilmez. Yalnız doğrulanmış ve onaylanmış `StoredPlanVersion`
kayıtları tek `database/seed/seed.json` dosyasında paylaşılır.

Seed, `plan_id` başına açık güncel sürüm ve tam, değiştirilemez sürüm kayıtları
taşır. Geçmiş doğrusaldır. Aynı parent'tan iki çocuk üretildiğinde uygulama
birini seçmez; paylaşım durur ve ekip güncel sürüm üzerinden yeniden simülasyon
yapar. Dosya deterministik yazılır, mevcut sürüm farklı içerikle ezilmez ve
içe aktarma plan zincirlerini tek transaction'da kaydeder.

Bu yöntem anlık çok kullanıcılı veritabanı değildir. Senkronizasyon Git
push/pull ve açık import komutuyla gerçekleşir. Gerçek müşteri ve kişisel
veriler Git seed'ine konmaz. Anlık ortak çalışma gerektiğinde PostgreSQL gibi
merkezi bir servis ayrı kararla değerlendirilir.

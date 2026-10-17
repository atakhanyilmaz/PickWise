# 006 — Onaylı plan sürümleri için ortak kayıt sözleşmesi

Tarih: 17 Ekim 2026.

Mevcut `WorkshopScenario` ve `PlanSnapshot` tekrar tanımlanmadan kullanılacak.
`StoredPlanVersion` bunlara şema sürümü, plan ailesi, parent ve onay denetim
bilgilerini ekler. Çizelge yüklemede bağımsız doğrulanır. Kullanıcı onayı ayrı
uygulama eylemidir; Pydantic nesnesi veya sipariş simülasyon onayı bunu sağlamaz.

`PlanRepository` yalnız tipli arayüzdür. SQLite uygulaması ayrı sorumluluktur;
beklenen güncel sürüm kontrolü ile sürüm ekleme/işaretçi değiştirme tek atomik
transaction gerektirir. Eski sürümler değiştirilemez. Demo planları açık kaynak
etiketleriyle desteklenir; retrospektif/öneri rotaları operasyonel kayıt olamaz.

Gerçek tarih dönüşümü ve eğitim veri sözleşmesi bu değişiklik kapsamında
değildir. Ayrıntılı alanlar ve depo kabul koşulları:
`docs/plan-data-contract.md`.

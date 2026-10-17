# 009 — İki retrospektif hedefin doğrulama deneyi

17 Ekim 2026. Kullanıcı öğrenilebilirliği ölçmeyi istedi. Toplam gözlenen
iş aralığı ve koşullu makine kaynakları arası bekleme için bağımsız
TabPFN v2, ExtraTrees ve train-only medyanlar çalıştırıldı. Son test
değerlendirmesine geçilmedi. İki hedefte de TabPFN global medyanı geçemedi;
bu sürüm ürün akışına bağlanmaz. Gözlenen aralıklar gerçek taşıma/teslim
süresi onayı değildir. Hedef makinenin önceden atanmış olduğu varsayımı açık.

Önceki audit'te yalnız Turning & Milling kaynaklarını makine sayma hatası
düzeltildi. Güncel makine adı alt kümesi Machine / Wire Cut - Machine
kaynaklarını kapsar; fiziksel uygunluk doğrulaması yerine geçmez.

Ayrı `.venv-tabpfn`, tam paket kilidi ve gerçek checkpoint checksum'u
kullanılır. Kullanıcı verisi bulut tahmin API'sine gönderilmedi. Detay,
başarısız sonuç dahil: `docs/learnability-results.md`.

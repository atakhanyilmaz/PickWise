# 015 — Production Analysis kayıtlarından başlangıç planı

18 Ekim 2026. Yerel SQLite boşken arayüz 2 işlik `order_demo.json` planına
düşüyordu. Başlangıç planı artık depodaki Production Analysis 2012 kayıtlarından
(`data/dataforNewVersion/production_analysis.csv`) üretilir ve `v1` olarak
saklanır.

## Karar

`core/retrospective_transform.py`:

- Yalnız tezgâh kaynakları (`Machine N`) makine olur. Kalite kontrol, paketleme,
  fırın ve elle işlemler plana alınmaz; kalite kontrol tek kapasiteli tezgâh gibi
  modellenirse yapay darboğaz oluşur.
- Bir iş emrinde art arda gelen aynı faaliyet kayıtları tek operasyondur. Tekrarlanan
  ve çakışan raporlar aralık birleşimiyle bir kez sayılır.
- Operasyon yalnız kaydedildiği tezgâhta çalışabilir; alternatif makine çıkarılmaz.
- Süre, o faaliyetin o tezgâhta bütün iş emirlerindeki geçen süresinin medyanıdır
  (`historical_median`). ADR 0002 gereği saf makine süresi değildir; adet dikkate
  alınmaz.
- Kayıttan çıkarılan rota kullanıcı onayı değildir (`docs/plan-data-contract.md`).
  Rotalar `demo_assumption` etiketlidir; çözücü kabul eder, arayüz rozeti bunu
  gösterir. Rota onayı ekranında düzenlenip onaylanan taslak `user_approved` olur.
  Bu etiket Nazlısu Başak'ın seçimidir.
- Plan: 5 Mart 2012 sonrası ilk başlayan 10 iş emri, 11 tezgâh, hepsi başlamamış,
  `current_time = 0`. Kayıtlarda aynı tezgâhta çakışan zaman damgaları olduğundan
  tamamlanmış/devam eden operasyonlar geçmiş saatlerle yeniden kurulmadı.
- Yeni sipariş taslakları, plandaki tezgâhları kullanan sıradaki 3 iş emridir.
- Makine adları `M4 Turning & Milling` biçimindedir. Gemma araçları `M4` ve `4`
  ifadesini kimlikle eşler; `Makine 4` ifadesi şu an sıra numarası olarak okunur
  (`core/llm/intake.py::_machine`), bu yüzden örnekler tam adı kullanır.

## Sonuç

`v1` CP-SAT ile OPTIMAL çözüldü (makespan 3347 dk) ve bağımsız doğrulayıcıdan
ihlalsiz geçti. `database/seed/seed.json` bu sürümü içerir; ekip
`plan_storage_cli import-seed` ile aynı başlangıç veritabanını kurar. Yerel
veritabanı Git'e eklenmez.

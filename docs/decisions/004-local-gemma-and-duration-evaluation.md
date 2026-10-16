# 004 — UI'den bağımsız Gemma servisi ve süre deneyi sözleşmesi

Tarih: 17 Ekim 2026. Kapsam: Atakan'ın doğal dil/planlama entegrasyonu ve süre
modeli deneyi için veri gelmeden hazırlanabilen parçalar.

## Gemma sınırı

`core/llm/ollama_client.py` yalnız loopback HTTP Ollama'ya bağlanır. İndirilecek
model seçmez; mevcut modelin ailesi, etiketi, ağırlık digest'i, quantization ve
Ollama sürümünü doğrular/kaydeder. Cloud-backed modeller reddedilir. Tam çevrimdışı
iddiası yoktur: ağ kapalı uçtan uca test yapılmadı. İlk model indirme bu teslimde yoktur.

`extract_order(text, baseline, client)` tipli IntakeResult döner. İstem v2,
JSON modu ve Pydantic doğrulaması kullanılır. Modelin verdiği makine/süre
alıntıları kullanıcı metninde bulunmalı, makine kimliği benzersiz çözülmeli,
süre pozitif tamsayı dakikaya çevrilmelidir. Hiçbir model çıktısı kod olarak
çalıştırılmaz. Eksik bilgi çözüm üretmez. Bozuk şema/model yokluğu farklı durumlardır.

Taslak rotası USER_PROPOSED'dır. `confirm_and_simulate(..., user_confirmed=True)`
ancak eksiksiz taslak ve gerçek boolean True ile USER_APPROVED yapıp simüle eder.
Bu fonksiyon LLM tarafından otomatik çağrılmaz; onay UI/CLI kullanıcısına aittir.
Sadece simülasyon oluşturur, plan sürümü kaydetmez. Önceki plan değişmez.

Başlangıç ve bitiş hesabı ortak t=0 dakika üzerinden yapılır. Bu sürüm yalnız
`t=20 dakika` gibi açık terminleri destekler. Gerçek tarih, göreli tarih,
vardiya, mola, maliyet ve duruş talebinin doğal dille yapılandırılması desteklenmez.
Duruş çekirdekte mevcut olsa da bu sipariş aracında ayrı destek gerektirir.

Gemma açıklamada hesaplanan fact_id'leri seçer; sayıları ve metinleri güvenilir
Türkçe şablonlar oluşturur. Serbest model metni yayımlanmaz. Kritik çözüm durumu,
hedef ve gecikme bilgisi atlanamaz. Hatalı seçim/model yokluğunda computed_fallback
etiketiyle doğrudan hesaplanan açıklama döner; gerçek Gemma çıktısı gibi sunulmaz.

## Canlı değerlendirme

Mock birim testleri gerçek model kalitesi sayılmaz. `benchmarks/gemma_evaluation.py`
beş sentetik talebi gerçek yerel modelde sınar; alan çıkarımı, araç seçimi,
netleştirme durumu ve hesaplanan açıklama kaynağını ayrı kaydeder.

İlk e2b şema-kısıtlı denemede 1/5, şemayı isteme ekleyen denemede 2/5,
JSON/Pydantic ve örnekli istem v2 ile 3/5 beklenen akışa ulaşıldı. Son v2
çalıştırmada tam sipariş, eksik süre ve plan inceleme geçti; belirsiz makine ve
tarih çıktıları reddedildi. Bu beş örnek geliştirme smoke setidir, bağımsız
üretim kalite ölçümü değildir. 12B MLX modelinin ilk denemeleri geçersiz çıktı
üretti; v2 denemesi yanıt alınamayınca durduruldu. Bu model varsayılan yapılmadı.

Varsayılan gerçek model: gemma4:e2b; mimari gemma4, 5.1B, Q4_K_M; Ollama 0.31.1.
Çalıştırma başına tam digest ve istem sürümü yerel JSON kayıtlarında bulunur.
Doğal dil girişi deneysel kalır; model çıktıları her durumda kullanıcı onayı
ister ve manuel JobModel/OrderRequest yolu çalışır.

## Süre deneyi

`ml_experiments/duration_evaluation.py` ham veriyi temizlemez. Yunus'un inceleyip
ayırdığı kayıtlara ortak kontrat sağlar. record_id, job_id, parça, işlem, makine,
parti miktarı, açık zaman dilimli başlangıç/bitiş ve hedef dakika bekler.
Hedef türü kullanıcı tarafından incelenmiş olmalıdır. recorded_elapsed_minutes
seçilirse hedef başlangıç-bitiş farkına uymalıdır; verified_processing_minutes
ancak ayrıca doğrulanmış net işlem süresi içindir.

Aynı iş emri eğitim/testte bulunamaz; bütün eğitim sonuçları ilk test başlangıcından
önce elde edilmiş olmalıdır. Yinelenen kimlik ve aynı olayı temsil eden kayıtlar
silinmez; inceleme için reddedilir. Bu kontrol ham loglarda yeniden işlem tespiti
ve semantik veri incelemesinin yerine geçmez.

Referans operasyon medyanıdır; bilinmeyen operasyonda yalnız eğitim verisinin
global medyanı kullanılır. Model arabirimi fit/predict ile yalnız izin verilen
parça, işlem, makine, parti alanlarını görür; zamanlar ve gerçekleşen hedefler
özelliklere girmez. MAE/RMSE, örnek/iş sayıları, bölme ve hedef tanımı raporlanır.

TabPFN paketi kurulmadı, model ağırlığı indirilmedi, gerçek veri deneyi yapılmadı.
Gerçek dosya, hedef anlamı ve seçilecek TabPFN sürümünün kullanım hakkı
netleşince model adaptörü bağlanacaktır. Şimdiki sentetik medyan çıktısı gerçek
fabrika/model başarısı olarak sunulamaz. Operasyonel varsayılan süre kaynağı
kullanıcı onaylı sürelerdir; tahminler çözücüye otomatik aktarılmaz.

## UI bağlantı noktaları

- extract_order -> IntakeResult(state, questions, proposed_order, model_metadata)
- confirm_and_simulate -> SimulationResult
- explain_simulation -> Explanation(text, origin, selected_fact_ids, model_metadata)
- Manuel giriş -> JobModel + OrderRequest + simulate_order

Plan onayı/kaydı, SQLite, Streamlit ve embedding araması sonraki bağlantılardır.
Model istemindeki schema bilgisi Ollama JSON modu ile gönderilir, çıktı ayrıca
Pydantic'ten geçirilir. Kaynaklar:
https://docs.ollama.com/api/chat
https://docs.ollama.com/capabilities/structured-outputs

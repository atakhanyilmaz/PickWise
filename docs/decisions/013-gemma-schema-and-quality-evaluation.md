# 013 — Gemma şeması ve gerçek model kalite kontrolü

17 Ekim 2026. Kapsam yalnız Gemma istemi, Ollama istemcisi ve değerlendirme araçlarıdır.
Çözücü, SQL ve senaryo servisleri değiştirilmedi. Model eğitimi veya fine-tuning yapılmadı.

## Sorun ve karar

Mevcut geliştirme setinde gerçek Gemma ile 7/8 akış geçti. Koruma isteğinde JSON
geçerli olmasına rağmen `preservation=completions` yanında `preservation_text=null`
geldi; kullanıcıya dayanmayan alanı kabul etmeyen doğrulayıcı taslağı reddetti.

Ollama `format` alanına `"json"` yerine Pydantic JSON şemasının tamamı gönderilir.
Şema sistem isteminde de kalır. Şema sınırlandırması anlam doğruluğu sağlamadığı
için yerel Pydantic doğrulaması, kaynak alıntısı, makine eşleme, süre dönüşümü ve
ayrı kullanıcı onayı korunur. Sessiz yanıt tamiri veya otomatik tekrar eklenmedi.
Şemanın SHA-256 değeri, istemci sürümü ve çıktı sınırı audit metadata'sına eklenir.

Bu yöntem [Ollama'nın resmî yapılandırılmış çıktı örneğine](https://github.com/ollama/ollama-python/blob/main/examples/structured-outputs.py)
uyar. Sadece şema değişimi aynı örneklerde 7/8 verdi; tek başına semantik hatayı
çözmedi. `order-fields-v3` istemi koruma alıntısının boş bırakılamayacağını açıklar.
Niyet istemi `intent-v1` olarak kaldı.

## Değerlendirme

Gerçek yerel model: `gemma4:e2b`, 5.1B, Q4_K_M, Ollama 0.31.1;
digest `7fbdbf8f5e45a75bb122155ed546e765b4d9c53a1285f62fd9f506baa1c5a47e`.
Temperature=0, seed=0, num_ctx=8192, num_predict=1400, think=false.

- Aynı geliştirme seti: değişiklik öncesi 7/8; şema değişimi 7/8; son istem 8/8.
- Ek geliştirme seti `data/examples/gemma/quality.json`: 6/6. İki ardışık operasyon,
  tek operasyonda iki alternatif makine, yumuşak termin, eksik makine, belirsiz
  koruma ve birimsiz süreyi kapsar. Beklenen takip alanı ayrıca ölçülür: 3/3.
- Açıklama: uygulanabilir ve mevcut bitişleri koruma nedeniyle INFEASIBLE olan
  iki sentetik senaryoda 2/2 gerçek Gemma fact seçimi. Metin, seçilen hesaplanmış
  bulguların güvenilir şablonlarından üretildi; fallback başarısı Gemma başarısı
  sayılmadı. Başlangıç planının değişmediği kontrol edildi.
- Ayrı mevcut test seti, son istem dondurulduktan sonra yeniden çalıştırıldı: 6/6.
  Sonuç `results/gemma_quality_final/heldout/summary.json` içindedir. Bu set daha
  önce de kullanılmıştır; yeni ve hiç görülmemiş saha verisi olarak sunulmaz.
- 247 birim testi geçti; son istem değişikliğinden sonra ilgili 68 test tekrar
  geçti. Birim testleri gerçek model doğruluğu değildir. Ruff ve diff kontrolü geçti.

Bu küçük sentetik testler servis davranışını ölçer; kod kontrolleri ve önceden
yazılmış kullanıcı cevapları içerir. Genel doğruluk, saha kabulü veya ağ kapalı
çalışma kanıtı değildir. Duruş backend'i mevcut olsa da bu Gemma sipariş aracı
duruş talebini desteklemez. Takvim tarihleri otomatik çevrilmez; açık referans
zamanı istenir. İleri düzey prompt injection dayanıklılığı ayrıca değerlendirilmelidir.

## Tekrar çalıştırma

Ollama yerelde çalışıyor ve model kurulu olmalıdır. Komutlar indirme yapmaz.

```sh
.venv/bin/python -m benchmarks.gemma_conversation_evaluation --split development --output results/gemma_quality_final
.venv/bin/python -m benchmarks.gemma_conversation_evaluation --fixture data/examples/gemma/quality.json --output results/gemma_quality_extended
.venv/bin/python -m benchmarks.gemma_conversation_evaluation --split heldout --output results/gemma_quality_final
.venv/bin/python -m benchmarks.gemma_explanation_evaluation
.venv/bin/python -m pytest -q tests/test_ollama_structured.py tests/test_conversation.py tests/test_gemma_service.py
```

Gerçek çalıştırmanın mesajları ve model metadata'sı Git dışında `results/gemma*/`
altında saklanır. Özetlerde fixture yolu ve SHA-256 değeri vardır. Süreler model
yüklemesi, önbellek ve aynı anda yapılan isteklerden etkilenir; bu çalışma bir hız
karşılaştırması değildir.

Yunus'un bağlantı için kullanacağı API değişmedi: `begin_intake` → gerekiyorsa
`answer_intake` → `confirmation_required` taslağını göster → ayrı insan onayıyla
`confirm_and_simulate` → `explain_simulation`. Model yoksa manuel giriş korunur.

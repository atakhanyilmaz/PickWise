# 014 — Bağlamla araç seçimi ve doğal takip yanıtları

17 Ekim 2026. Atakan'ın gerçek CLI denemesinde “planı incelemek istiyorum”
cevabı, “planı incele” ile birebir eşleşmediği için tekrarlanan soruya takıldı.
Ayrıca “yeni sipariş” geçen bir bilgi sorusu sözcük kontrolü nedeniyle yanlış
akışa yönlenebiliyordu. Önceki küçük örneklerin geçmesi bunu kapsamıyordu.

## Karar ve akış

Gemma → araç seçimi → giriş doğrulaması → Python aracı → hesaplanan sonuç →
Gemma'nın ilgili bulguları seçmesi → Türkçe cevap.

`core/llm/tools.py` gerçek uygulanmış araç kataloğu, giriş/çıkış Pydantic şemaları
ve kapalı bir dispatcher içerir:

- `inspect_plan`: doğrulanmış snapshot'tan metrikler, iş ve operasyon durumları.
  Toplam, tamamlanmamış ve hiç başlamamış iş sayıları ayrı hesaplanır. Bunlar
  yalnız yüklü planı kapsar; gerçek veritabanındaki bütün sipariş sayısı denmez.
- `simulate_order`: mevcut onaylı simülasyon servisini çağırır. İnsan onayı
  dispatcher'ın host parametresidir; model argümanlarında kabul edilmez.
  Başlangıç planını değiştirmez veya kaydetmez.

`tool-router-v3` katalogdaki yetenekleri, konuşmayı, son cevabı ve bekleyen soruyu
birlikte yorumlar. Araç seçimi şemayla sınırlı JSON protokolüdür; Ollama'nın native
`tool_calls` API'si kullanılmadı. Yeni framework veya çok ajanlı yapı eklenmedi.
Araç girdileri ayrı adımda hazırlanır; model bir fonksiyon adı icat ederek kod
çalıştıramaz. Araç çağrısı ve çıktısı session audit'inde saklanır.

Niyet takiplerinde model tekrar bağlamla seçim yapar. Makine/süre gibi doğrudan
geçerli alanlarda deterministik dönüşüm korunur; doğal cümle gerektiğinde
`field-answer-v3` yalnız bekleyen alanı çıkarır. Makine, süre ve referans termin
cevapta gerçekten geçmelidir. Diğer alanlar yeniden çıkarılmaz.

Sert/yumuşak termin ve koruma tercihleri `PolicyAnswer` ile sınırlı kategorilere
ayrılır (`policy-answer-v1`); kaynak kullanıcı cevabını uygulama kaydeder.
Modelin kategori etiketini kullanıcıdan alıntı diye üretmesi istenmez.
Salt plan incelemeye geçişte alan değeri gerekmemesi de ayrı ele alınır;
araç değiştirme eylemiyle birlikte alan güncellemesi gönderilirse reddedilir.

CLI normal modda JSON yerine taslak veya hesaplanan cevabı gösterir. `--debug-json`
teknik çıktıyı açar. `inspection-answer-v1` kullanıcının sorusu ve gerçek araç
bulgularıyla ilgili fact kimliklerini seçer; sayıları güvenilir şablonlar yazar.
Serbest metinle sayı/teslim tarihi uydurulmaz. Model seçimi başarısızsa fallback
origin'i dosyada ayrıca kaydedilir. Açık taslak onayı hâlâ ayrı bir kullanıcı adımıdır.

## Gerçek model denemeleri

Yerel `gemma4:e2b`, Q4_K_M, Ollama 0.31.1; önceki kayıtla aynı model digest'i.
Başarısız denemeler de `results/gemma_tools*/` altında tutuldu.

- Atakan'ın tam cümlesi doğrudan `inspect_plan` çalıştırdı. Gerçek CLI çıktısı:
  “Yüklü planda 2 iş var; 2 iş henüz tamamlanmamış.” Bu, sentetik demo snapshot'ıdır.
- Yeni konuşma geliştirme seti: 6/6. Doğal niyet, süre, makine ve koruma yanıtları.
- Önceki geliştirme seti: 8/8; önceki ayrı set: 6/6 regresyon kontrolü.
- Dört yeni cümle ilk ayrı denemede 3/4 geçti. Alan toplarken plan incelemeye
  geçişte model doğru aracı seçti, fakat gereksiz alıntı kontrolü null evidence'ı
  reddetti. Bu protokol hatası düzeltildi; sonraki çalıştırma artık regresyon
  değerlendirmesidir ve 4/4 geçti; hiç görülmemiş test başarısı olarak sunulmaz.
- Son kayıtlar: `results/gemma_tools_final_policy/development/`,
  `results/gemma_tools_regression/`, `results/gemma_tools_navigation_regression/heldout/`.

Birim testleri araç whitelist'i, modele onay yetkisi vermeme, snapshot değişmezliği,
bağlam koruma, yalnız bekleyen alanı değiştirme, uydurma süreyi reddetme ve gerçek
araç verisiyle açıklamayı kapsar. Bunlar model kalite ölçümü değildir.
Son doğrulama: 259 birim testi geçti; Ruff ve `git diff --check` temiz.

Bu çalışma sınırlı plan inceleme ve sipariş hazırlama/simülasyon asistanıdır.
Kalıcı sohbet döngüsü, bütün araçları otonom zincirleme, duruş aracını doğal dile
bağlama, serbest çok alanlı taslak düzeltme ve tarih dönüşümü henüz uygulanmadı.
Yunus'un SQL/çözücü/senaryo kodu değiştirilmedi; push yapılmadı.

## Deneme

```sh
.venv/bin/python -m benchmarks.gemma_order_cli \
  --baseline results/workshop_order/baseline.json \
  --text "Yeni sipariş vermek için ne kadar sipariş var ön tarafta" \
  --output results/gemma_my_trial_tools

.venv/bin/python -m benchmarks.gemma_conversation_evaluation \
  --fixture data/examples/gemma/conversation_tools.json \
  --output results/gemma_tools_repeat
```

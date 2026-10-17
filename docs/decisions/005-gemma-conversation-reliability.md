# 005 — Niyet ayrımı ve alan bazlı takip soruları

Tarih: 17 Ekim 2026. Kapsam: yalnız Gemma servis güvenilirliği. Yunus'un gerçek
üretim verisi kullanılmadı; TabPFN veya duruş olay servisi bu değişiklikte yok.

## Karar

UI ve CLI için yeni giriş `begin_intake`, devamı `answer_intake` olur.
`extract_order` eski tek mesajlı düşük seviye API olarak korunur. Niyet çıkarımı
`IntentDecision` ile, sipariş alanları ayrı `OrderFields` ile yapılır. Plan
incelemede operasyon çıkarımı çağrılmaz. Makine kataloğu yalnız uygulamada eşleme
ve kullanıcı seçenekleri için kullanılır; alan çıkarımı modeline gönderilmez.
Geliştirme denemesinde katalogdaki makinelerin yeni operasyon gibi üretilmesi
bu ayrımın gerekçesidir.

`IntakeSession` doğrulanmış taslak, kullanıcı mesajları, sıradaki alanlar,
baseline sürümü/içerik fingerprint'i ve model/istem audit kayıtlarını taşır.
Kullanıcı yalnız sıradaki alanı cevaplar; makine veya süre yanıtında LLM yeniden
çağrılmaz. Daha önce alınan operasyon sırası, süre, termin ve koruma değerleri
baştan çıkarılmaz. Eksik operasyon listesi için ayrı kısıtlı çıkarım çağrısı vardır.
Niyet belirsizse kullanıcı plan inceleme veya yeni siparişi açıkça seçebilir.

Kopyalama ve yeniden doğrulama, eski session veya baseline'ın değişmesini önler.
Sürüm aynı olsa bile baseline içeriği değişmişse takip reddedilir. Dışarıdan
bozulmuş slot indisleri reddedilir. Son taslak yine USER_PROPOSED'dır;
`confirm_and_simulate` gerçek boolean onayı olmadan çağrılamaz. `evet` takip
cevabı otomatik onay veya simülasyon değildir; onay ayrı adımdır.

## Sayılar, zamanlar ve koruma

Süre alıntısı kaynak mesajda tam sınırlarla aranır; '10 dakika', '110 dakika'
içinden seçilemez. Dakika/saat ve yaygın Türkçe sayı ifadelerini kod çevirir:
iki saat=120, bir buçuk saat=90, yarım saat=30, yirmi beş dakika=25.
Desteklenmeyen sayı biçimi için açık değer istenir; sıfır/negatif/kesir dakika
kabul edilmez. Hangi makinenin kastedildiğini embedding veya benzerlikle seçmeyiz.

Sert/yumuşak termin türü açık kullanıcı ifadeleriyle kontrol edilir; belirtilmemiş
türde soru sorulur. Gerçek tarih/timezone dönüşümü bu sürümde yoktur. 'Yarın sabah'
kod tarafından saate çevrilmez. Kullanıcı ortak t=0 referansından örneğin
`t=40 dakika` ile açıkça yeni sınır verir; bu, tarihin otomatik dönüşümü olarak
sunulmaz. Termin yok cevabı açıkça sınırı kaldırır. 'İşleri geciktirme' isteğinde
mevcut plan bitişleri ve müşteri terminleri ayrıştırılır. Yumuşak müşteri
terminlerini sessizce sert sınıra çevirme yapılmaz.

Duruş, ödeme, vardiya ve plan kaydetme/silme bu araçta desteklenmez. Bunlar LLM
çağrısından önce de denetlenir. Duruş senaryo servisi sonraki aşamada eklenecektir.
Bilinmeyen kısıtlar için kusursuz doğal dil tespiti iddia edilmez; son taslak
insan tarafından kontrol edilmeye devam eder.

## Değerlendirme yöntemi ve sonuç

- Sentetik geliştirme seti: `data/examples/gemma/development.json`, 8 örnek.
- Ayrı sentetik test seti: `data/examples/gemma/heldout.json`, 6 örnek.
- Gerçek yerel model: gemma4:e2b, gemma4 mimarisi, 5.1B, Q4_K_M; Ollama 0.31.1.
- İstem sürümleri: intent-v1 ve order-fields-v2. Tam digest/model ayarları her
  başarılı aşamanın yerel JSON audit kaydında bulunur.
- Son geliştirme çalıştırması 7/8 beklenen akış; bir koruma isteğinde geçersiz
  model çıktısı reddedildi.
- Son ayrı test çalıştırması 6/6 beklenen akış. Başlangıç/son durum, servis araç
  seçimi ve son makine-süre/termin alanları ayrı kontrol edildi.
- CLI gerçek modelle eksik süreyi sordu; test cevabı sonrası ayrı taslak onayı,
  CP-SAT ve hesaplanan açıklamaya kadar çalıştı. Bu sentetik testte CLI onayı
  test girdisiyle sağlandı; gerçek kullanıcı kabul testi değildir.
- 166 birim testi, Ruff ve git diff --check geçti.

Bunlar küçük geliştirme fixture'larıdır; saha güvenilirliği veya genel yüzde 100
model doğruluğu iddiası değildir. Servis metrikleri kod kontrolleri ve önceden
belirlenmiş test kullanıcı cevaplarını içerir. Eski 3/5 tek mesajlı smoke sonucu
ile doğrudan aynı ölçüm değildir. Heldout değerlendirmesi sırasında istemler
sonuçlara göre değiştirilmedi. Birim testleri gerçek model başarısı sayılmaz.
Ağ kapalı çalışma testi yapılmadı.

## Kullanım

```python
from core.llm.conversation import begin_intake, answer_intake

session = begin_intake(user_text, baseline, client)
# UI session.pending[0].question / choices alanlarını gösterir.
session = answer_intake(session, user_answer, baseline, client)
# confirmation_required olduğunda taslağı göster, ayrı insan onayını al.
# confirm_and_simulate(session.result, baseline, scenario_id, user_confirmed=True)
```

Yeni istem başlatmak, taslağı düzeltmek, üretim planını kaydetmek ve model
erişilemezken manuel forma geçmek UI'nin bağlantı noktalarıdır. CLI 'iptal'
cevabında işlem yapmaz. Doğal dil oturumları results/gemma*/ altında Git dışında
saklanır. Sentetik fixture'lar paylaşılabilir; gerçek kullanıcı verisi eklenmez.

# CNC kalan süre tablosu: salt-okunur veri kontrolü

Kontrol tarihi: 17 Ekim 2026. İncelenen Yunus commit'i:
`3abae7380c7d724d47dd0335330de74a104f4b98`.

Ham ve türetilmiş CSV'ler bu commit'ten `git show` ile belleğe okunur;
dal birleştirilmez, kaynak CSV'lere yazılmaz. Kontrol kodu
`ml_experiments/cnc_audit.py`, ayrıntılı sonuç `results/cnc_audit.json`.
Raporda her girdi için SHA-256 vardır. Bu kontrol veri anlamının kaynak
makaleyle doğrulanması veya model performansı değerlendirmesi değildir.

## Sayısal sonuç

Kontroller hata üretmedi. Bu sonuç tabloyu operasyonel kullanım için onaylamaz.

| Kontrol | Sonuç |
| --- | --- |
| Ham tablo | 52.026 satır |
| Hedef tablo | 36.356 satır, tamamı ham veride `Label_03=0` |
| Ham hazırlık satırlarının hedefte kapsanması / sırası | Eksiksiz, aynı sıra |
| Ham faz geçişlerinden türetilen oturum kimlikleri | Hedefteki 30 oturumla eşleşiyor |
| Ürün geçiş etiketleri | 6 farklı yönlü geçiş, her biri 5 oturum |
| Bölmeler | Train 18 / validation 6 / test 6 oturum |
| Bölmelerin satırları | Train 24.309 / validation 5.915 / test 6.132 |
| Oturumun birden fazla bölüme dağılması | Yok |
| Train → validation → test zaman sırası | Korunmuş, zaman aralıkları çakışmıyor |
| Geçen süre | Satır zamanı − oturumun ilk hazırlık örneği ile eşleşiyor |
| Kalan süre | Oturumun son hazırlık örneği − satır zamanı ile eşleşiyor |
| Zaman damgaları | Geçerli, benzersiz ve artan |
| 1 saniyelik örneklemeden sapmalar | Ham tabloda 6; hazırlık oturumlarının içinde 0 |
| Geçmiş sayacı / 30–60 saniyelik pencere bayrakları | Oturum içi örnek sayısıyla tutarlı |
| Korunan sensör sütunlarındaki gözlenen değerler | Değiştirilmemiş |
| Eksik veri işaretleri | Ham verideki eksik konumlarla eşleşiyor |
| Hedef tablodaki boş hücreler | Yok; bu fiziksel bilgi eksikliği giderildi demek değildir |

Ürün etiketlerinin sayım tutarlılığı doğrulandı; A/B/C'nin fiziksel ürünlerle
eşlemesi bu audit tarafından bağımsız doğrulanmadı. Eğitim/test hedefleri
üzerinde yalnız bütünlük kontrolü yapıldı; model/özellik seçimi yapılmadı.

## Eksik değer dönüşümleri

Sayılar yalnız hedef tablodaki hazırlık satırlarına aittir:

| Sütun | Doldurulan hücre | Kodlama |
| --- | --- | --- |
| `Line_Content` | 35.945 | `__NO_NC_LINE__` |
| `Tool_ID` | 10.251 | `__NO_TOOL_IN_SPINDLE__` |
| `Tool_ID_Magazine_Place_49` | 1.449 | `__NOT_REPORTED__` |
| `Magazine_9999_number_Place_1` | 5.709 | `-1` |
| `Magazine_9999_position_Place_1` | 5.709 | `-1` |
| `Tool_ID_Magazine_9999_Place_1` | 5.709 | `__NOT_REPORTED__` |

Gözlenen mevcut değerlerin değişmediği ve her eksik için `__was_missing`
bayrağının doğru olduğu kontrol edildi. Kodlamalar sabit değerlerdir;
bu audit bunları öğrenilmiş istatistik veya fiziksel durum doğrulaması saymaz.
Özellikle `NO_TOOL` ifadesi kaynak doğrulaması olmadan "takım yok" diye
yorumlanmamalı. `-1` de gerçek sensör ölçümü değildir; ileride ölçekleme/PCA'ya
normal sayısal ölçüm gibi sokulmamalı. Eksik işareti ile anlamı belgelenmiş,
yalnız eğitimde öğrenilen ön işleme stratejisi gerekir.

## Kalan kararlar

1. **Bitiş sınırı:** Bütün 30 oturumda son hazırlık örneğinden 1 saniye sonra
   `Label_03=1` örneği geliyor. Mevcut hedef son hazırlık örneğinde sıfır.
   Üretim fazının ilk örneği bitiş kabul edilirse her hedef 1 saniye
   (`1/60` dakika) artar. Sayısal hata değil, açık seçilmesi gereken hedef
   tanımıdır; sessizce değiştirilmedi.
2. **Tahmin anı:** Bu tablo hazırlık sürerken kalan süre tahminine uygundur.
   Hazırlık başlamadan toplam süre tahmini için aynı sensör geçmişi kullanılamaz.
3. **Tekrarlanabilirlik:** Yeni commit'te hedef CSV'yi oluşturan dönüşüm kodu
   yok. Kod, kaldırılan sütun gerekçeleri, ürün eşlemesi ve güncel veri-model
   sözleşmesi teslim edilmelidir. Mevcut audit CSV'yi kontrol eder, onu üretmez.
4. **Özellik kapısı:** `remaining_changeover_time_min` yalnız hedef;
   `split`, oturum kimliği, mutlak `time`, ham `Label_*` alanları özellik değil.
   Her sensörün o andaki erişilebilirliği ayrıca incelenmeli. Pencereler ileriye
   bakmamalı ve oturum sınırını aşmamalı. Geçen süre online kullanılabilir;
   oturumun gerçek bitişinden hesaplanan toplam süre özellik olamaz.
5. **Küçük örneklem:** 36.356 bağımsız deney değil, 30 oturum vardır.
   Deneyde oturum bazlı hata, geçiş kapsamı ve train-only medyan referansı
   raporlanmalı. Bu kontrol PCA/TabPFN başarısı kanıtı değildir.
6. **Zaman dilimi:** Kaynak zaman damgaları offsetsizdir; İstanbul/UTC
   kendiliğinden atanmadı. İncelenen yerel sıralama gerçek dünya zaman
   diliminin doğrulanması anlamına gelmez.

Ham tablodan hedefe geçerken indeks, etiketler, üç program zaman alanı ve
`Program_Stop` kaldırılmış; tam sütun listesi JSON raporundadır. Bu audit
kaldırılan her sütunun gereksiz olduğunu kanıtlamaz.

## Yeniden çalıştırma

```sh
.venv/bin/python -m ml_experiments.cnc_audit \
  --ref 3abae7380c7d724d47dd0335330de74a104f4b98 \
  --output results/cnc_audit.json
.venv/bin/python -m pytest -q tests/test_cnc_audit.py
```

Sayısal hata varsa CLI sıfırdan farklı çıkış kodu verir. Fiziksel anlam ve
hedef sınırı gibi açık kararlar uyarı olarak kalır. Sentetik bozulma testleri;
yanlış hedef, oturum sızıntısı, değişmiş sensör, hatalı eksik bayrağı, yanlış
pencere bayrağı, eksik satır ve bozuk zaman damgasının yakalandığını kontrol
eder. Bu fixture'lar gerçek model değerlendirmesi değildir.

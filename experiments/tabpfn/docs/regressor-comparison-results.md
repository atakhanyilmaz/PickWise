# Medyan regresyonu, Gradient Boosting ve CatBoost karşılaştırması

17 Ekim 2026. **Sonuç: mevcut girdiler ve sabit ayarlarla global medyana
karşı güvenilir ek fayda gösteremedik.** Toplam sürede medyan en iyi; geçişte
medyan regresyonunun iş bazlı farkı yaklaşık 41 saniye ve belirsizlik aralığı
sıfırı kapsıyor. Yeni modellerin tümü gerçek fit/predict ile çalıştırıldı.

Built with PriorLabs-TabPFN. Önceki gerçek TabPFN/ExtraTrees tahminleri,
kaynak hash'leri ve validation satırlarının kimlik/hedef/özellik eşitliği
doğrulanarak karşılaştırmaya eklendi; bu tur yeniden fit edilmedi.
[Ağırlık lisansı](licenses/TabPFN-v2-reg-LICENSE.txt).

## Aynı veri, sabit protokol

- Toplam gözlenen iş aralığı: 72 eğitim / 17 doğrulama işi; X parça ve miktar.
- Koşullu makine kaynakları arası gözlenen bekleme: 106 çift / 52 eğitim işi,
  13 çift / 8 doğrulama işi; X parça, miktar, kaynak ve hedef makine.
- Bölmeler önceki deneyle aynı; hedef makinenin önceden bilindiği varsayımı
  yine doğrulanmış değil. Taşıma veya teslim süresi kanıtı değildir.
- Her model için tek konfigürasyon, fit öncesi fixed_protocol.json içine
  yazıldı. Grid search, validation early-stopping/eval_set yok.
- Modelin iç eğitim kaybı MAE/medyan odaklı; eğitim satır ağırlıkları eşit,
  geçişin ana değerlendirmesi iş başına MAE'lerin eşit ağırlıklı ortalaması.
- Önceki validation sonuçları görülmüş olduğundan bu yeni tur keşifseldir;
  bağımsız başarı teyidi sayılmaz. Final test skoru hesaplanmadı.

## Sayısal sonuçlar

| Yöntem | Toplam MAE (gün) | Geçiş iş bazlı MAE (saat) |
| --- | ---: | ---: |
| Global medyan | **6,56** | 29,67 |
| Grup medyanı | 7,40 | 32,05 |
| Medyan regresyonu | 6,69 | **29,66** |
| Gradient Boosting, MAE | 7,15 | 31,44 |
| CatBoost, MAE | 9,66 | 32,72 |
| Önceki TabPFN v2 | 7,89 | 39,25 |
| Önceki ExtraTrees | 9,76 | 41,79 |

Geçişte medyan regresyonu iş bazlı MAE'yi 1.780,3333 dakikadan 1.779,6458
dakikaya indiriyor: yalnız 0,6875 dakika (~41,25 saniye), yaklaşık %0,039.
Satır bazlı MAE ise 2.334,1154 → 2.335,3846 dakika ile biraz kötüleşiyor.
Bu sonuç anlamlı kazanım diye sunulmaz. İş bazlı bootstrap 8 doğrulama
işiyle keşifseldir; yeni modeller için aralıklar ham JSON'dadır.

Toplamda medyan regresyonu medyana en yakın öğrenen modeldir ama daha iyi
değildir. CatBoost kategorik destek sağladığı için adaydı; mevcut az örnekli
veride bu sabit ayarla iyi sonuç vermedi. Bu, başka veri/ayarlarla CatBoost'un
başarısız olacağını kanıtlamaz.

## Kullanılan ayarlar ve ön işleme

- QuantileRegressor: quantile=0.5, alpha=0.1, solver=highs. Kategoriler için
  train-only one-hot, miktar için train-only StandardScaler; bilinmeyen
  kategoriler sıfır one-hot'a döner.
- GradientBoostingRegressor: loss=absolute_error, 100 ağaç, learning_rate=0.05,
  max_depth=2, min_samples_leaf=5, random_state=0. Train-only one-hot.
- CatBoostRegressor 1.2.10: loss=MAE, 200 iterasyon, depth=3,
  learning_rate=0.03, l2_leaf_reg=10, boosting_type=Ordered, random_seed=0,
  thread_count=1. Kategoriler doğrudan train girdisiyle işlenir; eval_set yok.
- Bütün tahminler sıfırdan aşağı kırpılır; hedeflere kırpma uygulanmaz.
  PCA, yeni sensör özellikleri veya gelecekte bilinecek rota özetleri yok.

Kod: `experiments/tabpfn/compare_regressors.py`.
Ortam: ayrı `.venv-tabpfn`; tam kilit bu klasörün requirements-lock.txt dosyası.
Ana uygulamanın bağımlılıkları veya planlama davranışı değiştirilmedi.

## Karar

Modelleri ürün akışına bağlamıyoruz. Daha fazla algoritma deneyip bu küçük
validation bölümünde tesadüfi kazanan aramıyoruz. Sonraki anlamlı iyileştirme;
iş başlangıcında bilinen planlı rota, kaynak ataması, kapasite/takvim ve
doğrulanmış iş/parti hedefleriyle yeni veri protokolü kurmak. Bunlar veri
kaynağında yoksa özellik uydurulamaz. Daha geniş ve bağımsız doğrulama gerekir.

Medyanın kendisi de yüksek hatalıdır; "en iyi çıktı" olması işletmede
güvenilir olduğu anlamına gelmez. Kullanıcı onaylı işlem süreleriyle CP-SAT
planlaması bu başarısız tahmin deneyinden bağımsız çalışmaya devam eder.

## Tekrar çalıştırma

Depo kökünden:

```sh
.venv-tabpfn/bin/python -m pip install -r experiments/tabpfn/requirements-lock.txt
.venv-tabpfn/bin/python -m experiments.tabpfn.compare_regressors
```

Çıktılar `experiments/tabpfn/results/regressor_comparison/` altında:
fixed_protocol.json, validation_report.json ve iki validation prediction CSV.
Önceki gerçek tahmin dosyaları veya kaynaklar değişmişse karşılaştırma durur;
farklı veri sürümlerinin skorları aynı tabloya sessizce eklenmez.

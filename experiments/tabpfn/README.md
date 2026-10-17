# Ayrı TabPFN deney alanı

Built with PriorLabs-TabPFN.

Bu klasör ana planlama/Gemma/SQLite uygulamasına bağlı değildir. Kod,
denetim, deney testleri, ortam kilidi, lisans ve sayısal sonuçlar burada
toplanır. Girdi CSV'leri ve Yunus'un manifestleri depodaki mevcut yerlerinden
salt okunur kullanılır; kopyalanıp değiştirilmez.

## V1 ve V2 ne?

V1, ilk TabPFN neslidir; küçük tablosal **sınıflandırma** problemleri için
geliştirilmiştir. V2 sonraki nesildir; sınıflandırmanın yanında **regresyon**
ile sayısal değer tahminini destekler. V2 burada "bizim ikinci denememiz"
veya "ikinci süre modeli" demek değildir.
[İlk çalışma](https://arxiv.org/abs/2207.01848),
[v2 çalışması](https://www.nature.com/articles/s41586-024-08328-6).

İki görevde de aynı `tabpfn-v2-regressor.ckpt` ağırlıklarıyla **iki ayrı
TabPFNRegressor nesnesi** çalıştırıldı. Eğitim bağlamları ve hedefleri ayrıdır:

| Görev | Eğitim / doğrulama | Özellikler |
| --- | --- | --- |
| Toplam gözlenen iş süresi | 72 / 17 iş | Parça, sipariş miktarı |
| Koşullu makine kaynakları arası gözlenen bekleme | 106 / 13 çift (52 / 8 iş) | Parça, miktar, kaynak ve hedef makine |

Ağırlıklar sıfırdan eğitilmedi. Sonuçlar rapor/prediction CSV olarak saklandı;
ayrı fit edilmiş model nesneleri pickle olarak kaydedilmedi. Tek komut iki
eğitim bağlamını yeniden kurar. Hedef makinenin önceden bilindiği varsayımı
ve hedeflerin fiziksel anlam sınırı [sonuç raporunda](docs/learnability-results.md).

## Sonuç

Doğrulamada global medyan daha iyi:

| Hedef | Medyan MAE | TabPFN v2 MAE |
| --- | ---: | ---: |
| Toplam iş aralığı | 6,56 gün | 7,89 gün |
| Bekleme (iş bazlı MAE ortalaması) | 29,67 saat | 39,25 saat |

Final test başarısı ölçülmedi, ürün akışına bağlanmadı. Bu küçük deney tüm
olası modellerin başarısız olacağını kanıtlamaz.

## Dosyalar

- `learnability.py`: iki görevin veri üretimi, medyan/ExtraTrees/TabPFN ve
  yalnız validation değerlendirmesi.
- `process_target_audit.py`: aday sürelerin/sıralamanın veri yeterliliği kontrolü.
- `tests/`: sızıntı kapıları, metrikler ve hedef denetimi testleri.
- `results/learnability/`: gerçek validation raporu ve iki prediction CSV.
- `results/process_target_audit/`: iş ve aday geçiş denetim çıktıları.
- `docs/`: araştırma, sonuç, hedef yeterliliği ve kararlar.
- `requirements.txt`, `requirements-lock.txt`: deney ortamı; ana ortamdan ayrı.
- `docs/licenses/`: v2 regressor lisansı.

## Çalıştırma

Komutlar depo kökünden çalıştırılır:

```sh
python3.11 -m venv .venv-tabpfn
.venv-tabpfn/bin/python -m pip install -r experiments/tabpfn/requirements-lock.txt
.venv-tabpfn/bin/python -m experiments.tabpfn.process_target_audit
.venv-tabpfn/bin/python -m experiments.tabpfn.learnability --tabpfn --device cpu
```

Mevcut ayrı sanal ortam `.venv-tabpfn/` kökte bırakılmıştır; çalıştırıcıların
mutlak yollarını bozmamak için taşınmadı ve Git dışındadır. Ağırlık/cache
`experiments/tabpfn/results/learnability/model_cache/` altında, Git dışındadır.
Bu paket ana uygulamanın bağımlılık listesine TabPFN/torch eklemez.

Deneyin veri/metrik testleri mevcut ana test ortamında çalışabilir:

```sh
.venv/bin/python -m pytest -q experiments/tabpfn/tests
```

Ana testler ayrı kalır: `.venv/bin/python -m pytest -q tests`.

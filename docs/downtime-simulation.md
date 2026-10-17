# Planlı makine duruşu simülasyonu

`core.downtime.simulate_downtime` mevcut `PlanSnapshot` ve tipli
`DowntimeRequest` alır. Yeni senaryo üretir; başlangıç nesnesini, plan sürümünü
veya SQLite kaydını değiştirmez. CP-SAT'ın mevcut downtime kısıtını kullanır;
benchmark modeli değişmedi. Bütün zamanlar senaryonun t=0 referansından
tamsayı dakikadır; gerçek tarih veya doğal dil dönüşümü yapılmaz.

## Bağlantı

```python
from core.downtime import DowntimeRequest, simulate_downtime

# baseline: SQLitePlanRepository.load_current(plan_id).snapshot olabilir.
request = DowntimeRequest(
    baseline_version_id=baseline.version_id,
    scenario_id="planned-maintenance",
    machine_id=100,
    start=10,
    end=20,
    reason="Kullanıcının doğruladığı planlı bakım",
    preserve_existing_completions=False,
    time_limit_seconds=10,
)
simulation = simulate_downtime(baseline, request)
```

Çıktı: baseline_version_id, request, yeni scenario, doğrulanmış result,
varsa comparison ve Türkçe durum mesajı. Sürüm yanlışsa veya scenario_id
başlangıçla aynıysa istek reddedilir. Tanınmayan makine, bozuk aralık ve
current_time öncesine yeni duruş ekleme de reddedilir.

## Desteklenen davranış

- Duruş `[start, end)` aralığıdır: işlem duruş başlangıcında bitebilir,
  duruş sonunda başlayabilir.
- Var olan duruşlar korunur; çakışan/bitişik aralıklar birleşim olarak tutulur.
  Yeni aralık var olanı kaldırmaz veya kısaltmaz.
- Uygun makine listeleri değişmez. Çözücü yalnız önceden tanımlı alternatif
  makineleri kullanabilir; makineye bağlı işlem süreleri korunur.
- İşler, operasyon sırası, hazır olma zamanı, sert/yumuşak terminler ve mevcut
  completion_limits korunur. Amaç sert sınırlar altında makespan azaltmadır;
  yumuşak termin gecikmesi raporlanır, minimize edildiği iddia edilmez.
- `preserve_existing_completions=True` başlangıç planındaki bitişleri ayrı
  sert sınır yapar; mevcut daha sıkı sınır gevşetilmez.
- Karşılaştırma makespan, etkilenen/geciken mevcut işler, operasyon değişimleri
  ve yumuşak termin gecikmelerini verir. Yeni iş eklenmez; new_job_ids boştur.
- Duruş gerekçesi request'te ve yeni senaryo açıklamasında tutulur; onaylanan
  plan yeni sürüm olarak kaydedilirse açıklama ve aralıklar da kalıcı olur.

## Bilerek desteklenmeyen

Başlamış bir operasyonun işgal aralığını kesecek duruş açık `ValueError`
üretir. İlk sürüm operasyonu bölmez, kalan süreyi uydurmaz veya geçmiş
başlangıcı değiştirmez. Bu yüzden "şu an çalışan makine bozuldu, işi durdur
sonra devam ettir" akışı henüz yoktur. Planlı duruş mevcut başlamış iş
bittikten sonra uygulanabilir; geçmiş kayıtları değiştirme desteği yoktur.

OPTIMAL, FEASIBLE, INFEASIBLE, UNKNOWN ve MODEL_INVALID ayrımı korunur.
Çözüm yoksa comparison=None olur. UNKNOWN imkânsızlık kanıtı değildir;
INFEASIBLE yalnız modellenen kısıtlar içindir. Baseline FEASIBLE ise yeni
çözüm farkının bir bölümü yeniden optimizasyondan gelebilir; salt duruşun
nedensel etkisinin optimum karşılaştırması diye sunulmaz.

## Sentetik demo ve manuel giriş

```sh
.venv/bin/python -m benchmarks.workshop_downtime_demo
```

Mevcut sentetik `data/examples/order_demo.json` kullanılır. Dört çıktı:

| Senaryo | Sonuç |
| --- | --- |
| M100 için [10,20) duruş | Bitiş 15 → 25, 1 mevcut iş gecikir, termin gecikmesi 5 dakika |
| İşin 15'te bittiği sınırda [15,20) | Bitiş 15, geciken iş yok |
| Aynı duruş + mevcut bitişleri koruma | INFEASIBLE; karşılaştırma yok |
| Bekleyen iş için önceden uygun M200, süre 7 | Alternatif makineye geçer, bitiş 17, termin gecikmesi yok |

Alternatif örneğin baseline'ında M200 uygunluğu baştan vardır; simülasyon
kendi kendine makine uygunluğu eklemez. Tamamlanmış 0–3 ve başlamış 3–10
operasyonları bütün uygulanabilir sonuçlarda korunur.

Her örnekte `results/workshop_downtime/NAME/` altında baseline.json,
simulation.json ve çevrimdışı Plotly içeren report.html üretilir. Gri taralı
çubuklar yalnız ilgili makinenin duruşunu gösterir. Bunlar gerçek atölye
ölçümü değildir.

Elle sağlanan snapshot ve request JSON için:

```sh
.venv/bin/python -m benchmarks.workshop_downtime_demo \
  --baseline YOUR_BASELINE.json --request YOUR_DOWNTIME_REQUEST.json \
  --output results/manual_downtime
```

Uygulanabilir simülasyonu kullanıcı ayrıca seçerse `PlanSnapshot` yeni
version_id ile kurulur, `StoredPlanVersion.parent_version_id` başlangıç
sürümü olur ve mevcut SQLite repository'ye kaydedilir. Simülasyon çağrısı
bunu yapmaz. UI ve Gemma'nın doğal dil duruş işlemi henüz bağlanmadı;
mevcut Gemma desteklenmeyen duruş talebini sessizce siparişe çevirmemeli.

Testler: yeni duruşun etkisi, alternatif makine, sert termin/cap uygunsuzluğu,
yarı açık sınır, aralık birleşimi, history koruma, geçersiz/geçmiş/başlamış iş
istekleri, UNKNOWN mesajı, karşılaştırmada değişmez alanlar ve SQLite'ta ayrı
seçimle yeni sürüm kaydı. Gerçek makine kesme/devam testi değildir.

# Türkçe atölye planlama prototipi

Ürün adı henüz kesinleşmedi. Mevcut çalışan dilim Atakan'ın WP-1A görevi:
Brandimarte Mk01–Mk10 girdilerini kaynak parser ile okumak, kaynak CP-SAT
modeliyle çözmek ve bağımsız doğrulamak.

## Kurulum ve tekrar çalıştırma

Python 3.11 kullanıldı. Proje kökünde:

```sh
sh scripts/fetch_upstream.sh
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements-lock.txt
.venv/bin/python -m pytest -q tests
.venv/bin/ruff check core benchmarks tests
.venv/bin/python -m benchmarks.brandimarte_runner --time-limit 10
```

Tek örnek: `.venv/bin/python -m benchmarks.brandimarte_runner --instances Mk01 --time-limit 10 --output results/mk01`.
Her çalıştırma seçilen çıktı klasöründeki aynı adlı raporları yeniler; eski deneyi
korumak için farklı `--output` verin. Süre sınırı örnek başına çözücü aramasına
uygulanır; parser, model kurma ve grafik süresi buna dahil değildir.

## Çıktılar

- `results/brandimarte/summary.csv`: her problem/yöntem için boyutlar, durum,
  makespan, varsa alt sınır, çalışma süresi, ihlal sayısı.
- `results/brandimarte/Mk01.json` … `Mk10.json`: tam çizelgeler, dosya SHA256,
  kaynak commit, Python/OR-Tools/platform, seed ve worker ayarları.
- `results/brandimarte/Mk01_cp_sat.html`: internet gerektirmeyen etkileşimli Gantt.
- `results/brandimarte/Mk01_job_order_eft.html`: referans yöntemin Gantt'ı.

Süreler **benchmark zaman birimi**; dakika veya gerçek teslim tarihi değildir.
`FEASIBLE` geçerli bulunan planı, `OPTIMAL` bu model için optimum kanıtını belirtir.
`UNKNOWN` süre içinde çözüm/kanıt elde edilememesidir, imkânsızlık değildir.
`INFEASIBLE` modellenen kısıtların uygulanamazlığını, `MODEL_INVALID` model hatasını
belirtir. Çözüm yoksa makespan ve ihlal sayısı boş bırakılır; doğrulandı sayılmaz.
Runner doğrulanmamış veya geçersiz herhangi bir sonuçta hata koduyla çıkar.

## Kaynak ve katkı ayrımı

[Kaynak depo](https://github.com/ai-for-decision-making-tue/Job_Shop_Scheduling_Benchmark_Environments_and_Instances)
commit: `d088a26582f5cb79c6b4f2ad94f68ac7c50878cb`.

Kaynak `external/job_shop_benchmark` altında ayrı Git checkout olarak tutulur;
Yunus kaynak geçmişini ayrıca ana repoya birleştirmiştir; kökteki kaynak dosyalar korunur.
Benchmark adaptörü sabit external checkout üzerinden çalışır. `origin` ekip reposudur. Checkout
`.gitignore` içindedir, ekip arkadaşları fetch scriptiyle aynı sürümü getirir.
Kaynağın MIT lisansı ve atıfları kendi klasöründe korunur. Benchmark dosyalarının
kökeni kaynak deponun `data/fjsp/brandimarte` dizinidir; dış benchmark haklarının
ayrı ticari kullanım incelemesi bu test kapsamında yapılmadı.

Kaynak katkısı: Brandimarte girdileri, parser, Job/Operation/Machine/JobShop ve
FJSP CP-SAT modeli (kaynak dosyada OR-Tools örneğine atıf bulunur).
Bizim katkımız: sıkı girdi denetimi, küçük adaptör, deterministik job-order/EFT
referansı, bağımsız doğrulayıcı, testler, raporlar ve Plotly Gantt çıktısı.
Bu referans yöntem kaynak deponun FIFO/SPT uygulaması değildir.

Kaynak runner'daki import/sonuç raporlama sorunları nedeniyle doğrudan model
fonksiyonu çağrılır; kaynak kod değiştirilmez. Ayrıntı: [ADR](docs/decisions/001-upstream-adapter.md).
Tüm kaynak algoritmalarının çalıştığı iddia edilmez; bu test yalnızca FJSP CP-SAT hattını kapsar.

## Öğrenme ve kapsam

[Adım adım depo rehberi](docs/repo-walkthrough-tr.md).

Atölye katmanı, sert termin, hazır olma zamanı, sabit tamamlanmış/devam eden
operasyonlar ve makine duruşlarını destekler. Tüm gerçek senaryo süreleri
integer dakikadır. Benchmark birimleri bundan ayrıdır. SQLite, yeni siparişin
önce/sonra karşılaştırma servisi, Streamlit, Gemma ve süre tahmini henüz yoktur.

## Atölye modeli (WP-2A)

```python
from core.cpsat_solver import solve
from core.workshop_fjsp_builder import build_env, demo_scenario

env, jobs, n_machines = build_env(demo_scenario())
result = solve(env, time_limit=10)
print(result["status"], result["makespan"], result["violations"])
```

`current_time` yeniden planlama anı; `release_time` en erken iş başlangıcıdır.
`deadline` sert termindir. Tamamlanmış işlemlerde `fixed_machine_id`,
`fixed_start`, `fixed_end`; devam eden işlemlerde gerçek makine, başlangıç ve
`remaining_duration` zorunludur. Başlamamış işler geçmişe yerleştirilmez.
Duruşlar `unavailable_intervals=[(başlangıç, bitiş)]` ile verilir. Operasyonlar
bölünemez; duruşla çelişen sabit işlem uygulanamaz senaryo üretir.

Sonuçtaki `source_*_id` alanları kaynak kimliklerini korur; `job`, `operation`,
`machine` alanları iç indislerdir. Uygulanabilir sonuçlar bağımsız atölye
doğrulayıcısından geçer. Demo rotaları/süreleri sentetik varsayım olarak etiketlidir.
Retrospektif rota varsayılan olarak engellenir; açık retrospektif simülasyon
`approved_only=False` ile mümkündür ve sonuçta etiketlenir.

Karar ve sınırlar: [Atölye ADR](docs/decisions/002-workshop-constraints.md).

## Entegrasyon ve bağımlılıklar

Kaynak README ve bilimsel atıflar [ayrı belgede](docs/upstream-README.md) korunur.
Kökteki `requirements.txt` kaynak deponun listesidir. Bizim doğrudan
bağımlılıklarımız `requirements-benchmark.txt`, tam kilidimiz
`requirements-lock.txt` içindedir. Pydantic 2.14.1 sabitlenmiştir.

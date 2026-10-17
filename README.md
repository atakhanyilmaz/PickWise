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
integer dakikadır. Benchmark birimleri bundan ayrıdır. Yeni sipariş ve önce/sonra karşılaştırma servisi aşağıdaki demo ile çalışır.
SQLite, Streamlit, Gemma ve süre tahmini henüz yoktur.

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

## Yeni sipariş ve önce/sonra demo

```sh
.venv/bin/python -m benchmarks.workshop_order_demo
```

Girdi: `data/examples/order_demo.json` (tamamen sentetik). Çıktı:
`results/workshop_order/comparison.html`, başlangıç snapshot JSON'u, üç
simülasyon JSON'u ve `summary.csv`. Farklı deney için `--input`, `--output` ve
`--time-limit` seçenekleri vardır; aynı çıktı klasörü yeniden kullanılırsa
raporlar yenilenir.

Mevcut plan 15 dakikada biter. Yeni sipariş yalnız Torna 1'e verilirse makespan
25 dakika, mevcut bir işin termin gecikmesi 5 dakikadır. Doğrulanmış demo
alternatifi Torna 2 ile makespan 17, mevcut işlerde gecikme 0'dır. Yalnız Torna 1
kullanılırken mevcut bitişleri korumak zorunluysa senaryo INFEASIBLE'dır.
Bu sayılar gerçek işletme ölçümü değildir.

`core/scenarios.py`: tipli snapshot, sipariş isteği, simülasyon ve karşılaştırma
sonuçları. `simulate_order` başlangıç planını değiştirmez; uygulanamaz veya
UNKNOWN sonuçta önce/sonra metriği uydurmaz. `deadline` sert sınırdır;
`due_date` raporlanan yumuşak termindir. Hedef makespan azaltmadır, yumuşak
gecikme minimizasyonu değildir. `completion_limits`, müşteri termininden ayrı
mevcut bitiş koruma kısıtıdır. Ayrıntı: [Sipariş ADR](docs/decisions/003-order-simulation.md).

SQLite'ya onaylı plan sürümü kaydetme, Streamlit ve Gemma entegrasyonu henüz yoktur.

## UI'den bağımsız yerel Gemma servisi (deneysel)

Ollama'da hazır `gemma4:e2b` kullanılır; otomatik model indirilmez.

```sh
ollama serve
.venv/bin/python -m benchmarks.gemma_order_cli \
  --baseline results/workshop_order/baseline.json \
  --text 'Yeni sipariş: tornalama, Torna 1 üzerinde 10 dakika. Sert termin t=20 dakika.'
```

Taslak önce gösterilir; CLI `evet` onayı olmadan simülasyon çalıştırmaz.
Eksik bilgi, desteklenmeyen kısıt veya geçersiz model çıktısı soruyla/mesajla döner.
`USER_PROPOSED` rota çözücüye doğrudan sokulamaz. Model yokken insan onaylı JSON
sipariş `--order-json PATH` ile çalıştırılabilir; sayısal açıklama computed_fallback
olarak etiketlenir. Model varken de açıklamanın bütün sayıları hesaplanan bulgulardan
gelir; Gemma bu bulguları seçer. `core/llm/` UI'nin bağlanacağı servisleri içerir.

Gerçek model smoke testi: `.venv/bin/python -m benchmarks.gemma_evaluation`.
İstem v2, beş geliştirme örneğinde 3/5 beklenen akışı geçti; tam sipariş doğru
çıkarıldı. Belirsiz makine/tarih hataları reddedildi. Bu sonuç, üretim kalitesi
veya ağ kapalı çevrimdışı çalışma kanıtı değildir. Yerel talep/model kayıtları
`results/gemma*/` altında Git'ten hariç tutulur. SQLite ve UI bağlanmadı.

## Süre tahmini hazırlığı

```sh
.venv/bin/python -m ml_experiments.duration_evaluation \
  --dataset data/examples/duration_experiment_synthetic.json
```

Bu komut yalnız sentetik veride medyan referansını hesaplar. Gerçek veri veya
TabPFN deneyi yapılmadı. Veri sözleşmesi, iş emri/zaman sızıntısı kontrolleri,
medyan fallback, izinli özellikler ve MAE/RMSE raporlaması hazırdır.
[Yunus veri teslim sözleşmesi](docs/duration-data-handoff.md).
[Gemma ve deney kararı](docs/decisions/004-local-gemma-and-duration-evaluation.md).

Genişletilmiş kontrol: `.venv/bin/ruff check core tests benchmarks ml_experiments`.

## Gemma: niyet ayrımı ve takip soruları

UI/CLI akışı artık `core.llm.conversation.begin_intake` ve `answer_intake`
fonksiyonlarını kullanır. Niyet ve alan çıkarımı ayrı model çağrılarıdır.
Eksik/belirsiz alan `session.pending` içinde soru ve seçeneklerle döner.
Makine/süre yanıtı yalnız ilgili alanı kodla değiştirir; diğer alanlar korunur.
Süre örnekleri `iki saat`, `bir buçuk saat`, `25 dakika` olabilir. Son taslak
ayrı insan onayı gerektirir. `extract_order` eski tek mesajlı API olarak kalır.

```sh
.venv/bin/python -m benchmarks.gemma_order_cli \
  --baseline results/workshop_order/baseline.json \
  --text 'Yeni sipariş: Torna 1 üzerinde tornalama yapacağız.'
```

CLI süreyi sorar; ardından tamamlanmış taslağı gösterip ayrıca onay ister.
Gerçek tarih dönüşümü yoktur: göreli termin için kullanıcıdan `t=40 dakika`
gibi açık sınır istenir. Duruş doğal dil aracı sonraki aşamadadır;
manuel planlı duruş servisi aşağıdaki bölümde açıklanır.

```sh
.venv/bin/python -m benchmarks.gemma_conversation_evaluation --split development
.venv/bin/python -m benchmarks.gemma_conversation_evaluation --split heldout
```

Son gerçek model çalıştırmasında geliştirme 7/8, ayrı test 6/6 akış geçti.
Bu küçük sentetik servis testi; genel model/saha doğruluğu iddiası değildir.
Kod kontrolleri ve test kullanıcı yanıtları sonuca dahildir. Önceki 3/5 rapor
tek mesajlı eski API'ye aittir. [Karar ve kapsam](docs/decisions/005-gemma-conversation-reliability.md).
Yunus'un gerçek veri hazırlığı bu çalışmanın girdisi değildir; TabPFN deneyi
onaylı hedef ve veri kümesini bekler.

## Arayüz (WP-1N, WP-2N)

```sh
.venv/bin/streamlit run ui/app.py
```

Plan, Rota onayı, Benchmark ve Hakkında sayfaları. `ui/components.py` tekrar
kullanılan bileşenleri (metrik satırı, Altair Gantt, tablo, kaynak rozetleri,
rota düzenleyici), `ui/pages.py` sayfaları içerir. Gündüz ve gece temaları
`.streamlit/config.toml` içindedir; kullanıcı sağ üstteki ⋮ menüsünden Light,
Dark veya System seçer;
hesaplama mevcut `core` servislerinden gelir. Plan sayfası
`database/local/workshop.sqlite3` içinde `synthetic-workshop` için onaylı sürüm
varsa onu, yoksa kaydedilmemiş demo planı gösterir. Benchmark sayfası
`results/brandimarte/` sonuçlarını okur ve seçilen örneği yeniden çözebilir.

Rota onayı sayfası bir sipariş taslağının işlem sırasını, uygun tezgâhlarını ve
dakika sürelerini düzenletir. Düzenlenen süre `user_input`, düzenlenen rota
`user_proposed` olur; rota yalnız açık onay kutusu ve düğmesiyle
`user_approved` olur ve oturumda saklanır. Rota ve süre kaynakları Plan
tablosunda ve onay ekranında aynı renkli rozetlerle gösterilir. Geçmiş veriden
otomatik rota önerisi henüz yok (WP-2A); retrospektif taslak gelirse uyarıyla
gösterilir. Simülasyon, önce/sonra ve plan kaydetme sonraki pakettir (WP-4N).

## Planlama hattı

`core/pipeline.py` mevcut servisleri tek girişte sıralar: plan → tek değişiklik
(yeni sipariş `simulate_order` veya duruş `simulate_downtime`) → çözüm ve
doğrulama → `dispatch`. `dispatch`, seçilen dakikada her tezgâhın işlediği
operasyonu (`[başlangıç, bitiş)`) ve sıradakini verir; Plan sayfasındaki
"Şu an tezgâhlarda" kartları bunu gösterir. Başlangıç planı değişmez; değişiklik
uygulanamazsa görünüm başlangıç planına döner. Plan yükleme ve onaylı kayıt
çağıranda kalır. Gemma için LangGraph katmanı bu hattı araç olarak kullanacak
şekilde planlandı, henüz eklenmedi.

## Otomatik kontroller (CI)

`.github/workflows/ci.yml` her PR'da ve `main`'e push'ta Python 3.11 ile kaynak
depoyu sabit commit'ten getirir, `requirements-lock.txt` ve Streamlit'i kurar,
`ruff check core benchmarks tests ui`, `pytest tests` ve `tutorials/`
notebook'larını çalıştırır. Streamlit 1.66 `pillow<13` istediği için kurulumda
kilitteki pillow 13 düşürülür. `ml_experiments` biçim uyarıları düzelince
ruff kapsamına eklenmeli.

## Plan kayıt sözleşmesi

[Yunus için Pydantic kayıt/yükleme sözleşmesi](docs/plan-data-contract.md),
mevcut senaryo ve sonuç modellerini `core.plan_contract.StoredPlanVersion`
içinde birleştirir. Onay denetim bilgileri ve önceki sürüm kimliği korunur;
içe aktarılan çizelge yeniden doğrulanır. `PlanRepository` tipli arayüzdür;
SQLite uygulaması `core.sqlite_repository.SQLitePlanRepository` içindedir.
Kayıt/yükleme doğrulaması, atomik sürüm kontrolü ve eski sürümün korunması
çalışır; UI'nin ayrı plan onayıyla bağlaması gerekir. Kullanım ve CLI
komutları yukarıdaki sözleşme dokümanındadır.

## CNC veri kontrolü

[CNC hedef tablosunun kontrol raporu](docs/cnc-data-audit.md):
`ml_experiments.cnc_audit` belirtilen Git commit'indeki ham ve hedef CSV'leri
değiştirmeden karşılaştırır. Oturum/bölme, süre hesabı, sensörlerin korunması
ve eksik veri bayrakları kontrol edilir. Bu kalan süre deneyi;
planlamaya bağlı toplam hazırlık tahmini veya fiziksel anlam onayı değildir.

## Ayrı TabPFN deneyleri

İki regresyonun kodu, raporları, sonuçları, testleri ve bağımlılık kilidi
[experiments/tabpfn](experiments/tabpfn/README.md) altında tutulur.
Uygulamanın planlama, Gemma ve SQLite akışı bu paketi import etmez.
İki gerçek v2 doğrulama deneyinde global medyan geçilemedi; ürün akışına
bağlanmadı.

## Veri hazırlama testleri

Veri hazırlama ve testleri için ek doğrudan bağımlılık:

```sh
.venv/bin/python -m pip install -r requirements-data.txt
.venv/bin/python -m pytest -q tests
```

`matplotlib==3.9.2` ve kurulu ek bağımlılıkları `requirements-lock.txt` içine
alındı. Son yerel doğrulamada Yunus'un veri hazırlama testleri dahil 202 test
geçti; matplotlib/pyparsing kaynaklı deprecation uyarıları hata değildir.

## Planlı makine duruşu

`core.downtime.simulate_downtime` mevcut planı değiştirmeden makine duruşu
ekler, uygun alternatifleri çözer ve mevcut işlerin bitiş/termin etkisini
hesaplar. Başlamış operasyonu kesme/devam ettirme desteklenmez; açıkça
reddedilir. Kaydetme ayrı insan seçimi ve SQLite sürüm kaydı gerektirir.
[Servis sözleşmesi ve sınırlar](docs/downtime-simulation.md).

```sh
.venv/bin/python -m benchmarks.workshop_downtime_demo
```

JSON ve önce/sonra Gantt çıktıları `results/workshop_downtime/` altında.
Gemma doğal dil duruş aracı ve UI bağlantısı henüz yoktur.

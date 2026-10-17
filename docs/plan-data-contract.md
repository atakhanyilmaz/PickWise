# Atakan → Yunus: Pydantic plan kayıt sözleşmesi v1

Bu sözleşme gerçek veri beklemeden kullanılabilir. Planlama nesneleri
`core/domain_rules.py`, çizelge ve simülasyon nesneleri `core/scenarios.py`,
kayıt zarfı ve depo arayüzü `core/plan_contract.py` içindedir.
Bunları import edin; ikinci bir Machine/Job/Operation modeli oluşturmayın.

**Mevcut:** Pydantic doğrulaması, bağımsız çizelge kontrolü, tipli depo arayüzü
ve `core.sqlite_repository.SQLitePlanRepository` uygulaması. SQLite şeması
Yunus'un `database/schema.sql` dosyasından kullanılır. `PlanRepository` yalnız
bir Python Protocol'dür; somut sınıf SQLite işlemlerini yürütür.
UI'nin ayrı plan onay eylemini bu sınıfa bağlaması gerekir.
JSON Schema çapraz alan ve çizelge
doğrulayıcılarını çalıştırmaz; kayıt/yüklemede Pydantic doğrulaması zorunludur.

## Alanların anlamı

| Model / alan | Anlam ve kayıt kuralı |
| --- | --- |
| `MachineModel.machine_id` | Senaryo içinde benzersiz, sıfır veya pozitif tamsayı kaynak kimliği. |
| `unavailable_intervals` | Dakika çiftleri `[başlangıç, bitiş)`; pozitif uzunluk, çakışmasız. Varsayılan boş. |
| `JobModel.job_id` | Senaryo içinde benzersiz kaynak iş kimliği. |
| `operations` | Sıralı operasyon listesi: her operasyon bir öncekinden sonra gelir. Sıra korunur; serbest DAG/`predecessors` alanı yoktur. |
| `OperationModel.operation_id` | İş içinde benzersizdir; iki ayrı işte aynı değer olabilir. Veritabanında tek başına global anahtar yapmayın. |
| `processing_times` | Uygun makine kimliği → pozitif tamsayı dakika. Listede olmayan makine uygun değildir. |
| `duration_source` | `user_input`, `benchmark`, `tabpfn_estimate`, `historical_median`, `demo_assumption`. Kaynak etiketi, tahminin doğruluğuna veya kullanım onayına kanıt değildir. |
| `route_source` | `user_approved`, `user_proposed`, `retrospective`, `demo_assumption`. Öneri kullanıcı onayı değildir. Kayıt zarfı yalnız onaylı veya açıkça demo rotaları kabul eder. |
| `release_time` | İşin hazır olma zamanı; varsayılan 0. |
| `deadline` | Sert sınır: çözücüde işin bitişi bu değeri aşamaz. `null` sınır yok demektir. |
| `due_date` | Yumuşak termin: raporlama içindir; mevcut hedef toplam gecikmeyi minimize etmez. |
| `WorkshopScenario.current_time` | Simülasyonun şu anı, t=0'dan dakika. Başlamamış işler bundan önce yerleştirilemez. |
| `completion_limits` | Kaynak iş kimliği → ayrı sert bitiş sınırı; müşteri terminini değiştirmez. |
| `time_unit`, `time_unit_note` | Workshop için `minutes`; varsayımlar notta tutulur. Benchmark birimleri otomatik dakika değildir. |
| `ScheduleResult` | Durum, çizelge, makespan, bound, çözüm/süre sınırı, seed, workers ve kaynak kimlik eşlemeleri birlikte korunur. |
| `PlanSnapshot` | `version_id`, tam `scenario`, tam `result`. Yalnız OPTIMAL/FEASIBLE, bağımsız doğrulanan planı kabul eder. Tek başına kullanıcı onayı anlamına gelmez. |

Operasyon durumları:

- `not_started`: fixed/remaining alanları `null` olmalı.
- `completed`: `fixed_machine_id`, `fixed_start`, `fixed_end` zorunlu;
  bitiş `current_time` sonrasına geçemez, `remaining_duration` yoktur.
- `in_progress`: gerçek `fixed_machine_id`, `fixed_start`, pozitif
  `remaining_duration` zorunlu; `fixed_end` yoktur. Modellenen bitiş
  `current_time + remaining_duration` olur. Geçmiş başlangıç korunur;
  planlanan toplam aralık nominal işlem süresinden farklı olabilir.

Başlamış operasyonlar rota başında tutarlı bir önek oluşturur.
Kaynak kimlikleri ile solver indekslerini karıştırmayın:
`ScheduleRow.job/operation/machine` sıfır tabanlı liste indeksleridir;
`source_job_id/source_operation_id/source_machine_id` alanları kullanıcı/veri
kimlikleridir. Liste sıraları ve eşlemeleri kayıt/yüklemede aynen korunur.

## Onaylanan sürümün zarfı

`StoredPlanVersion` aşağıdaki alanları içerir; bilinmeyen alanlar reddedilir:

| Alan | Kural |
| --- | --- |
| `schema_version` | Şimdilik yalnız `1`; otomatik eski sürüm dönüşümü yok. |
| `plan_id` | Plan ailesinin boş olmayan metin kimliği; sürümler arasında sabit. |
| `parent_version_id` | İlk kayıtta `null`; sonraki kayıtta bu planın güncel sürümü. Kendi sürümüne eşit olamaz. |
| `approved_by` | Onaylayan kişinin/yerel kullanıcının boş olmayan kimliği. |
| `approved_at` | Açık UTC offset içeren ISO 8601 zaman damgası. |
| `snapshot` | Mevcut `PlanSnapshot`; yeni sürüm kimliği bunun `version_id` alanındadır. |

Onay alanları denetim kaydıdır; kullanıcı onayını veya kimlik doğrulamayı
kendiliğinden sağlamaz. UI/servis bunları ayrı **planı seç/kaydet** eyleminden
sonra doldurur. Sipariş taslağını simüle etmeye verilen onay, çıkan planı
kaydetme onayı değildir. Demo rotaları gerçek işletme verisi gibi gösterilmez.

## Python / JSON aktarımı

Aşağıdaki örnek sentetik girdiyi çözer, zarfı üretir ve JSON dönüşünü doğrular.
SQLite'a yazmaz; `approved_by`/`approved_at` örnek denetim değerleridir,
gerçek insan onayı iddiası değildir.

```python
import json
from datetime import datetime
from pathlib import Path

from core.domain_rules import WorkshopScenario
from core.plan_contract import StoredPlanVersion
from core.scenarios import create_snapshot

demo = json.loads(Path("data/examples/order_demo.json").read_text())
scenario = WorkshopScenario.model_validate(demo["baseline"])
snapshot = create_snapshot(scenario, version_id="demo-v1", time_limit=2)
record = StoredPlanVersion(
    plan_id="synthetic-workshop",
    parent_version_id=None,
    approved_by="demo-user",
    approved_at=datetime.fromisoformat("2026-10-17T12:00:00+03:00"),
    snapshot=snapshot,
)
payload = record.model_dump_json()
loaded = StoredPlanVersion.model_validate_json(payload)
assert loaded.model_dump() == record.model_dump()

# Şemayı ihtiyaç duyulan istemci için üretin; elle ayrı şema yazmayın.
schema = StoredPlanVersion.model_json_schema()
```

JSON'da `processing_times` ve `completion_limits` anahtarları metne dönüşür
(`"100"` gibi); Pydantic içe aktarımda tamsayı anahtarları geri kurar.
`model_construct()` veya doğrulamasız `model_copy(update=...)` ile içe aktarım
yapmayın. `StoredPlanVersion` kendisine verilen mevcut snapshot nesnesini de
yeniden doğrular; `violations=[]` kaydına güvenmez.

## Yunus'un depo uygulaması

`PlanRepository` şu metotları tanımlar:

```python
load_current(plan_id: str) -> StoredPlanVersion
load_version(plan_id: str, version_id: str) -> StoredPlanVersion
save_approved_version(
    record: StoredPlanVersion,
    *, expected_current_version_id: str | None,
) -> None
save_approved_versions(
    records: list[StoredPlanVersion],
    *, expected_current_version_ids: dict[str, str | None],
) -> None
```

Kayıt/yükleme davranışları:

1. Her kayıtta ve yüklemede `StoredPlanVersion.model_validate_json` veya
   eşdeğer tam doğrulama uygulanır. Geçersiz plan aktif hale getirilmez.
2. İlk kayıtta güncel sürüm yoktur; hem expected hem parent `None` olur.
3. Sonraki kayıtta expected, parent ve veritabanındaki güncel sürüm eşit
   olmalıdır. `parent` aynı `plan_id` içinde var olmalıdır. Bunlar yerel
   Pydantic modelinin değil, depo transaction'ının kontrolleridir.
4. `(plan_id, snapshot.version_id)` benzersizdir. Eski sürümün içeriği
   değiştirilemez; aynı kimlikle tekrar kayıt `PlanVersionConflict` verir.
5. Sürüm ekleme ile güncel sürüm işaretçisini değiştirme **tek atomik
   transaction** olur. İki istemci aynı eski sürümden kayıt denediğinde biri
   başarır, diğeri `PlanVersionConflict` alır; son yazan sessizce kazanmaz.
6. Bulunamayan plan/sürüm `KeyError`; bozuk içerik Pydantic `ValidationError`
   verir. Yüklemede bozuk kayıt otomatik düzeltilmez veya yeniden çözülmez.
7. Simülasyon depo metotlarını çağırmaz. `SimulationResult` taslaktır;
   başarısız çözümler onaylı plan olarak kaydedilemez. Kullanıcı uygulanabilir
   sonucu seçince yeni `PlanSnapshot` ve onay zarfı oluşturulur.

Başlangıç için tam doğrulanmış JSON payload saklamak yeterlidir; ilişkisel
tablolar eklenirse liste sırası, dict anahtarları ve tüm metadata kayıpsız geri
kurulmalı. Normalleştirilmiş operasyon anahtarı en az
`(plan_id, version_id, job_id, operation_id)` kapsamını taşımalı.
Veritabanı dosyası ve gerçek müşteri içerikleri Git'e eklenmemeli.

## Zaman ve deney verisinin sınırı

`approved_at` denetim zamanıdır; çizelgenin t=0 referansı değildir.
Workshop çekirdeği göreli tamsayı dakikalar kullanır. Şu anda gerçek tarih
başlangıcı/zaman dilimi alanı veya tarih dönüştürücüsü yoktur; kayıt katmanı
t=0 için kendiliğinden bugünü atamaz. Gerçek takvim desteği ayrı sözleşme
sürümü ve açık referans gerektirir. Sürekli çalışma ve bölünemez operasyon
varsayımları geçerlidir.

Production Analysis / CNC eğitim tabloları bu plan zarfı değildir. Kaynak
faaliyetlerden atölye işi, rota ve uygun makineye dönüşüm ayrıca doğrulanmalıdır.
Kayıtta gözlenen geçen süre otomatik net makine süresi kabul edilmez;
TabPFN/medyan hedefi ve veri teslimi `docs/duration-data-handoff.md` kapsamındadır.
Bu sözleşme TabPFN modelini veya veri adaptörünü uygulamaz.

## SQLite tesliminin kabul kontrolü

- Sentetik planı kaydet/yükle: bütün payload ve kaynak kimlikler eşit kalmalı;
  tamamlanmış ve başlamış operasyonların gerçek makine/zamanları korunmalı.
- İkinci sürümü kaydet: ilk sürüm değişmemeli, güncel sürüm ikinciye geçmeli.
- Eski sürüm bekleyen ikinci istemci reddedilmeli; yarım kayıt bırakılmamalı.
- Bozulmuş çizelge, olmayan parent, tekrarlanan sürüm ve no-solution plan
  aktif sürüm olamamalı.
- Simülasyon ve iptal güncel planı değiştirmemeli.

Bu maddeler `tests/test_sqlite_repository.py` içinde gerçek geçici SQLite
dosyalarıyla kontrol edilir; iki ayrı bağlantı yarışması ve işlem sonundaki
hata sonrası rollback dahildir. UI üzerinden gerçek insan onayı test edilmedi.

## Somut bağlantı

```python
from core.sqlite_repository import SQLitePlanRepository

repository = SQLitePlanRepository("database/local/workshop.sqlite3")
repository.initialize()
# Yalnız kullanıcı sonucu ayrıca seçip kaydetmeyi onayladıktan sonra:
repository.save_approved_version(record, expected_current_version_id=None)
current = repository.load_current(record.plan_id)
baseline = current.snapshot  # simulate_order / Gemma servislerinin mevcut girdisi
```

İlk kayıtta expected ve parent `None`; sonraki kayıtta ikisi de yüklenen
güncel snapshot'ın `version_id` değeridir. `PlanVersionConflict` durumunda
planı tekrar yükleyip yeni simülasyon/insan onayı gerekir; kör tekrar kayıt yok.
`record` yerine başarısız `SimulationResult` veya onaylanmamış taslak verilmez.

Kayıt ve yüklemede bütün Pydantic/çizelge doğrulaması tekrar çalışır.
JSON ile tüm ilişkisel satırlar ve sıraları karşılaştırılır; uyuşmazlık
`PlanStorageError` üretir. Her bağlantıda foreign key kontrolü açıktır.
Kayıt `BEGIN IMMEDIATE` transaction kullanır; hata halinde rollback yapılır.
SQLite kilit bekleme süresi 5 saniyedir; kilit/disk/SQL hataları çağırana döner,
otomatik onay veya tekrar kayıt yapılmaz.

`initialize()` boş dosyaya şemayı kurar, mevcut tabloları silmez. Otomatik
şema migration desteği yoktur. Yeni şemada JSON `version_id` alanının eksik
olması SQL'de reddedilir; daha eski mevcut DB'ye bu CHECK kendiliğinden
eklenmez, fakat uygulama katmanı her durumda tam doğrulama yapar.

Elle CLI kullanımı (save girdisi tam `StoredPlanVersion` JSON dosyasıdır):

```sh
.venv/bin/python -m benchmarks.plan_storage_cli --db database/local/workshop.sqlite3 init
.venv/bin/python -m benchmarks.plan_storage_cli --db database/local/workshop.sqlite3 save \
  --record YOUR_APPROVED_RECORD.json --first-version --confirm-save
.venv/bin/python -m benchmarks.plan_storage_cli --db database/local/workshop.sqlite3 load \
  --plan-id YOUR_PLAN_ID --snapshot-only --output YOUR_BASELINE.json
```

Sonraki kayıtta `--first-version` yerine `--expected-current VERSION_ID`
kullanılır. `load --version VERSION_ID` eski sürümü seçer; `--snapshot-only`
çıktısı mevcut Gemma CLI'nin `--baseline` girdisiyle uyumludur. Export mevcut
dosyanın üzerine yazmaz. `init` açıkça çağrılmadan kayıt/yükleme yeni DB
oluşturmaz. Yerel SQLite dosyaları/journalleri Git dışında tutulur.

## Git seed alışverişi

`database/seed/seed.json` yalnız onaylı plan sürümlerini taşır. Üst seviye
`seed_schema_version=1`; her plan kaydı bir `current_version_id` ve
`version_id` anahtarlı tam `StoredPlanVersion` nesneleri içerir. Plan geçmişi
tek kökten tek güncel yaprağa uzanan doğrusal bir zincir olmalıdır. Eksik
parent, farklı içerikli aynı sürüm, birden fazla çocuk veya bozuk çizelge tüm
dosyanın reddedilmesine neden olur.

`publish-seed` yerel SQLite'daki seçilen onaylı sürümü ve eksik atalarını
atomik dosya değişimiyle seed'e ekler; Git komutu çalıştırmaz. `import-seed`
önce bütün dosyayı ve yerel/paylaşılan ortak geçmişi doğrular, sonra bütün
eksik kuyrukları tek SQLite transaction'ında ekler. Tekrar import güvenlidir.
Yerel ve paylaşılan geçmiş ayrışırsa kullanıcı güncel plan üzerinden yeniden
simülasyon ve onay yapmadan hiçbir sürüm aktif hale getirilmez.

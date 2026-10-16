# Atakan için kaynak depo rehberi

## 1. Repo ilişkisi

`git remote` yalnızca başka bir Git deposunun adresini kaydeder; kodu uygulamana
çalışır şekilde bağlamaz. Bu depo bizim ürün kodumuzun atası olmadığı için
PickWise'a merge etmek yerine `external/job_shop_benchmark` içine ayrı clone
aldık. İki repo farklı geçmişlere sahiptir. Kaynak commit sabittir; ana uygulama
küçük bir adaptörle bu checkout'taki Python dosyalarını çağırır.

Ekip arkadaşları kendi clone'larında README kurulumunu uygular. Kaynağın tamamı
ana repo commit'ine eklenmez. İleride submodule'a geçmek mümkün; şu an sabit
commit ve kurulum scripti yeterlidir.

## 2. Problem ne?

İş (job) bir siparişin operasyon zinciridir. Operasyon tek bir üretim adımıdır.
Makine (machine) aynı anda en fazla bir operasyon işler. FJSP'de bir operasyonun
birden çok uygun makinesi olabilir ve süre makineye göre değişebilir.

Amaç: bütün işler bittiğinde saat kaç olacak? Bu son bitişin adı **makespan**.
CP-SAT bunu küçültür; burada müşteri terminini veya gecikme maliyetini optimize etmez.

Mk01–Mk10 on satır değil, on farklı problem dosyasıdır. Mk01'in başlığında
`10 6 2` var: ilk iki değer 10 iş ve 6 makinedir. Üçüncü alanı operasyon sayısı
olarak kullanmıyoruz. Operasyon sayıları her iş satırından bağımsız okunur;
Mk01 toplam 55 operasyon içerir.

## 3. Mk01'in ilk satırını birlikte okuyalım

İlk iş satırının başlangıcı:

```text
6  2 1 5 3 4  3 5 3 3 5 2 1 ...
```

- `6`: bu işte altı operasyon var.
- `2 1 5 3 4`: ilk operasyon için iki seçenek; M1'de 5 veya M3'te 4 birim.
- `3 5 3 3 5 2 1`: ikinci operasyon için üç seçenek; M5'te 3,
  M3'te 5 veya M2'de 1 birim.

İkinci operasyon birinciden sonra başlamalı. Daha kısa süreli makine her zaman
en iyi seçim olmayabilir: o makine başka bir iş yüzünden dolu olabilir.

Kaynak parser dosyadaki 1 tabanlı makine numaralarını 0 tabanlı Python kimliğine
çevirir. Böylece ilk operasyon `processing_times = {0: 5, 2: 4}` olur. JSON
çıktıları 0 tabanlıdır; Gantt'ta kullanıcıya J1/O1/M1 biçiminde 1 tabanlı gösterilir.

## 4. Dosyaların sorumlulukları

Kaynak checkout içinde:

| Yol | Görev |
| --- | --- |
| `data/fjsp/brandimarte/Mk01.fjs` | Sabit benchmark girdisi |
| `data/data_parsers/parser_fjsp.py` | Metni JobShop nesnelerine çevirir |
| `scheduling_environment/job.py` | Bir işin operasyonlarını tutar |
| `scheduling_environment/operation.py` | Süre seçeneklerini ve öncülleri tutar |
| `scheduling_environment/machine.py` | Bir makinenin çizelgesini tutar |
| `scheduling_environment/jobShop.py` | İşleri, makineleri ve operasyonları birleştirir |
| `solution_methods/cp_sat/models/FJSPmodel.py` | OR-Tools kısıt modelini kurar |
| `configs/cp_sat.toml` | Kaynak runner için örnek ayarlar |
| `visualization/` | Kaynağın grafik yardımcıları |

Kaynağın tutorial notebook'ları örnek kullanımlardır. Onları okumak faydalıdır,
ama doğrudan çalıştırmak ek algoritma bağımlılıkları isteyebilir. Bizim çalışan
komutumuz README'deki benchmark runner'ıdır.

## 5. Uçtan uca çağrı zinciri

```text
benchmarks.brandimarte_runner
  → core.cpsat_solver.read_instance
      → sıkı token/boyut/makine/süre denetimi
      → kaynak parse_fjsp(JobShop(), dosya)
      → iki okumanın eşitlik kontrolü
  → kaynak fjsp_cp_sat_model(env)
  → OR-Tools CpSolver.Solve(model)
  → seçilen makine ve başlangıçlardan JSON çizelgesi
  → core.validation.validate (çözücüden bağımsız)
  → CSV + JSON + Mk01 Plotly Gantt
```

Model, her operasyona başlangıç/bitiş ve bir aralık değişkeni tanımlar. Alternatif
makineler için isteğe bağlı aralıklar ve seçim değişkenleri kurar. `AddExactlyOne`
yalnız bir makineyi seçtirir. `AddNoOverlap` aynı makinede çakışmayı engeller.
`start >= previous_end` iş içindeki sırayı korur. En büyük iş bitişini makespan
değişkenine bağlayıp `Minimize` eder. Süreleri öğrenmez; dosyadan verilen süreleri kullanır.

Biz kaynak `update_env` yerine çözücü değişkenlerinden ayrı çizelge çıkarıyoruz.
Bu nedenle kaynak ortamına plan yazıldığı varsayılmamalı; entegrasyonda JSON
`schedule` alanı kullanılmalı. Ortam girdisi değiştirilmez.

## 6. Referans yöntem ve testin anlamı

Referans yöntem işleri dosyadaki sırayla ele alır. Her operasyon için en erken
bitişi sağlayan uygun makineyi seçer; eşitlikte küçük makine kimliği kazanır.
Makine kuyruğunun sonuna ekler. Basit ve tekrarlanabilirdir; optimum iddiası yoktur.

CP-SAT aynı girdide makine ve sıra seçimlerini birlikte arar. Tek worker, seed=0
ve örnek başına 10 saniye kullanılır. Süre sınırı aynı olsa da başka donanımda
farklı sayıda arama adımı atılabilir; aynı CP-SAT çizelgesi garanti edilmez.

Doğrulayıcı tüm operasyonların tam bir kez atanmasını, makine uygunluğunu,
süreleri, sıralamayı, negatif olmayan başlangıçları ve çakışmamayı kontrol eder.
Aralıklar [başlangıç, bitiş): biri 5'te biterken diğeri 5'te başlayabilir.
Runner ayrıca raporlanan makespan'i çizelgenin en büyük bitişiyle karşılaştırır.

18 test; optimumu elle hesaplanabilen 2 iş/2 makine örneğini, alternatif
makineyi, deterministik referansı, bozuk girdileri, yedi farklı bozuk çizelgeyi,
geçersiz süre sınırlarını ve UNKNOWN durumunu kapsar. Termin veya dinamik sipariş
testleri değildir; bu özellikler henüz yok.

## 7. Ekip için bağlantı noktası

Atakan'ın adaptörü: `core/cpsat_solver.py`. Toplu deney:
`benchmarks/brandimarte_runner.py`. Yunus ortak veri sözleşmesini hazırlarken
makineye bağlı süre seçeneklerini korumalı. Nazlısu Gantt için JSON'daki
`job, operation, machine, start, end` alanlarını kullanabilir. İleride bu alanlar
ortak tipli şemaya taşınmalı; mevcut benchmark sözleşmesi ürün API'si değildir.

Sonraki aşamada önce küçük özel atölye girdisi ve yeni sipariş senaryosu kurulur;
terminler ve başlamış işler için modele yeni kısıtlar eklenir. Statik benchmark
modeline yalnız alan eklemek bu davranışları sağlamaz.

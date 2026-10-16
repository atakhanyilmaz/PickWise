# 🚀 Dinamik Atölye Planlama ve Karar Destek Sistemi
## 18 Ekim Yarışma Teslimi İçin 5 İterasyonluk Teknoloji, Veri ve Adil İş Paketi Sunumu

---

## 🎯 Slayt 1: Yönetici Özeti ve Mimari Dönüşüm Vizyonu

Deftere eklenen yeni **Süreç Madenciliği Verileri (Work Orders Analysis)**, **Teknoloji Devreye Alma Tablosu (Aşama 1–5)** ve **Takvimden Bağımsız Çıkış Kapıları** doğrultusunda proje mimarimiz güncellenmiştir:

* **Hedef Tarih:** **18 Ekim** (Yarışma Asgari Teslimi — MVP).
* **Çekirdek Mimari Değişikliği:** Hızlı prototipleme ve yarışma kriterlerine tam uyum için arayüz katmanı **Streamlit + Plotly** üzerine, veri kalıcılığı ve sürümleme **SQLite + Pydantic + pandas** üzerine, yapay zeka katmanı ise **TabPFN + EmbeddingGemma 2 + Gemma** üzerine inşa edilecektir.
* **Açık Kaynak Şeffaflığı:** Temel çizelgeleme ortamı olarak kullanılan açık depo (`ai-for-decision-making-tue/Job_Shop_Scheduling_Benchmark_Environments_and_Instances`) kaynak kodda açıkça referans gösterilecek; ekibimizin geliştirdiği **SQLite veri kökeni (lineage), TabPFN süre tahmini, dinamik duruş yönetimi ve Gemma Türkçe ajan katmanı** ayrı modüller olarak konumlandırılacaktır.
* **Kapsam Sınırı:** Ücretli önceliklendirme ve tahsilat modülleri temel MVP (18 Ekim) sonrasına bırakılmıştır.

---

## 📊 Slayt 2: Yeni Atölye Verileri ve Kritik İş Kuralları (Domain Rules)

Deftere eklenen *Work Orders Analysis* (Disco süreç madenciliği) verileri, gerçek bir talaşlı imalat atölyesinin darboğazlarını ve parça dağılımını ortaya koymaktadır. Sistem tasarımımızda şu **4 altın kural** zorunlu olarak uygulanacaktır:

1. **Birim ve Darboğaz Ayrıştırması (`pandas` & `Pydantic`):**
   * Ham veride işlem süreleri dakika/saat ($\text{Turning \& Milling Machine 4: } 6.4\text{ sa}$, $\text{Laser Marking Machine 7: } 64.5\text{ dk}$, $\text{Lapping Machine 1: } 2.1\text{ sa}$, $\text{Round Grinding Machine 2: } 2.7\text{ sa}$) cinsinden iken, operasyonlar arası bekleme (idle) süreleri gün ($6.2\text{ gün}$, $7.2\text{ gün}$, $13.5\text{ gün}$) mertebesindedir. Tüm süreler standart birime ($\text{dakika}$ veya $\text{saat}$) dönüştürülecek ve **net işleme süresi** ile **kuyruk/bekleme süresi** birbirinden ayrılacaktır.
2. **Retrospektif Rota vs. Onaylı Rota Ayrımı:**
   * Geçmiş kayıt loglarından (`Cable Head %34.73`, `Ballnut %16.6`, `Spur Gear %5.32`, `Punch Holder %5.17`, `Plug %3.65`, `Housing %2.66` vb.) otomatik çıkarılan rotalar veritabanında ve arayüzde zorunlu olarak **`[Retrospektif Senaryo]`** etiketiyle işaretlenir.
   * Yeni bir sipariş çizelgeye alınırken **`[Kullanıcı Tarafından Onaylı Rota]`** bayrağı (`is_route_approved = True`) olmadan kesin planlamaya geçilmez.
3. **Ticari Kapanış Kuralı:**
   * Bir iş emrinin son operasyon kayıt zamanı (ör. `Final Inspection Q.C.` veya `Packing` bitişi), otomatik olarak **sevkiyat veya ticari kapanış zamanı sayılmaz**.
4. **Süre Kaynağı Şeffaflığı (Data Lineage):**
   * Arayüzdeki her operasyon süresinin yanında verinin kökeni açıkça gösterilir: `👤 Kullanıcı Süresi`, `🤖 TabPFN Tahmini` veya `📜 Retrospektif Kayıt`.

---

## ⚖️ Slayt 3: Ekip Profilleri ve "Ağır İşlerin Ortaklaştırılması" Stratejisi

Üç geliştiricinin yetkinliklerine göre iş yükü **$\approx \%33.3 - \%33.3 - \%33.3$** oranında dengelenmiş; projenin darboğaz oluşturabilecek **4 ağır iş paketi** tek bir kişinin sırtına yüklenmek yerine modüler olarak bölünmüştür:

| Ağır İş Paketi | Neden Ağır? | Atakan Yılmaz (`atakhanyilmaz`) Payı | Yunus (`yunussfr`) Payı | Nazlısu Başak (`nazlisu07`) Payı |
| :--- | :--- | :--- | :--- | :--- |
| **1. Açık Depo + Gerçek Veri Standardizasyonu** (Aşama 1–2) | Farklı zaman birimleri (`dk`, `sa`, `gün`), geri dönüş döngüleri (rework loops) ve Brandimarte formatı. | Açık depodaki `jobShopEnv` ve `CP-SAT` çözücüsünü SQLite nesneleriyle bağlamak. | `pandas` ve `Pydantic` ile ham veriyi temizlemek, birim doğrulamak ve `SQLite` şemasını kurmak. | `Streamlit` üzerinde veri doğrulama, rota onaylama ve Brandimarte karşılaştırma ekranını kurmak. |
| **2. TabPFN ile Gerçek Veride Süre Tahmini Deneyi** (Aşama 3) | Gerçek veride gürültü yüksek; özellik çıkarımı ve model entegrasyonu birlikte yapılmalı. | `TabPFN` modelini kurmak, eğitmek, metrikleri ($\text{MAE}$, $\text{RMSE}$, $R^2$) üretmek ve yedek (fallback) mantığını yazmak. | `regression-and-classification` deneyimiyle eğitim/test ayrımını (split) ve temiz alt küme (*Cable Head*, *Ballnut* vb.) özellik matrisini hazırlamak. | Tahmin vs. gerçek süre saçılım grafiklerini (`Plotly`) ve arayüzdeki **"Süre Kaynağı Görünürlük Rozetlerini"** kodlamak. |
| **3. Dinamik Sipariş / Duruş Değişikliği** (Aşama 4) | Makine duruşunda veya yeni siparişte mevcut planı bozmadan yeni sürüm ($v_1 \rightarrow v_2$) üretmek. | `CP-SAT` içinde çalışan işleri dondurup kalan operasyonları alternatif makinelere (*Machine 4 $\leftrightarrow$ Machine 5*) atamak. | `SQLite` içinde plan sürümlerini (`plan_versions`) saklamak ve iki sürüm arasındaki fark (diff) raporunu hesaplamak. | `Streamlit` üzerinde etkileşimli "Duruş / Sipariş Ekle" simülatörünü ve Önce/Sonra Gantt karşılaştırmasını sunmak. |
| **4. EmbeddingGemma 2 + Gemma + Video** (Aşama 5) | Hem vektör arama hem Türkçe LLM açıklaması hem de 18 Ekim sunum videosu aynı fazda. | `Gemma` ile Türkçe doğal dil talebini yapısal JSON'a çevirmek ve CP-SAT sonucunu Türkçe açıklamak. | `Knowledge_Extraction_Platform` deneyimiyle `EmbeddingGemma 2` tabanlı geçmiş iş özeti vektör arama hattını kurmak. | `Streamlit` üzerinde Türkçe AI asistan panelini birleştirmek, açık depo katkı ayrımını göstermek ve demo videosunu çekmek. |

---

## 🗓️ Slayt 4: 5 İterasyonluk (Aşama 1–5) Geliştirme ve Teknoloji Matrisi

| İterasyon / Aşama | Zaman Dilimi | Devreye Alınan Teknolojiler | İterasyon Hedefi ve Çıkış Kapısı (Quality Gate) |
| :--- | :--- | :--- | :--- |
| **İterasyon 1 (Aşama 1)** | 16 Ekim Cuma `15:00 – 22:00` | `pandas`, `Pydantic`, `SQLite`, `Açık Depo & CP-SAT`, `Streamlit & Plotly` (Temel) | Dosya dönüşümü, birim/şema doğrulama, SQLite kurulumu, **Brandimarte karşılaştırması** ve ilk sonuç ekranı. <br>🚪 **Kapı 1:** *Planlama geçerliliği doğrulanmadan Aşama 3'e geçilmez.* |
| **İterasyon 2 (Aşama 2)** | 16 Ekim Cuma `22:00` – 17 Ekim Cmt `04:00` | `pandas`, `SQLite` (Veri Kökeni), `Streamlit` (Rota Onay) | *Work Orders* verisinin (*Turning & Milling, Lapping, Grinding, Q.C.*) içeri alınması, **retrospektif senaryo** etiketlemesi ve kullanıcı onaylı rota akışı. <br>🚪 **Kapı 2:** *Rapor anlamı/döngüler karmaşıksa doğrulanmış küçük alt küme seçilir.* |
| **İterasyon 3 (Aşama 3)** | 17 Ekim Cmt `08:00 – 15:00` | `TabPFN`, `scikit-learn`, `pandas`, `Plotly` | Gerçek veride ayrılmış (train/test split) **süre tahmini deneyi** ve planlamaya entegrasyonu. <br>🚪 **Kapı 3:** *Tahmin başarısı zayıfsa kullanıcı süreleriyle devam edilir; kaynak arayüzde görünür tutulur.* |
| **İterasyon 4 (Aşama 4)** | 17 Ekim Cmt `15:00 – 23:00` | `CP-SAT` (Dinamik), `SQLite` (Plan Sürümleri), `Streamlit & Plotly` | Küçük atölye senaryosunda **sipariş eklentisi veya makine duruşu değişikliği**, plan sürümleme ($v_1 \rightarrow v_2$) ve etkileşimli Gantt karşılaştırması. |
| **İterasyon 5 (Aşama 5)** | 18 Ekim Pazar `00:00 – 14:00` | `EmbeddingGemma 2`, `Gemma`, `Streamlit & Plotly` (Etkileşimli Demo) | Geçmiş iş özetlerinden benzer kayıt arama (`EmbeddingGemma 2`), Türkçe talep yapılandırma ve sonuç açıklama (`Gemma`), **kısa yarışma videosu ve final teslimi**. |

---

## 🛠️ Slayt 5: İterasyon 1 (Aşama 1) — Çekirdek Planlama, SQLite ve Brandimarte Doğrulaması
**🕒 Süre:** 16 Ekim `15:00 – 22:00` | **Odak:** Temel Altyapı ve Planlama Geçerliliği Kapısı

### 👨‍💻 Atakan Yılmaz (`WP-1A`: Açık Depo & CP-SAT Entegrasyonu ve Brandimarte Kıyaslaması)
* **Görev Tanımı:**
  * Referans açık depodaki (`Job_Shop_Scheduling_Benchmark_Environments_and_Instances`) `scheduling_environment` ve `solution_methods` modüllerini projeye dahil etmek ve açık kaynak atıf başlıklarını (`attribution`) eklemek.
  * Literatürdeki **Brandimarte (`Mk01` – `Mk10`)** örneklerini hem açık depodaki sezgisel kurallarla (FIFO/SPT) hem de **CP-SAT** çözücüsüyle koşturarak karşılaştırma tablosu ($\text{Makespan}$, $\text{Çözüm Süresi}$) üretmek.
* **Teslim Çıktısı:** `core/cpsat_solver.py` ve `benchmarks/brandimarte_runner.py`.

### 👨‍💻 Yunus (`WP-1Y`: pandas/Pydantic Şema Doğrulama ve SQLite Veri Kökeni Mimarisi)
* **Görev Tanımı:**
  * `Pydantic` ile `JobSchema`, `OperationSchema`, `ResourceSchema` ve `ScheduleVersionSchema` modellerini oluşturmak.
  * Zaman birimlerini (`mins`, `hrs`, `days`) otomatik olarak standart dakikaya ($\text{dk}$) çeviren `pandas` dönüşüm boru hattını yazmak.
  * `SQLite` üzerinde `jobs`, `resources`, `operations`, `data_lineage` (veri kökeni: kullanıcı, TabPFN, retrospektif) ve `plan_versions` tablolarını kurmak.
* **Teslim Çıktısı:** `data_pipeline/validators.py` ve `database/sqlite_manager.py`.

### 👩‍💻 Nazlısu Başak (`WP-1N`: Streamlit Sonuç Ekranı ve İlk Plotly Gantt Görselleştirmesi)
* **Görev Tanımı:**
  * `Streamlit` çoklu sekme (multi-tab) ana iskeletini kurmak: **Sekme 1: Brandimarte Doğrulama & Planlama Sonuç Ekranı**.
  * Atakan'ın ürettiği Brandimarte karşılaştırma metriklerini ve CP-SAT çizelgesini `Plotly` (`px.timeline` / özel Gantt) ile ekrana basmak.
  * Açık depo modülleri ile ekibin yeni katkılarının ayrımını gösteren bilgi kutusunu arayüze yerleştirmek.
* **Teslim Çıktısı:** `app/main_streamlit.py` ve `app/components/gantt_chart.py`.

> 🚪 **Çıkış Kapısı 1 Kontrolü:** Brandimarte örneklerinde CP-SAT çakışmasız (no-overlap) ve öncelik kurallarına (precedence) uygun geçerli çizelge üretiyor mu? **Evet ise İterasyon 2'ye geçilir.**

---

## 🔍 Slayt 6: İterasyon 2 (Aşama 2) — Gerçek Atölye Verisi, Retrospektif Etiketleme ve Küçük Atölye Kurulumu
**🕒 Süre:** 16 Ekim `22:00` – 17 Ekim `04:00` | **Odak:** İş Kurallarının Kodlanması ve Alt Küme Seçimi

### 👨‍💻 Yunus (`WP-2Y`: Work Orders Verisinin Ayrıştırılması ve Doğrulanmış Küçük Alt Küme Çıkarımı)
* **Görev Tanımı:**
  * Defterdeki *Work Orders Analysis* verisinde yer alan parça tiplerini (`Cable Head`, `Ballnut`, `Spur Gear`, `Punch Holder`, `Plug`, `Housing` vb.) ve makineleri (`Turning & Milling - Machine 4`, `Turning & Milling - Machine 5`, `Turning & Milling Q.C.`, `Laser Marking - Machine 7`, `Flat Grinding - Machine 11`, `Lapping - Machine 1`, `Round Grinding - Machine 2/3`, `Final Inspection Q.C.`, `Packing`) `pandas` ile yapılandırmak.
  * Kalite kontrolden geri dönen döngüleri (rework loops: ör. `Final Inspection Q.C.` $\rightarrow 66$ tekrar) tespit edip ayırmak ve `TabPFN` deneyi için **doğrulanmış, temiz küçük alt kümeyi** `SQLite`'a kaydetmek.
* **Teslim Çıktısı:** `data_pipeline/work_orders_etl.py` ve `database/seed_workshop.sql`.

### 👨‍💻 Atakan Yılmaz (`WP-2A`: Retrospektif vs. Onaylı Rota Motoru ve Alternatif Makine Modellemesi)
* **Görev Tanımı:**
  * Geçmiş veriden gelen rotaları otomatik olarak `scenario_type = "retrospective"` şeklinde etiketleyen, yeni siparişlerde ise `is_route_approved == True` koşulunu arayan iş kuralı katmanını yazmak.
  * İşin son kayıt zamanının (`Packing` veya `Final Inspection Q.C.` bitişi) ticari kapanış/sevkiyat sayılmamasını sağlayan durum (status) mantığını `jobShopEnv` içerisine entegre etmek.
  * Aynı parçanın alternatif makinelerdeki süre farklarını (ör. *Turning & Milling Machine 4: $4.5\text{ sa}$* vs. *Machine 5: $5.2\text{ sa}$*; *Round Grinding Machine 2: $2.7\text{ sa}$* vs. *Machine 3: $4.2\text{ sa}$*) FJSP matrisine tanımlamak.
* **Teslim Çıktısı:** `core/domain_rules.py` ve `core/workshop_fjsp_builder.py`.

### 👩‍💻 Nazlısu Başak (`WP-2N`: Kullanıcı Rota Onay Ekranı ve Süre Kaynağı Görünürlük Tasarımı)
* **Görev Tanımı:**
  * `Streamlit` üzerinde **"Yeni Sipariş & Rota Onay Paneli"** oluşturmak: Geçmişten gelen rotayı kullanıcıya "📜 Retrospektif Senaryo" uyarısıyla sunmak ve kullanıcının **"Rotayı Onayla / Düzenle"** butonuyla onaylamasını sağlamak.
  * Operasyon tablolarında ve Gantt üzerinde her sürenin kaynağını (`Kullanıcı Süresi` / `Retrospektif Kayıt` / `TabPFN Tahmini`) renkli rozetlerle görünür kılmak.
* **Teslim Çıktısı:** `app/components/route_approval_ui.py`.

> 🚪 **Çıkış Kapısı 2 Kontrolü:** Ham süreç madenciliği raporlarındaki bekleme süresi ($6.2\text{ gün}$ – $14.3\text{ gün}$) ile net işlem süresi ($37.4\text{ dk}$ – $6.4\text{ sa}$) başarıyla ayrıştırıldı mı? **Doğrulanmış küçük alt küme dondurularak İterasyon 3'e geçilir.**

---

## 🧠 Slayt 7: İterasyon 3 (Aşama 3) — TabPFN ile Gerçek Veride Ayrılmış Süre Tahmini Deneyi
**🕒 Süre:** 17 Ekim `08:00 – 15:00` | **Odak:** Ağır Makine Öğrenmesi İşinin Ortaklaştırılması ve Çıkış Kapısı 3

> 💡 **Adil İş Paylaşımı Notu:** `TabPFN` deneyi tek başına ağır bir veri bilimi + sistem entegrasyonu işidir. Bu nedenle veri hazırlığı/bölünmesi **Yunus**, model çıkarımı/fallback mekanizması **Atakan**, deney sonuçlarının ve süre kaynağı şeffaflığının görselleştirilmesi **Nazlısu** tarafından paralel yürütülür.

### 👨‍💻 Yunus (`WP-3Y`: TabPFN İçin Özellik Mühendisliği ve Train/Test Split Hattı)
* **Görev Tanımı:**
  * Doğrulanmış gerçek atölye alt kümesinde girdi özelliklerini (`part_desc`, `machine_id`, `operation_type`, `batch_size`, `previous_qc_loop_count`, `historical_mean_duration`) hazırlamak.
  * Veri sızıntısını (data leakage) önleyerek iş emri bazlı **Eğitim (%80) ve Test (%20) ayrımını** (`train_test_split`) oluşturmak ve `Pydantic` ile doğrulanan deney veri setini dışa aktarmak.
* **Teslim Çıktısı:** `ml_experiments/dataset_splitter.py`.

### 👨‍💻 Atakan Yılmaz (`WP-3A`: TabPFN Model Kurulumu, Tahmin Deneyi ve Çıkış Kapısı Fallback Mekanizması)
* **Görev Tanımı:**
  * Tabular verilerde sıfır hiperparametre ile güçlü sonuç veren **TabPFN** modelini (`tabpfn`) kurmak ve Yunus'un hazırladığı ayrılmış gerçek veri üzerinde süre tahmini deneyini koşturmak.
  * Temel referans (baseline: geçmiş ortalama süre) ile `TabPFN` tahminlerini $\text{MAE}$, $\text{RMSE}$ ve $\text{MAPE}$ metrikleriyle karşılaştırmak.
  * **Çıkış Kapısı 3 Kuralını Kodlamak:** Eğer bir parça/operasyon için `TabPFN` güven skoru düşükse veya tahmin hatası eşik değeri aşarsa otomatik olarak **kullanıcı onaylı sürelere** geri dönen (`fallback_to_user_duration`) hibrit süre sağlayıcıyı yazmak.
* **Teslim Çıktısı:** `ml_experiments/tabpfn_predictor.py` ve `ml_experiments/evaluation_report.json`.

### 👩‍💻 Nazlısu Başak (`WP-3N`: TabPFN Deney Panosu ve Süre Kökeni Karşılaştırma Grafikleri)
* **Görev Tanımı:**
  * `Streamlit` içinde **Sekme 2: Gerçek Veride TabPFN Süre Tahmini Deneyi** ekranını oluşturmak.
  * `Plotly` ile "Gerçekleşen Süre vs. TabPFN Tahmini vs. Kullanıcı Tahmini" karşılaştırma grafiklerini çizdirmek.
  * Planlama motoruna gönderilecek sürelerin hangi kaynaktan geldiğini (`🤖 TabPFN` mi yoksa `👤 Kullanıcı Süresi` mi) kullanıcının tek tıkla seçebildiği veya otomatik fallback durumunu gördüğü kontrol kutusunu eklemek.
* **Teslim Çıktısı:** `app/components/tabpfn_experiment_view.py`.

> 🚪 **Çıkış Kapısı 3 Kontrolü:** Tahmin başarısı yeterli olan operasyonlarda `TabPFN` süreleri, zayıf olanlarda ise `Kullanıcı Süreleri` kaynak etiketiyle birlikte CP-SAT'a aktarılır.

---

## 🔄 Slayt 8: İterasyon 4 (Aşama 4) — Küçük Atölye Senaryosunda Sipariş / Duruş Değişikliği
**🕒 Süre:** 17 Ekim `15:00 – 23:00` | **Odak:** Dinamik Yeniden Çizelgeleme ve Plan Sürümleme ($v_1 \rightarrow v_2$)

### 👨‍💻 Atakan Yılmaz (`WP-4A`: Dinamik CP-SAT Yeniden Çizelgeleme Motoru)
* **Görev Tanımı:**
  * Küçük atölye senaryosunda iki temel olayı (event) destekleyen `reschedule_workshop()` fonksiyonunu yazmak:
    1. **Makine Duruşu / Arızası:** Örn. `Turning & Milling - Machine 4` veya `Round Grinding - Machine 2` için $4\text{ saatlik}$ plansız duruş girildiğinde, başlamış işleri koruyup bekleyen işleri alternatif makinelere (`Machine 5` veya `Machine 3`) yönlendirmek.
    2. **Yeni / Değişen Sipariş:** Kullanıcı onaylı rotaya sahip yeni bir `Cable Head` veya `Ballnut` siparişi eklendiğinde çizelgeyi yeniden optimize etmek.
* **Teslim Çıktısı:** `core/dynamic_rescheduler.py`.

### 👨‍💻 Yunus (`WP-4Y`: SQLite Plan Sürümleme ve Sürüm Farkı — Diff — Hesaplayıcı)
* **Görev Tanımı:**
  * Her yeniden çizelgeleme sonrasında oluşan planı `SQLite` içindeki `plan_versions` tablosuna (`v1: Başlangıç Planı`, `v2: Machine 4 Duruş Sonrası Plan` vb.) kaydetmek.
  * İki plan sürümü arasındaki farkları ($\Delta \text{Makespan}$, makinesi değişen operasyonlar, ötelenen iş emirleri ve süre kaynakları) hesaplayan `compare_plan_versions(v1_id, v2_id)` servisini yazmak.
* **Teslim Çıktısı:** `database/version_diff_service.py`.

### 👩‍💻 Nazlısu Başak (`WP-4N`: Etkileşimli Kriz / Değişiklik Simülatörü ve Çiftli Gantt Görünümü)
* **Görev Tanımı:**
  * `Streamlit` yan paneline (sidebar) **"Atölye Değişiklik Simülatörü"** eklemek (Makine Duruşu Ekle / Yeni Onaylı Sipariş Ekle).
  * Aynı ekranda üst üste veya yan yana **$v_1$ (Eski Plan)** ve **$v_2$ (Yeni Plan)** Gantt şemalarını `Plotly` ile göstererek makine değişimlerini (`Machine 4` $\rightarrow$ `Machine 5`) görsel olarak vurgulamak.
* **Teslim Çıktısı:** `app/components/simulation_diff_view.py`.

---

## 🤖 Slayt 9: İterasyon 5 (Aşama 5) — EmbeddingGemma 2, Gemma ve 18 Ekim Final Teslimi
**🕒 Süre:** 18 Ekim `00:00 – 14:00` | **Odak:** Türkçe Yapay Zeka Katmanı, Etkileşimli Demo ve Kısa Video

### 👨‍💻 Yunus (`WP-5Y`: EmbeddingGemma 2 ile Geçmiş İş Özetlerinden Benzer Kayıt Arama)
* **Görev Tanımı:**
  * Geçmiş iş emirlerinin metinsel özetlerini (ör. *"Cable Head - Turning & Milling Machine 4 (6.4 sa) -> Q.C. (94 dk) -> Laser Marking (64 dk) -> Lapping (2.1 sa) - Kalite döngüsü yaşandı"*) oluşturmak.
  * **EmbeddingGemma 2** modelini kullanarak bu özetlerin vektör temsillerini (embeddings) üretmek ve `SQLite` ile entegre çalışacak kosinüs benzerliği (cosine similarity) arama fonksiyonunu (`search_similar_past_jobs(query_text, top_k=3)`) yazmak.
* **Teslim Çıktısı:** `ai_layer/embedding_search.py`.

### 👨‍💻 Atakan Yılmaz (`WP-5A`: Gemma ile Türkçe Talep Yapılandırma ve Hesaplanmış Sonucu Açıklama)
* **Görev Tanımı:**
  * Atakan'ın Türkçe NLP ve LLM (`ipekgpt`) deneyimini kullanarak **Gemma** modelini iki görev için yapılandırmak:
    1. **Türkçe Talebi Yapılandırma (Text-to-Action):** Kullanıcının yazdığı *"Machine 4'te 3 saatlik duruş var ve 20 adet yeni Ballnut siparişi geldi, planı güncelle"* cümlesini `Pydantic` şemasına uygun JSON komutuna dönüştürmek.
    2. **Hesaplanmış Sonucu Türkçe Açıklama:** CP-SAT ve TabPFN'den çıkan sayısal fark tablosunu alıp atölye sahibine anlaşılır Türkçe ile özetlemek (halüsinasyon yapmadan, yalnızca hesaplanmış verilere dayanarak).
* **Teslim Çıktısı:** `ai_layer/gemma_agent.py`.

### 👩‍💻 Nazlısu Başak (`WP-5N`: Etkileşimli Demo Bütünleştirmesi, Açık Depo Etiketleri ve Kısa Video)
* **Görev Tanımı:**
  * `Streamlit` üzerinde `EmbeddingGemma 2` benzer iş arama kartlarını ve `Gemma` Türkçe talep/açıklama sohbet kutusunu ana ekrana entegre etmek.
  * Arayüzün alt bilgi (footer) ve "Hakkında & Mimari" sekmesinde **kullanılan açık depoyu (`TU Eindhoven Job Shop Benchmark Repo`)** ve **ekibin yeni uygulama katkılarını** net bir tabloyla ayırmak.
  * 18 Ekim yarışma teslimi için 5 adımı (Brandimarte $\rightarrow$ TabPFN Deneyi $\rightarrow$ Sipariş/Duruş Değişikliği $\rightarrow$ EmbeddingGemma 2 & Gemma Türkçe Açıklama) gösteren **kısa demo videosunu** kaydetmek.
* **Teslim Çıktısı:** `app/final_demo_dashboard.py` ve `18_Ekim_Sunum_Videosu.mp4`.

---

## 📈 Slayt 10: Kişi Bazlı Adalet ve İş Yükü Dağılım Özeti

| Geliştirici | Toplam İş Paketi | Birincil Sorumluluk Alanları | Ağır İşlerdeki Paydaş Rolü | Toplam Yük Oranı |
| :--- | :---: | :--- | :--- | :---: |
| **Atakan Yılmaz** (`atakhanyilmaz`) | **5 Paket** (`WP-1A` .. `WP-5A`) | • Açık Depo & CP-SAT Çözücü <br>• Brandimarte Kıyaslaması <br>• Dinamik Yeniden Çizelgeleme <br>• **Gemma** Türkçe Yapılandırma & Açıklama | • **TabPFN:** Model eğitimi ve Fallback mantığı <br>• **İş Kuralları:** Retrospektif/Onaylı rota motoru | **$\%33.3$** |
| **Yunus** (`yunussfr`) | **5 Paket** (`WP-1Y` .. `WP-5Y`) | • `pandas` & `Pydantic` Doğrulama <br>• `SQLite` Veri Kökeni & Plan Sürümleri <br>• *Work Orders* Veri Hattı (ETL) <br>• **EmbeddingGemma 2** Benzer Kayıt Arama | • **TabPFN:** Özellik çıkarımı ve Train/Test ayrımı <br>• **Dinamik Plan:** $v_1 \rightarrow v_2$ Diff hesaplama motoru | **$\%33.3$** |
| **Nazlısu Başak** (`nazlisu07`) | **5 Paket** (`WP-1N` .. `WP-5N`) | • `Streamlit` Çoklu Sekme Arayüzü <br>• `Plotly` İnteraktif Gantt & Grafikler <br>• Süre Kaynağı & Rota Onay Rozetleri <br>• Etkileşimli Demo & **Kısa Video** | • **TabPFN:** Deney panosu ve hata grafikleri <br>• **Dinamik Plan:** Çiftli Gantt ($v_1 / v_2$) simülatörü | **$\%33.3$** |

---

## 🎬 Slayt 11: 18 Ekim Kısa Yarışma Videosu İçin Dakika Dakika Akış Senaryosu

Yarışma jürisinin asgari teslim listesindeki her maddeyi saniyeler içinde doğrulayabilmesi için çekilecek **3–4 dakikalık** videonun akışı:

1. **`00:00 – 00:40` | Açık Depo Atfı ve Brandimarte Karşılaştırması (Aşama 1):**
   * `Streamlit` ilk sekmesinde açık deponun (`TU Eindhoven Benchmark`) belirtilmesi, `Brandimarte Mk01/Mk02` örneklerinde Sezgisel Kural vs. CP-SAT sonuçlarının ve ilk `Plotly` Gantt şemasının gösterilmesi.
2. **`00:40 – 01:25` | Gerçek Atölye Verisi, Veri Kökeni ve TabPFN Deneyi (Aşama 2 & 3):**
   * *Work Orders* verisinden (`Cable Head`, `Ballnut`, `Turning & Milling`, `Lapping`, `Grinding`) türetilen doğrulanmış alt küme üzerinde `TabPFN` ayrılmış süre tahmini deney sonuçlarının gösterilmesi.
   * Arayüzde sürelerin kaynağının (`🤖 TabPFN Tahmini`, `👤 Kullanıcı Süresi`, `📜 Retrospektif Senaryo`) nasıl şeffaf biçimde etiketlendiğinin vurgulanması.
3. **`01:25 – 02:20` | Küçük Atölye Senaryosunda Duruş / Sipariş Değişikliği (Aşama 4):**
   * Kullanıcı onaylı rotaya sahip yeni bir siparişin eklenmesi veya `Turning & Milling - Machine 4` üzerinde plansız duruş simüle edilmesi; `SQLite` üzerinde $v_1 \rightarrow v_2$ plan sürümünün oluşması ve işlerin `Machine 5`'e kaymasının `Plotly` Gantt üzerinde canlı izlenmesi.
4. **`02:20 – 03:15` | EmbeddingGemma 2 Benzer İş Arama ve Gemma Türkçe Açıklama (Aşama 5):**
   * Yeni gelen iş için `EmbeddingGemma 2`'nin geçmiş *Work Orders* özetlerinden en benzer 3 kaydı getirmesi; ardından `Gemma`'nın Türkçe talebi yapılandırıp yeni çizelgedeki değişimi Türkçe olarak açıklaması.
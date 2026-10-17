# Türkçe tutorial'lar

Repodaki gerçek kodu adım adım çalıştıran notebook'lar. Yeni çözücü veya doğrulayıcı yazmazlar;
`core/`, `benchmarks/` ve `ml_experiments/` modüllerini çağırırlar.

| Notebook | Konu | Kullanılan modüller |
| --- | --- | --- |
| [01_brandimarte_cpsat](01_brandimarte_cpsat.ipynb) | Mk01'i sıkı denetimle okuma, referans yöntem ve CP-SAT, bağımsız doğrulama, Gantt | `core.cpsat_solver`, `core.validation` |
| [02_atolye_modeli](02_atolye_modeli.ipynb) | İş ve operasyon durumları, termin türleri, hatalı girdinin reddi, makine duruşu, retrospektif rota | `core.domain_rules`, `core.workshop_fjsp_builder` |
| [03_yeni_siparis_simulasyonu](03_yeni_siparis_simulasyonu.ipynb) | Başlangıç planı, üç sipariş senaryosu, önce/sonra, INFEASIBLE, onaylı sürüm kaydı | `core.scenarios`, `core.plan_contract` |
| [04_gemma_talep_akisi](04_gemma_talep_akisi.ipynb) | Türkçe talep, eksik bilgi soruları, insan onayı kapısı (test istemcisiyle, gerçek model değil) | `core.llm.conversation`, `core.llm.intake` |
| [05_sure_deneyi](05_sure_deneyi.ipynb) | Süre verisi sözleşmesi, sızıntı kontrolleri, medyan referansı (sentetik veri) | `ml_experiments.duration_evaluation` |

## Çalıştırma

Repo kökünde README'deki kurulumdan sonra (`sh scripts/fetch_upstream.sh` dahil) Jupyter ile açın.
Notebook'lar `tutorials/` veya repo kökünden açılabilir.

## Sınırlar

- Atölye süreleri ve terminler sentetik demo değeridir; Brandimarte süreleri birimsizdir.
- 04 numaralı notebook gerçek Gemma'yı çağırmaz; model yanıtları elle yazılmış test yanıtlarıdır.
- 05 numaralı notebook yalnız sentetik veriyi kullanır. Gerçek veri ve TabPFN deneyi, `data_preprocesing` dalı birleştirildikten sonra eklenecek.
- Çıktılar Python 3.13 ve OR-Tools 9.12 ile üretildi. Ekibin kilitli ortamı Python 3.11 ve OR-Tools 9.11; CP-SAT süreleri farklı donanımda değişebilir.

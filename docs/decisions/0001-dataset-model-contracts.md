# ADR 0001 Veri Seti ve Model Sorumluluklarının Ayrılması

Tarih: 16 Ekim 2026  
Durum: İlk beş veri hazırlama adımında uygulandı

## Bağlam

Depoda planlama benchmarkları, iş emri olay günlüğü ve bir saniyelik CNC sensör verisi birlikte bulunmaktadır. Bu kaynakların örnekleme düzeyi, hedefi ve doğrulama biçimi farklıdır. Tek bir eğitim tablosunda birleştirilmeleri hedef sızıntısı ve yanlış performans iddiaları doğurur.

## Karar

- Brandimarte yalnızca çizelgeleme ve çözücü doğrulamasında kullanılacaktır.
- Production Analysis, anlamı doğrulanmış operasyon süresi regresyonu ve geçmiş iş araması için kullanılacaktır.
- CNC Changeovers v1.0.1, 30 oturum ve beş değişim matrisi üzerinden betimleyici hazırlık/değişim analizi için kullanılacaktır. `Label_03` oturum/faz sınırlarını, `Label_10` daha ayrıntılı fazları betimlemek için kullanılabilir; bu sözleşme CNC sınıflandırma modelini tanımlamaz.
- CNC değişim süresi oturum bazında açıklayıcı metrik olarak raporlanacak; 30 oturum, 52.026 bağımsız regresyon örneği gibi sunulmayacaktır.
- Gemma bu iki CSV'den süre veya makine uygunluğu öğrenmeyecek; doğrulanmış kullanıcı talebini yapılandıracak ve hesaplanmış sonuçları açıklayacaktır.
- EmbeddingGemma 2 indeksi yalnızca ilgili splitin geçmişinde kalan Production Analysis özetlerinden kurulacaktır.
- Production Analysis başlangıç-bitiş farkı doğrulanana kadar `recorded_duration_min` adıyla tutulacaktır.

## Sonuçlar

Her görev için ayrı veri sözleşmesi, kalite raporu ve split manifesti gerekir. Ortak alan adları kullanılabilir, ancak ham kayıtlar fiziksel olarak birleştirilmeyecektir. Model karşılaştırmaları yalnızca aynı hedef, aynı örnekleme birimi ve aynı split üzerinde yapılacaktır.

## Açık nokta

Production Analysis `Report Type` değerlerinin kaynak anlamı ve operasyon agregasyonu doğrulanmadan regresyon hedef tablosu dondurulmayacaktır.


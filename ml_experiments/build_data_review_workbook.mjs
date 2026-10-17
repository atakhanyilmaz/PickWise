import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const artifactToolPath = process.env.ARTIFACT_TOOL_PATH ?? "C:/Users/yunus emre/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs";
const { Workbook, SpreadsheetFile } = await import(pathToFileURL(artifactToolPath).href);

const root = process.cwd();
const dataDir = path.join(root, "data", "dataforNewVersion");
const intermediateDir = path.join(root, "reports", "data_preparation", "intermediate");
const qualityPath = path.join(root, "reports", "data_preparation", "quality_report.json");

function readCsv(filePath) {
  const text = fs.readFileSync(filePath, "utf8").replace(/^\uFEFF/, "");
  const rows = [];
  let row = [], field = "", quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') { field += '"'; i += 1; }
      else if (ch === '"') quoted = false;
      else field += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") { row.push(field); field = ""; }
    else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i += 1;
      row.push(field); field = "";
      if (row.some((value) => value !== "")) rows.push(row);
      row = [];
    } else field += ch;
  }
  if (field !== "" || row.length) { row.push(field); rows.push(row); }
  const headers = rows.shift();
  return { headers, rows: rows.map((values) => Object.fromEntries(headers.map((h, i) => [h, values[i] ?? ""]))) };
}

function issue(report, name) {
  return report.issues.find((entry) => entry.issue_code === name) ?? { count: 0, severity: "info" };
}

function display(value) {
  if (value === null || value === undefined || value === "") return "";
  const n = Number(value);
  return Number.isFinite(n) && /^-?\d+(\.\d+)?$/.test(String(value)) ? n : String(value);
}

function styleHeader(sheet, lastCol, titleRow = 1) {
  const header = sheet.getRangeByIndexes(titleRow - 1, 0, 1, lastCol);
  header.format = {
    fill: "#18324B",
    font: { bold: true, color: "#FFFFFF", size: 10 },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
  };
  header.format.rowHeight = 32;
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(titleRow);
}

const qualityText = fs.readFileSync(qualityPath, "utf8").replace(/:\s*(?:NaN|Infinity|-Infinity)\b/g, ": null");
const quality = JSON.parse(qualityText);
const prod = quality.datasets.production_analysis;
const cnc = quality.datasets.cnc_changeovers;
const imputation = JSON.parse(fs.readFileSync(path.join(root, "reports", "data_preparation", "imputation_report.json"), "utf8"));
const production = readCsv(path.join(intermediateDir, "production_analysis_review.csv"));
const cncReview = readCsv(path.join(intermediateDir, "cnc_changeover_review.csv"));
const timeGaps = readCsv(path.join(intermediateDir, imputation.datasets.cnc_changeovers.time_series.gap_file));
const workbook = Workbook.create();

const summary = workbook.worksheets.add("Özet");
summary.getRange("A1:B1").merge();
summary.getRange("A1").values = [["Veri inceleme raporu"]];
summary.getRange("A1:B1").format = { fill: "#18324B", font: { bold: true, color: "#FFFFFF", size: 16 }, rowHeight: 34, verticalAlignment: "center" };
summary.getRange("A3:B3").values = [["Konu", "Bulgular / kullanım"]];
const summaryRows = [
  ["Ham dosyalar", "Aynı klasörde korunuyor; bu rapor ve *_review.csv dosyaları ayrı inceleme kopyalarıdır."],
  ["Production Analysis", `${prod.rows.toLocaleString("tr-TR")} kayıt. Ayrıntı sayfasında bütün satırlar ve dakika karşılaştırmaları bulunur.`],
  ["Span uyuşmazlığı", `${issue(prod, "span_elapsed_mismatch_over_one_minute").count} kayıtta Span ile zaman damgalarından hesaplanan süre arasında 1 dakikadan fazla fark var. Otomatik düzeltilmedi.`],
  ["Sıfır / biçimsiz süre", `${issue(prod, "zero_elapsed_minutes").count} sıfır zaman farkı; ${issue(prod, "malformed_span").count} biçimsiz Span. Kaynak kayda göre elle değerlendirilmeli.`],
  ["Tekrar kayıt işaretleri", `${issue(prod, "exact_duplicate_row").count} birebir tekrar satırı; ${issue(prod, "duplicate_event_key").count} yinelenen olay anahtarı. Silinmedi.`],
  ["CNC değişim verisi", `${cnc.rows.toLocaleString("tr-TR")} örnek, 1 saniyelik örnekleme aralığında ${issue(cnc, "sampling_gap_not_one_second").count} sapma. CNC sayfasında bu zaman noktaları listelenir.`],
  ["CNC eksik ölçümler", `${issue(cnc, "sensor_columns_with_missing_values").count} sensör sütununda eksik değer var. Tam satır/sütun verisi CNC inceleme CSV'sinde.`],
  ["Doldurma işlemi", `${imputation.datasets.production_analysis.imputed_cells.toLocaleString("tr-TR")} Production hücresi işlendi. CNC Tool_ID boşluğu açık durum belirteciyle temsil edildi; belirsiz magazin alanları çıkarıldı.`],
  ["Zaman serisi", "Normal örnek aralığı 1 saniye. 6 uzun aralık kaynakta gözlenen zamanlar olarak korundu; zaman damgalarında geçersiz veya boş değer yok."],
  ["Önemli", "Doldurulan değerler istatistiksel yer tutuculardır. Rework ve Line_Content alanlarında eksiklik %99'u aşıyor; anlamı doğrulanmadan model özelliği olarak kullanma."],
  ["Dosyalar", `Ham CSV ve ilk review kopyaları korunur. Güncel adaylar: ${imputation.datasets.production_analysis.output} ve ${imputation.datasets.cnc_changeovers.output}. Hücre kaydı: ${imputation.audit_file.split("/").pop()}.`],
];
summary.getRangeByIndexes(2, 0, 1 + summaryRows.length, 2).values = [["Konu", "Bulgular / kullanım"], ...summaryRows];
summary.tables.add(`A3:B${3 + summaryRows.length}`, true, "ReviewSummary");
styleHeader(summary, 2, 3);
summary.getRange(`A4:A${3 + summaryRows.length}`).format = { fill: "#EAF0F5", font: { bold: true, color: "#18324B" } };
summary.getRange(`A1:B${3 + summaryRows.length}`).format.wrapText = true;
summary.getRange("A:A").format.columnWidth = 24;
summary.getRange("B:B").format.columnWidth = 100;
summary.getRange(`A4:B${3 + summaryRows.length}`).format.rowHeight = 36;

const prodSheet = workbook.worksheets.add("Production");
const prodValues = [production.headers, ...production.rows.map((record) => production.headers.map((header) => display(record[header])))];
prodSheet.getRangeByIndexes(0, 0, prodValues.length, production.headers.length).values = prodValues;
prodSheet.tables.add(`A1:${String.fromCharCode(64 + production.headers.length)}${prodValues.length}`, true, "ProductionReviewRows");
styleHeader(prodSheet, production.headers.length);
prodSheet.getRange("A:A").format.columnWidth = 20;
prodSheet.getRange("B:D").format.columnWidth = 26;
prodSheet.getRange("E:F").format.columnWidth = 23;
prodSheet.getRange("P:Q").format.columnWidth = 24;
prodSheet.getRange("R:V").format.columnWidth = 23;
prodSheet.getRange("W:W").format.columnWidth = 24;
prodSheet.getRange("H:H").format.columnWidth = 18;

const cncSheet = workbook.worksheets.add("CNC");
cncSheet.getRange("A1:D1").merge();
cncSheet.getRange("A1").values = [["CNC veri kümesinde örnekleme aralığı sapmaları"]];
cncSheet.getRange("A1:D1").format = { fill: "#18324B", font: { bold: true, color: "#FFFFFF", size: 14 }, rowHeight: 32, verticalAlignment: "center" };
cncSheet.getRange("A3:D3").values = [["Kaynak satırı", "Zaman", "Önceki satırdan saniye", "İnceleme notu"]];
const gapRows = cncReview.rows
  .filter((record) => record.review_issues?.includes("sampling_gap_not_one_second"))
  .map((record) => [display(record.source_row_number), record.time, display(record.seconds_from_previous_row), "Gözlenen zaman korundu; bunun veri kaybı veya duruş olma ihtimalini incele."]);
cncSheet.getRangeByIndexes(2, 0, Math.max(1, gapRows.length + 1), 4).values = [["Kaynak satırı", "Zaman", "Önceki satırdan saniye", "İnceleme notu"], ...gapRows];
if (gapRows.length) cncSheet.tables.add(`A3:D${3 + gapRows.length}`, true, "CncTimestampGaps");
styleHeader(cncSheet, 4, 3);
cncSheet.getRange("A:A").format.columnWidth = 16;
cncSheet.getRange("B:B").format.columnWidth = 24;
cncSheet.getRange("C:C").format.columnWidth = 26;
cncSheet.getRange("D:D").format.columnWidth = 72;
cncSheet.getRange("A10:B10").merge();
cncSheet.getRange("A10").values = [["Tüm CNC sinyal satırları için: cnc_changeover_review.csv dosyasını açın."]];
cncSheet.getRange("A10:B10").format = { fill: "#EAF0F5", font: { bold: true, color: "#18324B" }, wrapText: true };

const fillSheet = workbook.worksheets.add("Doldurma");
const fillRows = Object.entries(imputation.datasets).flatMap(([dataset, details]) => details.columns.map((item) => {
  const warning = item.method === "preserved_missing"
    ? item.column === "Rework"
      ? "Yalnızca 32 satır Y, hiç N yok; modla doldurmak doğru olmaz."
      : "Kaynak tanımı: o anda NC kod satırı çalışmıyorsa boş kalır."
    : item.warning ? "Eksik oranı yüksek; anlamı doğrulamadan modelde kullanma." : "";
  return [
    dataset === "production_analysis" ? "Production Analysis" : "CNC değişim verisi", item.column, item.dtype,
    item.missing, `${(item.missing_fraction * 100).toFixed(2)}%`,
    item.method === "mode" ? "mod" : item.method === "median" ? "medyan" : "korundu",
    display(item.fill_value), item.imputed, item.preserved_missing ?? 0, warning,
  ];
}));
fillSheet.getRange("A1:J1").values = [["Veri seti", "Sütun", "Tür", "Eksik hücre", "Eksik oranı", "Yöntem", "Doldurma değeri", "Doldurulan", "Boş bırakılan", "Açıklama"]];
fillSheet.getRangeByIndexes(1, 0, fillRows.length, 10).values = fillRows;
fillSheet.tables.add(`A1:J${fillRows.length + 1}`, true, "ImputationSummary");
styleHeader(fillSheet, 10);
fillSheet.getRange("A:A").format.columnWidth = 25;
fillSheet.getRange("B:B").format.columnWidth = 38;
fillSheet.getRange("C:F").format.columnWidth = 18;
fillSheet.getRange("G:G").format.columnWidth = 50;
fillSheet.getRange("H:H").format.columnWidth = 16;
fillSheet.getRange("I:I").format.columnWidth = 18;
fillSheet.getRange("J:J").format.columnWidth = 62;
fillSheet.getRange("A1:J20").format.wrapText = true;

const gapSheet = workbook.worksheets.add("Zaman aralıkları");
const gapFields = ["source_row_number", "previous_observed_time", "observed_time", "observed_interval_seconds", "nominal_mean_interval_seconds", "next_expected_sample_after_previous", "note"];
const gapHeaders = ["Kaynak satırı", "Önceki zaman", "Gözlenen zaman", "Gözlenen aralık (sn)", "Normal ortalama aralık (sn)", "Sonraki beklenen örnek zamanı", "Not"];
const gapValues = [gapHeaders, ...timeGaps.rows.map((record) => gapFields.map((field) => display(record[field])))];
gapSheet.getRangeByIndexes(0, 0, gapValues.length, gapHeaders.length).values = gapValues;
gapSheet.tables.add(`A1:G${gapValues.length}`, true, "TimeGapReview");
styleHeader(gapSheet, gapHeaders.length);
gapSheet.getRange("A:A").format.columnWidth = 18;
gapSheet.getRange("B:C").format.columnWidth = 24;
gapSheet.getRange("D:E").format.columnWidth = 28;
gapSheet.getRange("F:F").format.columnWidth = 38;
gapSheet.getRange("G:G").format.columnWidth = 82;

const outPath = path.join(dataDir, "data_review.xlsx");
const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outPath);
const previewDir = path.join(root, "reports", "data_preparation", "_preview");
fs.mkdirSync(previewDir, { recursive: true });
for (const [sheetName, range, fileName] of [
  ["Özet", "A1:B14", "data-review-summary.png"],
  ["Production", "A1:H12", "data-review-production.png"],
  ["CNC", "A1:D10", "data-review-cnc.png"],
  ["Doldurma", "A1:J8", "data-review-imputation.png"],
  ["Zaman aralıkları", "A1:G7", "data-review-time-gaps.png"],
]) {
  const preview = await workbook.render({ sheetName, range, scale: 1, format: "png" });
  await fs.promises.writeFile(path.join(previewDir, fileName), new Uint8Array(await preview.arrayBuffer()));
}
console.log(`Created ${outPath}`);

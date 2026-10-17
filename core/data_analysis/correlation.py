from pathlib import Path
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt

INPUT_FILE = Path(
    r"C:\software_study\projelerim\Job_Shop_Scheduling_Benchmark_Environments_and_Instances\data\dataforNewVersion\cnc_changeover_remaining_time_target.csv"
)

OUTPUT_PATH = INPUT_FILE.parent / "correlation_results"
OUTPUT_PATH.mkdir(parents=True, exist_ok=True)

df = pd.read_csv(INPUT_FILE)
numeric_df = df.select_dtypes(include="number")

pearson = numeric_df.corr(method="pearson")
spearman = numeric_df.corr(method="spearman")

pearson.to_csv(OUTPUT_PATH / "pearson.csv")
spearman.to_csv(OUTPUT_PATH / "spearman.csv")

for method_name, corr in [("pearson", pearson), ("spearman", spearman)]:
    plt.figure(figsize=(14, 10))
    sns.heatmap(corr, cmap="coolwarm", center=0, vmin=-1, vmax=1)
    plt.title(f"{method_name.title()} Korelasyon Matrisi")
    plt.tight_layout()
    plt.savefig(OUTPUT_PATH / f"{method_name}_heatmap.png", dpi=200)
    plt.close()

print(f"Çıktılar oluşturuldu: {OUTPUT_PATH}")
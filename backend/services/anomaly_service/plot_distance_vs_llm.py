import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv("analysis_out/windows.csv")

# Your anomaly_eval produces llm_alert as strings: YES/NO/UNKNOWN/N/A
df["llm_alert"] = df["llm_alert"].astype(str).str.upper().str.strip()

yes = df[df["llm_alert"] == "YES"]
no = df[df["llm_alert"] == "NO"]

# Drop rows missing numeric fields
yes = yes.dropna(subset=["cosine_distance", "radius_threshold"])
no = no.dropna(subset=["cosine_distance", "radius_threshold"])

plt.figure(figsize=(7, 5))
plt.scatter(yes["cosine_distance"], yes["radius_threshold"], label="LLM: ALERT YES")
plt.scatter(no["cosine_distance"], no["radius_threshold"], label="LLM: ALERT NO")

plt.xlabel("Cosine distance to nearest cluster")
plt.ylabel("Cluster radius threshold")
plt.legend()
plt.title("Clustering Distance vs LLM Decision")
plt.tight_layout()
plt.savefig("analysis_out/distance_vs_llm.png", dpi=300)
plt.show()

import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv("analysis_out/windows.csv")

# Derive fight name if not already present
if "fight" not in df.columns:
    df["fight"] = df["event_key"].astype(str).str.split("-win-").str[0]

# 🔴 REMOVE test/debug events
df = df[df["fight"].str.startswith("Fight")]

df["llm_alert"] = df["llm_alert"].astype(str).str.upper().str.strip()

df2 = df[df["llm_alert"].isin(["YES", "NO"])]

fight_counts = (
    df2.groupby(["fight", "llm_alert"])
       .size()
       .unstack(fill_value=0)
       .sort_index()
)

fight_counts.plot(
    kind="bar",
    stacked=True,
    figsize=(8, 5)
)

plt.ylabel("Number of windows")
plt.title("LLM Alert Distribution per Fight Video")
plt.tight_layout()
plt.savefig("analysis_out/per_fight_alerts.png", dpi=300)
plt.show()

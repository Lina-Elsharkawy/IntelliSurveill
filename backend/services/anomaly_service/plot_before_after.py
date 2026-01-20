import json
from pathlib import Path
import matplotlib.pyplot as plt

summary = json.loads(
    Path("analysis_out/summary.json").read_text(encoding="utf-8")
)

before = summary["baseline_detected_anomalies_before_llm"]
after_yes = summary["llm_alert_yes_after"]
after_no = summary["llm_alert_no_after"]

labels = ["Before LLM\n(Detector)", "After LLM\n(Alert YES)", "After LLM\n(Alert NO)"]
values = [before, after_yes, after_no]

plt.figure(figsize=(7, 5))
plt.bar(labels, values)
plt.ylabel("Number of windows")
plt.title("Anomaly Detection Before and After LLM Reasoning")
plt.tight_layout()
plt.savefig("analysis_out/before_after_llm.png", dpi=300)
plt.show()

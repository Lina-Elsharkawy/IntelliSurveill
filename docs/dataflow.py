import shutil
import sys
from graphviz import Digraph

# Create a directed graph
dot = Digraph("Streaming_Architecture", format="png")

# Global graph attributes
dot.attr(rankdir="LR", bgcolor="white", splines="ortho")
dot.attr("node", shape="box", style="rounded,filled", fontname="Helvetica")

# --- Individual main pipeline nodes ---
dot.node("camera", "Camera", fillcolor="#fdebd0", color="#e67e22")
dot.node("edge_ai", "Edge AI", fillcolor="#d6eaf8", color="#2980b9")
dot.node("kafka", "Kafka", fillcolor="#e8daef", color="#8e44ad")
dot.node("flink", "Flink", fillcolor="#d5f5e3", color="#27ae60")

dot.node("backend", "Backend Services", fillcolor="#f9ebea", color="#c0392b")

# --- Storage / Serving cluster ---
with dot.subgraph(name="cluster_storage") as c:
    c.attr(label="Storage & Serving Layer", fontsize="12", fontname="Helvetica-Bold",
           style="rounded,dashed", color="#7f8c8d")
    c.attr("node", shape="box", style="rounded,filled")

    c.node("s3", "S3 Snapshot Bucket", fillcolor="#fef9e7", color="#f1c40f")
    c.node("postgres", "PostgreSQL Database", fillcolor="#e8f8f5", color="#16a085")
    c.node("vector_db", "Vector Database", fillcolor="#fceef5", color="#c2185b")

# --- Output / Consumption cluster ---
with dot.subgraph(name="cluster_outputs") as c:
    c.attr(label="User-Facing Outputs", fontsize="12", fontname="Helvetica-Bold",
           style="rounded,dashed", color="#133b3e")
    c.attr("node", shape="box", style="rounded,filled")

    c.node("dashboard", "Dashboard", fillcolor="#d6eaf8", color="#2980b9")
    c.node("chatbot", "Chatbot", fillcolor="#f6ddcc", color="#d35400")
    c.node("alerts", "Alerts", fillcolor="#f9ebea", color="#c0392b")

# --- Edges: main flow ---
dot.edge("camera", "edge_ai")
dot.edge("edge_ai", "kafka")
dot.edge("edge_ai", "s3")
dot.edge("kafka", "flink")

# Flink writes to multiple storages
dot.edge("flink", "postgres")

# Storage feeds Backend Analytics
dot.edge("s3", "backend")
dot.edge("postgres", "backend")
dot.edge("postgres", "vector_db")
dot.edge("vector_db", "backend")

# Backend fan-out to outputs
dot.edge("backend", "dashboard")
dot.edge("backend", "chatbot")
dot.edge("backend", "alerts")

# Try to render the diagram (creates Streaming_Architecture.png).
# Rendering requires the Graphviz "dot" executable available on PATH.
if shutil.which("dot"):
    # dot exists -> render and try to open the image viewer
    dot.render("Streaming_Architecture", view=True)
else:
    # If dot isn't available (common on Windows if Graphviz isn't installed),
    # save the DOT source and print an actionable message instead of raising.
    filename = "Streaming_Architecture.dot"
    dot.save(filename)
    print(f"Graphviz 'dot' executable not found on PATH. Saved DOT source to '{filename}'.")
    print()
    print("To generate the image on this machine, install Graphviz and add it to PATH:")
    print("  1) Download and install Graphviz from https://graphviz.org/download/")
    print("  2) Add the Graphviz 'bin' folder (e.g., C:\\Program Files\\Graphviz\\bin) to your PATH environment variable")
    print("     - Open a new terminal after updating PATH so the change takes effect.")
    print("  3) Re-run this script: python dataflow.py (it will render the PNG)")
    print()
    # Exit with a non-zero code so automated runners or CI will catch the missing dependency
    sys.exit(2)

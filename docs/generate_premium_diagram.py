from diagrams import Diagram, Cluster, Edge
from diagrams.onprem.analytics import Flink
from diagrams.onprem.queue import Kafka
from diagrams.onprem.database import PostgreSQL
from diagrams.onprem.client import User
from diagrams.generic.device import Tablet
from diagrams.programming.language import Nodejs
from diagrams.programming.framework import React

# Global graph attributes
graph_attr = {
    "fontsize": "20",
    "bgcolor": "white",
    "splines": "ortho",
    "nodesep": "0.8",
    "ranksep": "1.2",
    "fontname": "Sans-Serif",
    "pad": "0.5"
}

try:
    with Diagram("Intelligent Surveillance Architecture", show=False, filename="premium_architecture", graph_attr=graph_attr, direction="LR"):
        
        # --- ACTORS ---
        with Cluster("Edge Layer"):
            camera = Tablet("Edge Device")
        
        # --- STREAMING LAYER ---
        with Cluster("Streaming Backbone\n(Kafka & Flink)"):
            
            # Topics
            topic_logs = Kafka("logs\n(Events)")
            topic_freq = Kafka("frequency_alerts")
            topic_config = Kafka("anomaly-config\n(Rules)")
            topic_anom = Kafka("anomalies\n(General)")
            
            flink = Flink("Flink Job\n(Freq. Analysis)")
            
        # --- APPLICATION LAYER ---
        with Cluster("Backend & Storage"):
            api = Nodejs("Backend API")
            db = PostgreSQL("Postgres DB")
            
        with Cluster("Frontend"):
            dashboard = React("Web Dashboard")

        # --- FLOW ---
        
        # 1. Edge -> Logs & Anomalies
        # constraint=True ensures this defines the structure (L -> R)
        camera >> Edge(label="1a. Ingest Logs", color="#2980b9", style="bold") >> topic_logs
        camera >> Edge(label="1b. Ingest Anomalies", color="#c0392b", style="bold") >> topic_anom
        
        # 2. Logs -> Flink
        topic_logs >> Edge(label="2. Consume", color="#2980b9") >> flink
        
        # 3. Flink -> Alerts & DB
        flink >> Edge(color="#c0392b", style="bold", label="3a. Alert") >> topic_freq
        flink >> Edge(color="#27ae60", label="3b. Audit") >> db
        
        # 4. Alerts -> Backend
        topic_freq >> Edge(color="#c0392b", label="4. Consume") >> api
        topic_anom >> Edge(color="#c0392b") >> api 
        
        # 5. Backend -> Frontend
        # constraint="true" (default) ensures Dashboard is placed AFTER Backend (to the right/bottom)
        api >> Edge(label="Notify", style="dashed", color="#e67e22") >> dashboard
        
        # 6. Config Flow (Feedback Loop)
        # constraint="false" here is CRITICAL. It prevents the graph from trying to put Dashboard BEFORE API.
        dashboard >> Edge(label="Update Rules", style="dotted", color="#7f8c8d", constraint="false") >> api
        api >> Edge(style="dotted", color="#7f8c8d", constraint="false") >> topic_config
        topic_config >> Edge(label="Broadcast", style="dotted", color="#7f8c8d", constraint="false") >> flink

    print("Successfully generated 'premium_architecture.png'")

except ImportError as e:
    print("---------------------------------------------------------")
    print("IMPORT ERROR")
    print(f"Details: {e}")
    print("Please ensure 'diagrams' is installed: pip install diagrams")
    print("---------------------------------------------------------")
except Exception as e:
    print(f"An error occurred: {e}")
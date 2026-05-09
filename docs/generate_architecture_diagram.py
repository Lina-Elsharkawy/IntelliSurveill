from graphviz import Digraph
import os

def generate_kafka_diagram():
    # Create Digraph object
    # dpi='300' ensures high resolution for a premium look
    dot = Digraph('Kafka_Data_Flow', comment='Surveillance System Streaming Architecture')
    
    # Global layout settings
    # 'splines=curved' often looks smoother/more modern than ortho, but ortho is cleaner for architecture. 
    # Let's stick to ortho but refine the spacing.
    dot.attr(rankdir='LR')
    dot.attr(splines='ortho') 
    dot.attr(nodesep='1.0')
    dot.attr(ranksep='1.5')
    dot.attr(dpi='300') 
    dot.attr(bgcolor='transparent') 
    
    # Font settings - using a clean sans-serif
    font_name = 'Helvetica'
    
    # Default Node Attributes
    dot.attr('node', 
             shape='plain', # We will use HTML labels for custom styling
             fontname=font_name)
             
    # Default Edge Attributes
    dot.attr('edge', 
             fontname=font_name, 
             fontsize='10', 
             color='#455A64', 
             penwidth='1.5',
             arrowsize='0.8')

    # --- HELPER FOR HTML LABELS ---
    def html_label(title, subtitle, color, text_color='white'):
        # Creates a card-like node
        return f'''<
            <TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="4">
                <TR>
                    <TD BGCOLOR="{color}" BORDER="1" COLOR="{color}" VALIFGN="MIDDLE" ROUNDED="TRUE">
                        <FONT COLOR="{text_color}" POINT-SIZE="12"><B>  {title}  </B></FONT><BR/>
                        <FONT COLOR="{text_color}" POINT-SIZE="9">  {subtitle}  </FONT>
                    </TD>
                </TR>
            </TABLE>
        >'''

    # --- CLUSTERS ---
    
    # Edge Cluster
    with dot.subgraph(name='cluster_edge') as c:
        c.attr(label='Edge Layer', fontname=font_name, fontsize='14', color='#CFD8DC', style='dashed', fontcolor='#455A64')
        
        # Jetson / Camera
        c.node('Edge', label=html_label('Edge Device', 'Face & Anomaly Detection\n+ Embeddings', '#263238')) # Dark Slate

    # Kafka Cluster
    with dot.subgraph(name='cluster_kafka') as c:
        c.attr(label='Streaming Layer (Kafka)', fontname=font_name, fontsize='14', color='#CFD8DC', style='dashed', fontcolor='#455A64')
        
        # Topics
        # Muted Orange/Terra-cotta palette for Data
        topic_color = '#E64A19' 
        c.node('T_Logs', label=html_label('Topic: logs', 'Access Events', topic_color))
        c.node('T_Freq', label=html_label('Topic: freq_alerts', 'Anomalies', topic_color))
        c.node('T_Config', label=html_label('Topic: config', 'Rules & Thresholds', '#F57C00')) # Lighter orange
        c.node('T_Anom', label=html_label('Topic: anomalies', 'General Alerts', topic_color))

    # Flink Cluster
    with dot.subgraph(name='cluster_flink') as c:
        c.attr(label='Processing Layer (Flink)', fontname=font_name, fontsize='14', color='#CFD8DC', style='dashed', fontcolor='#455A64')
        
        # Flink Job
        # Deep Purple for Logic/Processing
        c.node('FlinkJob', label=html_label('Flink Job', 'Frequency Detection\n(Windowed Aggregation)', '#6A1B9A'))

    # Backend/Storage Cluster
    with dot.subgraph(name='cluster_backend') as c:
        c.attr(label='Backend & Storage', fontname=font_name, fontsize='14', color='#CFD8DC', style='dashed', fontcolor='#455A64')
        
        # Postgres - Green
        c.node('Postgres', label=html_label('PostgreSQL', 'Audit Logs & Events', '#2E7D32'))
        
        # Backend - Blue
        c.node('Backend', label=html_label('Backend API', 'Node.js / Express', '#1565C0'))
        
        # Frontend - Teal
        c.node('Frontend', label=html_label('Frontend', 'React Dashboard', '#00695C'))

    # --- EDGES (DATA FLOW) ---
    
    # 1. Edge -> Kafka (Logs)
    dot.edge('Edge', 'T_Logs', label=' 1. Ingest')
    
    # 2. Kafka (Logs) -> Flink
    dot.edge('T_Logs', 'FlinkJob', label=' 2. Consume')
    
    # 3. Flink Processing -> Sinks
    
    # 3a. Flink -> Kafka (Alerts)
    dot.edge('FlinkJob', 'T_Freq', label=' 3a. Alert')
    
    # 3b. Flink -> Postgres (Dual Sink)
    dot.edge('FlinkJob', 'Postgres', label=' 3b. Audit')
    
    # 4. Kafka (Alerts) -> Backend
    dot.edge('T_Freq', 'Backend', label=' 4. Consume')
    
    # 5. Backend -> Frontend (Notification)
    # Using 'odot' (open dot) or normal arrow with dashed style for signaling vs data flow
    dot.edge('Backend', 'Frontend', label=' 5. Notify', style='dashed', color='#1565C0')
    
    # 6. Config Updates (Frontend -> Backend -> Kafka -> Flink)
    # Dotted lines for control plane
    control_color = '#78909C'
    dot.edge('Frontend', 'Backend', label=' Update Rules', style='dotted', color=control_color, fontcolor=control_color)
    dot.edge('Backend', 'T_Config', label=' Publish', style='dotted', color=control_color, fontcolor=control_color)
    dot.edge('T_Config', 'FlinkJob', label=' Broadcast', style='dotted', color=control_color, fontcolor=control_color)

    # Render
    output_path = 'streaming_architecture_diagram'
    # 'cleanup=True' removes the source .dot file
    dot.render(output_path, view=False, format='png', cleanup=True)
    print(f"Diagram generated successfully: {os.path.abspath(output_path + '.png')}")

if __name__ == '__main__':
    try:
        generate_kafka_diagram()
    except Exception as e:
        print("Error generating diagram.")
        print(f"Details: {e}")
# create_diagram.py

import json
import os
import xml.etree.ElementTree as ET
from xml.dom import minidom
from dotenv import load_dotenv
import google.generativeai as genai

# --- Automatically load environment variables from a .env file ---
load_dotenv()
# -----------------------------------------------------------------

# --- Part 1: Gemini Integration ---

class GeminiProcessor:
    def __init__(self):
        try:
            api_key = os.environ["GOOGLE_API_KEY"]
            if not api_key: raise KeyError
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('gemini-1.5-flash-latest')
            print("✅ [Gemini] API configured successfully.")
        except KeyError:
            print("❌ ERROR: GOOGLE_API_KEY not found. Please check your .env file.")
            raise

    def get_architecture_json(self, text_input: str) -> dict:
        print("🤖 [Gemini] Calling Gemini API to process input text...")
        # *** CHANGE: Removed request for `\n` to simplify labels ***
        prompt = f"""
        You are an expert system architect. Your task is to convert a natural language description
        of a cloud architecture into a structured JSON object.

        The JSON must have two top-level keys: "nodes" and "edges".

        1.  **nodes**: A list of all components.
            - `id`: A unique, simple Python-variable-safe string (e.g., "user", "alb", "rds_db").
            - `label`: The text to display on the icon (e.g., "Application Load Balancer"). Do not use newlines.
            - `type`: The type of the component. This is CRITICAL. Choose from this list:
              - `aws.compute.ec2_auto_scaling`
              - `aws.network.route53`, `aws.network.elb_application_load_balancer`
              - `aws.storage.s3`
              - `aws.database.rds_postgresql_instance`
              - `user` (for human users)
              - `generic_client` (for web browsers, mobile apps)

        2.  **edges**: A list of connections between the nodes.
            - `source`: The `id` of the starting node.
            - `target`: The `id` of the ending node.
            - `label`: A short description of the connection.

        USER'S ARCHITECTURE DESCRIPTION:
        ---
        {text_input}
        ---
        """
        try:
            response = self.model.generate_content(prompt)
            json_text = response.text.strip().replace("```json", "").replace("```", "")
            return json.loads(json_text)
        except Exception as e:
            print(f"❌ [Gemini] Failed to generate or parse JSON from API response: {e}")
            return None

# --- Part 2: Direct draw.io XML Generation (Guaranteed to work) ---

class DiagramGenerator:
    def __init__(self):
        self.cell_id_counter = 2

    def _create_cell(self, parent_element, **attrs):
        return ET.SubElement(parent_element, 'mxCell', {str(k): str(v) for k, v in attrs.items()})

    def _create_node(self, root, node_id, label, x, y, width=120, height=80):
        # *** CHANGE: Using a single, reliable style for all nodes ***
        style = "rounded=1;whiteSpace=wrap;html=1;arcSize=12;"
        cell = self._create_cell(root, id=node_id, value=label, style=style, parent="1", vertex="1")
        ET.SubElement(cell, 'mxGeometry', {'x': str(x), 'y': str(y), 'width': str(width), 'height': str(height), 'as': 'geometry'})

    def _create_edge(self, root, source_node_id, target_node_id, label=""):
        cell_id = self.cell_id_counter
        self.cell_id_counter += 1
        style = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;endArrow=classic;endFill=1;"
        cell = self._create_cell(root, id=cell_id, value=label, style=style, parent="1", edge="1", source=source_node_id, target=target_node_id)
        ET.SubElement(cell, 'mxGeometry', {'relative': "1", 'as': 'geometry'})

    def generate_xml_string(self, data: dict):
        print("🎨 [XML Generator] Building reliable draw.io XML structure...")
        mxfile = ET.Element('mxfile', host="app.diagrams.net", agent="doodle-ai")
        diagram = ET.SubElement(mxfile, 'diagram', id="diagram-1", name="Page-1")
        mxGraphModel = ET.SubElement(diagram, 'mxGraphModel', dx="1400", dy="800", grid="1", gridSize="10", guides="1", tooltips="1", connect="1", arrows="1")
        root = ET.SubElement(mxGraphModel, 'root')
        self._create_cell(root, id="0")
        self._create_cell(root, id="1", parent="0")
        
        # Simple tiered layout logic
        tiers = {
            'user': 0, 'generic_client': 0, 'aws.network.route53': 1,
            'aws.network.elb_application_load_balancer': 2,
            'aws.compute.ec2_auto_scaling': 3,
            'aws.database.rds_postgresql_instance': 4, 'aws.storage.s3': 4
        }
        nodes_in_tier = {i: [] for i in range(5)}
        for node in data['nodes']:
            tier = tiers.get(node['type'], 3)
            nodes_in_tier[tier].append(node)

        node_id_map = {}
        y_pos = 40
        for i in range(5):
            tier_count = len(nodes_in_tier[i])
            tier_width = tier_count * 180  # node width + padding
            x_pos = 600 - (tier_width / 2)
            for node in nodes_in_tier[i]:
                cell_id = self.cell_id_counter
                node_id_map[node['id']] = cell_id
                self.cell_id_counter += 1
                self._create_node(root, cell_id, node['label'], x_pos, y_pos)
                x_pos += 180
            if tier_count > 0: y_pos += 140
                
        for edge in data['edges']:
            source_cell_id = node_id_map.get(edge['source'])
            target_cell_id = node_id_map.get(edge['target'])
            if source_cell_id and target_cell_id:
                self._create_edge(root, source_cell_id, target_cell_id, edge.get('label', ''))
            
        rough_string = ET.tostring(mxfile, 'utf-8')
        reparsed = minidom.parseString(rough_string)
        return reparsed.toprettyxml(indent="  ")

# --- Main Application Flow ---
class ArchitectureAPI:
    def __init__(self):
        self.nlp_processor = GeminiProcessor()
        self.diagram_generator = DiagramGenerator()

    def create_from_text(self, text: str, output_filename: str = "aws_web_app_architecture"):
        print("--- Starting Architecture Diagram Generation ---")
        arch_data = self.nlp_processor.get_architecture_json(text)
        if arch_data:
            print("\n📄 [Intermediate JSON] Generated structured data from Gemini:")
            print(json.dumps(arch_data, indent=2))
            print("----------------------------------------------")
            xml_content = self.diagram_generator.generate_xml_string(arch_data)
            
            with open(f"{output_filename}.drawio", "w", encoding="utf-8") as f:
                f.write(xml_content)
                
            print(f"\n✅ Success! Editable diagram saved to '{output_filename}.drawio'")
            print("   You can open this file directly with draw.io or at https://app.diagrams.net/")
        else:
            print("\n🛑 Halting execution due to Gemini processing error.")

if __name__ == "__main__":
    user_input = """
    A user with a web browser first hits Route 53 for DNS resolution.
    Route 53 points to an Application Load Balancer. The browser then sends the
    HTTPS request to the ALB. The ALB forwards the request to a fleet of EC2 web servers
    in an Auto Scaling Group. These servers read and write user data to an RDS
    PostgreSQL database and also read static assets like images from an S3 bucket.
    """
    try:
        api = ArchitectureAPI()
        api.create_from_text(user_input)
    except Exception as e:
        print(f"\nAn unexpected error occurred in the main application flow: {e}")
import json
import os
import xml.etree.ElementTree as ET
from xml.dom import minidom
import boto3
from botocore.exceptions import ClientError
import logging

# --- Configure logging to work with AWS CloudWatch ---
logger = logging.getLogger()
logger.setLevel(logging.INFO)
# ----------------------------------------------------


# --- Part 1: Amazon Bedrock Integration (using Claude 3 Sonnet) ---

class BedrockProcessor:
    """
    Processes natural language input using Anthropic's Claude 3 Sonnet model
    on Amazon Bedrock to generate structured JSON.
    """
    def __init__(self, region_name=None):
        try:
            # If region is not specified, boto3 will use the region of the Lambda function
            self.client = boto3.client(service_name='bedrock-runtime', region_name=region_name)
            self.model_id = 'anthropic.claude-3-sonnet-v1:0'
            logger.info(f"✅ [Bedrock] Client configured successfully for model '{self.model_id}'.")
        except Exception as e:
            logger.error(f"❌ ERROR: Could not create Bedrock runtime client: {e}")
            raise

    def get_architecture_json(self, text_input: str) -> dict:
        logger.info("🤖 [Bedrock] Calling Claude 3 Sonnet to process input text...")
        
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
        
        # Claude 3 Sonnet uses the "messages" API format
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 4096,
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": prompt}],
                }
            ],
        }

        try:
            response = self.client.invoke_model(
                modelId=self.model_id,
                body=json.dumps(request_body),
                contentType='application/json',
                accept='application/json'
            )
            
            response_body = json.loads(response['body'].read())
            json_text = response_body['content'][0]['text']
            
            # Clean up potential markdown formatting from the response
            cleaned_json_text = json_text.strip().replace("```json", "").replace("```", "")
            return json.loads(cleaned_json_text)
            
        except ClientError as e:
            logger.error(f"❌ [Bedrock] ClientError: Couldn't invoke model '{self.model_id}'. Check IAM permissions. Details: {e}")
            raise Exception("Failed to invoke Bedrock model due to a client error.") from e
        except Exception as e:
            logger.error(f"❌ [Bedrock] Failed to generate or parse JSON from API response: {e}")
            raise Exception("Failed to get a valid response from Bedrock API.") from e


# --- Part 2: Direct draw.io XML Generation ---

class DiagramGenerator:
    """
    Generates a draw.io compatible XML file from a structured
    JSON object containing nodes and edges.
    """
    def __init__(self):
        self.cell_id_counter = 2

    def _create_cell(self, parent_element, **attrs):
        return ET.SubElement(parent_element, 'mxCell', {str(k): str(v) for k, v in attrs.items()})

    def _create_node(self, root, node_id, label, x, y, width=120, height=80):
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
        logger.info("🎨 [XML Generator] Building reliable draw.io XML structure...")
        self.cell_id_counter = 2 # Reset for each invocation
        mxfile = ET.Element('mxfile', host="app.diagrams.net", agent="doodle-ai")
        diagram = ET.SubElement(mxfile, 'diagram', id="diagram-1", name="Page-1")
        mxGraphModel = ET.SubElement(diagram, 'mxGraphModel', dx="1400", dy="800", grid="1", gridSize="10", guides="1", tooltips="1", connect="1", arrows="1")
        root = ET.SubElement(mxGraphModel, 'root')
        self._create_cell(root, id="0")
        self._create_cell(root, id="1", parent="0")

        # Simple tiered layout logic to position nodes automatically
        tiers = {
            'user': 0, 'generic_client': 0, 'aws.network.route53': 1,
            'aws.network.elb_application_load_balancer': 2,
            'aws.compute.ec2_auto_scaling': 3,
            'aws.database.rds_postgresql_instance': 4, 'aws.storage.s3': 4
        }
        nodes_in_tier = {i: [] for i in range(5)}
        for node in data.get('nodes', []):
            tier = tiers.get(node['type'], 3)
            nodes_in_tier[tier].append(node)

        node_id_map = {}
        y_pos = 40
        for i in range(5):
            tier_count = len(nodes_in_tier[i])
            if tier_count == 0: continue
            tier_width = tier_count * 180
            x_pos = 600 - (tier_width / 2)
            for node in nodes_in_tier[i]:
                cell_id = self.cell_id_counter
                node_id_map[node['id']] = cell_id
                self.cell_id_counter += 1
                self._create_node(root, cell_id, node['label'], x_pos, y_pos)
                x_pos += 180
            y_pos += 140

        for edge in data.get('edges', []):
            source_cell_id = node_id_map.get(edge['source'])
            target_cell_id = node_id_map.get(edge['target'])
            if source_cell_id and target_cell_id:
                self._create_edge(root, source_cell_id, target_cell_id, edge.get('label', ''))

        rough_string = ET.tostring(mxfile, 'utf-8')
        reparsed = minidom.parseString(rough_string)
        return reparsed.toprettyxml(indent="  ")


# --- Global Initializations (for Lambda warm starts) ---
try:
    bedrock_processor = BedrockProcessor()
    diagram_generator = DiagramGenerator()
    s3_client = boto3.client('s3') # Initialize S3 client once
except Exception as e:
    logger.fatal(f"CRITICAL: Failed to initialize a processor or client: {e}")
    bedrock_processor = None
    diagram_generator = None
    s3_client = None
# --------------------------------------------------------


# --- Main Lambda Handler ---
def lambda_handler(event, context):
    """
    Main entry point for the Lambda function.
    Expects an event from API Gateway with a JSON body:
    {
        "text_input": "Your architecture description..."
    }
    """
    if not all([bedrock_processor, diagram_generator, s3_client]):
        return {"statusCode": 500, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"error": "Service is not available due to an initialization failure."})}
    
    # Get S3 bucket name from environment variables for flexibility
    bucket_name = os.environ.get('DIAGRAM_BUCKET')
    if not bucket_name:
        logger.error("FATAL: DIAGRAM_BUCKET environment variable not set.")
        return {"statusCode": 500, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"error": "Server is not configured correctly."})}

    try:
        logger.info(f"Received event: {json.dumps(event)}")
        body = json.loads(event.get('body', '{}'))
        text_input = body.get('text_input')

        if not text_input:
            logger.error("Validation Error: 'text_input' not found in request body.")
            return {"statusCode": 400, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"error": "Request body must be a JSON object with a 'text_input' key."})}

        # --- Main Application Flow ---
        # 1. Get structured data from Bedrock
        arch_data = bedrock_processor.get_architecture_json(text_input)
        
        # 2. Generate the XML content for the diagram
        xml_content = diagram_generator.generate_xml_string(arch_data)

        # 3. Save the XML file to S3
        # Use the Lambda request ID for a unique filename to prevent overwrites
        file_name = f"{context.aws_request_id}.drawio"
        
        s3_client.put_object(
            Bucket=bucket_name,
            Key=file_name,
            Body=xml_content.encode('utf-8'), # S3 expects bytes
            ContentType='application/xml'
        )
        
        s3_uri = f"s3://{bucket_name}/{file_name}"
        logger.info(f"✅ Success! Diagram saved to {s3_uri}")

        # 4. Return a success response with the S3 location
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*" # Add CORS header
            },
            "body": json.dumps({
                "message": "Diagram created successfully.",
                "s3_uri": s3_uri,
                "s3_bucket": bucket_name,
                "s3_key": file_name
            })
        }

    except json.JSONDecodeError:
        logger.error("Error decoding JSON from event body.")
        return {"statusCode": 400, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"error": "Invalid JSON in request body."})}
    except ClientError as e:
        logger.error(f"AWS Client Error: {e.response['Error']['Message']}", exc_info=True)
        return {"statusCode": 500, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"error": "An AWS service error occurred. Check IAM permissions and resource names."})}
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        return {"statusCode": 500, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"error": "An internal server error occurred."})}
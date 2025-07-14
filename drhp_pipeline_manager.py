import os
import sys
import logging
import glob
import json
from datetime import datetime
from dotenv import load_dotenv
from mongoengine import (
    connect,
    Document,
    StringField,
    DateTimeField,
    IntField,
    ListField,
    ReferenceField,
    DoesNotExist,
)
from bson import ObjectId
from pathlib import Path
import pytz
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add DRHP_crud_backend to sys.path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), "DRHP_crud_backend"))
from DRHP_crud_backend.local_drhp_processor_final import LocalDRHPProcessor
from DRHP_crud_backend.baml_client import b
from DRHP_crud_backend.DRHP_ai_processing.note_checklist_processor import (
    DRHPNoteChecklistProcessor,
)
from qdrant_client import QdrantClient

# --- Logging Setup ---
class ISTFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        ist = pytz.timezone("Asia/Kolkata")
        ct = datetime.fromtimestamp(record.created, tz=ist)
        return ct.strftime(datefmt or "%Y-%m-%d %H:%M:%S")

log_formatter = ISTFormatter(fmt="%(asctime)s - %(levelname)s - %(message)s")
file_handler = logging.FileHandler("drhp_pipeline_manager.log", encoding="utf-8")
file_handler.setFormatter(log_formatter)
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
logging.basicConfig(
    level=logging.INFO, handlers=[file_handler, console_handler], force=True
)
logger = logging.getLogger("DRHP_Pipeline_Manager")

# --- Environment and Constants ---
load_dotenv()
QDRANT_URL = os.getenv("QDRANT_URL")
MONGODB_URI = os.getenv("DRHP_MONGODB_URI")
DB_NAME = os.getenv("DRHP_DB_NAME", "DRHP_NOTES")
CHECKLIST_PATH = os.path.join(
    os.path.dirname(__file__),
    "DRHP_crud_backend",
    "Checklists",
    "IPO_Notes_Checklist_AI_Final_prod_updated.xlsx",
)

# --- MongoEngine Models ---
class Company(Document):
    meta = {"db_alias": "core", "collection": "company"}
    name = StringField(required=True)
    corporate_identity_number = StringField(required=True, unique=True)
    drhp_file_url = StringField(required=True)
    website_link = StringField()
    created_at = DateTimeField(default=datetime.utcnow)

class Page(Document):
    meta = {"db_alias": "core", "collection": "pages"}
    company_id = ReferenceField(Company, required=True)
    page_number_pdf = IntField(required=True)
    page_number_drhp = StringField()
    page_content = StringField()

class ChecklistOutput(Document):
    meta = {"db_alias": "core", "collection": "checklist_outputs"}
    company_id = ReferenceField(Company, required=True)
    checklist_name = StringField(required=True)
    row_index = IntField(required=True)
    topic = StringField()
    section = StringField()
    ai_prompt = StringField()
    ai_output = StringField()
    citations = ListField(StringField())
    commentary = StringField()
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

class FinalMarkdown(Document):
    meta = {"db_alias": "core", "collection": "final_markdown"}
    company_id = ReferenceField(Company, required=True)
    company_name = StringField(required=True)
    markdown = StringField(required=True)

# --- Database and Environment Management ---
def connect_to_db():
    try:
        connect(alias="core", host=MONGODB_URI, db=DB_NAME)
        logger.info(f"Connected to MongoDB at {MONGODB_URI}, DB: {DB_NAME}")
    except Exception as e:
        logger.error(f"[MONGODB CONNECTION ERROR] {e}")
        raise

def validate_env():
    required_vars = ["OPENAI_API_KEY", "QDRANT_URL", "DRHP_MONGODB_URI"]
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        msg = f"Missing required environment variables: {', '.join(missing)}"
        logger.error(msg)
        raise EnvironmentError(msg)
    logger.info("All required environment variables are set.")

# --- Core Pipeline Functions ---

def _extract_company_details(pdf_path, update_callback):
    """Step 1: Extract company details from the first 10 pages of the PDF."""
    update_callback({"status": "processing", "stage": "details", "progress": 5, "message": "Extracting company details..."})
    processor = LocalDRHPProcessor(qdrant_url=QDRANT_URL)
    json_path = processor.process_pdf_locally(pdf_path, "TEMP_COMPANY")
    
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    pdf_name = list(data.keys())[0]
    pages = data[pdf_name]
    first_pages_text = "\n".join(
        [pages.get(str(i), {}).get("page_content", "") for i in range(1, 11)]
    )
    
    company_details = b.ExtractCompanyDetails(first_pages_text)
    if not company_details.name or not company_details.corporate_identity_number:
        raise ValueError("BAML failed to return a valid company name or unique identifier.")
    
    logger.info(f"Fetched company details: {company_details.name}")
    return company_details, pages, json_path

def _save_pages(company_doc, pages, update_callback):
    """Step 2: Save extracted page content to MongoDB."""
    update_callback({"status": "processing", "stage": "pages", "progress": 25, "message": "Saving PDF pages to database..."})
    
    page_items = [(k, v) for k, v in pages.items() if k.isdigit()]
    
    def save_page_safe(page_no, page_info):
        Page(
            company_id=company_doc,
            page_number_pdf=int(page_no),
            page_number_drhp=page_info.get("page_number_drhp", ""),
            page_content=page_info.get("page_content", ""),
        ).save()

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(save_page_safe, k, v) for k, v in page_items]
        for future in as_completed(futures):
            future.result() # Raise exceptions if any
    logger.info(f"Saved {len(page_items)} pages for company {company_doc.name}")

def _upsert_to_qdrant(company_doc, company_name, json_path, qdrant_collection, update_callback):
    """Step 3: Upsert page embeddings into Qdrant."""
    update_callback({"status": "processing", "stage": "qdrant", "progress": 50, "message": "Creating vector embeddings..."})
    processor = LocalDRHPProcessor(qdrant_url=QDRANT_URL, collection_name=qdrant_collection)
    processor.upsert_pages_to_qdrant(json_path, company_name, str(company_doc.id))
    logger.info(f"Embeddings upserted to Qdrant collection: {qdrant_collection}")

def _run_checklist_processor(company_doc, qdrant_collection, update_callback):
    """Step 4: Run the AI checklist processor."""
    update_callback({"status": "processing", "stage": "checklist", "progress": 75, "message": "Running AI checklist processor..."})
    checklist_name = os.path.basename(CHECKLIST_PATH)
    note_processor = DRHPNoteChecklistProcessor(
        CHECKLIST_PATH, qdrant_collection, str(company_doc.id), checklist_name
    )
    note_processor.process()
    logger.info("Checklist processing complete.")

def _generate_and_save_markdown(company_doc, update_callback):
    """Step 5: Generate the final markdown report and save it."""
    update_callback({"status": "processing", "stage": "markdown", "progress": 90, "message": "Generating final markdown report..."})
    
    rows = ChecklistOutput.objects(company_id=company_doc).order_by("row_index")
    md_lines = [f"# IPO Investment Note: {company_doc.name}\n\n"]
    for row in rows:
        heading = f"**{row.topic}**" if row.topic else ""
        commentary = f'<span style="font-size:10px;"><i>AI Commentary : {row.commentary}</i></span>' if row.commentary else ""
        md_lines.append(f"{heading}\n\n{row.ai_output or ''}\n\n{commentary}\n\n---\n\n")
    
    markdown = "".join(md_lines)
    FinalMarkdown.objects(company_id=company_doc).update_one(
        set__company_name=company_doc.name, set__markdown=markdown, upsert=True
    )
    logger.info(f"Saved markdown for {company_doc.name}")
    return markdown

# --- Public API Functions ---

def run_full_pipeline(pdf_path, update_callback):
    """Main orchestrator function for the entire DRHP processing pipeline."""
    json_path = None
    company_doc = None
    try:
        # Step 1: Extract details
        company_details, pages, json_path = _extract_company_details(pdf_path, update_callback)
        company_name = company_details.name
        unique_id = company_details.corporate_identity_number
        qdrant_collection = f"drhp_notes_{company_name.replace(' ', '_').upper()}"

        # Step 2: Get or create company, check for existing data
        company_doc = Company.objects(corporate_identity_number=unique_id).first()
        if not company_doc:
            company_doc = Company(
                name=company_name,
                corporate_identity_number=unique_id,
                drhp_file_url=pdf_path,
                website_link=getattr(company_details, "website_link", None),
            ).save()
            logger.info(f"New company created: {company_name}")
            _save_pages(company_doc, pages, update_callback)
            _upsert_to_qdrant(company_doc, company_name, json_path, qdrant_collection, update_callback)
            _run_checklist_processor(company_doc, qdrant_collection, update_callback)
        else:
            logger.info(f"Company '{company_name}' already exists. Skipping to markdown generation.")

        # Step 5: Generate and save markdown
        final_markdown = _generate_and_save_markdown(company_doc, update_callback)
        
        update_callback({"status": "completed", "progress": 100, "message": "IPO Notes generated successfully!", "markdown": final_markdown})

    except Exception as e:
        logger.error(f"PIPELINE FAILED: {e}", exc_info=True)
        if company_doc: # Attempt cleanup on failure
            delete_company_and_all_data(str(company_doc.id))
        update_callback({"status": "error", "message": str(e)})
    finally:
        if json_path and os.path.exists(json_path):
            os.remove(json_path)
        update_callback(None) # Signal end of stream

def rerun_pipeline_for_company(company_id, update_callback):
    """Orchestrator to re-run checklist and markdown generation for an existing company."""
    try:
        company_doc = Company.objects.get(id=ObjectId(company_id))
        qdrant_collection = f"drhp_notes_{company_doc.name.replace(' ', '_').upper()}"
        
        # Delete old checklist outputs
        ChecklistOutput.objects(company_id=company_doc).delete()
        logger.info(f"Deleted existing checklist outputs for {company_doc.name}")

        # Re-run checklist and markdown generation
        _run_checklist_processor(company_doc, qdrant_collection, update_callback)
        final_markdown = _generate_and_save_markdown(company_doc, update_callback)

        update_callback({"status": "completed", "progress": 100, "message": "IPO Note regenerated successfully!", "markdown": final_markdown})

    except DoesNotExist:
        update_callback({"status": "error", "message": "Company not found."})
    except Exception as e:
        logger.error(f"REGENERATION FAILED for company {company_id}: {e}", exc_info=True)
        update_callback({"status": "error", "message": str(e)})
    finally:
        update_callback(None) # Signal end of stream

def get_all_companies_with_status():
    """Retrieves all companies and determines their status."""
    companies = []
    all_company_docs = Company.objects.all()
    for doc in all_company_docs:
        has_markdown = FinalMarkdown.objects(company_id=doc).first() is not None
        companies.append({
            "id": str(doc.id),
            "name": doc.name,
            "uin": doc.corporate_identity_number,
            "uploadDate": doc.created_at.strftime("%Y-%m-%d"),
            "status": "completed" if has_markdown else "processing",
            "hasMarkdown": has_markdown,
        })
    return companies

def get_final_markdown(company_id):
    """Gets the final markdown for a single company."""
    try:
        markdown_doc = FinalMarkdown.objects.get(company_id=ObjectId(company_id))
        return markdown_doc.markdown
    except DoesNotExist:
        return None

def delete_company_and_all_data(company_id):
    """Deletes a company and all related data from MongoDB and Qdrant."""
    try:
        company_doc = Company.objects.get(id=ObjectId(company_id))
        qdrant_collection = f"drhp_notes_{company_doc.name.replace(' ', '_').upper()}"

        # Delete from MongoDB
        Page.objects(company_id=company_doc).delete()
        ChecklistOutput.objects(company_id=company_doc).delete()
        FinalMarkdown.objects(company_id=company_doc).delete()
        company_doc.delete()

        # Delete from Qdrant
        try:
            client = QdrantClient(url=QDRANT_URL)
            if qdrant_collection in [c.name for c in client.get_collections().collections]:
                client.delete_collection(collection_name=qdrant_collection)
            logger.info(f"Deleted Qdrant collection: {qdrant_collection}")
        except Exception as qe:
            logger.error(f"Could not delete Qdrant collection {qdrant_collection}: {qe}")
        
        logger.info(f"Successfully deleted company {company_id} and all related data.")
        return True
    except DoesNotExist:
        logger.warning(f"Attempted to delete non-existent company with ID: {company_id}")
        return False

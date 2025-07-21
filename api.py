import os
import sys
import asyncio
import json
import tempfile
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
import pytz
from fastapi import FastAPI, UploadFile, File, HTTPException, Path, BackgroundTasks
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from mongoengine import connect, disconnect, DoesNotExist
import markdown
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML, CSS
from contextlib import asynccontextmanager

# Add the backend directory to the Python path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), "DRHP_crud_backend"))

# Import your existing modules
from DRHP_crud_backend.local_drhp_processor_final import LocalDRHPProcessor
from DRHP_crud_backend.baml_client import b
from DRHP_crud_backend.DRHP_ai_processing.note_checklist_processor import DRHPNoteChecklistProcessor
from qdrant_client import QdrantClient
from azure_blob_utils import get_blob_storage

# Import your existing database models
from mongoengine import (
    Document, StringField, DateTimeField, IntField, 
    ListField, ReferenceField, ObjectIdField
)

# Setup logging with IST timestamps
class ISTFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        ist = pytz.timezone("Asia/Kolkata")
        ct = datetime.fromtimestamp(record.created, tz=ist)
        if datefmt:
            s = ct.strftime(datefmt)
        else:
            s = ct.strftime("%Y-%m-%d %H:%M:%S")
        return s

log_formatter = ISTFormatter(fmt="%(asctime)s - %(levelname)s - %(message)s")
file_handler = logging.FileHandler("drhp_api.log", encoding="utf-8")
file_handler.setFormatter(log_formatter)
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)

logging.basicConfig(
    level=logging.INFO, handlers=[file_handler, console_handler], force=True
)
logger = logging.getLogger("DRHP_API")

# Database Models
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
    page_number_drhp = IntField()
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
    citations = ListField(IntField())
    commentary = StringField()
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

class FinalMarkdown(Document):
    meta = {"db_alias": "core", "collection": "final_markdown"}
    company_id = ReferenceField(Company, required=True)
    company_name = StringField(required=True)
    markdown = StringField(required=True)

# Pydantic Models
class ProcessingStatus(BaseModel):
    pages_processed: bool
    qdrant_indexed: bool
    checklist_completed: bool
    markdown_generated: bool

class CompanyResponse(BaseModel):
    company_id: str
    company_name: str
    corporate_identity_number: str
    website_link: Optional[str] = None
    created_at: str
    has_markdown: bool

class CompanyDetailResponse(BaseModel):
    company_id: str
    company_name: str
    corporate_identity_number: str
    website_link: Optional[str] = None
    created_at: str
    has_markdown: bool
    processing_status: ProcessingStatus

class ReportResponse(BaseModel):
    company_id: str
    company_name: str
    markdown: Optional[str] = None
    html: Optional[str] = None
    format: str

class CompanyListResponse(BaseModel):
    total_companies: int
    companies: List[CompanyResponse]

class ProcessingUpdate(BaseModel):
    status: str  # "processing", "completed", "error"
    stage: Optional[str] = None  # "details", "pages", "qdrant", "checklist", "markdown"
    progress: int  # 0-100
    message: str
    company_id: Optional[str] = None
    markdown: Optional[str] = None

class HealthResponse(BaseModel):
    status: str
    mongodb_connected: bool
    qdrant_connected: bool
    timestamp: str

# FastAPI App Initialization
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        validate_env()
        # Disconnect any existing connections first
        try:
            disconnect(alias="core")
        except:
            pass  # Ignore if no connection exists
        
        connect(alias="core", host=MONGODB_URI, db=DB_NAME)
        logger.info(f"Connected to MongoDB at {MONGODB_URI}, DB: {DB_NAME}")
        yield
    except Exception as e:
        logger.error(f"Startup error: {e}")
        raise
    finally:
        # Shutdown
        try:
            disconnect(alias="core")
            logger.info("Disconnected from MongoDB")
        except Exception as e:
            logger.error(f"Shutdown error: {e}")

# Update the FastAPI app initialization to use lifespan
app = FastAPI(
    title="DRHP IPO Notes Generator API",
    description="API to manage and process DRHP documents for IPO note generation.",
    version="2.0.0",
    lifespan=lifespan
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this to your frontend's domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global variables
QDRANT_URL = os.getenv("QDRANT_URL")
MONGODB_URI = os.getenv("DRHP_MONGODB_URI")
DB_NAME = os.getenv("DRHP_DB_NAME", "DRHP_NOTES")
CHECKLIST_PATH = os.path.join(
    os.path.dirname(__file__),
    "DRHP_crud_backend",
    "Checklists",
    "IPO_Notes_Checklist_AI_Final_prod_updated.xlsx",
)

# Utility Functions
def validate_env():
    """Validate required environment variables"""
    required_vars = ["OPENAI_API_KEY", "QDRANT_URL", "DRHP_MONGODB_URI"]
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        logger.error(f"Missing required environment variables: {', '.join(missing)}")
        raise EnvironmentError(f"Missing required environment variables: {', '.join(missing)}")
    logger.info("All required environment variables are set.")

def qdrant_collection_exists(collection_name: str, qdrant_url: str) -> bool:
    """Check if Qdrant collection exists"""
    try:
        client = QdrantClient(url=qdrant_url)
        return collection_name in [c.name for c in client.get_collections().collections]
    except Exception as e:
        logger.error(f"Failed to check Qdrant collections: {e}")
        return False

def get_company_processing_status(company_doc: Company) -> ProcessingStatus:
    """Check processing status for a company"""
    qdrant_collection = f"drhp_notes_{company_doc.name.replace(' ', '_').upper()}"
    
    return ProcessingStatus(
        pages_processed=Page.objects(company_id=company_doc).first() is not None,
        qdrant_indexed=qdrant_collection_exists(qdrant_collection, QDRANT_URL),
        checklist_completed=ChecklistOutput.objects(company_id=company_doc).first() is not None,
        markdown_generated=FinalMarkdown.objects(company_id=company_doc).first() is not None
    )

async def validate_pdf_file(file: UploadFile) -> bool:
    """Validate uploaded PDF file"""
    if file.content_type != "application/pdf":
        return False
    if file.size and file.size > 50 * 1024 * 1024:  # 50MB limit
        return False
    return True

def generate_markdown_for_company(company_doc: Company) -> str:
    """Generate markdown from checklist outputs"""
    rows = (
        ChecklistOutput.objects(company_id=company_doc)
        .order_by("row_index")
        .only("topic", "ai_output", "commentary", "row_index")
    )
    
    md_lines = []
    for row in rows:
        topic = row.topic or ""
        ai_output = row.ai_output or ""
        commentary = row.commentary or ""
        
        heading_md = f"**{topic}**" if topic else ""
        commentary_md = (
            f'<span style="font-size:10px;"><i>AI Commentary : {commentary}</i></span>'
            if commentary else ""
        )
        
        md_lines.append(f"{heading_md}\n\n{ai_output}\n\n{commentary_md}\n\n")
    
    return "".join(md_lines)

def save_final_markdown(company_doc: Company, markdown_content: str):
    """Save final markdown to database"""
    FinalMarkdown.objects(company_id=company_doc).update_one(
        set__company_name=company_doc.name,
        set__markdown=markdown_content,
        upsert=True
    )
    logger.info(f"Saved markdown for {company_doc.name} to final_markdown collection.")

def load_image_base64(path: str) -> str:
    """Load image and convert to base64 data URL"""
    try:
        with open(path, "rb") as f:
            import base64
            return f"data:image/png;base64,{base64.b64encode(f.read()).decode()}"
    except Exception as e:
        logger.warning(f"Failed to load image {path}: {e}")
        return ""

def render_template(env: Environment, template_name: str, context: dict) -> str:
    """Render Jinja2 template with given context"""
    return env.get_template(template_name).render(context)

def generate_pdf_from_markdown(company_name: str, markdown_content: str) -> str:
    """Generate PDF from markdown content"""
    try:
        # Setup paths
        base_dir = os.path.join(os.path.dirname(__file__), "DRHP_crud_backend")
        templates_dir = os.path.join(base_dir, "templates")
        styles_dir = os.path.join(base_dir, "styles")
        assets_dir = os.path.join(base_dir, "assets")
        
        # Setup Jinja2 environment
        env = Environment(loader=FileSystemLoader(templates_dir))
        
        # Convert markdown to HTML
        html_body = markdown.markdown(markdown_content, extensions=["tables", "fenced_code"])
        
        # Prepare context
        context = {
            "company_name": company_name.upper(),
            "document_date": datetime.today().strftime("%B %Y"),
            "company_logo_data": load_image_base64(os.path.join(assets_dir, "Pine Labs_logo.png")),
            "content": html_body,
        }
        
        # Render HTML
        front_html = render_template(env, "front_page.html", context)
        content_html = render_template(env, "content_page.html", context)
        full_html = front_html + content_html
        
        # Create temporary PDF file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        temp_path = temp_file.name
        temp_file.close()
        
        # Generate PDF
        HTML(string=full_html, base_url=base_dir).write_pdf(
            temp_path, stylesheets=[CSS(os.path.join(styles_dir, "styles.css"))]
        )
        
        logger.info(f"PDF generated for {company_name}")
        return temp_path
        
    except Exception as e:
        logger.error(f"Failed to generate PDF: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate PDF: {e}")

async def process_drhp_pipeline(pdf_path: str, queue: asyncio.Queue):
    """Process DRHP pipeline with progress updates"""
    try:
        # Initialize blob storage
        blob_storage = get_blob_storage()
        
        # Upload PDF to blob storage
        await queue.put({
            "status": "processing",
            "stage": "upload",
            "progress": 5,
            "message": "Uploading PDF to storage..."
        })
        
        import uuid
        unique_id = str(uuid.uuid4())
        pdf_filename = os.path.basename(pdf_path)
        pdf_blob_name = f"pdfs/{unique_id}_{pdf_filename}"
        pdf_blob_url = blob_storage.upload_file(pdf_path, pdf_blob_name)
        
        # Extract company details
        await queue.put({
            "status": "processing",
            "stage": "details",
            "progress": 15,
            "message": "Extracting company details..."
        })
        
        processor = LocalDRHPProcessor(
            qdrant_url=QDRANT_URL,
            collection_name=None,
            max_workers=5,
            company_name=None,
        )
        
        json_path = processor.process_pdf_locally(pdf_path, "TEMP_COMPANY")
        
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        pdf_name = list(data.keys())[0]
        pages = data[pdf_name]
        
        first_pages_text = "\n".join([
            pages[str(i)].get("page_content", "")
            for i in range(1, 11)
            if str(i) in pages
        ])
        
        company_details = b.ExtractCompanyDetails(first_pages_text)
        company_name = company_details.name
        unique_id = company_details.corporate_identity_number
        
        if not company_name or not unique_id:
            raise ValueError("Could not extract valid company details")
        
        # Create or get company
        await queue.put({
            "status": "processing",
            "stage": "company",
            "progress": 25,
            "message": f"Processing company: {company_name}"
        })
        
        try:
            company_doc = Company.objects.get(corporate_identity_number=unique_id)
            logger.info(f"Company already exists: {company_doc.id}")
        except DoesNotExist:
            company_doc = Company(
                name=company_name,
                corporate_identity_number=unique_id,
                drhp_file_url=pdf_blob_url,
                website_link=getattr(company_details, "website_link", None),
            ).save()
            logger.info(f"Company created: {company_doc.id}")
        
        # Process pages
        await queue.put({
            "status": "processing",
            "stage": "pages",
            "progress": 40,
            "message": "Processing PDF pages..."
        })
        
        # Save pages if not already done
        if not Page.objects(company_id=company_doc).first():
            page_items = [(k, v) for k, v in pages.items() if k != "_metadata"]
            page_items = [(k, v) for k, v in page_items if k.isdigit()]
            
            for k, v in page_items:
                try:
                    page_number_drhp_val = v.get("page_number_drhp", None)
                    if page_number_drhp_val and str(page_number_drhp_val).strip():
                        try:
                            page_number_drhp_val = int(page_number_drhp_val)
                        except (ValueError, TypeError):
                            page_number_drhp_val = None
                    else:
                        page_number_drhp_val = None
                    
                    Page(
                        company_id=company_doc,
                        page_number_pdf=int(k),
                        page_number_drhp=page_number_drhp_val,
                        page_content=v.get("page_content", ""),
                    ).save()
                except Exception as e:
                    logger.error(f"Failed to save page {k}: {e}")
        
        # Process Qdrant embeddings
        await queue.put({
            "status": "processing",
            "stage": "qdrant",
            "progress": 60,
            "message": "Creating vector embeddings..."
        })
        
        qdrant_collection = f"drhp_notes_{company_name.replace(' ', '_').upper()}"
        if not qdrant_collection_exists(qdrant_collection, QDRANT_URL):
            processor.collection_name = qdrant_collection
            processor.upsert_pages_to_qdrant(json_path, company_name, str(company_doc.id))
        
        # Process checklist
        await queue.put({
            "status": "processing",
            "stage": "checklist",
            "progress": 80,
            "message": "Running AI checklist processing..."
        })
        
        checklist_name = os.path.basename(CHECKLIST_PATH)
        if not ChecklistOutput.objects(company_id=company_doc, checklist_name=checklist_name).first():
            note_processor = DRHPNoteChecklistProcessor(
                CHECKLIST_PATH, qdrant_collection, str(company_doc.id), checklist_name
            )
            note_processor.process()
        
        # Generate markdown
        await queue.put({
            "status": "processing",
            "stage": "markdown",
            "progress": 95,
            "message": "Generating final report..."
        })
        
        markdown_content = generate_markdown_for_company(company_doc)
        save_final_markdown(company_doc, markdown_content)
        
        # Complete
        await queue.put({
            "status": "completed",
            "stage": "completed",
            "progress": 100,
            "message": "Processing completed successfully!",
            "company_id": str(company_doc.id),
            "markdown": markdown_content
        })
        
        # Cleanup
        try:
            os.remove(json_path)
        except Exception as e:
            logger.warning(f"Failed to cleanup JSON file: {e}")
            
    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        await queue.put({
            "status": "error",
            "stage": "error",
            "progress": 0,
            "message": f"Processing failed: {str(e)}"
        })

# API Endpoints

@app.get("/health", response_model=HealthResponse)
def health_check():
    """Health check endpoint"""
    try:
        # Test MongoDB connection
        mongodb_connected = True
        try:
            Company.objects.first()
        except Exception:
            mongodb_connected = False
        
        # Test Qdrant connection
        qdrant_connected = True
        try:
            client = QdrantClient(url=QDRANT_URL)
            client.get_collections()
        except Exception:
            qdrant_connected = False
        
        status = "healthy" if mongodb_connected and qdrant_connected else "degraded"
        
        return HealthResponse(
            status=status,
            mongodb_connected=mongodb_connected,
            qdrant_connected=qdrant_connected,
            timestamp=datetime.utcnow().isoformat()
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail="Health check failed")

@app.post("/companies/upload")
async def upload_and_process_drhp(file: UploadFile = File(...)):
    """Upload and process DRHP PDF with real-time updates"""
    
    # Validate file
    if not await validate_pdf_file(file):
        raise HTTPException(status_code=400, detail="Invalid file. Please upload a PDF under 50MB.")
    
    # Save uploaded file temporarily
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(await file.read())
        temp_pdf_path = tmp.name
    
    async def event_stream():
        try:
            queue = asyncio.Queue()
            loop = asyncio.get_event_loop()
            
            # Run pipeline in background
            future = loop.run_in_executor(
                None, lambda: asyncio.run(process_drhp_pipeline(temp_pdf_path, queue))
            )
            
            while True:
                try:
                    update = await asyncio.wait_for(queue.get(), timeout=600)  # 10 min timeout
                    yield f"data: {json.dumps(update.dict() if hasattr(update, 'dict') else update)}\n\n"
                    
                    if update.get("status") in ["completed", "error"]:
                        break
                        
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'status': 'error', 'message': 'Processing timed out.'})}\n\n"
                    break
            
            await future
            
        except Exception as e:
            error_message = f"An unexpected error occurred: {str(e)}"
            yield f"data: {json.dumps({'status': 'error', 'message': error_message})}\n\n"
        finally:
            # Cleanup temporary file
            if os.path.exists(temp_pdf_path):
                os.remove(temp_pdf_path)
    
    return StreamingResponse(event_stream(), media_type="text/event-stream")

@app.get("/companies", response_model=CompanyListResponse)
def get_all_companies():
    """Get list of all companies"""
    try:
        companies = []
        for company in Company.objects.all():
            has_markdown = FinalMarkdown.objects(company_id=company).first() is not None
            
            companies.append(CompanyResponse(
                company_id=str(company.id),
                company_name=company.name,
                corporate_identity_number=company.corporate_identity_number,
                website_link=company.website_link,
                created_at=company.created_at.isoformat(),
                has_markdown=has_markdown
            ))
        
        return CompanyListResponse(
            total_companies=len(companies),
            companies=companies
        )
    except Exception as e:
        logger.error(f"Failed to retrieve companies: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve companies: {e}")

@app.get("/companies/{company_id}", response_model=CompanyDetailResponse)
def get_company_details(company_id: str = Path(..., description="The MongoDB ID of the company")):
    """Get detailed information about a specific company"""
    try:
        company = Company.objects.get(id=company_id)
        processing_status = get_company_processing_status(company)
        has_markdown = processing_status.markdown_generated
        
        return CompanyDetailResponse(
            company_id=str(company.id),
            company_name=company.name,
            corporate_identity_number=company.corporate_identity_number,
            website_link=company.website_link,
            created_at=company.created_at.isoformat(),
            has_markdown=has_markdown,
            processing_status=processing_status
        )
    except DoesNotExist:
        raise HTTPException(status_code=404, detail="Company not found")
    except Exception as e:
        logger.error(f"Failed to get company details: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get company details: {e}")

@app.get("/companies/{company_id}/report", response_model=ReportResponse)
def get_company_report(company_id: str = Path(..., description="The MongoDB ID of the company")):
    """Get company report in markdown format"""
    try:
        company = Company.objects.get(id=company_id)
        markdown_doc = FinalMarkdown.objects(company_id=company).first()
        
        if not markdown_doc:
            raise HTTPException(status_code=404, detail="Report not found for this company")
        
        return ReportResponse(
            company_id=str(company.id),
            company_name=company.name,
            markdown=markdown_doc.markdown,
            format="markdown"
        )
    except DoesNotExist:
        raise HTTPException(status_code=404, detail="Company not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get company report: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get company report: {e}")

@app.get("/companies/{company_id}/report-html", response_model=ReportResponse)
def get_company_report_html(company_id: str = Path(..., description="The MongoDB ID of the company")):
    """Get company report in HTML format for preview"""
    try:
        company = Company.objects.get(id=company_id)
        markdown_doc = FinalMarkdown.objects(company_id=company).first()
        
        if not markdown_doc:
            raise HTTPException(status_code=404, detail="Report not found for this company")
        
        # Setup paths
        base_dir = os.path.join(os.path.dirname(__file__), "DRHP_crud_backend")
        templates_dir = os.path.join(base_dir, "templates")
        assets_dir = os.path.join(base_dir, "assets")
        
        # Setup Jinja2 environment
        env = Environment(loader=FileSystemLoader(templates_dir))
        
        # Convert markdown to HTML
        html_body = markdown.markdown(markdown_doc.markdown, extensions=["tables", "fenced_code"])
        
        # Prepare context
        context = {
            "company_name": company.name.upper(),
            "document_date": datetime.today().strftime("%B %Y"),
            "company_logo_data": load_image_base64(os.path.join(assets_dir, "Pine Labs_logo.png")),
            "content": html_body,
        }
        
        # Render HTML
        front_html = render_template(env, "front_page.html", context)
        content_html = render_template(env, "content_page.html", context)
        full_html = front_html + content_html
        
        # Read CSS
        css_path = os.path.join(base_dir, "styles", "web_styles.css")
        with open(css_path, 'r') as f:
            css_content = f.read()
        
        # Wrap with CSS
        styled_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{company.name} - IPO Report</title>
            <style>
                {css_content}
            </style>
        </head>
        <body>
            {full_html}
        </body>
        </html>
        """
        
        return ReportResponse(
            company_id=str(company.id),
            company_name=company.name,
            html=styled_html,
            format="html"
        )
    except DoesNotExist:
        raise HTTPException(status_code=404, detail="Company not found")
    except Exception as e:
        logger.error(f"Failed to generate HTML report: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate HTML report: {e}")

@app.get("/companies/{company_id}/report-pdf")
def get_company_report_pdf(company_id: str = Path(..., description="The MongoDB ID of the company")):
    """Get company report as downloadable PDF"""
    try:
        company = Company.objects.get(id=company_id)
        markdown_doc = FinalMarkdown.objects(company_id=company).first()
        
        if not markdown_doc:
            raise HTTPException(status_code=404, detail="Report not found for this company")
        
        # Generate PDF
        pdf_path = generate_pdf_from_markdown(company.name, markdown_doc.markdown)
        
        # Return PDF file
        return FileResponse(
            path=pdf_path,
            media_type="application/pdf",
            filename=f"{company.name.replace(' ', '_')}_IPO_Notes.pdf"
        )
    except DoesNotExist:
        raise HTTPException(status_code=404, detail="Company not found")
    except Exception as e:
        logger.error(f"Failed to generate PDF: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate PDF: {e}")

@app.post("/companies/{company_id}/regenerate")
async def regenerate_company_report(company_id: str = Path(..., description="The MongoDB ID of the company")):
    """Regenerate company report by re-running AI processing"""
    
    async def event_stream():
        try:
            company = Company.objects.get(id=company_id)
            
            await asyncio.sleep(0.1)  # Small delay to ensure connection
            
            # Delete existing checklist outputs
            yield f"data: {json.dumps({'status': 'processing', 'stage': 'cleanup', 'progress': 10, 'message': 'Cleaning up existing data...'})}\n\n"
            
            ChecklistOutput.objects(company_id=company).delete()
            FinalMarkdown.objects(company_id=company).delete()
            
            # Re-run checklist processing
            yield f"data: {json.dumps({'status': 'processing', 'stage': 'checklist', 'progress': 50, 'message': 'Re-running AI checklist processing...'})}\n\n"
            
            qdrant_collection = f"drhp_notes_{company.name.replace(' ', '_').upper()}"
            checklist_name = os.path.basename(CHECKLIST_PATH)
            
            note_processor = DRHPNoteChecklistProcessor(
                CHECKLIST_PATH, qdrant_collection, str(company.id), checklist_name
            )
            note_processor.process()
            
            # Generate new markdown
            yield f"data: {json.dumps({'status': 'processing', 'stage': 'markdown', 'progress': 90, 'message': 'Generating updated report...'})}\n\n"
            
            markdown_content = generate_markdown_for_company(company)
            save_final_markdown(company, markdown_content)
            
            # Complete
            yield f"data: {json.dumps({'status': 'completed', 'stage': 'completed', 'progress': 100, 'message': 'Report regenerated successfully!', 'company_id': company_id, 'markdown': markdown_content})}\n\n"
            
        except DoesNotExist:
            yield f"data: {json.dumps({'status': 'error', 'message': 'Company not found'})}\n\n"
        except Exception as e:
            logger.error(f"Regeneration error: {e}")
            yield f"data: {json.dumps({'status': 'error', 'message': f'Regeneration failed: {str(e)}'})}\n\n"
    
    return StreamingResponse(event_stream(), media_type="text/event-stream")

@app.delete("/companies/{company_id}", status_code=204)
def delete_company(company_id: str = Path(..., description="The MongoDB ID of the company")):
    """Delete a company and all its associated data"""
    try:
        company = Company.objects.get(id=company_id)
        
        # Delete related data
        Page.objects(company_id=company).delete()
        ChecklistOutput.objects(company_id=company).delete()
        FinalMarkdown.objects(company_id=company).delete()
        
        # Delete Qdrant collection
        try:
            qdrant_collection = f"drhp_notes_{company.name.replace(' ', '_').upper()}"
            client = QdrantClient(url=QDRANT_URL)
            if qdrant_collection in [c.name for c in client.get_collections().collections]:
                client.delete_collection(collection_name=qdrant_collection)
                logger.info(f"Deleted Qdrant collection: {qdrant_collection}")
        except Exception as qe:
            logger.error(f"Failed to delete Qdrant collection: {qe}")
        
        # Delete company
        company.delete()
        
        logger.info(f"Deleted company and all related data: {company.name}")
        return None
        
    except DoesNotExist:
        raise HTTPException(status_code=404, detail="Company not found")
    except Exception as e:
        logger.error(f"Failed to delete company: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete company: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

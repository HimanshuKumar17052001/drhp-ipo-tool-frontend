import os
import sys
import asyncio
import json
import tempfile
import logging
from typing import List
from fastapi import FastAPI, UploadFile, File, HTTPException, Path
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from mongoengine import connect, disconnect
from weasyprint import HTML, CSS

# Add the backend directory to the Python path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), "DRHP_crud_backend"))

import drhp_pipeline_manager as pipeline
from report_generator import generate_report_pdf

# Setup logging
logger = logging.getLogger("DRHP_API")

def safe_load_image_base64(assets_dir: str, filename: str) -> str:
    """Safely load image with fallback for missing assets"""
    try:
        from DRHP_crud_backend.report_generator import load_image_base64
        return load_image_base64(os.path.join(assets_dir, filename))
    except Exception as e:
        logger.warning(f"Could not load image {filename}: {e}")
        return ""  # Return empty string for missing images

# --- FastAPI App Initialization ---
app = FastAPI(
    title="DRHP IPO Notes Generator API",
    description="API to manage and process DRHP documents for IPO note generation.",
    version="1.0.0",
)

# --- CORS Configuration ---
# Allows the frontend (e.g., running on localhost:3000) to communicate with this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this to your frontend's domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Pydantic Models for API Data Validation ---
class CompanyModel(BaseModel):
    id: str
    name: str
    corporate_identity_number: str
    website_link: str | None = None
    created_at: str
    has_markdown: bool

class ReportRequest(BaseModel):
    markdown_content: str
    company_name: str
    output_filename: str

# --- API Lifespan Events (Connect/Disconnect DB) ---
@app.on_event("startup")
def startup_db_client():
    pipeline.connect_to_db()
    pipeline.validate_env()

@app.on_event("shutdown")
def shutdown_db_client():
    disconnect(alias="core")

# --- API Endpoints ---

@app.post("/companies/", summary="Upload and Process DRHP PDF")
async def upload_and_process_drhp(file: UploadFile = File(...)):
    """
    Accepts a DRHP PDF, processes it through the full pipeline,
    and streams real-time status updates using Server-Sent Events (SSE).
    """
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload a PDF.")

    # Save the uploaded file to a temporary location
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(await file.read())
        temp_pdf_path = tmp.name

    async def event_stream():
        try:
            # Use an asyncio queue to get updates from the sync pipeline function
            queue = asyncio.Queue()
            loop = asyncio.get_event_loop()

            # Run the synchronous pipeline function in a separate thread
            # and pass the queue to it for sending updates.
            future = loop.run_in_executor(
                None, pipeline.run_full_pipeline, temp_pdf_path, queue.put_nowait
            )

            while True:
                try:
                    # Wait for an update from the queue
                    update = await asyncio.wait_for(queue.get(), timeout=600) # 10-min timeout
                    if update is None: # End of stream signal
                        break
                    yield f"data: {json.dumps(update)}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'status': 'error', 'message': 'Processing timed out.'})}\n\n"
                    break
            
            # Wait for the pipeline thread to finish
            await future

        except Exception as e:
            error_message = f"An unexpected error occurred: {str(e)}"
            yield f"data: {json.dumps({'status': 'error', 'message': error_message})}\n\n"
        finally:
            # Clean up the temporary file
            if os.path.exists(temp_pdf_path):
                os.remove(temp_pdf_path)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/companies/", response_model=List[CompanyModel], summary="List All Companies")
def get_all_companies():
    """
    Retrieves a list of all companies from the database, along with their processing status.
    """
    try:
        companies = pipeline.get_all_companies_with_status()
        return companies
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve companies: {e}")


@app.get("/debug/companies", summary="Debug: List All Companies with IDs")
def debug_get_all_companies():
    """
    Debug endpoint to list all companies with their IDs for troubleshooting.
    """
    try:
        companies = pipeline.get_all_companies_with_status()
        debug_info = []
        for company in companies:
            debug_info.append({
                "id": company["id"],
                "name": company["name"],
                "corporate_identity_number": company["corporate_identity_number"],
                "created_at": company["created_at"],
                "has_markdown": company["has_markdown"]
            })
        return JSONResponse(content={"companies": debug_info, "total": len(debug_info)})
    except Exception as e:
        return JSONResponse(content={"error": str(e), "companies": [], "total": 0})


@app.get("/companies/{company_id}/markdown", response_class=JSONResponse, summary="Get Company's Final Markdown")
def get_company_markdown(company_id: str = Path(..., description="The MongoDB ID of the company.")):
    """
    Fetches the final generated markdown report for a specific company.
    """
    markdown_content = pipeline.get_final_markdown(company_id)
    if markdown_content is None:
        raise HTTPException(status_code=404, detail="Markdown not found for this company.")
    return JSONResponse(content={"markdown": markdown_content})


@app.get("/companies/{company_id}/report", response_class=JSONResponse, summary="Get Company's Report")
def get_company_report(company_id: str = Path(..., description="The MongoDB ID of the company.")):
    """
    Fetches the final generated markdown report for a specific company.
    This endpoint is specifically for the frontend to get the report for preview.
    """
    markdown_content = pipeline.get_final_markdown(company_id)
    if markdown_content is None:
        raise HTTPException(status_code=404, detail="Report not found for this company.")
    return JSONResponse(content={"markdown": markdown_content})


@app.get("/companies/{company_id}/report-html", response_class=JSONResponse, summary="Get Company's Report as HTML")
def get_company_report_html(company_id: str = Path(..., description="The MongoDB ID of the company.")):
    """
    Fetches the final generated markdown report for a specific company and renders it as HTML
    using the template system with proper styling.
    """
    try:
        # Get company details
        company_doc = pipeline.get_company_by_id(company_id)
        if not company_doc:
            # Log the attempted company ID for debugging
            print(f"DEBUG: Company not found for ID: {company_id}")
            # Let's also check if there are any companies in the database
            try:
                all_companies = pipeline.get_all_companies_with_status()
                print(f"DEBUG: Total companies in database: {len(all_companies)}")
                if all_companies:
                    print(f"DEBUG: Available company IDs: {[c['id'] for c in all_companies]}")
            except Exception as e:
                print(f"DEBUG: Error getting all companies: {e}")
            raise HTTPException(status_code=404, detail=f"Company not found with ID: {company_id}")
        
        # Get markdown content
        markdown_content = pipeline.get_final_markdown(company_id)
        if markdown_content is None:
            print(f"DEBUG: Markdown not found for company ID: {company_id}")
            raise HTTPException(status_code=404, detail="Report not found for this company.")
        
        print(f"DEBUG: Successfully found company: {company_doc.name} with ID: {company_id}")
        
        # Import the report generator functions
        from DRHP_crud_backend.report_generator import render_template, load_image_base64
        from jinja2 import Environment, FileSystemLoader
        import markdown
        import os
        from datetime import datetime
        
        # Setup Jinja2 environment
        base_dir = os.path.join(os.path.dirname(__file__), "DRHP_crud_backend")
        templates_dir = os.path.join(base_dir, "templates")
        assets_dir = os.path.join(base_dir, "assets")
        
        # Check if directories exist
        if not os.path.exists(templates_dir):
            raise HTTPException(status_code=500, detail=f"Templates directory not found: {templates_dir}")
        if not os.path.exists(assets_dir):
            raise HTTPException(status_code=500, detail=f"Assets directory not found: {assets_dir}")
        
        env = Environment(loader=FileSystemLoader(templates_dir))

        # Convert Markdown to HTML
        html_body = markdown.markdown(markdown_content, extensions=["tables", "fenced_code"])

        # Prepare dynamic context
        context = {
            "company_name": company_doc.name.upper(),
            "document_date": datetime.today().strftime("%B %Y"),
            "company_logo_data": load_image_base64(os.path.join(assets_dir, "Pine Labs_logo.png")),
            "content": html_body,
        }

        # Render full HTML
        front_html = render_template(env, "front_page.html", context)
        content_html = render_template(env, "content_page.html", context)
        full_html = front_html + content_html
        
        # Read the web CSS file
        css_path = os.path.join(base_dir, "styles", "web_styles.css")
        if not os.path.exists(css_path):
            raise HTTPException(status_code=500, detail=f"CSS file not found: {css_path}")
            
        with open(css_path, 'r') as f:
            css_content = f.read()
        
        # Wrap HTML with CSS
        styled_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{company_doc.name} - IPO Report</title>
            <style>
                {css_content}
            </style>
        </head>
        <body>
            {full_html}
        </body>
        </html>
        """
        
        return JSONResponse(content={"html": styled_html})
        
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        print(f"DEBUG: Unexpected error in report-html endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate HTML report: {e}")


@app.post("/companies/{company_id}/regenerate", summary="Regenerate IPO Note for a Company")
async def regenerate_company_report(company_id: str = Path(..., description="The MongoDB ID of the company.")):
    """
    Deletes existing checklist outputs and re-runs the AI processing steps
    to generate a new IPO note. Streams progress via SSE.
    """
    async def event_stream():
        try:
            queue = asyncio.Queue()
            loop = asyncio.get_event_loop()
            
            future = loop.run_in_executor(
                None, pipeline.rerun_pipeline_for_company, company_id, queue.put_nowait
            )

            while True:
                try:
                    update = await asyncio.wait_for(queue.get(), timeout=600)
                    if update is None:
                        break
                    yield f"data: {json.dumps(update)}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'status': 'error', 'message': 'Regeneration timed out.'})}\n\n"
                    break
            
            await future

        except Exception as e:
            error_message = f"An unexpected error occurred during regeneration: {str(e)}"
            yield f"data: {json.dumps({'status': 'error', 'message': error_message})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.delete("/companies/{company_id}", status_code=204, summary="Delete a Company and All Its Data")
def delete_company(company_id: str = Path(..., description="The MongoDB ID of the company.")):
    """
    Deletes a company and all its associated data from MongoDB and Qdrant.
    """
    try:
        success = pipeline.delete_company_and_all_data(company_id)
        if not success:
            raise HTTPException(status_code=404, detail="Company not found.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete company: {e}")
    return None # Return 204 No Content on success


@app.post("/generate-report-pdf/", response_class=FileResponse, summary="Generate PDF from Markdown")
def create_report_pdf(request: ReportRequest):
    """
    Takes markdown content and other details, and returns a generated PDF file.
    This endpoint is used by the frontend to render both newly generated notes
    and previously generated reports as downloadable PDFs.
    """
    try:
        # The base directory for templates, styles, etc.
        base_dir = os.path.join(os.path.dirname(__file__), "DRHP_crud_backend")
        
        pdf_path = generate_report_pdf(
            markdown_content=request.markdown_content,
            company_name=request.company_name,
            output_filename=request.output_filename,
            base_dir=base_dir,
        )
        
        # Return the generated PDF file, which will be automatically cleaned up
        # after the response is sent, thanks to how FileResponse works with temp files.
        return FileResponse(
            pdf_path,
            media_type="application/pdf",
            filename=request.output_filename,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate PDF report: {e}")


@app.get("/report/{company_id}")
async def get_final_report(company_id: str, format: str = "pdf"):
    """
    Get final report for a company by ID

    Args:
        company_id: The company ID (ObjectId as string)
        format: Output format (pdf, html, markdown)

    Returns:
        The report in the requested format
    """
    try:
        # Get company details
        company_doc = pipeline.get_company_by_id(company_id)
        if not company_doc:
            raise HTTPException(
                status_code=404,
                detail=f"Company with ID {company_id} not found",
            )

        # Get markdown content
        markdown_content = pipeline.get_final_markdown(company_id)
        if not markdown_content:
            raise HTTPException(
                status_code=404,
                detail=f"No markdown content found for company {company_id}",
            )

        company_name = company_doc.name
        logger.info(f"✅ Found markdown for company {company_id}: {company_name}")

        # Return based on requested format
        if format.lower() == "markdown":
            return {
                "company_id": company_id,
                "company_name": company_name,
                "content": markdown_content,
                "format": "markdown",
            }

        elif format.lower() == "html":
            # Import required modules
            from DRHP_crud_backend.report_generator import render_template, load_image_base64
            from jinja2 import Environment, FileSystemLoader
            import markdown
            import os
            from datetime import datetime
            
            # Setup Jinja2 environment
            base_dir = os.path.join(os.path.dirname(__file__), "DRHP_crud_backend")
            templates_dir = os.path.join(base_dir, "templates")
            assets_dir = os.path.join(base_dir, "assets")
            
            env = Environment(loader=FileSystemLoader(templates_dir))

            # Convert Markdown to HTML
            html_body = markdown.markdown(markdown_content, extensions=["tables", "fenced_code"])

            # Prepare dynamic context with safe image loading
            context = {
                "company_name": company_name.upper(),
                "document_date": datetime.today().strftime("%B %Y"),
                            "company_logo_data": safe_load_image_base64(assets_dir, "Pine Labs_logo.png"),
                "content": html_body,
            }

            # Render full HTML
            front_html = render_template(env, "front_page.html", context)
            content_html = render_template(env, "content_page.html", context)
            full_html = front_html + content_html
            
            # Read the web CSS file
            css_path = os.path.join(base_dir, "styles", "web_styles.css")
            with open(css_path, 'r') as f:
                css_content = f.read()
            
            # Wrap HTML with CSS
            styled_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>{company_name} - IPO Report</title>
                <style>
                    {css_content}
                </style>
            </head>
            <body>
                {full_html}
            </body>
            </html>
            """
            
            return {
                "company_id": company_id,
                "company_name": company_name,
                "content": styled_html,
                "format": "html",
            }

        elif format.lower() == "pdf":
            # Import required modules
            from DRHP_crud_backend.report_generator import render_template, load_image_base64
            from jinja2 import Environment, FileSystemLoader
            import markdown
            import tempfile
            from datetime import datetime
            
            # Setup Jinja2 environment
            base_dir = os.path.join(os.path.dirname(__file__), "DRHP_crud_backend")
            templates_dir = os.path.join(base_dir, "templates")
            styles_dir = os.path.join(base_dir, "styles")
            assets_dir = os.path.join(base_dir, "assets")
            
            env = Environment(loader=FileSystemLoader(templates_dir))

            # Convert Markdown to HTML
            html_body = markdown.markdown(markdown_content, extensions=["tables", "fenced_code"])

            # Prepare dynamic context
            context = {
                "company_name": company_name.upper(),
                "document_date": datetime.today().strftime("%B %Y"),
                            "company_logo_data": load_image_base64(os.path.join(assets_dir, "Pine Labs_logo.png")),
                "content": html_body,
            }

            # Render full HTML
            front_html = render_template(env, "front_page.html", context)
            content_html = render_template(env, "content_page.html", context)
            full_html = front_html + content_html

            # Create temporary file for PDF
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            temp_path = temp_file.name
            temp_file.close()

            # Generate PDF
            HTML(string=full_html, base_url=base_dir).write_pdf(
                temp_path, stylesheets=[CSS(os.path.join(styles_dir, "styles.css"))]
            )

            logger.info(f"✅ PDF generated for {company_name}")
            
            # Return PDF file
            return FileResponse(
                path=temp_path,
                media_type="application/pdf",
                filename=f"{company_name.replace(' ', '_')}_ipo_notes.pdf",
                background=None,  # This ensures the file is deleted after sending
            )

        else:
            raise HTTPException(
                status_code=400,
                detail="Invalid format. Supported formats: pdf, html, markdown",
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error processing request for company {company_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.get("/companies")
async def list_companies():
    """List all companies in the final_markdown collection"""
    try:
        companies = pipeline.get_all_companies_with_status()
        
        # Format the response to match the reference
        formatted_companies = []
        for company in companies:
            formatted_companies.append({
                "company_id": company["id"],
                "company_name": company["name"],
            })
        
        return {"total_companies": len(formatted_companies), "companies": formatted_companies}

    except Exception as e:
        logger.error(f"❌ Error listing companies: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error listing companies: {str(e)}"
        )

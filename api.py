import os
import sys
import asyncio
import json
import tempfile
from typing import List
from fastapi import FastAPI, UploadFile, File, HTTPException, Path
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from mongoengine import connect, disconnect

# Add the backend directory to the Python path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), "DRHP_crud_backend"))

import drhp_pipeline_manager as pipeline
from report_generator import generate_report_pdf

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
    uin: str
    uploadDate: str
    status: str
    hasMarkdown: bool

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


@app.get("/companies/{company_id}/markdown", response_class=JSONResponse, summary="Get Company's Final Markdown")
def get_company_markdown(company_id: str = Path(..., description="The MongoDB ID of the company.")):
    """
    Fetches the final generated markdown report for a specific company.
    """
    markdown_content = pipeline.get_final_markdown(company_id)
    if markdown_content is None:
        raise HTTPException(status_code=404, detail="Markdown not found for this company.")
    return JSONResponse(content={"markdown": markdown_content})


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

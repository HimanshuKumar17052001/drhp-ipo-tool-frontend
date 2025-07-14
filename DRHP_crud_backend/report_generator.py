import markdown
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML, CSS
from datetime import datetime
import base64
import os
import tempfile
import logging

logger = logging.getLogger("ReportGenerator")

def load_image_base64(path):
    """Loads an image from a given path and returns its base64 encoded string."""
    try:
        with open(path, 'rb') as f:
            return f"data:image/png;base64,{base64.b64encode(f.read()).decode()}"
    except FileNotFoundError:
        logger.error(f"Image file not found: {path}")
        return "" # Return empty string or a placeholder base64 for missing images

def render_template(env, template_name, context):
    """Renders a Jinja2 template with the given context."""
    return env.get_template(template_name).render(context)

def generate_report_pdf(
    markdown_content: str,
    company_name: str,
    output_filename: str,
    base_dir: str, # Base directory where templates, styles, assets are located
    company_logo_path: str = "assets/Pine Labs_logo.png", # Default placeholder
    axis_logo_path: str = "assets/axis_logo.png", # Default placeholder
    front_header_path: str = "assets/front_header.png", # Default placeholder
) -> str:
    """
    Generates a PDF report from markdown content using Jinja2 templates and WeasyPrint.

    Args:
        markdown_content: The markdown string to convert to PDF.
        company_name: The name of the company for branding.
        output_filename: The desired name for the output PDF file (e.g., "report.pdf").
        base_dir: The base directory where 'templates', 'styles', and 'assets' folders reside.
        company_logo_path: Relative path to the company logo within base_dir/assets.
        axis_logo_path: Relative path to the Axis logo within base_dir/assets.
        front_header_path: Relative path to the front header image within base_dir/assets.

    Returns:
        The absolute path to the generated PDF file.
    """
    try:
        # Setup Jinja2 environment
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
            "company_logo_data": load_image_base64(os.path.join(assets_dir, company_logo_path)),
            "axis_logo_data": load_image_base64(os.path.join(assets_dir, axis_logo_path)),
            "front_header_data": load_image_base64(os.path.join(assets_dir, front_header_path)),
            "content": html_body,
        }

        # Render full HTML
        front_html = render_template(env, "front_page.html", context)
        content_html = render_template(env, "content_page.html", context)
        full_html = front_html + content_html

        # Create a temporary directory for the output PDF
        temp_output_dir = tempfile.mkdtemp()
        output_pdf_path = os.path.join(temp_output_dir, output_filename)

        # Generate PDF
        HTML(string=full_html, base_url=base_dir).write_pdf(
            output_pdf_path, stylesheets=[CSS(os.path.join(styles_dir, "styles.css"))]
        )
        logger.info(f"✅ PDF generated: {output_pdf_path}")
        return output_pdf_path
    except Exception as e:
        logger.error(f"Error generating PDF report: {e}")
        raise

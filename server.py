import io
from sanic import Sanic, Request
from sanic.response import raw
import weasyprint
from weasyprint.text.fonts import FontConfiguration

app = Sanic(__name__)
# Set SANIC_SERVER_NAME env variable to the prefix relative path (no starting slash)
app.config.SERVER_NAME = getattr(app.config, "SERVER_NAME", "")
app.static(app.config.SERVER_NAME, "static/index.html")


@app.post("/pdf")
async def get_api(request: Request):
    if not request.form:
        return raw(html_to_pdf(), content_type="application/pdf")

    return raw(
        html_to_pdf(request.form.get("html") or "", request.form.get("css") or ""),
        content_type="application/pdf",
    )


def html_to_pdf(html: str = "", css: str = ""):
    # print html and css to PDF buffer using weasyprint
    font_config = FontConfiguration()
    stylesheets = [weasyprint.CSS(string=css, font_config=font_config)]
    prepared_pdf_html = weasyprint.HTML(string=html)
    pdf_document = prepared_pdf_html.render(
        font_config=font_config,
        stylesheets=stylesheets,
        optimize_size=("images", "fonts"),
    )
    pdf_file = pdf_document.write_pdf(pdf_variant="pdf/ua-1")
    pdf_io = io.BytesIO(pdf_file if pdf_file else bytes())
    pdf_io.seek(0)
    return pdf_io.getbuffer()

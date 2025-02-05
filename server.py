import io
from sanic import Sanic, Request
from sanic.response import raw
import weasyprint
from weasyprint.text.fonts import FontConfiguration

app = Sanic(__name__)

app.static("/", "static/index.html")


@app.post("/pdf")
async def get_api(request: Request):
    return raw(html_to_pdf(request.form["html"][0], request.form["css"][0]), content_type="application/pdf")


def html_to_pdf(html: str = "", css: str = "") -> io.BytesIO:
    # print html and css to PDF buffer using weasyprint
    font_config = FontConfiguration()
    stylesheets = [weasyprint.CSS(string=css)]
    prepared_pdf_html = weasyprint.HTML(string=html)
    pdf_document = prepared_pdf_html.render(
        font_config=font_config,
        stylesheets=stylesheets,
        optimize_size=('images', 'fonts'),
    )
    pdf_file: bytes = pdf_document.write_pdf(pdf_variant='pdf/a-3b')
    pdf_io = io.BytesIO(pdf_file)
    pdf_io.seek(0)
    return pdf_io.getbuffer()

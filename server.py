import io
from typing import BinaryIO

import pikepdf
import weasyprint
from sanic import Request, Sanic
from sanic.response import ResponseStream
from weasyprint.text.fonts import FontConfiguration

app = Sanic(__name__)
# Set SANIC_SERVER_NAME env variable to the prefix relative path (no starting slash)
app.config.SERVER_NAME = getattr(app.config, "SERVER_NAME", "")
app.static(app.config.SERVER_NAME, "static/index.html")


@app.post("/pdf")
async def get_api(request: Request):
    form = request.form
    html = form.get("html") or "" if form else ""
    css = form.get("css") or "" if form else ""

    input_pdf = io.BytesIO(html_to_pdf(html, css))
    output_pdf = io.BytesIO()
    merge_split_struct_tags(input_pdf, output_pdf)
    convert_divs_to_artifacts(output_pdf, input_pdf)
    input_pdf.seek(0)

    async def stream_pdf(response):
        while chunk := input_pdf.read(64 * 1024):
            await response.write(chunk)

    return ResponseStream(stream_pdf, content_type="application/pdf")


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
    pdf_io = io.BytesIO(pdf_file if pdf_file else b"")
    pdf_io.seek(0)
    return pdf_io.getbuffer()


def merge_split_struct_tags(
    input_pdf: BinaryIO,
    output_pdf: BinaryIO,
    tags_to_merge=("/Art", "/L", "/Table"),
):
    input_pdf.seek(0)
    output_pdf.seek(0)
    output_pdf.truncate()

    with pikepdf.open(input_pdf) as pdf:
        struct_root = pdf.Root.get("/StructTreeRoot")

        def normalize_array(val):
            if val is None:
                return pikepdf.Array()
            if isinstance(val, pikepdf.Array):
                return val
            return pikepdf.Array([val])

        def propagate_page(elem, inherited_pg=None):
            """Ensure child struct elements carry an explicit /Pg before reparenting."""
            if not isinstance(elem, pikepdf.Dictionary):
                return
            current_pg = elem.get("/Pg", inherited_pg)
            if current_pg is not None and "/Pg" not in elem and "/S" in elem:
                elem["/Pg"] = current_pg

            if "/K" not in elem:
                return
            kids = elem["/K"]
            if isinstance(kids, pikepdf.Array):
                for kid in kids:
                    propagate_page(kid, current_pg)
            elif isinstance(kids, pikepdf.Dictionary):
                propagate_page(kids, current_pg)

        def merge_kids(parent):
            if "/K" not in parent:
                return
            kids = parent["/K"]

            if isinstance(kids, pikepdf.Dictionary):
                merge_kids(kids)
                return
            if not isinstance(kids, pikepdf.Array):
                return

            merged = pikepdf.Array()
            for kid in kids:
                if not isinstance(kid, pikepdf.Dictionary):
                    merged.append(kid)
                    continue

                # Recursively merge nested structures first (e.g., <L> or <Table> inside <Art>)
                merge_kids(kid)

                tag_type = str(kid.get("/S", ""))
                if (
                    merged
                    and isinstance(merged[-1], pikepdf.Dictionary)
                    and str(merged[-1].get("/S", "")) == tag_type
                    and tag_type in tags_to_merge
                ):
                    prev_kid = merged[-1]
                    prev_k = normalize_array(prev_kid.get("/K"))
                    curr_k = normalize_array(kid.get("/K"))

                    for item in curr_k:
                        if isinstance(item, pikepdf.Dictionary):
                            item["/P"] = prev_kid
                        elif (
                            isinstance(item, int)
                            and "/Pg" in kid
                            and prev_kid.get("/Pg") != kid.get("/Pg")
                        ):
                            # Wrap bare MCID in an MCR dictionary if its page differs from prev_kid
                            item = pikepdf.Dictionary(
                                {
                                    "/Type": pikepdf.Name("/MCR"),
                                    "/Pg": kid["/Pg"],
                                    "/MCID": item,
                                }
                            )
                        prev_k.append(item)

                    prev_kid["/K"] = prev_k
                else:
                    merged.append(kid)

            parent["/K"] = merged

        if struct_root:
            propagate_page(struct_root)
            merge_kids(struct_root)
        pdf.save(output_pdf)


def convert_divs_to_artifacts(
    input_pdf: BinaryIO,
    output_pdf: BinaryIO,
):
    input_pdf.seek(0)
    output_pdf.seek(0)
    output_pdf.truncate()

    with pikepdf.open(input_pdf) as pdf:
        struct_root = pdf.Root.get("/StructTreeRoot")
        if not struct_root:
            raise ValueError(
                "PDF does not contain a StructTreeRoot (ensure pdf_tags=True)."
            )

        # Map page object gen/num -> set of MCIDs to convert to Artifact
        mcids_by_page = {}

        def process_struct_elem(node, parent=None, index_in_parent=None):
            if not isinstance(node, pikepdf.Dictionary):
                return

            # Check if this node matches our marker (from HTML title="artifact-marker")
            if str(node.get("/S", "")) == "/Div":
                collect_mcids(node)
                # Remove this node from its parent's /K array
                if parent is not None and "/K" in parent:
                    k_val = parent["/K"]
                    if isinstance(k_val, pikepdf.Array):
                        del k_val[index_in_parent]
                    elif k_val == node:
                        del parent["/K"]
                return

            # Otherwise, recurse through children in /K
            kids = node.get("/K")
            if isinstance(kids, pikepdf.Array):
                # Iterate backwards so deletions don't shift indices
                for i in range(len(kids) - 1, -1, -1):
                    process_struct_elem(kids[i], node, i)
            elif isinstance(kids, pikepdf.Dictionary):
                process_struct_elem(kids, node, None)

        def collect_mcids(node, current_page=None):
            page = node.get("/Pg", current_page)
            kids = node.get("/K")
            if isinstance(kids, int):
                if page is not None:
                    mcids_by_page.setdefault(page.objgen, set()).add(kids)
            elif isinstance(kids, pikepdf.Array):
                for item in kids:
                    if isinstance(item, int) and page is not None:
                        mcids_by_page.setdefault(page.objgen, set()).add(item)
                    elif isinstance(item, pikepdf.Dictionary):
                        collect_mcids(item, page)
            elif isinstance(kids, pikepdf.Dictionary):
                collect_mcids(kids, page)

        # 1. Traverse StructTreeRoot and prune matched elements
        root_kids = struct_root.get("/K")
        if isinstance(root_kids, pikepdf.Array):
            for i in range(len(root_kids) - 1, -1, -1):
                process_struct_elem(root_kids[i], struct_root, i)
        elif isinstance(root_kids, pikepdf.Dictionary):
            process_struct_elem(root_kids, struct_root, None)

        # 2. Rewrite content streams on affected pages
        for page in pdf.pages:
            target_mcids = mcids_by_page.get(page.obj.objgen)
            if not target_mcids:
                continue

            instructions = pikepdf.parse_content_stream(page)
            new_instructions = []

            for operands, operator in instructions:
                if operator == pikepdf.Operator("BDC") and len(operands) == 2:
                    props = operands[1]
                    if (
                        isinstance(props, pikepdf.Dictionary)
                        and int(props.get("/MCID", -1)) in target_mcids
                    ):
                        # Replace '/Div <</MCID X>> BDC' with '/Artifact BMC'
                        new_instructions.append(
                            ([pikepdf.Name("/Artifact")], pikepdf.Operator("BMC"))
                        )
                        continue
                new_instructions.append((operands, operator))

            page.Contents = pdf.make_stream(
                pikepdf.unparse_content_stream(new_instructions)
            )

        pdf.save(output_pdf)

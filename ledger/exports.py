import csv
from io import BytesIO
from xml.sax.saxutils import escape
from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


def pdf_table(headers,rows,width,styles,ratios=None,totals=None,compact=False):
    data=[headers,*rows]
    if totals is not None: data.append(totals)
    cells=[[Paragraph(escape(str(c)),styles['Normal']) for c in row] for row in data]
    widths=[width*r for r in ratios] if ratios else [width/len(headers)]*len(headers)
    table=Table(cells,colWidths=widths,repeatRows=1,splitInRow=1,hAlign='LEFT',spaceBefore=9,spaceAfter=12)
    commands=[('BACKGROUND',(0,0),(-1,0),colors.HexColor('#dceee9')),('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),6 if compact else 9),('TOPPADDING',(0,0),(-1,-1),6 if compact else 9),('LINEBELOW',(0,0),(-1,-1),.3,colors.HexColor('#dce3e0')),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f5f8f7')])]
    if totals is not None:
        commands.extend([('NOSPLIT',(0,-2),(-1,-1)),('BACKGROUND',(0,-1),(-1,-1),colors.HexColor('#dceee9')),('LINEABOVE',(0,-1),(-1,-1),1,colors.HexColor('#93b5a9'))])
    table.setStyle(TableStyle(commands))
    return table


def pdf_footer(canvas,doc):
    canvas.setFont('Helvetica',8)
    canvas.drawString(30,20,'Control operativo - Documento interno. No es factura electrónica DIAN.')
    canvas.drawRightString(810,20,f'Página {doc.page}')


def export_table(kind,title,headers,rows,summary='',totals=None):
    if kind=='csv':
        response=HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition']='attachment; filename="reporte.csv"'
        response.write('\ufeff')
        writer=csv.writer(response,delimiter=';')
        def safe(v):
            s=str(v)
            return "'"+s if s.startswith(('=','+','-','@','\t','\r')) else s
        writer.writerow(headers)
        for row in rows: writer.writerow([safe(x) for x in row])
        if totals is not None: writer.writerow([safe(x) for x in totals])
        return response
    buffer=BytesIO()
    styles=getSampleStyleSheet()
    styles['Normal'].fontSize=8
    styles['Normal'].leading=11
    doc=SimpleDocTemplate(buffer,pagesize=landscape(A4),leftMargin=30,rightMargin=30,topMargin=30,bottomMargin=36,title=title)
    story=[Paragraph(escape(title),styles['Title']),Paragraph(escape(summary),styles['Normal']),Spacer(1,16)]
    story.append(pdf_table(headers,rows,doc.width,styles,totals=totals))
    doc.build(story,onFirstPage=pdf_footer,onLaterPages=pdf_footer)
    response=HttpResponse(buffer.getvalue(),content_type='application/pdf')
    response['Content-Disposition']='attachment; filename="reporte.pdf"'
    return response


def export_sales_pdf(sales,summary,report=None):
    from django.utils import timezone
    from .templatetags.money import cop,plain_number
    from .reporting import sales_summary
    if report is None: report=sales_summary(sales)
    buffer=BytesIO()
    styles=getSampleStyleSheet()
    styles['Normal'].fontSize=9
    styles['Normal'].leading=13
    styles['Heading2'].fontSize=12
    styles['Heading2'].spaceBefore=16
    styles['Heading2'].spaceAfter=6
    doc=SimpleDocTemplate(buffer,pagesize=landscape(A4),leftMargin=30,rightMargin=30,topMargin=30,bottomMargin=36,title='Reporte de ventas - Mi Contabilidad')
    story=[Paragraph('Reporte de ventas',styles['Title']),Paragraph(escape(summary),styles['Normal']),Spacer(1,10)]
    for sale in sales:
        story.append(Paragraph(escape(f'{sale} · {sale.customer_name}'),styles['Heading2']))
        description=f'{timezone.localtime(sale.occurred_at):%d/%m/%Y %H:%M} | Medio: {sale.method_name}'
        description_style=styles['Normal'].clone('SaleDescription')
        description_style.keepWithNext=True
        story.append(Paragraph(escape(description),description_style))
        rows=[[l.name,plain_number(l.quantity),plain_number(l.total_weight) if l.by_weight else '—',cop(l.price),cop(l.subtotal)] for l in sale.lines.all()]
        totals=['TOTAL DE LA VENTA',plain_number(sale.report_totals['quantity']),plain_number(sale.report_totals['weight']),'',cop(sale.total)]
        story.append(pdf_table(['Producto','Cantidad','Libras totales','Precio unidad / lb','Subtotal'],rows,doc.width,styles,[.34,.12,.16,.18,.20],totals,compact=True))
    if not sales: story.append(Paragraph('No hay ventas para el periodo consultado.',styles['Normal']))
    story.append(Paragraph('Resumen general por producto',styles['Heading2']))
    rows=[[r['name'],plain_number(r['quantity']),plain_number(r['weight']) if r['by_weight'] else '—',cop(r['total'])] for r in report['products']]
    totals=['TOTAL GENERAL VENDIDO',plain_number(report['quantity']),plain_number(report['weight']),cop(report['total'])]
    story.append(pdf_table(['Producto','Cantidad total','Libras totales','Total vendido'],rows,doc.width,styles,[.40,.17,.18,.25],totals,compact=True))
    doc.build(story,onFirstPage=pdf_footer,onLaterPages=pdf_footer)
    response=HttpResponse(buffer.getvalue(),content_type='application/pdf')
    response['Content-Disposition']='attachment; filename="reporte-ventas.pdf"'
    return response

"""Totales de consulta calculados con los detalles históricos de las ventas."""
from decimal import Decimal
ZERO=Decimal('0')

def line_totals(lines):
    lines=list(lines)
    return {'quantity':sum((l.quantity for l in lines),ZERO),
            'weight':sum((l.total_weight for l in lines if l.by_weight),ZERO),
            'total':sum((l.subtotal for l in lines),ZERO)}

def sales_summary(sales):
    sales=list(sales)
    products={}
    for sale in sorted(sales,key=lambda s:(s.occurred_at,s.pk)):
        sale.report_totals=line_totals(sale.lines.all())
        for line in sale.lines.all():
            # Separa productos distintos y configuraciones históricas incompatibles.
            key=(line.product_id,line.unit,line.by_weight)
            row=products.setdefault(key,{'product_id':line.product_id,'name':line.name,'unit':line.unit,'by_weight':line.by_weight,'quantity':ZERO,'weight':ZERO,'total':ZERO})
            row['name']=line.name
            row['quantity']+=line.quantity
            row['weight']+=line.total_weight if line.by_weight else ZERO
            row['total']+=line.subtotal
    return {'products':sorted(products.values(),key=lambda row:(row['name'].casefold(),row['product_id'],row['unit'],row['by_weight'])),
            'quantity':sum((s.report_totals['quantity'] for s in sales),ZERO),
            'weight':sum((s.report_totals['weight'] for s in sales),ZERO),
            'total':sum((s.total for s in sales),ZERO),'count':len(sales)}

# Verificación de entrega

Fecha: 21/10/2026. Entorno: Python 3.14, Django 5.2.18, SQLite y PostgreSQL 17 aislado en Docker.

## Pruebas automáticas

`python manage.py test --verbosity 1`: 40 pruebas. Ejecutadas contra SQLite y PostgreSQL. Incluyen los casos A–G y los escenarios descritos en README. Las pruebas crean y destruyen una base independiente.

También se ejecutaron:

```sh
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py collectstatic --noinput
```

Sin errores y sin migraciones pendientes. `check --deploy` se ejecutó con `DEBUG=false`, clave de prueba aislada y orígenes HTTPS de prueba: sin advertencias. Esto valida la configuración, no equivale a publicar o certificar un servidor real.

## Recorrido en navegador

Se utilizó Chromium con Playwright contra un servidor local en el puerto 8765, conectado exclusivamente a `tmp/ui.sqlite3`. El usuario y los movimientos de prueba no se crearon en la base principal.

Se comprobó mediante los formularios reales:

1. Ingreso con usuario y contraseña.
2. Creación de cliente con identificación y campos opcionales vacíos.
3. Creación de producto a $2.000 por libra con presentación de 16 lb.
4. Venta de diez canastas: cálculo visual y persistido de $320.000.
5. Crédito con pago inicial en efectivo de $100.000: saldo de $220.000.
6. Abono posterior de $70.000: comprobante con la aplicación.
7. Extracto con venta, pago inicial, abono y saldo final de $150.000.
8. Descarga del PDF y revisión visual de su renderizado con Poppler: encabezados, columnas, saldos y aviso de documento interno legibles.
9. Registro de gastos de $50.000 y $30.000: total de $80.000.
10. Panel con esos valores, vista de escritorio de 1440 px y móvil de 390 px.
11. Sin errores JavaScript ni desbordamiento del documento en las pantallas móviles de panel, ventas, nueva venta, extracto, gastos y abonos. Las tablas conservan desplazamiento horizontal dentro de su contenedor.
12. Cierre de sesión, regreso al formulario de ingreso y nueva sesión usando el correo: el saldo persistió en $150.000.

Los archivos temporales de esta verificación se guardaron en `tmp/`, excluido del control de versiones.

## Concurrencia

Se verificaron dos envíos simultáneos del mismo pago: una sola aplicación. También dos pagos diferentes de $70.000 contra deuda de $100.000: uno se acepta, el otro se rechaza y el saldo queda en $30.000. Ambos escenarios se ejecutaron en SQLite y PostgreSQL.

## Respaldo

`python manage.py backup_db --directory tmp/backup-check` creó una copia SQLite. La copia se abrió separadamente y `PRAGMA integrity_check` devolvió `ok`; estaban presentes las 23 tablas. El procedimiento de PostgreSQL con `pg_dump`/`pg_restore` está documentado; el comando de respaldo PostgreSQL no se ensayó desde el host porque no tiene instalado `pg_dump`.

## Estado de la base principal y límites

La base principal contiene solo las migraciones y la configuración inicial: cero clientes, ventas, abonos y gastos. No hay usuario administrador predeterminado. Se crea de forma interactiva con `python manage.py createsuperuser`.

No se ha publicado la aplicación en internet ni ensayado un dominio, certificados, correo o carga sostenida. No se han implementado facturación electrónica, contabilidad de partida doble, inventario, saldos a favor, reversión de movimientos o exportación `.xlsx` nativa. CSV y PDF sí están implementados. Antes de operar en producción deben configurarse el acceso HTTPS y los respaldos automáticos y ensayarse su recuperación en la infraestructura elegida.

## Ajustes posteriores solicitados (21/10/2026)

La suite actual contiene **47 pruebas** y pasa con SQLite y PostgreSQL 17. Se añadieron verificaciones para cantidades enteras, aplicación FIFO obligatoria incluso frente a un formulario manipulado, orden intercalado de ventas y abonos del mismo día, peso opcional según tipo de producto, conservación de referencias antiguas de gastos y lectura del contenido real del PDF de ventas.

Cambios comprobados también con Chromium en una base aislada (`tmp/revision-ui.sqlite3`):

- Buscar «fresa» devuelve productos con un botón Agregar independiente y limpia el buscador después de elegir.
- Las cantidades decimales se rechazan; los pesos siguen admitiendo decimales.
- El peso fijo se oculta para productos por unidades y para peso variable.
- No aparecen la distribución manual de abonos, la referencia del formulario de gastos ni el menú de usuarios.
- Una venta de $320.000 y su pago inicial aparecen antes de una segunda venta en el extracto.
- Un abono de $230.000 a saldos de $220.000 y $45.000 aplica $220.000 al primero y $10.000 al segundo, dejando $35.000.
- PDF revisado visualmente tras renderizar con Poppler: cada venta tiene su detalle interno con producto, presentación, cantidad sin ceros sobrantes, libras totales, precio y subtotal.
- Las pantallas modificadas no desbordan el documento en un ancho de 390 px.

Se hizo un respaldo antes de editar. Se compararon todos los registros de las tablas del negocio con ese respaldo: permanecieron idénticos. No hubo migraciones ni modificaciones de movimientos existentes. Las restricciones de cantidades enteras y FIFO se aplican a las operaciones nuevas.

Para ejecutar la suite actual instale primero `pip install -r requirements-dev.txt`; `pypdf` se usa solo para verificar el contenido de las exportaciones PDF en las pruebas.

## Reportes de ventas y totales al pie (21/10/2026)

La suite se amplió a **53 pruebas**. Se verificaron filtros de fechas y cliente, varias ventas del mismo producto, conservación de precios y pesos históricos, resumen por producto y totales que coinciden con la suma de las ventas. El reporte de ventas en pantalla, PDF y CSV excluye abonos, saldos y la columna Presentación. Cada venta tiene su total al pie y al final aparece el resumen general por producto.

Las tablas de estados de cuenta, cartera, ventas individuales, abonos, clientes y gastos incluyen los totales pertinentes. El borrador de venta y la aplicación de abonos actualizan sus pies en pantalla. En el extracto se usa el saldo final real, incluyendo el saldo inicial del periodo; no se suman saldos acumulados. La cartera incluye todos los pagos iniciales en el total abonado.

Se verificó con Chromium en la base aislada existente: dos ventas de $320.000 y $45.000 totalizan $365.000, 13 unidades/presentaciones y 160 lb. Los pagos de $330.000 dejan deuda de $35.000. Un rango sin ventas muestra totales cero. Se comprobó ordenamiento sin mover el pie, PDF y vistas de 390 px sin desbordamiento del documento. El PDF se renderizó y revisó visualmente con Poppler, incluidos el resumen y los totales finales. Una prueba adicional de 35 ventas verifica que todas aparecen en un PDF de varias páginas y que la última página contiene el resumen y el total de $525.000.

Los cambios no requieren migraciones ni alteran datos financieros existentes. Se creó un respaldo antes de comenzar.

## App móvil offline (27 de octubre de 2026)

Se preparó un servidor y una base SQLite de ensayo separados de la instalación y
los datos reales. Con pantalla de 390×844 se comprobó en Chromium y WebKit:

1. Acceso con usuario y regreso a `/movil/`.
2. Instalación del service worker y copia local del catálogo.
3. Apertura de `/movil/` con el servidor inaccesible y conservación al recargar.
4. Venta de dos canastas de 16 lb a $2.000/lb: total $64.000 y pago inicial $1.000.
5. Abono de $500 y gasto de $100 sin conexión; tres movimientos en IndexedDB.
6. Reconexión, vaciado confirmado de la cola y aumento de cartera de $62.500.
7. Ausencia de errores JavaScript durante el recorrido.

En Chromium se utilizó el modo offline del navegador. En WebKit se detuvo y
reinició el servidor de ensayo: la emulación offline de Playwright tiene un
[problema conocido con navegaciones atendidas por service workers](https://github.com/microsoft/playwright/issues/42775).
La prueba de WebKit no equivale a una validación en un iPhone físico: antes de
usar datos reales debe repetirse desde el acceso instalado de los dispositivos
concretos, en modo avión y después de cerrar y abrir la app.

La suite `python manage.py test ledger config.test_settings --noinput` incluye
75 pruebas de contabilidad, configuración y sincronización. La instalación local
se preparó de forma aislada en `.offline/`, con migraciones y comprobación Django.
La primera descarga y el envío real a Vercel quedan pendientes de conectar la
cuenta de Vercel, configurar sus variables privadas y publicar la nueva versión.
